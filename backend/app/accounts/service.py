"""Registered test accounts: real customers and agents created by a super admin.

Each account uses a real phone number. The customer or agent signs in with that number and
a PIN, and confirmation calls and SMS for a registered customer go to that number. The
synthetic numbers of seeded wallets are never dialled.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from app.staff.service import hash_pin, verify_pin

KINDS = ("customer", "agent")
REGIONS = ("dhaka", "chittagong", "rajshahi", "khulna", "barishal", "sylhet", "rangpur",
           "mymensingh")
MSISDN_RE = re.compile(r"^01[3-9]\d{8}$")
MAX_OPENING_BALANCE = Decimal("500000")
# An agent may serve this many registered customers (their token carries the list).
MAX_AGENT_CUSTOMERS = 500


class AccountError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def normalize_msisdn(raw: str) -> str:
    """Accept 01XXXXXXXXX, 8801XXXXXXXXX or +880 1XXX-XXXXXX."""
    digits = re.sub(r"[\s\-()]", "", raw or "")
    digits = re.sub(r"^\+?88(?=01)", "", digits)
    if not MSISDN_RE.fullmatch(digits):
        raise AccountError("INVALID_PHONE", "Enter a Bangladesh mobile number like "
                           "01712345678.", 422)
    return digits


def subject_for(kind: str, msisdn: str) -> str:
    return f"{'U' if kind == 'customer' else 'A'}_P_{msisdn}"


def e164(msisdn: str) -> str:
    return "+88" + msisdn


def _money(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise AccountError("INVALID_AMOUNT", "Amount must be a number.", 422) from exc
    if amount < 0 or amount > MAX_OPENING_BALANCE:
        raise AccountError("INVALID_AMOUNT", "Amount must be between 0 and "
                           f"{MAX_OPENING_BALANCE:,.0f} Taka.", 422)
    return amount


def _row(r: tuple) -> dict[str, Any]:
    return {"account_id": r[0], "kind": r[1], "msisdn": r[2], "subject": r[3] or r[4],
            "display_name": r[5], "active": r[6], "created_by": r[7],
            "created_at": r[8].isoformat(),
            "last_login_at": r[9].isoformat() if r[9] else None,
            "region": r[10], "balance": float(r[11]) if r[11] is not None else None}


_SELECT = """
    SELECT a.account_id, a.kind, a.msisdn, a.user_id, a.agent_id, a.display_name, a.active,
           a.created_by, a.created_at, a.last_login_at, COALESCE(u.region, g.region),
           (SELECT t.balance_after FROM transactions t WHERE a.user_id IS NOT NULL
              AND t.user_id = a.user_id ORDER BY t.ts DESC, t.txn_id DESC LIMIT 1)
    FROM registered_accounts a
    LEFT JOIN users u ON u.user_id = a.user_id
    LEFT JOIN agents g ON g.agent_id = a.agent_id
"""


class AccountService:
    def __init__(self, get_connection: Callable) -> None:
        self._conn = get_connection

    # ------------------------------------------------------------------ management
    def list(self) -> list[dict[str, Any]]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(_SELECT + " ORDER BY a.created_at DESC;")
            return [_row(r) for r in cur.fetchall()]

    def get(self, account_id: int) -> dict[str, Any] | None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(_SELECT + " WHERE a.account_id = %s;", (account_id,))
            r = cur.fetchone()
        return _row(r) if r else None

    def create(self, kind: str, phone: str, display_name: str, pin: str, region: str,
               opening_balance: Any, actor: str) -> dict[str, Any]:
        if kind not in KINDS:
            raise AccountError("INVALID_KIND", "Kind must be customer or agent.", 422)
        msisdn = normalize_msisdn(phone)
        name = (display_name or "").strip()
        if not 2 <= len(name) <= 80:
            raise AccountError("INVALID_NAME", "Name must be 2 to 80 characters.", 422)
        if not re.fullmatch(r"\d{4,8}", pin or ""):
            raise AccountError("INVALID_PIN", "PIN must be 4 to 8 digits.", 422)
        region = (region or "dhaka").lower()
        if region not in REGIONS:
            raise AccountError("INVALID_REGION", "Unknown region.", 422)
        balance = _money(opening_balance or 0) if kind == "customer" else Decimal(0)
        subject = subject_for(kind, msisdn)
        table = "users" if kind == "customer" else "agents"
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT 1 FROM {table} WHERE msisdn = %s;", (msisdn,))
            if cur.fetchone():
                raise AccountError("PHONE_IN_USE", f"This number already belongs to a {kind}.",
                                   409)
            if kind == "customer":
                cur.execute(
                    "INSERT INTO users (user_id, region, urban_rural, msisdn) "
                    "VALUES (%s, %s, 'urban', %s) ON CONFLICT (user_id) DO NOTHING;",
                    (subject, region, msisdn))
            else:
                cur.execute(
                    "INSERT INTO agents (agent_id, region, volume_band, agent_type, msisdn) "
                    "VALUES (%s, %s, 'medium', 'normal', %s) ON CONFLICT (agent_id) DO NOTHING;",
                    (subject, region, msisdn))
            if cur.rowcount == 0:
                raise AccountError("PHONE_IN_USE", f"This number already belongs to a {kind}.",
                                   409)
            cur.execute(
                "INSERT INTO registered_accounts (kind, msisdn, user_id, agent_id, display_name, "
                "pin_hash, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "RETURNING account_id;",
                (kind, msisdn, subject if kind == "customer" else None,
                 subject if kind == "agent" else None, name, hash_pin(pin), actor))
            account_id = cur.fetchone()[0]
            if balance > 0:
                self._credit(cur, subject, balance, Decimal(0))
            conn.commit()
        return self.get(account_id) or {}

    def update(self, account_id: int, active: bool | None = None,
               display_name: str | None = None, pin: str | None = None) -> dict[str, Any]:
        sets, params = [], []
        if active is not None:
            sets.append("active = %s")
            params.append(bool(active))
        if display_name is not None:
            name = display_name.strip()
            if not 2 <= len(name) <= 80:
                raise AccountError("INVALID_NAME", "Name must be 2 to 80 characters.", 422)
            sets.append("display_name = %s")
            params.append(name)
        if pin is not None:
            if not re.fullmatch(r"\d{4,8}", pin):
                raise AccountError("INVALID_PIN", "PIN must be 4 to 8 digits.", 422)
            sets.append("pin_hash = %s")
            params.append(hash_pin(pin))
        if not sets:
            raise AccountError("NOTHING_TO_UPDATE", "No changes given.", 422)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE registered_accounts SET {', '.join(sets)} "
                        "WHERE account_id = %s;", (*params, account_id))
            if cur.rowcount == 0:
                raise AccountError("ACCOUNT_NOT_FOUND", "Account not found.", 404)
            conn.commit()
        return self.get(account_id) or {}

    def add_money(self, account_id: int, amount: Any) -> dict[str, Any]:
        value = _money(amount)
        if value <= 0:
            raise AccountError("INVALID_AMOUNT", "Amount must be more than 0.", 422)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT user_id FROM registered_accounts WHERE account_id = %s;",
                        (account_id,))
            row = cur.fetchone()
            if not row:
                raise AccountError("ACCOUNT_NOT_FOUND", "Account not found.", 404)
            if not row[0]:
                raise AccountError("NOT_A_CUSTOMER", "Only customers have a balance.", 422)
            cur.execute("SELECT balance_after FROM transactions WHERE user_id = %s "
                        "ORDER BY ts DESC, txn_id DESC LIMIT 1 FOR UPDATE;", (row[0],))
            last = cur.fetchone()
            self._credit(cur, row[0], value, Decimal(str(last[0])) if last and last[0] else
                         Decimal(0))
            conn.commit()
        return self.get(account_id) or {}

    @staticmethod
    def _credit(cur: Any, user_id: str, amount: Decimal, balance: Decimal) -> None:
        cur.execute(
            "INSERT INTO transactions (user_id, agent_id, txn_type, credit_source, amount, fee, "
            "balance_after, channel, ts) VALUES (%s, NULL, 'credit', 'add_money', %s, 0, %s, "
            "'app', %s);",
            (user_id, amount, balance + amount, datetime.now(timezone.utc)))

    # ------------------------------------------------------------------ sign in
    def authenticate(self, kind: str, phone: str, pin: str) -> dict[str, Any] | None:
        try:
            msisdn = normalize_msisdn(phone)
        except AccountError:
            return None
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT account_id, COALESCE(user_id, agent_id), display_name, pin_hash, "
                        "active FROM registered_accounts WHERE kind = %s AND msisdn = %s;",
                        (kind, msisdn))
            row = cur.fetchone()
            # Hash anyway when the number is unknown so timing does not reveal accounts.
            if not row:
                verify_pin(pin, hash_pin("0000"))
                return None
            if not row[4] or not verify_pin(pin, row[3]):
                return None
            cur.execute("UPDATE registered_accounts SET last_login_at = now() "
                        "WHERE account_id = %s;", (row[0],))
            allowed: list[str] = []
            if kind == "agent":
                cur.execute("SELECT user_id FROM registered_accounts WHERE kind = 'customer' "
                            "AND active ORDER BY created_at LIMIT %s;", (MAX_AGENT_CUSTOMERS,))
                allowed = [r[0] for r in cur.fetchall()]
            conn.commit()
        return {"subject": row[1], "display_name": row[2], "allowed_users": allowed}


def registered_number(get_connection: Callable, user_id: str) -> str | None:
    """E.164 number of an active registered customer, else None (never a synthetic number)."""
    if not user_id.startswith("U_P_"):
        return None
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT msisdn FROM registered_accounts WHERE user_id = %s AND active;",
                        (user_id,))
            row = cur.fetchone()
    except Exception:
        return None
    return e164(row[0]) if row else None


def get_account_service() -> AccountService:
    from app.mandates.router import get_mandate_service

    return AccountService(get_mandate_service().get_connection)
