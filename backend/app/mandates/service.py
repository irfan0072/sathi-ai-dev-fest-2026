"""Mandate Service and Deterministic Policy Engine for Sathi.

Implements mandate lifecycle, single-use one-time hashed codes, TTL expiry,
repeated wrong-code lockout, cash gap anomaly detection, audit logging,
and policy parameter enforcement loaded from data/config.yaml.
"""

from __future__ import annotations

import datetime
import hashlib
import secrets
import uuid
from datetime import timezone
from pathlib import Path
from typing import Any

import yaml


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


class MandateRecord:
    """Internal mandate entity."""

    def __init__(
        self,
        mandate_id: str,
        user_id: str,
        agent_id: str,
        amount: float,
        purpose: str,
        expires_at: datetime.datetime,
        code_hash: str = "",
        status: str = "requested",
        created_at: datetime.datetime | None = None,
        redeemed_txn_id: int | None = None,
    ):
        self.mandate_id = mandate_id
        self.user_id = user_id
        self.agent_id = agent_id
        self.amount = float(amount)
        self.purpose = purpose
        self.code_hash = code_hash
        self.status = status
        self.expires_at = expires_at
        self.created_at = created_at or datetime.datetime.now(timezone.utc)
        self.redeemed_txn_id = redeemed_txn_id

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


class MandateService:
    """Mandate Service implementing deterministic policy engine rules."""

    def __init__(
        self,
        config_path: str | Path | None = None,
        db_url: str | None = None,
    ) -> None:
        self.db_url = db_url
        self.policy = self._load_policy_config(config_path)

        # Policy parameters with guaranteed fallbacks
        self.user_cap_default: float = float(self.policy.get("user_cap_default", 5000.0))
        self.daily_cash_out_limit: float = float(self.policy.get("daily_cash_out_limit", 25000.0))
        self.mandate_ttl_minutes: int = int(self.policy.get("mandate_ttl_minutes", 15))
        self.max_verification_attempts: int = int(self.policy.get("max_verification_attempts", 2))
        
        cash_gap_conf = self.policy.get("cash_gap", {})
        self.cash_gap_min_bdt: float = float(cash_gap_conf.get("min_bdt", 50.0))
        self.cash_gap_rate: float = float(cash_gap_conf.get("rate", 0.02))

        # In-memory stores
        self.mandates: dict[str, MandateRecord] = {}
        self.verification_events: list[dict[str, Any]] = []
        self.cases: list[dict[str, Any]] = []
        self.audit_log: list[dict[str, Any]] = []
        self.redemption_attempts: dict[str, int] = {}
        self.user_daily_totals: dict[tuple[str, str], float] = {}

        self._txn_counter: int = 900000

    def _load_policy_config(self, config_path: str | Path | None) -> dict[str, Any]:
        """Load policy configuration from config.yaml."""
        search_paths = []
        if config_path:
            search_paths.append(Path(config_path))
        
        cwd = Path.cwd()
        search_paths.extend([
            cwd / "data" / "config.yaml",
            cwd.parent / "data" / "config.yaml",
            Path(__file__).resolve().parent.parent.parent.parent / "data" / "config.yaml",
        ])

        for path in search_paths:
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    if isinstance(data, dict) and "policy" in data:
                        return data["policy"]
                except Exception:
                    continue

        # Default fallback
        return {
            "mandate_ttl_minutes": 15,
            "user_cap_default": 5000.0,
            "daily_cash_out_limit": 25000.0,
            "max_verification_attempts": 2,
            "cash_gap": {"min_bdt": 50.0, "rate": 0.02},
        }

    def _now(self) -> datetime.datetime:
        """Current UTC timestamp."""
        return datetime.datetime.now(timezone.utc)

    def log_audit(
        self,
        actor: str,
        action: str,
        entity: str,
        entity_id: str,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record an entry into the audit trail."""
        entry = {
            "log_id": len(self.audit_log) + 1,
            "actor": actor,
            "action": action,
            "entity": entity,
            "entity_id": str(entity_id),
            "policy_version": "v1.0",
            "model_versions": {"policy_engine": "deterministic_v1"},
            "detail": detail or {},
            "ts": self._now().isoformat(),
        }
        self.audit_log.append(entry)
        return entry

    def create_case(
        self,
        mandate_id: str,
        agent_id: str,
        reason: str,
        evidence: dict[str, Any],
    ) -> int:
        """Create a review case in the case management store."""
        case_id = len(self.cases) + 1
        case = {
            "case_id": case_id,
            "mandate_id": mandate_id,
            "agent_id": agent_id,
            "reason": reason,
            "evidence": evidence,
            "status": "open",
            "created_at": self._now().isoformat(),
        }
        self.cases.append(case)
        return case_id

    def get_user_daily_cashout(self, user_id: str, date_str: str | None = None) -> float:
        """Compute user's cumulative cash-out amount for the given date (default today UTC)."""
        if date_str is None:
            date_str = self._now().strftime("%Y-%m-%d")
        return self.user_daily_totals.get((user_id, date_str), 0.0)

    def record_user_cashout(self, user_id: str, amount: float) -> None:
        """Record a completed cash-out towards the user's daily cumulative total."""
        date_str = self._now().strftime("%Y-%m-%d")
        current = self.user_daily_totals.get((user_id, date_str), 0.0)
        self.user_daily_totals[(user_id, date_str)] = current + amount

    def request_mandate(
        self,
        user_id: str,
        agent_id: str,
        amount: float,
        purpose: str = "cash_out",
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Initiate a cash-out mandate request with deterministic policy validation."""
        now = self._now()

        # 1. Basic amount validation
        if amount <= 0:
            raise InvalidAmountError(f"Mandate amount {amount} must be greater than zero")

        # 2. Amount cap check (default 5000 BDT)
        if amount > self.user_cap_default:
            raise AmountExceedsCapError(
                f"Requested amount {amount:.2f} BDT exceeds mandate cap of "
                f"{self.user_cap_default:.2f} BDT"
            )

        # 3. Daily cumulative limit check (default 25000 BDT)
        current_daily = self.get_user_daily_cashout(user_id)
        if current_daily + amount > self.daily_cash_out_limit:
            raise DailyLimitExceededError(
                f"Cumulative daily cash-out would be {current_daily + amount:.2f} BDT, "
                f"exceeding daily limit of {self.daily_cash_out_limit:.2f} BDT"
            )

        # 4. Check for existing active or requested unexpired mandate
        for m in self.mandates.values():
            if m.user_id == user_id and m.status in ("requested", "verified", "active"):
                if now < m.expires_at:
                    raise ActiveMandateExistsError(
                        f"Active unexpired mandate {m.mandate_id} already exists for user {user_id}"
                    )

        # 5. Create mandate
        mandate_id = str(uuid.uuid4())
        expires_at = now + datetime.timedelta(minutes=self.mandate_ttl_minutes)

        record = MandateRecord(
            mandate_id=mandate_id,
            user_id=user_id,
            agent_id=agent_id,
            amount=amount,
            purpose=purpose,
            expires_at=expires_at,
            code_hash="",
            status="requested",
            created_at=now,
        )
        self.mandates[mandate_id] = record

        # 6. Audit log
        self.log_audit(
            actor=actor or agent_id,
            action="mandate_requested",
            entity="mandate",
            entity_id=mandate_id,
            detail={"user_id": user_id, "agent_id": agent_id, "amount": amount, "purpose": purpose},
        )

        return {
            "mandate_id": mandate_id,
            "status": "requested",
            "next": "verify",
            "verification_modes": ["keypad", "voice"],
        }

    def verify_mandate(
        self,
        mandate_id: str,
        mode: str,
        stated_amount: float,
        attempt: int = 1,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Customer verification submission verifying stated amount and issuing one-time code."""
        now = self._now()
        record = self.mandates.get(mandate_id)
        if not record:
            raise MandateNotFoundError(f"Mandate {mandate_id} not found")

        # Check existing state
        if record.status == "active":
            raise AlreadyVerifiedError(f"Mandate {mandate_id} is already active")
        if record.status in ("redeemed", "revoked"):
            raise InvalidMandateStateError(f"Cannot verify mandate in {record.status} state")

        # Expiry check
        if now > record.expires_at:
            record.status = "expired"
            raise MandateExpiredError(
                f"Mandate {mandate_id} expired at {record.expires_at.isoformat()}"
            )

        # Attempt count check
        if attempt > self.max_verification_attempts:
            record.status = "rejected"
            raise MaxAttemptsExceededError(
                f"Attempt {attempt} exceeds max verification attempts of "
                f"{self.max_verification_attempts}"
            )

        # Record event
        event = {
            "event_id": len(self.verification_events) + 1,
            "mandate_id": mandate_id,
            "mode": mode,
            "stated_amount": stated_amount,
            "attempt": attempt,
            "ts": now.isoformat(),
        }
        self.verification_events.append(event)

        # Amount match comparison
        if abs(stated_amount - record.amount) < 0.01:
            # Match: Issue mandate
            # Cryptographically secure 6-digit random code (100000 - 999999)
            plain_code = f"{secrets.randbelow(900000) + 100000:06d}"
            code_hash = hashlib.sha256(plain_code.encode("utf-8")).hexdigest()

            # Store only hash
            record.code_hash = code_hash
            record.status = "active"
            record.expires_at = now + datetime.timedelta(minutes=self.mandate_ttl_minutes)

            self.log_audit(
                actor=actor or "customer_channel",
                action="mandate_verified",
                entity="mandate",
                entity_id=mandate_id,
                detail={"outcome": "match", "mode": mode, "attempt": attempt},
            )

            return {
                "outcome": "match",
                "decision": "ISSUE_MANDATE",
                "status": "active",
                "expires_at": record.expires_at.isoformat(),
                "code_delivery": "agent_terminal",
                "one_time_code": plain_code,  # Displayed only on verified response
                "case_id": None,
            }
        else:
            # Mismatch: Create review case
            record.status = "rejected"
            case_id = self.create_case(
                mandate_id=mandate_id,
                agent_id=record.agent_id,
                reason="stated_amount_mismatch",
                evidence={
                    "expected_amount": record.amount,
                    "stated_amount": stated_amount,
                    "mode": mode,
                    "attempt": attempt,
                },
            )

            self.log_audit(
                actor=actor or "customer_channel",
                action="mandate_verification_mismatch",
                entity="mandate",
                entity_id=mandate_id,
                detail={
                    "outcome": "mismatch",
                    "mode": mode,
                    "attempt": attempt,
                    "case_id": case_id,
                },
            )

            return {
                "outcome": "mismatch",
                "decision": "REVIEW",
                "status": "rejected",
                "expires_at": record.expires_at.isoformat(),
                "code_delivery": "agent_terminal",
                "one_time_code": None,
                "case_id": case_id,
            }

    def redeem_mandate(
        self,
        mandate_id: str,
        code: str,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Redeem an active mandate using the one-time code."""
        now = self._now()
        record = self.mandates.get(mandate_id)
        if not record:
            raise MandateNotFoundError(f"Mandate {mandate_id} not found")

        # Status validations
        if record.status == "redeemed":
            raise AlreadyRedeemedError(f"Mandate {mandate_id} has already been redeemed")
        if record.status == "locked":
            raise AccountLockedError(
                f"Mandate {mandate_id} is locked due to repeated failed attempts"
            )
        if record.status == "revoked":
            raise InvalidMandateStateError(f"Mandate {mandate_id} is revoked")
        if record.status != "active":
            raise InvalidMandateStateError(
                f"Mandate {mandate_id} is in status '{record.status}'; must be active to redeem"
            )

        # Expiry check
        if now > record.expires_at:
            record.status = "expired"
            raise MandateExpiredError(
                f"Mandate {mandate_id} expired at {record.expires_at.isoformat()}"
            )

        # Verify hashed code
        submitted_hash = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()
        if submitted_hash != record.code_hash:
            attempts = self.redemption_attempts.get(mandate_id, 0) + 1
            self.redemption_attempts[mandate_id] = attempts

            if attempts >= 3:
                record.status = "locked"
                case_id = self.create_case(
                    mandate_id=mandate_id,
                    agent_id=record.agent_id,
                    reason="repeated_code_failures_lockout",
                    evidence={"failed_attempts": attempts},
                )
                self.log_audit(
                    actor=actor or record.agent_id,
                    action="mandate_locked",
                    entity="mandate",
                    entity_id=mandate_id,
                    detail={"failed_attempts": attempts, "case_id": case_id},
                )
                raise AccountLockedError(
                    f"Mandate {mandate_id} locked after {attempts} consecutive failed attempts"
                )
            else:
                remaining = 3 - attempts
                self.log_audit(
                    actor=actor or record.agent_id,
                    action="mandate_redeem_failed",
                    entity="mandate",
                    entity_id=mandate_id,
                    detail={"attempt": attempts, "remaining": remaining},
                )
                raise InvalidCodeError(f"Invalid one-time code ({remaining} attempt(s) remaining)")

        # Success: Redeem mandate
        record.status = "redeemed"
        self._txn_counter += 1
        record.redeemed_txn_id = self._txn_counter

        # Track user's daily cashout
        self.record_user_cashout(record.user_id, record.amount)

        self.log_audit(
            actor=actor or record.agent_id,
            action="mandate_redeemed",
            entity="mandate",
            entity_id=mandate_id,
            detail={"txn_id": record.redeemed_txn_id, "amount": record.amount},
        )

        return {
            "txn_id": record.redeemed_txn_id,
            "amount": record.amount,
            "fee": 0.0,
            "status": "redeemed",
        }

    def confirm_cash(
        self,
        mandate_id: str,
        cash_received: float,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Post-redemption cash confirmation from customer calculating physical cash gap."""
        record = self.mandates.get(mandate_id)
        if not record:
            raise MandateNotFoundError(f"Mandate {mandate_id} not found")

        gap = round(abs(record.amount - cash_received), 2)
        tolerance = max(self.cash_gap_min_bdt, self.cash_gap_rate * record.amount)
        flagged = gap > tolerance

        case_id = None
        if flagged:
            case_id = self.create_case(
                mandate_id=mandate_id,
                agent_id=record.agent_id,
                reason="cash_gap_tolerance_exceeded",
                evidence={
                    "expected_amount": record.amount,
                    "cash_received": cash_received,
                    "gap": gap,
                    "tolerance": tolerance,
                },
            )

        self.log_audit(
            actor=actor or "customer_channel",
            action="cash_confirmed",
            entity="mandate",
            entity_id=mandate_id,
            detail={
                "cash_received": cash_received,
                "gap": gap,
                "flagged": flagged,
                "case_id": case_id,
            },
        )

        return {
            "gap": gap,
            "flagged": flagged,
            "case_id": case_id,
        }

    def revoke_mandate(
        self,
        mandate_id: str,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Revoke an unredeemed mandate."""
        record = self.mandates.get(mandate_id)
        if not record:
            raise MandateNotFoundError(f"Mandate {mandate_id} not found")

        if record.status == "redeemed":
            raise AlreadyRedeemedError(f"Cannot revoke already redeemed mandate {mandate_id}")

        old_status = record.status
        record.status = "revoked"

        self.log_audit(
            actor=actor or "customer_channel",
            action="mandate_revoked",
            entity="mandate",
            entity_id=mandate_id,
            detail={"previous_status": old_status},
        )

        return {
            "mandate_id": mandate_id,
            "status": "revoked",
        }
