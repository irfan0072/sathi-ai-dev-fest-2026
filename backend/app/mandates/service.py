"""Durable PostgreSQL Mandate Service and Deterministic Policy Engine for Sathi.

Implements mandate lifecycle, single-use one-time hashed codes, TTL expiry,
repeated wrong-code lockout, cash gap anomaly detection, audit logging,
and policy parameter enforcement loaded from data/config.yaml.

PostgreSQL is the single, durable source of truth. All operations execute
within parameterized transactions with row-level locks and exact Decimal cents.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import secrets
import uuid
from datetime import timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from app.data.config import load_config
from app.data.database import DatabaseError, get_connection
from app.verification.keypad import parse_keypad_amount


class MandateError(Exception):
    """Base domain exception for mandate operations."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class MandateNotFoundError(MandateError):
    def __init__(self, message: str = "Mandate not found"):
        super().__init__("MANDATE_NOT_FOUND", message, status_code=404)


class ActiveMandateExistsError(MandateError):
    def __init__(self, message: str = "Active mandate already exists for user"):
        super().__init__("ACTIVE_MANDATE_EXISTS", message, status_code=409)


class AlreadyRedeemedError(MandateError):
    def __init__(self, message: str = "Mandate has already been redeemed"):
        super().__init__("ALREADY_REDEEMED", message, status_code=409)


class AlreadyVerifiedError(MandateError):
    def __init__(self, message: str = "Mandate is already verified"):
        super().__init__("ALREADY_VERIFIED", message, status_code=409)


class InvalidMandateStateError(MandateError):
    def __init__(self, message: str = "Invalid mandate state for requested operation"):
        super().__init__("INVALID_MANDATE_STATE", message, status_code=409)


class MandateExpiredError(MandateError):
    def __init__(self, message: str = "Mandate has expired"):
        super().__init__("MANDATE_EXPIRED", message, status_code=410)


class InvalidCodeError(MandateError):
    def __init__(self, message: str = "Invalid one-time code"):
        super().__init__("INVALID_ONE_TIME_CODE", message, status_code=401)


class AccountLockedError(MandateError):
    def __init__(self, message: str = "Account locked after excessive failed attempts"):
        super().__init__("ACCOUNT_LOCKED", message, status_code=423)


class AmountExceedsCapError(MandateError):
    def __init__(self, message: str = "Requested amount exceeds user cap"):
        super().__init__("AMOUNT_EXCEEDS_CAP", message, status_code=422)


class DailyLimitExceededError(MandateError):
    def __init__(self, message: str = "Cumulative daily cash-out limit exceeded"):
        super().__init__("DAILY_LIMIT_EXCEEDED", message, status_code=422)


class MaxAttemptsExceededError(MandateError):
    def __init__(self, message: str = "Maximum verification attempts exceeded"):
        super().__init__("MAX_ATTEMPTS_EXCEEDED", message, status_code=422)


class InvalidAmountError(MandateError):
    def __init__(self, message: str = "Amount must be strictly positive"):
        super().__init__("INVALID_AMOUNT", message, status_code=422)


class InsufficientBalanceError(MandateError):
    def __init__(self, message: str = "Insufficient balance for withdrawal and fee"):
        super().__init__("INSUFFICIENT_BALANCE", message, status_code=422)


class MandateRecord:
    """Live proxy to durable PostgreSQL mandate row."""

    def __init__(
        self,
        service: MandateService,
        mandate_id: str,
        user_id: str,
        agent_id: str,
        amount: float,
        purpose: str,
        expires_at: datetime.datetime,
        code_hash: str | None = None,
        status: str = "requested",
        created_at: datetime.datetime | None = None,
        redeemed_txn_id: int | None = None,
        verification_attempts: int = 0,
        redemption_attempts: int = 0,
    ):
        self._service = service
        self.mandate_id = mandate_id
        self.user_id = user_id
        self.agent_id = agent_id
        self.amount = float(amount)
        self.purpose = purpose
        self._code_hash = code_hash or ""
        self._status = status
        self._expires_at = expires_at
        self.created_at = created_at or datetime.datetime.now(timezone.utc)
        self.redeemed_txn_id = redeemed_txn_id
        self.redeemed_at: datetime.datetime | None = None
        self.verification_attempts = verification_attempts
        self.redemption_attempts = redemption_attempts

    @property
    def status(self) -> str:
        return self._status

    @status.setter
    def status(self, val: str) -> None:
        self._status = val
        self._update_db("status", val)

    @property
    def code_hash(self) -> str:
        return self._code_hash

    @code_hash.setter
    def code_hash(self, val: str | None) -> None:
        self._code_hash = val or ""
        self._update_db("code_hash", val)

    @property
    def expires_at(self) -> datetime.datetime:
        return self._expires_at

    @expires_at.setter
    def expires_at(self, val: datetime.datetime) -> None:
        self._expires_at = val
        self._update_db("expires_at", val)

    def _update_db(self, field: str, val: Any) -> None:
        """Propagate changes directly to PostgreSQL."""
        try:
            with self._service.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE mandates SET {field} = %s WHERE mandate_id = %s;",
                        (val, self.mandate_id),
                    )
                conn.commit()
        except Exception:
            pass

    def to_dict(self) -> dict[str, Any]:
        return {
            "mandate_id": self.mandate_id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "amount": self.amount,
            "purpose": self.purpose,
            "code_hash": self.code_hash,
            "status": self.status,
            "expires_at": self.expires_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "redeemed_txn_id": self.redeemed_txn_id,
        }


class _DurableMandatesProxy:
    """Dict-like proxy for service.mandates reading directly from PostgreSQL."""

    def __init__(self, service: MandateService):
        self._service = service

    def __getitem__(self, mandate_id: str) -> MandateRecord:
        record = self.get(mandate_id)
        if record is None:
            raise KeyError(f"Mandate {mandate_id} not found")
        return record

    def get(self, mandate_id: str, default: Any = None) -> MandateRecord | None:
        try:
            with self._service.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT mandate_id, user_id, agent_id, amount_cap, purpose,
                               code_hash, status, expires_at, created_at, redeemed_txn_id,
                               verification_attempts, redemption_attempts
                        FROM mandates WHERE mandate_id = %s;
                        """,
                        (mandate_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return default
                    return MandateRecord(
                        service=self._service,
                        mandate_id=str(row[0]),
                        user_id=row[1],
                        agent_id=row[2],
                        amount=float(row[3]),
                        purpose=row[4],
                        code_hash=row[5],
                        status=row[6],
                        expires_at=row[7],
                        created_at=row[8],
                        redeemed_txn_id=row[9],
                        verification_attempts=row[10],
                        redemption_attempts=row[11],
                    )
        except Exception:
            return default

    def __contains__(self, mandate_id: str) -> bool:
        return self.get(mandate_id) is not None

    def values(self) -> list[MandateRecord]:
        results = []
        try:
            with self._service.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT mandate_id, user_id, agent_id, amount_cap, purpose,
                               code_hash, status, expires_at, created_at, redeemed_txn_id,
                               verification_attempts, redemption_attempts
                        FROM mandates;
                        """
                    )
                    for row in cur.fetchall():
                        results.append(
                            MandateRecord(
                                service=self._service,
                                mandate_id=str(row[0]),
                                user_id=row[1],
                                agent_id=row[2],
                                amount=float(row[3]),
                                purpose=row[4],
                                code_hash=row[5],
                                status=row[6],
                                expires_at=row[7],
                                created_at=row[8],
                                redeemed_txn_id=row[9],
                                verification_attempts=row[10],
                                redemption_attempts=row[11],
                            )
                        )
        except Exception:
            pass
        return results


class MandateService:
    """Durable PostgreSQL Mandate Service implementing deterministic policy engine rules."""

    def __init__(
        self,
        config_path: str | Path | None = None,
        db_url: str | None = None,
        schema: str | None = None,
    ) -> None:
        self.config_path = config_path
        self._cfg = load_config(config_path)
        self.policy = self._cfg["policy"]
        self.simulation = self._cfg["simulation"]

        # Fail-closed parameter validation from validated config (no fallback defaults)
        self.user_cap_default: Decimal = Decimal(str(self.policy["user_cap_default"]))
        self.daily_cash_out_limit: Decimal = Decimal(str(self.policy["daily_cash_out_limit"]))
        self.mandate_ttl_minutes: int = int(self.policy["mandate_ttl_minutes"])
        self.max_verification_attempts: int = int(self.policy["max_verification_attempts"])
        self.max_redemption_attempts: int = int(self.policy["max_redemption_attempts"])
        self.official_fee_rate: Decimal = Decimal(str(self.simulation["official_fee_rate"]))

        cash_gap_conf = self.policy["cash_gap"]
        self.cash_gap_min_bdt: Decimal = Decimal(str(cash_gap_conf["min_bdt"]))
        self.cash_gap_rate: Decimal = Decimal(str(cash_gap_conf["rate"]))

        self.db_url = (
            db_url
            or os.environ.get("SATHI_TEST_DATABASE_URL")
            or os.environ.get("DATABASE_URL")
        )
        self.schema = schema or os.environ.get("DATABASE_SCHEMA")

        # Live proxy exposing PostgreSQL records with dict-compatible interface
        self.mandates = _DurableMandatesProxy(self)

    def get_connection(self):
        """Establish PostgreSQL connection with configured schema fail-closed."""
        if not self.db_url:
            raise DatabaseError("Database URL is not configured. Service fails closed.")
        return get_connection(self.db_url, schema=self.schema)

    def _now(self) -> datetime.datetime:
        """Current UTC timestamp."""
        return datetime.datetime.now(timezone.utc)

    @property
    def cases(self) -> list[dict[str, Any]]:
        """Durable review cases from PostgreSQL cases table."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT case_id, mandate_id, agent_id, reason, evidence, status, created_at
                        FROM cases ORDER BY case_id ASC;
                        """
                    )
                    rows = cur.fetchall()
                    return [
                        {
                            "case_id": r[0],
                            "mandate_id": str(r[1]) if r[1] else None,
                            "agent_id": r[2],
                            "reason": r[3],
                            "evidence": (
                                r[4] if isinstance(r[4], dict) else json.loads(r[4] or "{}")
                            ),
                            "status": r[5],
                            "created_at": (
                                r[6].isoformat() if hasattr(r[6], "isoformat") else str(r[6])
                            ),
                        }
                        for r in rows
                    ]
        except Exception:
            return []

    @property
    def audit_log(self) -> list[dict[str, Any]]:
        """Durable audit trail from PostgreSQL audit_log table."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT log_id, actor, action, entity, entity_id, policy_version,
                               model_versions, detail, ts
                        FROM audit_log ORDER BY log_id ASC;
                        """
                    )
                    rows = cur.fetchall()
                    return [
                        {
                            "log_id": r[0],
                            "actor": r[1],
                            "action": r[2],
                            "entity": r[3],
                            "entity_id": r[4],
                            "policy_version": r[5],
                            "model_versions": (
                                r[6] if isinstance(r[6], dict) else json.loads(r[6] or "{}")
                            ),
                            "detail": (
                                r[7] if isinstance(r[7], dict) else json.loads(r[7] or "{}")
                            ),
                            "ts": r[8].isoformat() if hasattr(r[8], "isoformat") else str(r[8]),
                        }
                        for r in rows
                    ]
        except Exception:
            return []

    @property
    def verification_events(self) -> list[dict[str, Any]]:
        """Durable verification events from PostgreSQL verification_events table."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT event_id, mandate_id, mode, stated_amount, outcome,
                               cash_received_reported, ts
                        FROM verification_events ORDER BY event_id ASC;
                        """
                    )
                    rows = cur.fetchall()
                    return [
                        {
                            "event_id": r[0],
                            "mandate_id": str(r[1]) if r[1] else None,
                            "mode": r[2],
                            "stated_amount": float(r[3]) if r[3] is not None else None,
                            "outcome": r[4],
                            "cash_received_reported": float(r[5]) if r[5] is not None else None,
                            "ts": r[6].isoformat() if hasattr(r[6], "isoformat") else str(r[6]),
                        }
                        for r in rows
                    ]
        except Exception:
            return []

    def log_audit(
        self,
        actor: str,
        action: str,
        entity: str,
        entity_id: str,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record an entry into the durable PostgreSQL audit trail."""
        detail_json = json.dumps(detail or {})
        model_ver_json = json.dumps({"policy_engine": "deterministic_v1"})
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_log (
                        actor, action, entity, entity_id, policy_version,
                        model_versions, detail, ts
                    ) VALUES (%s, %s, %s, %s, 'v1.0', %s::jsonb, %s::jsonb, now())
                    RETURNING log_id, ts;
                    """,
                    (actor, action, entity, str(entity_id), model_ver_json, detail_json),
                )
                row = cur.fetchone()
                log_id, ts = row[0], row[1]
            conn.commit()

        return {
            "log_id": log_id,
            "actor": actor,
            "action": action,
            "entity": entity,
            "entity_id": str(entity_id),
            "policy_version": "v1.0",
            "model_versions": {"policy_engine": "deterministic_v1"},
            "detail": detail or {},
            "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
        }

    def create_case(
        self,
        mandate_id: str | None,
        agent_id: str | None,
        reason: str,
        evidence: dict[str, Any],
    ) -> int:
        """Create a durable review case in the PostgreSQL cases store."""
        evidence_json = json.dumps(evidence)
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cases (
                        mandate_id, agent_id, reason, evidence, status, created_at
                    ) VALUES (%s, %s, %s, %s::jsonb, 'open', now())
                    RETURNING case_id;
                    """,
                    (mandate_id, agent_id, reason, evidence_json),
                )
                case_id = cur.fetchone()[0]
            conn.commit()
        return case_id

    def get_user_daily_cashout(self, user_id: str, date_str: str | None = None) -> float:
        """Compute user's cumulative cash-out total in Asia/Dhaka timezone from durable ledger."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                if date_str:
                    cur.execute(
                        """
                        SELECT COALESCE(SUM(amount), 0)
                        FROM transactions
                        WHERE user_id = %s
                          AND txn_type = 'cash_out'
                          AND (ts AT TIME ZONE 'Asia/Dhaka')::date = %s::date;
                        """,
                        (user_id, date_str),
                    )
                else:
                    cur.execute(
                        """
                        SELECT COALESCE(SUM(amount), 0)
                        FROM transactions
                        WHERE user_id = %s
                          AND txn_type = 'cash_out'
                          AND (ts AT TIME ZONE 'Asia/Dhaka')::date =
                              (now() AT TIME ZONE 'Asia/Dhaka')::date;
                        """,
                        (user_id,),
                    )
                total = cur.fetchone()[0]
        return float(total)

    def request_mandate(
        self,
        user_id: str,
        agent_id: str,
        amount: float | int | str | Decimal,
        purpose: str = "cash_out",
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Initiate a cash-out mandate request with row locks and policy validations."""
        if purpose != "cash_out":
            raise MandateError(
                "INVALID_PURPOSE",
                f"Unsupported purpose '{purpose}'. Only 'cash_out' is supported.",
                status_code=422,
            )

        # 1. Parse and validate amount
        try:
            dec_amount = parse_keypad_amount(amount)
        except Exception as exc:
            raise InvalidAmountError(f"Mandate amount is invalid: {exc}") from exc

        # 2. Amount cap check
        if dec_amount > self.user_cap_default:
            raise AmountExceedsCapError(
                f"Requested amount {dec_amount:.2f} BDT exceeds mandate cap of "
                f"{self.user_cap_default:.2f} BDT"
            )

        fee = (dec_amount * self.official_fee_rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        payout = dec_amount
        total_debit = dec_amount + fee

        mandate_id = str(uuid.uuid4())
        now = self._now()
        expires_at = now + datetime.timedelta(minutes=self.mandate_ttl_minutes)

        conn = self.get_connection()
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    # Verify user exists and acquire user row lock
                    cur.execute(
                        "SELECT user_id FROM users WHERE user_id = %s FOR UPDATE;",
                        (user_id,),
                    )
                    u_row = cur.fetchone()
                    if not u_row:
                        raise MandateNotFoundError(f"User '{user_id}' does not exist.")

                    # Verify agent exists
                    cur.execute(
                        "SELECT agent_id FROM agents WHERE agent_id = %s;",
                        (agent_id,),
                    )
                    if not cur.fetchone():
                        raise MandateNotFoundError(f"Agent '{agent_id}' does not exist.")

                    # Transition expired live rows for user and record audit log before checks
                    cur.execute(
                        """
                        SELECT mandate_id FROM mandates
                        WHERE user_id = %s
                          AND status IN ('requested', 'verified', 'active')
                          AND expires_at <= %s
                        FOR UPDATE;
                        """,
                        (user_id, now),
                    )
                    expired_mandates = [r[0] for r in cur.fetchall()]
                    for exp_m_id in expired_mandates:
                        cur.execute(
                            "UPDATE mandates SET status = 'expired' WHERE mandate_id = %s;",
                            (exp_m_id,),
                        )
                        cur.execute(
                            """
                            INSERT INTO audit_log (
                                actor, action, entity, entity_id, policy_version, detail, ts
                            ) VALUES (
                                %s, 'mandate_expired', 'mandate', %s, 'v1.0', %s::jsonb, %s
                            );
                            """,
                            (
                                actor or agent_id,
                                exp_m_id,
                                json.dumps({"stage": "request_expiry_sweep"}),
                                now,
                            ),
                        )

                    # Daily cumulative limit check in Asia/Dhaka timezone with injected now
                    cur.execute(
                        """
                        SELECT COALESCE(SUM(amount), 0)
                        FROM transactions
                        WHERE user_id = %s
                          AND txn_type = 'cash_out'
                          AND (ts AT TIME ZONE 'Asia/Dhaka')::date =
                              (%s::timestamptz AT TIME ZONE 'Asia/Dhaka')::date;
                        """,
                        (user_id, now),
                    )
                    current_daily = Decimal(str(cur.fetchone()[0]))
                    if current_daily + dec_amount > self.daily_cash_out_limit:
                        raise DailyLimitExceededError(
                            f"Cumulative daily cash-out would be "
                            f"{current_daily + dec_amount:.2f} BDT, exceeding daily limit "
                            f"of {self.daily_cash_out_limit:.2f} BDT"
                        )

                    # Check for existing live unexpired mandate for user
                    cur.execute(
                        """
                        SELECT mandate_id FROM mandates
                        WHERE user_id = %s
                          AND status IN ('requested', 'verified', 'active')
                          AND expires_at > %s
                        FOR UPDATE;
                        """,
                        (user_id, now),
                    )
                    if cur.fetchone():
                        raise ActiveMandateExistsError(
                            f"Active unexpired mandate already exists for user {user_id}"
                        )

                    # Insert requested mandate (code_hash is NULL)
                    cur.execute(
                        """
                        INSERT INTO mandates (
                            mandate_id, user_id, agent_id, purpose, amount_cap,
                            code_hash, status, expires_at, created_at,
                            verification_attempts, redemption_attempts
                        ) VALUES (%s, %s, %s, %s, %s, NULL, 'requested', %s, %s, 0, 0);
                        """,
                        (mandate_id, user_id, agent_id, purpose, dec_amount, expires_at, now),
                    )

                    # Record audit log
                    cur.execute(
                        """
                        INSERT INTO audit_log (
                            actor, action, entity, entity_id, policy_version,
                            model_versions, detail, ts
                        ) VALUES (
                            %s, 'mandate_requested', 'mandate', %s, 'v1.0',
                            %s::jsonb, %s::jsonb, %s
                        );
                        """,
                        (
                            actor or agent_id,
                            mandate_id,
                            json.dumps({"policy_engine": "deterministic_v1"}),
                            json.dumps(
                                {
                                    "user_id": user_id,
                                    "agent_id": agent_id,
                                    "amount": float(dec_amount),
                                    "fee": float(fee),
                                    "payout": float(payout),
                                    "total_debit": float(total_debit),
                                    "purpose": purpose,
                                }
                            ),
                            now,
                        ),
                    )
        finally:
            conn.close()

        return {
            "mandate_id": mandate_id,
            "status": "requested",
            "next": "verify",
            "verification_modes": ["keypad", "voice"],
            "amount": float(dec_amount),
            "fee": float(fee),
            "payout": float(payout),
            "total_debit": float(total_debit),
        }

    def verify_mandate(
        self,
        mandate_id: str,
        mode: str,
        stated_amount: Any,
        attempt: int = 1,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Customer verification verifying stated amount and advancing state to verified.

        Customer NEVER receives plaintext code. Response returns verified status
        and code_delivery='agent_terminal'.
        """
        # Parse stated amount via keypad parser (normalizing Bangla digits, grouping commas)
        parsed_amount = parse_keypad_amount(stated_amount)
        now = self._now()

        conn = self.get_connection()
        error_to_raise: Exception | None = None
        result: dict[str, Any] | None = None
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT mandate_id, user_id, agent_id, amount_cap, code_hash,
                               status, expires_at, verification_attempts
                        FROM mandates WHERE mandate_id = %s FOR UPDATE;
                        """,
                        (mandate_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise MandateNotFoundError(f"Mandate {mandate_id} not found")

                    (
                        m_id,
                        user_id,
                        agent_id,
                        amount_cap,
                        code_hash,
                        status_val,
                        expires_at_val,
                        cur_ver_attempts,
                    ) = row
                    expected_amount = Decimal(str(amount_cap)).quantize(Decimal("0.01"))

                    # State checks
                    if status_val in ("active", "verified"):
                        raise AlreadyVerifiedError(
                            f"Mandate {mandate_id} is already verified or active"
                        )
                    if status_val in ("redeemed", "revoked"):
                        raise InvalidMandateStateError(
                            f"Cannot verify mandate in {status_val} state"
                        )
                    if status_val == "rejected":
                        raise MaxAttemptsExceededError(
                            f"Mandate {mandate_id} is locked after exceeding "
                            f"max verification attempts ({self.max_verification_attempts})"
                        )

                    # Expiry check (exact TTL boundary now >= expires_at)
                    if now >= expires_at_val:
                        cur.execute(
                            "UPDATE mandates SET status = 'expired' WHERE mandate_id = %s;",
                            (mandate_id,),
                        )
                        cur.execute(
                            """
                            INSERT INTO audit_log (
                                actor, action, entity, entity_id, policy_version, detail, ts
                            ) VALUES (
                                %s, 'mandate_expired', 'mandate', %s, 'v1.0', %s::jsonb, now()
                            );
                            """,
                            (
                                actor or "customer_channel",
                                mandate_id,
                                json.dumps({"stage": "verify"}),
                            ),
                        )
                        error_to_raise = MandateExpiredError(
                            f"Mandate {mandate_id} expired at {expires_at_val.isoformat()}"
                        )

                    # Check if attempts limit exceeded
                    elif (cur_ver_attempts + 1) > self.max_verification_attempts:
                        new_ver_attempts = cur_ver_attempts + 1
                        cur.execute(
                            """
                            UPDATE mandates
                            SET status = 'rejected', verification_attempts = %s
                            WHERE mandate_id = %s;
                            """,
                            (new_ver_attempts, mandate_id),
                        )
                        cur.execute(
                            """
                            INSERT INTO audit_log (
                                actor, action, entity, entity_id, policy_version, detail, ts
                            ) VALUES (%s, 'mandate_max_verification_attempts_exceeded',
                                      'mandate', %s, 'v1.0', %s::jsonb, now());
                            """,
                            (
                                actor or "customer_channel",
                                mandate_id,
                                json.dumps({"attempts": new_ver_attempts}),
                            ),
                        )
                        error_to_raise = MaxAttemptsExceededError(
                            f"Attempt {new_ver_attempts} exceeds max verification attempts "
                            f"of {self.max_verification_attempts}"
                        )

                    else:
                        new_ver_attempts = cur_ver_attempts + 1
                        # Amount match comparison
                        is_match = abs(parsed_amount - expected_amount) < Decimal("0.01")
                        if is_match:
                            # Success: advance to verified state; extend expiry
                            # starting at verification
                            verified_expires_at = now + datetime.timedelta(
                                minutes=self.mandate_ttl_minutes
                            )
                            cur.execute(
                                """
                                UPDATE mandates
                                SET status = 'verified',
                                    expires_at = %s,
                                    verification_attempts = %s
                                WHERE mandate_id = %s;
                                """,
                                (verified_expires_at, new_ver_attempts, mandate_id),
                            )

                            cur.execute(
                                """
                                INSERT INTO verification_events (
                                    mandate_id, mode, stated_amount, outcome, ts
                                ) VALUES (%s, %s, %s, 'match', now());
                                """,
                                (mandate_id, mode, parsed_amount),
                            )

                            cur.execute(
                                """
                                INSERT INTO audit_log (
                                    actor, action, entity, entity_id, policy_version, detail, ts
                                ) VALUES (
                                    %s, 'mandate_verified', 'mandate', %s, 'v1.0',
                                    %s::jsonb, now()
                                );
                                """,
                                (
                                    actor or "customer_channel",
                                    mandate_id,
                                    json.dumps(
                                        {
                                            "outcome": "match",
                                            "mode": mode,
                                            "attempt": new_ver_attempts,
                                        }
                                    ),
                                ),
                            )

                            result = {
                                "outcome": "match",
                                "decision": "ISSUE_MANDATE",
                                "status": "verified",
                                "expires_at": verified_expires_at.isoformat(),
                                "code_delivery": "agent_terminal",
                                "one_time_code": None,  # Customer never receives code
                                "case_id": None,
                            }
                        else:
                            # Mismatch: review case created and persisted;
                            # status rejected if limit reached
                            new_status = (
                                "rejected"
                                if new_ver_attempts >= self.max_verification_attempts
                                else "requested"
                            )
                            cur.execute(
                                """
                                UPDATE mandates
                                SET status = %s,
                                    verification_attempts = %s
                                WHERE mandate_id = %s;
                                """,
                                (new_status, new_ver_attempts, mandate_id),
                            )

                            cur.execute(
                                """
                                INSERT INTO cases (
                                    mandate_id, agent_id, reason, evidence, status, created_at
                                ) VALUES (
                                    %s, %s, 'stated_amount_mismatch', %s::jsonb, 'open', now()
                                ) RETURNING case_id;
                                """,
                                (
                                    mandate_id,
                                    agent_id,
                                    json.dumps(
                                        {
                                            "expected_amount": float(expected_amount),
                                            "stated_amount": float(parsed_amount),
                                            "mode": mode,
                                            "attempt": new_ver_attempts,
                                        }
                                    ),
                                ),
                            )
                            case_id = cur.fetchone()[0]

                            cur.execute(
                                """
                                INSERT INTO verification_events (
                                    mandate_id, mode, stated_amount, outcome, ts
                                ) VALUES (%s, %s, %s, 'mismatch', now());
                                """,
                                (mandate_id, mode, parsed_amount),
                            )

                            cur.execute(
                                """
                                INSERT INTO audit_log (
                                    actor, action, entity, entity_id, policy_version, detail, ts
                                ) VALUES (
                                    %s, 'mandate_verification_mismatch', 'mandate', %s,
                                    'v1.0', %s::jsonb, now()
                                );
                                """,
                                (
                                    actor or "customer_channel",
                                    mandate_id,
                                    json.dumps(
                                        {
                                            "outcome": "mismatch",
                                            "mode": mode,
                                            "attempt": new_ver_attempts,
                                            "case_id": case_id,
                                        }
                                    ),
                                ),
                            )

                            result = {
                                "outcome": "mismatch",
                                "decision": "REVIEW",
                                "status": new_status,
                                "expires_at": expires_at_val.isoformat(),
                                "code_delivery": "agent_terminal",
                                "one_time_code": None,
                                "case_id": case_id,
                            }
        finally:
            conn.close()

        if error_to_raise is not None:
            raise error_to_raise

        return result

    def issue_code(
        self,
        mandate_id: str,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Issue cryptographic 6-digit one-time code to bound agent terminal exactly once.

        Mandate must be in verified state. Returns plaintext code only once; persists
        only the SHA-256 hash. Expiry starts at verification and does not extend.
        """
        now = self._now()
        conn = self.get_connection()
        error_to_raise: Exception | None = None
        result: dict[str, Any] | None = None
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT mandate_id, user_id, agent_id, status, expires_at, code_hash
                        FROM mandates WHERE mandate_id = %s FOR UPDATE;
                        """,
                        (mandate_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise MandateNotFoundError(f"Mandate {mandate_id} not found")

                    m_id, user_id, agent_id, status_val, expires_at_val, cur_code_hash = row

                    if actor and actor != agent_id:
                        raise MandateError(
                            "FORBIDDEN",
                            "Only bound agent may issue terminal code",
                            status_code=403,
                        )

                    if status_val != "verified":
                        raise InvalidMandateStateError(
                            f"Mandate {mandate_id} is in status '{status_val}'; "
                            "must be verified to issue code"
                        )

                    if now >= expires_at_val:
                        cur.execute(
                            "UPDATE mandates SET status = 'expired' WHERE mandate_id = %s;",
                            (mandate_id,),
                        )
                        cur.execute(
                            """
                            INSERT INTO audit_log (
                                actor, action, entity, entity_id, policy_version, detail, ts
                            ) VALUES (
                                %s, 'mandate_expired', 'mandate', %s, 'v1.0', %s::jsonb, now()
                            );
                            """,
                            (
                                actor or agent_id,
                                mandate_id,
                                json.dumps({"stage": "issue_code"}),
                            ),
                        )
                        error_to_raise = MandateExpiredError(
                            f"Mandate {mandate_id} expired at {expires_at_val.isoformat()}"
                        )
                    else:
                        # Generate cryptographic 6-digit code
                        plain_code = f"{secrets.randbelow(900000) + 100000:06d}"
                        code_hash = hashlib.sha256(plain_code.encode("utf-8")).hexdigest()

                        # Activate mandate; DO NOT extend expires_at
                        cur.execute(
                            """
                            UPDATE mandates
                            SET status = 'active', code_hash = %s
                            WHERE mandate_id = %s;
                            """,
                            (code_hash, mandate_id),
                        )

                        cur.execute(
                            """
                            INSERT INTO audit_log (
                                actor, action, entity, entity_id, policy_version, detail, ts
                            ) VALUES (
                                %s, 'mandate_code_issued', 'mandate', %s, 'v1.0', %s::jsonb, now()
                            );
                            """,
                            (
                                actor or agent_id,
                                mandate_id,
                                json.dumps({"status": "active"}),
                            ),
                        )

                        result = {
                            "mandate_id": mandate_id,
                            "status": "active",
                            "code": plain_code,
                            "one_time_code": plain_code,
                            "expires_at": expires_at_val.isoformat(),
                        }
        finally:
            conn.close()

        if error_to_raise is not None:
            raise error_to_raise

        return result

    def redeem_mandate(
        self,
        mandate_id: str,
        code: str,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Redeem active mandate, verify SHA256 code, and debit ledger balance atomically."""
        now = self._now()
        submitted_hash = hashlib.sha256(str(code).strip().encode("utf-8")).hexdigest()

        conn = self.get_connection()
        error_to_raise: Exception | None = None
        result: dict[str, Any] | None = None
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    # 1. Fetch user_id for mandate to establish consistent lock order
                    cur.execute(
                        "SELECT user_id FROM mandates WHERE mandate_id = %s;",
                        (mandate_id,),
                    )
                    m_user = cur.fetchone()
                    if not m_user:
                        raise MandateNotFoundError(f"Mandate {mandate_id} not found")
                    user_id = m_user[0]

                    # 2. Acquire user row lock first (consistent user -> mandate lock order)
                    cur.execute(
                        "SELECT user_id FROM users WHERE user_id = %s FOR UPDATE;",
                        (user_id,),
                    )
                    if not cur.fetchone():
                        raise MandateNotFoundError(f"User '{user_id}' does not exist.")

                    # 3. Acquire mandate row lock second
                    cur.execute(
                        """
                        SELECT mandate_id, user_id, agent_id, amount_cap, code_hash,
                               status, expires_at, redemption_attempts
                        FROM mandates WHERE mandate_id = %s FOR UPDATE;
                        """,
                        (mandate_id,),
                    )
                    row = cur.fetchone()

                    (
                        m_id,
                        user_id,
                        agent_id,
                        amount_cap,
                        expected_code_hash,
                        status_val,
                        expires_at_val,
                        cur_red_attempts,
                    ) = row

                    if actor and actor != agent_id:
                        raise MandateError(
                            "FORBIDDEN",
                            "Only bound agent may redeem mandate",
                            status_code=403,
                        )

                    if status_val == "redeemed":
                        raise AlreadyRedeemedError(
                            f"Mandate {mandate_id} has already been redeemed"
                        )
                    if status_val == "rejected":
                        raise AccountLockedError(
                            f"Mandate {mandate_id} is locked after excessive failed attempts"
                        )
                    if status_val == "revoked":
                        raise InvalidMandateStateError(f"Mandate {mandate_id} is revoked")
                    if status_val != "active":
                        raise InvalidMandateStateError(
                            f"Mandate {mandate_id} is in status '{status_val}'; "
                            "must be active to redeem"
                        )

                    # Expiry check
                    if now >= expires_at_val:
                        cur.execute(
                            "UPDATE mandates SET status = 'expired' WHERE mandate_id = %s;",
                            (mandate_id,),
                        )
                        cur.execute(
                            """
                            INSERT INTO audit_log (
                                actor, action, entity, entity_id, policy_version, detail, ts
                            ) VALUES (
                                %s, 'mandate_expired', 'mandate', %s, 'v1.0', %s::jsonb, now()
                            );
                            """,
                            (
                                actor or agent_id,
                                mandate_id,
                                json.dumps({"stage": "redeem"}),
                            ),
                        )
                        error_to_raise = MandateExpiredError(
                            f"Mandate {mandate_id} expired at {expires_at_val.isoformat()}"
                        )

                    # Constant-time code hash verification
                    elif not secrets.compare_digest(submitted_hash, expected_code_hash or ""):
                        new_red_attempts = cur_red_attempts + 1
                        if new_red_attempts >= self.max_redemption_attempts:
                            cur.execute(
                                """
                                UPDATE mandates
                                SET status = 'rejected', redemption_attempts = %s
                                WHERE mandate_id = %s;
                                """,
                                (new_red_attempts, mandate_id),
                            )
                            cur.execute(
                                """
                                INSERT INTO cases (
                                    mandate_id, agent_id, reason, evidence, status, created_at
                                ) VALUES (
                                    %s, %s, 'repeated_code_failures_lockout',
                                    %s::jsonb, 'open', now()
                                ) RETURNING case_id;
                                """,
                                (
                                    mandate_id,
                                    agent_id,
                                    json.dumps({"failed_attempts": new_red_attempts}),
                                ),
                            )
                            case_id = cur.fetchone()[0]

                            cur.execute(
                                """
                                INSERT INTO audit_log (
                                    actor, action, entity, entity_id, policy_version, detail, ts
                                ) VALUES (
                                    %s, 'mandate_locked', 'mandate', %s, 'v1.0', %s::jsonb, now()
                                );
                                """,
                                (
                                    actor or agent_id,
                                    mandate_id,
                                    json.dumps(
                                        {
                                            "failed_attempts": new_red_attempts,
                                            "case_id": case_id,
                                        }
                                    ),
                                ),
                            )
                            error_to_raise = AccountLockedError(
                                f"Mandate {mandate_id} locked after {new_red_attempts} "
                                "consecutive failed attempts"
                            )
                        else:
                            cur.execute(
                                """
                                UPDATE mandates SET redemption_attempts = %s
                                WHERE mandate_id = %s;
                                """,
                                (new_red_attempts, mandate_id),
                            )
                            remaining = self.max_redemption_attempts - new_red_attempts
                            cur.execute(
                                """
                                INSERT INTO audit_log (
                                    actor, action, entity, entity_id, policy_version, detail, ts
                                ) VALUES (
                                    %s, 'mandate_redeem_failed', 'mandate', %s,
                                    'v1.0', %s::jsonb, now()
                                );
                                """,
                                (
                                    actor or agent_id,
                                    mandate_id,
                                    json.dumps(
                                        {
                                            "attempt": new_red_attempts,
                                            "remaining": remaining,
                                        }
                                    ),
                                ),
                            )
                            error_to_raise = InvalidCodeError(
                                f"Invalid one-time code ({remaining} attempt(s) remaining)"
                            )

                    else:
                        # Code verified: Compute financial amounts
                        amount_dec = Decimal(str(amount_cap)).quantize(Decimal("0.01"))
                        fee_dec = (amount_dec * self.official_fee_rate).quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        )
                        total_debit = amount_dec + fee_dec

                        # Re-check daily cumulative limit under user lock using injected now
                        cur.execute(
                            """
                            SELECT COALESCE(SUM(amount), 0)
                            FROM transactions
                            WHERE user_id = %s
                              AND txn_type = 'cash_out'
                              AND (ts AT TIME ZONE 'Asia/Dhaka')::date =
                                  (%s::timestamptz AT TIME ZONE 'Asia/Dhaka')::date;
                            """,
                            (user_id, now),
                        )
                        current_daily = Decimal(str(cur.fetchone()[0]))
                        if current_daily + amount_dec > self.daily_cash_out_limit:
                            cur.execute(
                                """
                                INSERT INTO audit_log (
                                    actor, action, entity, entity_id, policy_version, detail, ts
                                ) VALUES (%s, 'mandate_redeem_daily_limit_exceeded',
                                          'mandate', %s, 'v1.0', %s::jsonb, %s);
                                """,
                                (
                                    actor or agent_id,
                                    mandate_id,
                                    json.dumps(
                                        {
                                            "current_daily": float(current_daily),
                                            "attempted_amount": float(amount_dec),
                                            "daily_limit": float(self.daily_cash_out_limit),
                                        }
                                    ),
                                    now,
                                ),
                            )
                            error_to_raise = DailyLimitExceededError(
                                f"Cumulative daily cash-out would be "
                                f"{current_daily + amount_dec:.2f} BDT, exceeding daily limit "
                                f"of {self.daily_cash_out_limit:.2f} BDT"
                            )
                        else:
                            # Fetch user's latest balance from ledger
                            cur.execute(
                                """
                                SELECT balance_after FROM transactions
                                WHERE user_id = %s
                                ORDER BY ts DESC, txn_id DESC LIMIT 1;
                                """,
                                (user_id,),
                            )
                            bal_row = cur.fetchone()
                            current_balance = (
                                Decimal(str(bal_row[0]))
                                if bal_row and bal_row[0] is not None
                                else Decimal("0.00")
                            )

                            if current_balance < total_debit:
                                cur.execute(
                                    """
                                    INSERT INTO audit_log (
                                        actor, action, entity, entity_id, policy_version, detail, ts
                                    ) VALUES (%s, 'mandate_redeem_insufficient_balance',
                                              'mandate', %s, 'v1.0', %s::jsonb, %s);
                                    """,
                                    (
                                        actor or agent_id,
                                        mandate_id,
                                        json.dumps(
                                            {
                                                "current_balance": float(current_balance),
                                                "required_total": float(total_debit),
                                            }
                                        ),
                                        now,
                                    ),
                                )
                                error_to_raise = InsufficientBalanceError(
                                    f"Insufficient balance ({current_balance:.2f} BDT) "
                                    f"for withdrawal of {amount_dec:.2f} BDT and fee "
                                    f"of {fee_dec:.2f} BDT"
                                )
                            else:
                                new_balance = current_balance - total_debit

                                # Insert transaction record into transactions table
                                # with injected timestamp
                                cur.execute(
                                    """
                                    INSERT INTO transactions (
                                        user_id, agent_id, txn_type, credit_source,
                                        amount, fee, balance_after, channel, ts
                                    ) VALUES (
                                        %s, %s, 'cash_out', NULL, %s, %s, %s,
                                        'agent_initiated', %s
                                    ) RETURNING txn_id;
                                    """,
                                    (user_id, agent_id, amount_dec, fee_dec, new_balance, now),
                                )
                                txn_id = cur.fetchone()[0]

                                # Mark mandate as redeemed linking to transaction
                                cur.execute(
                                    """
                                    UPDATE mandates
                                    SET status = 'redeemed', redeemed_txn_id = %s
                                    WHERE mandate_id = %s;
                                    """,
                                    (txn_id, mandate_id),
                                )

                                cur.execute(
                                    """
                                    INSERT INTO audit_log (
                                        actor, action, entity, entity_id, policy_version, detail, ts
                                    ) VALUES (
                                        %s, 'mandate_redeemed', 'mandate', %s, 'v1.0',
                                        %s::jsonb, %s
                                    );
                                    """,
                                    (
                                        actor or agent_id,
                                        mandate_id,
                                        json.dumps(
                                            {
                                                "txn_id": txn_id,
                                                "amount": float(amount_dec),
                                                "fee": float(fee_dec),
                                                "balance_after": float(new_balance),
                                            }
                                        ),
                                        now,
                                    ),
                                )

                                result = {
                                    "txn_id": txn_id,
                                    "amount": float(amount_dec),
                                    "fee": float(fee_dec),
                                    "status": "redeemed",
                                }
        finally:
            conn.close()

        if error_to_raise is not None:
            raise error_to_raise

        return result

    def confirm_cash(
        self,
        mandate_id: str,
        cash_received: Any,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Customer reports physical cash received.

        Allowed only after redemption. Identical repeat report is idempotent;
        different report is rejected. Discrepancy beyond tolerance creates durable case.
        """
        parsed_received = parse_keypad_amount(cash_received)

        conn = self.get_connection()
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT mandate_id, user_id, agent_id, amount_cap, status
                        FROM mandates WHERE mandate_id = %s FOR UPDATE;
                        """,
                        (mandate_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise MandateNotFoundError(f"Mandate {mandate_id} not found")

                    m_id, user_id, agent_id, amount_cap, status_val = row

                    if actor and actor != user_id:
                        raise MandateError(
                            "FORBIDDEN",
                            "Only bound customer may confirm physical cash",
                            status_code=403,
                        )

                    if status_val != "redeemed":
                        raise InvalidMandateStateError(
                            "Cash confirmation allowed only after redemption"
                        )

                    amount_dec = Decimal(str(amount_cap)).quantize(Decimal("0.01"))

                    # Check for existing cash confirmation event
                    cur.execute(
                        """
                        SELECT event_id, cash_received_reported, outcome
                        FROM verification_events
                        WHERE mandate_id = %s AND cash_received_reported IS NOT NULL;
                        """,
                        (mandate_id,),
                    )
                    existing_ev = cur.fetchone()

                    if existing_ev:
                        prev_reported = Decimal(str(existing_ev[1])).quantize(Decimal("0.01"))
                        if abs(prev_reported - parsed_received) < Decimal("0.01"):
                            # Identical repeat report: idempotent return
                            gap = float(abs(amount_dec - prev_reported))
                            tolerance = max(
                                float(self.cash_gap_min_bdt),
                                float(self.cash_gap_rate) * float(amount_dec),
                            )
                            flagged = gap > tolerance

                            case_id = None
                            if flagged:
                                cur.execute(
                                    """
                                    SELECT case_id FROM cases
                                    WHERE mandate_id = %s
                                      AND reason = 'cash_gap_tolerance_exceeded';
                                    """,
                                    (mandate_id,),
                                )
                                c_row = cur.fetchone()
                                if c_row:
                                    case_id = c_row[0]

                            return {
                                "gap": gap,
                                "flagged": flagged,
                                "case_id": case_id,
                            }
                        else:
                            raise InvalidMandateStateError(
                                "Cash confirmation has already been recorded "
                                "with a different amount"
                            )

                    # First cash confirmation submission
                    gap_dec = abs(amount_dec - parsed_received)
                    gap = float(gap_dec)
                    tolerance = max(
                        float(self.cash_gap_min_bdt),
                        float(self.cash_gap_rate) * float(amount_dec),
                    )
                    flagged = gap > tolerance

                    case_id = None
                    if flagged:
                        cur.execute(
                            """
                            INSERT INTO cases (
                                mandate_id, agent_id, reason, evidence, status, created_at
                            ) VALUES (
                                %s, %s, 'cash_gap_tolerance_exceeded', %s::jsonb, 'open', now()
                            ) RETURNING case_id;
                            """,
                            (
                                mandate_id,
                                agent_id,
                                json.dumps(
                                    {
                                        "expected_amount": float(amount_dec),
                                        "cash_received": float(parsed_received),
                                        "gap": gap,
                                        "tolerance": tolerance,
                                    }
                                ),
                            ),
                        )
                        case_id = cur.fetchone()[0]

                    cur.execute(
                        """
                        INSERT INTO verification_events (
                            mandate_id, mode, stated_amount, outcome, cash_received_reported, ts
                        ) VALUES (%s, 'keypad', %s, 'match', %s, now());
                        """,
                        (mandate_id, amount_dec, parsed_received),
                    )

                    cur.execute(
                        """
                        INSERT INTO audit_log (
                            actor, action, entity, entity_id, policy_version, detail, ts
                        ) VALUES (%s, 'cash_confirmed', 'mandate', %s, 'v1.0', %s::jsonb, now());
                        """,
                        (
                            actor or "customer_channel",
                            mandate_id,
                            json.dumps(
                                {
                                    "cash_received": float(parsed_received),
                                    "gap": gap,
                                    "flagged": flagged,
                                    "case_id": case_id,
                                }
                            ),
                        ),
                    )

                    return {
                        "gap": gap,
                        "flagged": flagged,
                        "case_id": case_id,
                    }
        finally:
            conn.close()

    def revoke_mandate(
        self,
        mandate_id: str,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Revoke an unredeemed mandate."""
        conn = self.get_connection()
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT mandate_id, user_id, agent_id, status
                        FROM mandates WHERE mandate_id = %s FOR UPDATE;
                        """,
                        (mandate_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise MandateNotFoundError(f"Mandate {mandate_id} not found")

                    m_id, user_id, agent_id, status_val = row

                    if status_val == "redeemed":
                        raise AlreadyRedeemedError(
                            f"Cannot revoke already redeemed mandate {mandate_id}"
                        )

                    if status_val == "revoked":
                        return {"mandate_id": mandate_id, "status": "revoked"}

                    cur.execute(
                        "UPDATE mandates SET status = 'revoked' WHERE mandate_id = %s;",
                        (mandate_id,),
                    )

                    cur.execute(
                        """
                        INSERT INTO audit_log (
                            actor, action, entity, entity_id, policy_version, detail, ts
                        ) VALUES (%s, 'mandate_revoked', 'mandate', %s, 'v1.0', %s::jsonb, now());
                        """,
                        (
                            actor or "customer_channel",
                            mandate_id,
                            json.dumps({"previous_status": status_val}),
                        ),
                    )

                    return {"mandate_id": mandate_id, "status": "revoked"}
        finally:
            conn.close()
