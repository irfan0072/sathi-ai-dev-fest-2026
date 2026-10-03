"""Anonymous community scam reports ("check before you pay").

- Customers report a seller by upay number, WhatsApp, Facebook/Instagram/Telegram page or
  website. Reports show as "unverified community reports" until a supervisor verifies them.
- Anonymity: only a keyed hash of the reporter is stored. Moderators and other customers
  never see who reported. One report per seller per customer; 5 reports per day each.
- Privacy: descriptions are redacted (phone numbers other than the reported one, emails,
  wallet IDs, long digit runs) and no reporter balance or transaction is ever shown.
- "Me too" lets other victims add weight without writing a new report.
- Supervisors verify, reject or hide reports; verified reports raise receiver risk and the
  warning shown to payers.
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Callable

from app.assistant.guard import EMAIL_RE, ID_RE, LONG_DIGITS_RE, PHONE_RE
from app.scam.identifiers import (
    BANGLA_DIGITS,
    IdentifierError,
    guess_type,
    mask_msisdn,
    normalize,
    reporter_hash,
)

CATEGORIES = {
    "not_delivered": "Paid but the product never came",
    "fake_product": "Fake or very different product",
    "advance_fee": "Asked for advance payment, then disappeared",
    "impersonation": "Pretended to be upay, a bank or a known shop",
    "investment": "Fake investment or double-your-money",
    "job_offer": "Fake job or training fee",
    "other": "Other",
}
DAILY_REPORTS = 5
PUBLIC = ("published", "verified")


class CommunityError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code


def clean_description(text: str, reported_number: str | None) -> str:
    """Strip personal data from free text; keep the reported number only."""
    out = (text or "").strip().translate(BANGLA_DIGITS)
    out = PHONE_RE.sub(lambda m: m.group(0) if reported_number and re.sub(
        r"\D", "", m.group(0)).endswith(reported_number[-10:]) else "[number hidden]", out)
    out = EMAIL_RE.sub("[email hidden]", out)
    out = ID_RE.sub("[id hidden]", out)
    if reported_number:
        out = out.replace(reported_number, "\x00")
    out = LONG_DIGITS_RE.sub("[number hidden]", out)
    if reported_number:
        out = out.replace("\x00", reported_number)
    return re.sub(r"\s+", " ", out)[:1000]


def _display(identifier_type: str, display: str, public: bool) -> str:
    if identifier_type in ("upay_number", "whatsapp") and public:
        return mask_msisdn(display)
    return display


class CommunityService:
    def __init__(self, get_connection: Callable) -> None:
        self._conn = get_connection

    def create(self, user_id: str, identifier_type: str | None, identifier: str,
               category: str, description: str, amount_lost: Any = None,
               incident_date: str | None = None, paid_via_upay: bool = False
               ) -> dict[str, Any]:
        kind = identifier_type or guess_type(identifier)
        try:
            norm, display = normalize(kind, identifier)
        except IdentifierError as exc:
            raise CommunityError("INVALID_IDENTIFIER", str(exc), 422) from None
        if category not in CATEGORIES:
            raise CommunityError("INVALID_CATEGORY", "Choose what happened.", 422)
        text = clean_description(description, display if kind in ("upay_number", "whatsapp")
                                 else None)
        if len(text) < 10:
            raise CommunityError("TOO_SHORT", "Describe what happened (at least 10 letters).",
                                 422)
        lost = None
        if amount_lost not in (None, ""):
            try:
                lost = round(float(amount_lost), 2)
            except (TypeError, ValueError):
                raise CommunityError("INVALID_AMOUNT", "Enter the amount you lost.", 422) from None
            if not 0 <= lost <= 10_000_000:
                raise CommunityError("INVALID_AMOUNT", "Enter the amount you lost.", 422)
        day = None
        if incident_date:
            try:
                day = datetime.date.fromisoformat(incident_date)
            except ValueError:
                raise CommunityError("INVALID_DATE", "Use a valid date.", 422) from None
            if day > datetime.date.today() + datetime.timedelta(days=1):
                raise CommunityError("INVALID_DATE", "The date cannot be in the future.", 422)
        if kind == "upay_number":
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT user_id FROM users WHERE msisdn = %s;", (display,))
                row = cur.fetchone()
            if row and row[0] == user_id:
                raise CommunityError("SELF_REPORT", "You cannot report your own number.", 422)
        who = reporter_hash(user_id)
        with self._conn() as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM community_reports WHERE reporter_hash = %s "
                            "AND created_at > now() - interval '24 hours';", (who,))
                if cur.fetchone()[0] >= DAILY_REPORTS:
                    raise CommunityError("RATE_LIMIT", "You can post 5 reports a day.", 429)
                cur.execute(
                    """
                    INSERT INTO community_reports (identifier_type, identifier_norm,
                        identifier_display, category, amount_lost, incident_date, description,
                        reporter_hash, paid_via_upay)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (identifier_norm, reporter_hash) DO NOTHING
                    RETURNING report_id;
                    """,
                    (kind, norm, display, category, lost, day, text, who, bool(paid_via_upay)))
                row = cur.fetchone()
                if row is None:
                    raise CommunityError("ALREADY_REPORTED",
                                         "You already reported this seller. Thank you.", 409)
        report_id = row[0]
        if kind in ("upay_number", "whatsapp"):
            self._rescore(display)
        return {"report_id": report_id, "identifier": _display(kind, display, True),
                "status": "published"}

    def _rescore(self, msisdn: str) -> None:
        from app.scam.service import ScamService

        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users WHERE msisdn = %s;", (msisdn,))
            row = cur.fetchone()
        if row:
            try:
                ScamService(self._conn).evaluate([row[0]])
            except Exception:
                pass

    def search(self, query: str, viewer_id: str | None = None) -> dict[str, Any]:
        kind = guess_type(query)
        try:
            norm, display = normalize(kind, query)
        except IdentifierError as exc:
            raise CommunityError("INVALID_IDENTIFIER", str(exc), 422) from None
        keys = [norm]
        if kind in ("upay_number", "whatsapp"):
            keys = [f"upay_number:{display}", f"whatsapp:{display}"]
        reports = self._list("r.identifier_norm = ANY(%s) AND r.status IN ('published','verified')",
                             (keys,), viewer_id, public=False)
        verified = sum(1 for r in reports if r["status"] == "verified")
        me_too = sum(r["me_too"] for r in reports)
        risk = None
        if kind in ("upay_number", "whatsapp"):
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT f.level FROM receiver_flags f JOIN users u USING (user_id) "
                            "WHERE u.msisdn = %s;", (display,))
                row = cur.fetchone()
                risk = row[0] if row else None
        level = "high" if verified or len(reports) >= 3 or risk == "high" else (
            "caution" if reports or risk in ("caution", "watch") else "none")
        return {"query": display, "type": kind, "level": level, "reports": reports,
                "report_count": len(reports), "verified_count": verified, "me_too": me_too,
                "payment_pattern_flag": risk is not None,
                "note": "Community reports are posted anonymously by customers and are "
                        "unverified unless marked verified by upay."}

    def _list(self, where: str, params: tuple, viewer_id: str | None, public: bool,
              limit: int = 50) -> list[dict[str, Any]]:
        viewer = reporter_hash(viewer_id) if viewer_id else ""
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT r.report_id, r.identifier_type, r.identifier_display, r.category,
                       r.amount_lost, r.incident_date, r.description, r.status, r.me_too_count,
                       r.created_at, r.paid_via_upay, r.reporter_hash = %s,
                       EXISTS(SELECT 1 FROM community_votes v WHERE v.report_id = r.report_id
                              AND v.voter_hash = %s AND v.kind = 'me_too')
                FROM community_reports r WHERE {where}
                ORDER BY r.created_at DESC LIMIT %s;
                """, (viewer, viewer, *params, limit))
            rows = cur.fetchall()
        return [{"report_id": r[0], "type": r[1], "identifier": _display(r[1], r[2], public),
                 "category": r[3], "category_text": CATEGORIES[r[3]],
                 "amount_lost": float(r[4]) if r[4] is not None else None,
                 "incident_date": r[5].isoformat() if r[5] else None, "description": r[6],
                 "status": r[7], "me_too": r[8], "posted_at": r[9].isoformat(),
                 "paid_via_upay": r[10], "mine": bool(r[11]), "i_also": bool(r[12])}
                for r in rows]

    def feed(self, viewer_id: str | None, limit: int = 30) -> dict[str, Any]:
        reports = self._list("r.status IN ('published','verified')", (), viewer_id, public=True,
                             limit=limit)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT identifier_type, identifier_display, count(*), sum(me_too_count), "
                "count(*) FILTER (WHERE status = 'verified') FROM community_reports "
                "WHERE status IN ('published','verified') AND created_at > now() - "
                "interval '30 days' GROUP BY identifier_type, identifier_display "
                "ORDER BY count(*) + sum(me_too_count) DESC LIMIT 8;")
            top = [{"type": r[0], "identifier": _display(r[0], r[1], True), "reports": r[2],
                    "me_too": int(r[3] or 0), "verified": r[4]} for r in cur.fetchall()]
            cur.execute("SELECT count(*), COALESCE(sum(amount_lost), 0) FROM community_reports "
                        "WHERE status IN ('published','verified') AND created_at > now() - "
                        "interval '30 days';")
            count, lost = cur.fetchone()
        return {"reports": reports, "most_reported": top,
                "stats_30d": {"reports": count, "amount_lost": float(lost)},
                "categories": CATEGORIES}

    def mine(self, user_id: str) -> list[dict[str, Any]]:
        return self._list("r.reporter_hash = %s", (reporter_hash(user_id),), user_id,
                          public=True)

    def me_too(self, report_id: int, user_id: str) -> dict[str, Any]:
        who = reporter_hash(user_id)
        with self._conn() as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("SELECT reporter_hash, status, identifier_type, identifier_display "
                            "FROM community_reports WHERE report_id = %s FOR UPDATE;",
                            (report_id,))
                row = cur.fetchone()
                if not row or row[1] not in PUBLIC:
                    raise CommunityError("NOT_FOUND", "Report not found.", 404)
                if row[0] == who:
                    raise CommunityError("OWN_REPORT", "This is your own report.", 409)
                cur.execute("INSERT INTO community_votes (report_id, voter_hash, kind) "
                            "VALUES (%s, %s, 'me_too') ON CONFLICT DO NOTHING;",
                            (report_id, who))
                if cur.rowcount:
                    cur.execute("UPDATE community_reports SET me_too_count = me_too_count + 1 "
                                "WHERE report_id = %s RETURNING me_too_count;", (report_id,))
                else:
                    cur.execute("SELECT me_too_count FROM community_reports "
                                "WHERE report_id = %s;", (report_id,))
                count = cur.fetchone()[0]
        if row[2] in ("upay_number", "whatsapp"):
            self._rescore(row[3])
        return {"report_id": report_id, "me_too": count}

    # ------------------------------------------------------------------ moderation
    def moderation_queue(self, status: str = "published", limit: int = 100) -> list[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.report_id, r.identifier_type, r.identifier_display, r.category,
                       r.amount_lost, r.description, r.status, r.me_too_count, r.created_at,
                       r.moderated_by, r.moderation_note,
                       (SELECT count(*) FROM community_reports o
                        WHERE o.identifier_norm = r.identifier_norm
                          AND o.status IN ('published','verified')),
                       u.user_id, f.level
                FROM community_reports r
                LEFT JOIN users u ON r.identifier_type IN ('upay_number','whatsapp')
                                 AND u.msisdn = r.identifier_display
                LEFT JOIN receiver_flags f ON f.user_id = u.user_id
                WHERE r.status = %s ORDER BY r.me_too_count DESC, r.created_at DESC LIMIT %s;
                """, (status, limit))
            rows = cur.fetchall()
        return [{"report_id": r[0], "type": r[1], "identifier": r[2], "category": r[3],
                 "category_text": CATEGORIES[r[3]],
                 "amount_lost": float(r[4]) if r[4] is not None else None,
                 "description": r[5], "status": r[6], "me_too": r[7],
                 "posted_at": r[8].isoformat(), "moderated_by": r[9], "note": r[10],
                 "reports_for_identifier": r[11], "wallet_user_id": r[12],
                 "payment_flag": r[13]} for r in rows]

    def moderate(self, report_id: int, decision: str, staff: str, note: str | None) -> dict:
        if decision not in ("verified", "rejected", "hidden", "published"):
            raise CommunityError("INVALID_DECISION", "Unknown decision.", 422)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE community_reports SET status = %s, moderated_by = %s, "
                        "moderated_at = now(), moderation_note = %s WHERE report_id = %s "
                        "RETURNING identifier_type, identifier_display;",
                        (decision, staff, (note or "")[:500] or None, report_id))
            row = cur.fetchone()
            if not row:
                raise CommunityError("NOT_FOUND", "Report not found.", 404)
            cur.execute("INSERT INTO audit_log (actor, action, entity, entity_id, policy_version, "
                        "detail, ts) VALUES (%s, %s, 'community_report', %s, 'v1.0', "
                        "'{}'::jsonb, now());", (staff, f"community_report_{decision}",
                                                 str(report_id)))
            conn.commit()
        if row[0] in ("upay_number", "whatsapp"):
            self._rescore(row[1])
        return {"report_id": report_id, "status": decision}
