"""Staff accounts: supervisors and super admins.

PINs are hashed with salted PBKDF2-SHA256 and compared in constant time. The demo
principals from data/config.yaml are mirrored into the staff table so that admins can see
and assign work to them; extra supervisors are seeded so the multi-supervisor queue has
more than one person to share work.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from typing import Any, Callable

# Tests lower this through the environment; stored hashes carry their own iteration count.
PBKDF2_ITERATIONS = int(os.environ.get("SATHI_PBKDF2_ITERATIONS", "120000"))
STAFF_ROLES = ("supervisor", "super_admin")
STAFF_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")

# Synthetic demo supervisors (public demo PIN, never a real credential).
DEMO_SUPERVISORS = (
    ("sup_nadia", "Nadia Rahman"),
    ("sup_karim", "Karim Hossain"),
    ("sup_farzana", "Farzana Akter"),
)
DEMO_SUPERVISOR_PIN = "3456"
CONFIG_STAFF_NAMES = {"supervisor_777": "Demo Supervisor", "admin_777": "Demo Super Admin"}


class StaffError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def hash_pin(pin: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PBKDF2_ITERATIONS)
    return "pbkdf2$%d$%s$%s" % (
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_pin(pin: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_b64, digest_b64 = stored.split("$")
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), base64.b64decode(salt_b64),
                                     int(iterations))
        return hmac.compare_digest(digest, base64.b64decode(digest_b64))
    except (ValueError, TypeError):
        return False


def _valid_pin(pin: str) -> bool:
    return bool(re.fullmatch(r"\d{4,8}", pin or ""))


class StaffService:
    def __init__(self, get_connection: Callable) -> None:
        self._conn = get_connection

    # ------------------------------------------------------------------ seeding
    def seed(self, config_principals: dict[str, Any]) -> int:
        """Idempotently mirror config staff and add demo supervisors. Never changes PINs."""
        rows: list[tuple[str, str, str, str]] = []
        for info in config_principals.values():
            role = info.get("role")
            if role in STAFF_ROLES:
                sub = str(info.get("subject", ""))
                if STAFF_ID_RE.fullmatch(sub):
                    rows.append((sub, CONFIG_STAFF_NAMES.get(sub, sub), role,
                                 hash_pin(str(info.get("pin", "")))))
        for staff_id, name in DEMO_SUPERVISORS:
            rows.append((staff_id, name, "supervisor", hash_pin(DEMO_SUPERVISOR_PIN)))
        inserted = 0
        with self._conn() as conn, conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    "INSERT INTO staff (staff_id, display_name, role, pin_hash) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT (staff_id) DO NOTHING;",
                    row,
                )
                inserted += cur.rowcount
            conn.commit()
        return inserted

    # ------------------------------------------------------------------ auth
    def authenticate(self, staff_id: str, pin: str) -> dict[str, Any] | None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT staff_id, display_name, role, pin_hash, active FROM staff "
                        "WHERE staff_id = %s;", (staff_id,))
            row = cur.fetchone()
            # Hash anyway when the account is missing so timing does not reveal staff IDs.
            if not row:
                verify_pin(pin, hash_pin("0000"))
                return None
            if not row[4] or not verify_pin(pin, row[3]):
                return None
            cur.execute("UPDATE staff SET last_login_at = now() WHERE staff_id = %s;",
                        (staff_id,))
            conn.commit()
        return {"staff_id": row[0], "display_name": row[1], "role": row[2]}

    def is_active(self, staff_id: str) -> bool | None:
        """True/False for known staff, None when the subject is not in the staff table."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT active FROM staff WHERE staff_id = %s;", (staff_id,))
            row = cur.fetchone()
        return None if row is None else bool(row[0])

    # ------------------------------------------------------------------ management
    def list(self, role: str | None = None) -> list[dict[str, Any]]:
        where, params = "", []
        if role:
            where, params = "WHERE s.role = %s", [role]
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT s.staff_id, s.display_name, s.role, s.active, s.created_by,
                       s.created_at, s.last_login_at,
                       (SELECT count(*) FROM call_tasks t WHERE t.assigned_to = s.staff_id
                          AND t.status IN ('assigned','in_progress')) AS open_calls,
                       (SELECT count(*) FROM cases c WHERE c.assigned_to = s.staff_id
                          AND c.status IN ('open','escalated')) AS open_cases,
                       (SELECT count(*) FROM call_tasks t WHERE t.resolved_by = s.staff_id
                          AND t.resolved_at > now() - interval '24 hours') AS calls_24h,
                       (SELECT count(*) FROM audit_reports r WHERE r.author = s.staff_id
                          AND r.created_at > now() - interval '24 hours') AS reports_24h
                FROM staff s {where}
                ORDER BY s.role DESC, s.active DESC, s.display_name;
                """,
                params,
            )
            return [
                {"staff_id": r[0], "display_name": r[1], "role": r[2], "active": r[3],
                 "created_by": r[4], "created_at": r[5].isoformat(),
                 "last_login_at": r[6].isoformat() if r[6] else None,
                 "open_calls": r[7], "open_cases": r[8], "calls_resolved_24h": r[9],
                 "reports_24h": r[10]}
                for r in cur.fetchall()
            ]

    def get(self, staff_id: str) -> dict[str, Any] | None:
        return next((s for s in self.list() if s["staff_id"] == staff_id), None)

    def create(self, staff_id: str, display_name: str, role: str, pin: str,
               actor: str) -> dict[str, Any]:
        staff_id = (staff_id or "").strip().lower()
        if not STAFF_ID_RE.fullmatch(staff_id):
            raise StaffError("INVALID_STAFF_ID", "Staff ID must be 3-41 lowercase letters, "
                             "digits or underscores, starting with a letter.", 422)
        if role not in STAFF_ROLES:
            raise StaffError("INVALID_ROLE", "Role must be supervisor or super_admin.", 422)
        if not _valid_pin(pin):
            raise StaffError("INVALID_PIN", "PIN must be 4 to 8 digits.", 422)
        name = (display_name or "").strip()
        if not 2 <= len(name) <= 80:
            raise StaffError("INVALID_NAME", "Name must be 2 to 80 characters.", 422)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO staff (staff_id, display_name, role, pin_hash, created_by) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (staff_id) DO NOTHING;",
                (staff_id, name, role, hash_pin(pin), actor),
            )
            if cur.rowcount == 0:
                raise StaffError("STAFF_EXISTS", "A staff member with this ID already exists.",
                                 409)
            conn.commit()
        return self.get(staff_id) or {}

    def update(self, staff_id: str, actor: str, active: bool | None = None,
               display_name: str | None = None, pin: str | None = None) -> dict[str, Any]:
        if staff_id == actor and active is False:
            raise StaffError("SELF_DEACTIVATE", "You cannot deactivate your own account.", 409)
        sets, params = [], []
        if active is not None:
            sets.append("active = %s")
            params.append(bool(active))
        if display_name is not None:
            name = display_name.strip()
            if not 2 <= len(name) <= 80:
                raise StaffError("INVALID_NAME", "Name must be 2 to 80 characters.", 422)
            sets.append("display_name = %s")
            params.append(name)
        if pin is not None:
            if not _valid_pin(pin):
                raise StaffError("INVALID_PIN", "PIN must be 4 to 8 digits.", 422)
            sets.append("pin_hash = %s")
            params.append(hash_pin(pin))
        if not sets:
            raise StaffError("NOTHING_TO_UPDATE", "No changes given.", 422)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE staff SET {', '.join(sets)} WHERE staff_id = %s;",
                        (*params, staff_id))
            if cur.rowcount == 0:
                raise StaffError("STAFF_NOT_FOUND", "Staff member not found.", 404)
            if active is False:
                # Hand unfinished work back to the shared queue.
                cur.execute("UPDATE call_tasks SET status = 'needs_manual', assigned_to = NULL, "
                            "assigned_by = NULL, assigned_at = NULL, updated_at = now() "
                            "WHERE assigned_to = %s AND status IN ('assigned','in_progress');",
                            (staff_id,))
                cur.execute("UPDATE cases SET assigned_to = NULL, assigned_by = NULL, "
                            "assigned_at = NULL WHERE assigned_to = %s "
                            "AND status IN ('open','escalated');", (staff_id,))
            conn.commit()
        return self.get(staff_id) or {}

    def active_supervisors(self) -> list[str]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT staff_id FROM staff WHERE role = 'supervisor' AND active "
                        "ORDER BY staff_id;")
            return [r[0] for r in cur.fetchall()]

    def require_active_supervisor(self, staff_id: str) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT role, active FROM staff WHERE staff_id = %s;", (staff_id,))
            row = cur.fetchone()
        if not row:
            raise StaffError("STAFF_NOT_FOUND", "Staff member not found.", 404)
        if row[0] != "supervisor" or not row[1]:
            raise StaffError("NOT_ASSIGNABLE", "Work can only be assigned to an active "
                             "supervisor.", 409)


def get_staff_service() -> StaffService:
    from app.mandates.router import get_mandate_service

    return StaffService(get_mandate_service().get_connection)
