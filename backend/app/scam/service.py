"""Send money with a recipient safety check, and the receiver-risk engine.

Problem: personal upay accounts are not allowed to sell goods, yet social-media "shops"
take payments into personal numbers, and some never deliver. Victims pay many small,
identical amounts (the product price) from many unrelated wallets in a short time, and
scam accounts often move the money out quickly.

Receiver-risk signals (last 24 hours unless stated), each explainable to a supervisor:
- fan_in        many different senders paid this personal account
- same_amount   most payments have exactly the same amount (a price point)
- burst         many payments inside one hour
- strangers     senders had never paid this account before (not family or friends)
- pass_through  money leaves soon after it arrives (cash-out or sent on within 2 hours)
- new_account   the account is less than 30 days old
- community     anonymous community reports about this number (verified ones weigh more)

The score is a transparent weighted sum, so every point can be explained. It never
blocks money. It (1) warns payers before they pay, (2) opens a review case for a
supervisor, and (3) suggests a merchant account to honest sellers.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from typing import Any, Callable

from app.scam.identifiers import IdentifierError, mask_msisdn, normalize_msisdn

MAX_SEND = Decimal("25000")
DAILY_SEND_LIMIT = Decimal("50000")
LEVELS = (("high", 0.70), ("caution", 0.45), ("watch", 0.25))
WEIGHTS = {"fan_in": 0.25, "same_amount": 0.25, "burst": 0.15, "strangers": 0.10,
           "pass_through": 0.15, "new_account": 0.05, "community": 0.40}
REASON_TEXT = {
    "fan_in": "{senders} different people paid this personal account in 24 hours.",
    "same_amount": "{same_share:.0%} of those payments were exactly ৳{top_amount:,.0f}, like a "
                   "product price.",
    "burst": "{burst} payments arrived within one hour.",
    "strangers": "{stranger_share:.0%} of payers had never paid this account before.",
    "pass_through": "{pass_through:.0%} of the money left the account within 2 hours.",
    "new_account": "The account is only {age_days} days old.",
    "community": "{reports} community report(s) about this number ({verified} verified by "
                 "upay).",
}
CUSTOMER_WARNING = {
    "same_amount": "Many people paid this personal number the same amount today. Personal "
                   "accounts are not allowed to sell products.",
    "community": "Other customers reported this number for a scam.",
    "pass_through": "Money sent to this number is moved out very quickly.",
    "fan_in": "This personal number is receiving payments from many strangers.",
}


class TransferError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400,
                 extra: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code
        self.extra = extra or {}


def _level(score: float) -> str | None:
    return next((name for name, cut in LEVELS if score >= cut), None)


class ScamService:
    def __init__(self, get_connection: Callable) -> None:
        self._conn = get_connection

    # ------------------------------------------------------------------ lookups
    def user_by_msisdn(self, msisdn: str) -> str | None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users WHERE msisdn = %s;", (msisdn,))
            row = cur.fetchone()
        return row[0] if row else None

    def msisdn_of(self, user_id: str) -> str | None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT msisdn FROM users WHERE user_id = %s;", (user_id,))
            row = cur.fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------ receiver risk
    def features(self, receiver_ids: list[str] | None = None,
                 min_inbound: int = 3) -> dict[str, dict[str, Any]]:
        """Aggregate the signals in PostgreSQL for one receiver or all active ones."""
        params: dict[str, Any] = {"min": min_inbound}
        scope = ""
        if receiver_ids is not None:
            scope = "AND p.receiver_id = ANY(%(ids)s)"
            params["ids"] = receiver_ids
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                WITH w AS (
                  SELECT p.* FROM p2p_transfers p
                  WHERE p.created_at > now() - interval '24 hours' {scope}
                ), agg AS (
                  SELECT receiver_id, count(*) n, count(DISTINCT sender_id) senders,
                         sum(amount) total
                  FROM w GROUP BY receiver_id HAVING count(*) >= %(min)s
                ), top_amount AS (
                  SELECT DISTINCT ON (receiver_id) receiver_id, amount, count(*) c
                  FROM w GROUP BY receiver_id, amount
                  ORDER BY receiver_id, count(*) DESC, amount
                ), burst AS (
                  SELECT receiver_id, max(c) b FROM (
                    SELECT a.receiver_id, a.transfer_id, count(*) c FROM w a JOIN w b
                      ON a.receiver_id = b.receiver_id
                     AND b.created_at BETWEEN a.created_at AND a.created_at + interval '1 hour'
                    GROUP BY a.receiver_id, a.transfer_id) x GROUP BY receiver_id
                ), strangers AS (
                  SELECT w.receiver_id, count(DISTINCT w.sender_id) FILTER (WHERE NOT EXISTS (
                      SELECT 1 FROM p2p_transfers e WHERE e.sender_id = w.sender_id
                        AND e.receiver_id = w.receiver_id
                        AND e.created_at < now() - interval '24 hours'
                        AND e.created_at > now() - interval '90 days')) s
                  FROM w GROUP BY w.receiver_id
                ), outflow AS (
                  SELECT a.receiver_id, COALESCE(sum(t.amount), 0) moved
                  FROM agg a JOIN transactions t ON t.user_id = a.receiver_id
                  WHERE t.txn_type IN ('cash_out','send')
                    AND t.ts > now() - interval '24 hours' AND t.ts <= now()
                  GROUP BY a.receiver_id
                )
                SELECT a.receiver_id, a.n, a.senders, a.total, ta.amount, ta.c, b.b, s.s,
                       COALESCE(o.moved, 0), u.created_at, u.msisdn
                FROM agg a
                JOIN top_amount ta USING (receiver_id)
                JOIN burst b USING (receiver_id)
                JOIN strangers s USING (receiver_id)
                LEFT JOIN outflow o USING (receiver_id)
                JOIN users u ON u.user_id = a.receiver_id;
                """, params)
            rows = cur.fetchall()
            out: dict[str, dict[str, Any]] = {}
            now = datetime.datetime.now(datetime.timezone.utc)
            for r in rows:
                out[r[0]] = {
                    "inbound_24h": r[1], "senders": r[2], "total_bdt": float(r[3]),
                    "top_amount": float(r[4]), "same_share": r[5] / r[1], "burst": r[6],
                    "stranger_share": r[7] / r[2] if r[2] else 0.0,
                    "pass_through": min(1.0, float(r[8]) / float(r[3])) if r[3] else 0.0,
                    "age_days": (now - r[9]).days, "msisdn": r[10],
                    "reports": 0, "verified": 0, "me_too": 0,
                }
            # Community reports can flag an account even before payments pile up.
            numbers = {f"upay_number:{v['msisdn']}": k for k, v in out.items() if v["msisdn"]}
            cur.execute(
                "SELECT identifier_norm, count(*) FILTER (WHERE status IN "
                "('published','verified')), count(*) FILTER (WHERE status = 'verified'), "
                "COALESCE(sum(me_too_count) FILTER (WHERE status IN ('published','verified')), 0) "
                "FROM community_reports WHERE identifier_type IN ('upay_number','whatsapp') "
                + ("AND identifier_norm = ANY(%(keys)s) " if receiver_ids is not None else "")
                + "GROUP BY identifier_norm;",
                {"keys": [f"upay_number:{m}" for m in self._msisdns(cur, receiver_ids)]}
                if receiver_ids is not None else {})
            for norm, reports, verified, me_too in cur.fetchall():
                number = norm.split(":", 1)[1]
                uid = numbers.get(f"upay_number:{number}")
                if uid is None:
                    cur.execute("SELECT user_id, created_at FROM users WHERE msisdn = %s;",
                                (number,))
                    found = cur.fetchone()
                    if not found or not reports:
                        continue
                    uid = found[0]
                    out.setdefault(uid, {
                        "inbound_24h": 0, "senders": 0, "total_bdt": 0.0, "top_amount": 0.0,
                        "same_share": 0.0, "burst": 0, "stranger_share": 0.0,
                        "pass_through": 0.0, "age_days": (now - found[1]).days,
                        "msisdn": number, "reports": 0, "verified": 0, "me_too": 0})
                out[uid].update(reports=int(reports), verified=int(verified),
                                me_too=int(me_too))
        return out

    @staticmethod
    def _msisdns(cur: Any, user_ids: list[str] | None) -> list[str]:
        if not user_ids:
            return []
        cur.execute("SELECT msisdn FROM users WHERE user_id = ANY(%s) AND msisdn IS NOT NULL;",
                    (user_ids,))
        return [r[0] for r in cur.fetchall()]

    @staticmethod
    def score(f: dict[str, Any]) -> tuple[float, list[dict[str, Any]], str]:
        hits: dict[str, float] = {}
        if f["senders"] >= 10:
            hits["fan_in"] = 1.0
        elif f["senders"] >= 5:
            hits["fan_in"] = 0.6
        if f["inbound_24h"] >= 5 and f["same_share"] >= 0.6:
            hits["same_amount"] = 1.0 if f["same_share"] >= 0.8 else 0.7
        if f["burst"] >= 8:
            hits["burst"] = 1.0
        elif f["burst"] >= 5:
            hits["burst"] = 0.6
        if f["senders"] >= 5 and f["stranger_share"] >= 0.8:
            hits["strangers"] = 1.0
        if f["inbound_24h"] >= 3 and f["pass_through"] >= 0.7:
            hits["pass_through"] = 1.0
        if f["inbound_24h"] >= 5 and f["age_days"] < 30:
            hits["new_account"] = 1.0
        community = min(1.0, 0.4 * f["reports"] + 0.15 * f["me_too"] / 5 + 1.0 * f["verified"])
        if community > 0:
            hits["community"] = min(1.0, community)
        score = min(1.0, sum(WEIGHTS[k] * v for k, v in hits.items()))
        reasons = [{"signal": k, "weight": round(WEIGHTS[k] * v, 3),
                    "text": REASON_TEXT[k].format(**f)} for k, v in
                   sorted(hits.items(), key=lambda kv: -WEIGHTS[kv[0]] * kv[1])]
        scam_like = "community" in hits or "pass_through" in hits
        kind = "possible_scam" if scam_like else "unregistered_business"
        return round(score, 4), reasons, kind

    def evaluate(self, receiver_ids: list[str] | None = None,
                 actor: str = "sathi-risk") -> list[dict[str, Any]]:
        """Score receivers, keep receiver_flags in sync, open a case for high risk."""
        results = []
        feats = self.features(receiver_ids)
        with self._conn() as conn:
            with conn.transaction(), conn.cursor() as cur:
                for uid, f in feats.items():
                    score, reasons, kind = self.score(f)
                    level = _level(score)
                    if level is None:
                        cur.execute("DELETE FROM receiver_flags WHERE user_id = %s "
                                    "AND case_id IS NULL;", (uid,))
                        continue
                    cur.execute("SELECT case_id FROM receiver_flags WHERE user_id = %s;", (uid,))
                    row = cur.fetchone()
                    case_id = row[0] if row else None
                    if level == "high" and case_id is None:
                        case_id = self._open_case(cur, uid, f, score, reasons, kind)
                    elif case_id is not None and kind == "possible_scam":
                        # A shop-like account that starts to look like a scam: escalate the
                        # open case instead of opening a second one.
                        cur.execute(
                            "UPDATE cases SET reason = 'p2p_scam_seller_suspected', "
                            "evidence = evidence || %s::jsonb WHERE case_id = %s "
                            "AND reason = 'p2p_merchant_misuse' AND status IN "
                            "('open','escalated');",
                            (json.dumps({"kind": kind, "score": score,
                                         "reasons": [r["text"] for r in reasons],
                                         "escalated": "payment pattern now looks like a scam"}),
                             case_id))
                    cur.execute(
                        """
                        INSERT INTO receiver_flags (user_id, score, level, reasons, features,
                                                    case_id)
                        VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
                        ON CONFLICT (user_id) DO UPDATE SET score = EXCLUDED.score,
                            level = EXCLUDED.level, reasons = EXCLUDED.reasons,
                            features = EXCLUDED.features,
                            case_id = COALESCE(receiver_flags.case_id, EXCLUDED.case_id),
                            updated_at = now();
                        """,
                        (uid, score, level, json.dumps(reasons), json.dumps({**f, "kind": kind}),
                         case_id))
                    results.append({"user_id": uid, "score": score, "level": level,
                                    "kind": kind, "case_id": case_id})
        return results

    @staticmethod
    def _open_case(cur: Any, uid: str, f: dict[str, Any], score: float,
                   reasons: list[dict[str, Any]], kind: str) -> int:
        reason = "p2p_scam_seller_suspected" if kind == "possible_scam" else \
            "p2p_merchant_misuse"
        evidence = {
            "receiver": uid, "upay_number": mask_msisdn(f.get("msisdn") or ""),
            "score": score, "kind": kind,
            "reasons": [r["text"] for r in reasons],
            "inbound_24h": f["inbound_24h"], "senders": f["senders"],
            "top_amount": f["top_amount"], "total_bdt": f["total_bdt"],
            "community_reports": f["reports"], "verified_reports": f["verified"],
            "recommendation": (
                "Contact the account holder. If they sell goods, ask them to open a upay "
                "merchant account. If payers report non-delivery, follow the scam procedure "
                "and contact the reporting customers." if kind == "unregistered_business" else
                "Treat as a possible scam seller: review community reports, contact recent "
                "payers, and escalate to the fraud team. Money is not blocked automatically."),
        }
        cur.execute("INSERT INTO cases (mandate_id, agent_id, reason, evidence, status) "
                    "VALUES (NULL, NULL, %s, %s::jsonb, 'open') RETURNING case_id;",
                    (reason, json.dumps(evidence)))
        case_id = cur.fetchone()[0]
        cur.execute("INSERT INTO audit_log (actor, action, entity, entity_id, policy_version, "
                    "detail, ts) VALUES ('sathi-risk', 'receiver_flagged', 'user', %s, 'v1.0', "
                    "%s::jsonb, now());", (uid, json.dumps({"case_id": case_id, "score": score})))
        return case_id

    # ------------------------------------------------------------------ payer side
    def check_recipient(self, payer_id: str, raw_number: str) -> dict[str, Any]:
        try:
            msisdn = normalize_msisdn(raw_number)
        except IdentifierError as exc:
            raise TransferError("INVALID_NUMBER", str(exc), 422) from None
        receiver = self.user_by_msisdn(msisdn)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FILTER (WHERE status IN ('published','verified')), "
                "count(*) FILTER (WHERE status = 'verified'), "
                "array_agg(DISTINCT category) FILTER (WHERE status IN ('published','verified')) "
                "FROM community_reports WHERE identifier_norm IN (%s, %s);",
                (f"upay_number:{msisdn}", f"whatsapp:{msisdn}"))
            reports, verified, categories = cur.fetchone()
            flag = None
            known = False
            if receiver:
                cur.execute("SELECT level, reasons FROM receiver_flags WHERE user_id = %s;",
                            (receiver,))
                flag = cur.fetchone()
                cur.execute("SELECT 1 FROM p2p_transfers WHERE sender_id = %s AND "
                            "receiver_id = %s LIMIT 1;", (payer_id, receiver))
                known = cur.fetchone() is not None
        warnings = []
        level = "none"
        if reports:
            warnings.append(CUSTOMER_WARNING["community"])
            level = "high" if verified or reports >= 2 else "caution"
        if flag:
            signals = [r["signal"] for r in (flag[1] if isinstance(flag[1], list)
                                             else json.loads(flag[1]))]
            for s in ("same_amount", "pass_through", "fan_in"):
                if s in signals and CUSTOMER_WARNING[s] not in warnings:
                    warnings.append(CUSTOMER_WARNING[s])
            if flag[0] == "high" or (flag[0] == "caution" and level == "none"):
                level = "high" if flag[0] == "high" else "caution"
        return {
            "number": msisdn, "masked": mask_msisdn(msisdn), "exists": receiver is not None,
            "is_self": receiver == payer_id, "paid_before": known,
            "warning_level": level, "warnings": warnings,
            "community_reports": int(reports or 0), "verified_reports": int(verified or 0),
            "report_categories": categories or [],
            "advice": ("Only pay people you know. For online shopping, prefer cash on delivery "
                       "or a verified upay merchant." if level != "none" else None),
        }

    def send(self, sender_id: str, raw_number: str, amount: Any, reference: str | None,
             acknowledged: bool, source: str = "app") -> dict[str, Any]:
        check = self.check_recipient(sender_id, raw_number)
        if not check["exists"]:
            raise TransferError("RECIPIENT_NOT_FOUND", "No upay account uses this number.", 404)
        if check["is_self"]:
            raise TransferError("SELF_TRANSFER", "You cannot send money to yourself.", 422)
        if check["warning_level"] == "high" and not acknowledged:
            raise TransferError("WARNING_NOT_ACKNOWLEDGED",
                                "Please read the warning and confirm before sending.", 409,
                                {"check": check})
        try:
            value = Decimal(str(amount)).quantize(Decimal("0.01"))
        except Exception:
            raise TransferError("INVALID_AMOUNT", "Enter a valid amount.", 422) from None
        if value <= 0 or value > MAX_SEND:
            raise TransferError("INVALID_AMOUNT", f"Send between ৳1 and ৳{MAX_SEND:,.0f}.", 422)
        receiver = self.user_by_msisdn(check["number"])
        now = datetime.datetime.now(datetime.timezone.utc)
        with self._conn() as conn:
            with conn.transaction(), conn.cursor() as cur:
                # Lock both wallets in a fixed order so two transfers never deadlock.
                for uid in sorted((sender_id, receiver)):
                    cur.execute("SELECT 1 FROM users WHERE user_id = %s FOR UPDATE;", (uid,))
                cur.execute("SELECT COALESCE(sum(amount), 0) FROM p2p_transfers "
                            "WHERE sender_id = %s AND created_at > now() - interval '24 hours';",
                            (sender_id,))
                if Decimal(str(cur.fetchone()[0])) + value > DAILY_SEND_LIMIT:
                    raise TransferError("DAILY_LIMIT",
                                        f"Daily send limit is ৳{DAILY_SEND_LIMIT:,.0f}.", 422)
                balances = {}
                for uid in (sender_id, receiver):
                    cur.execute("SELECT balance_after FROM transactions WHERE user_id = %s "
                                "ORDER BY ts DESC, txn_id DESC LIMIT 1;", (uid,))
                    row = cur.fetchone()
                    balances[uid] = Decimal(str(row[0])) if row and row[0] is not None else \
                        Decimal(0)
                if balances[sender_id] < value:
                    raise TransferError("INSUFFICIENT_BALANCE", "Not enough balance.", 422)
                cur.execute(
                    "INSERT INTO transactions (user_id, agent_id, txn_type, credit_source, amount, "
                    "fee, balance_after, channel, ts) VALUES (%s, NULL, 'send', NULL, %s, 0, %s, "
                    "'app', %s) RETURNING txn_id;",
                    (sender_id, value, balances[sender_id] - value, now))
                sender_txn = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO transactions (user_id, agent_id, txn_type, credit_source, amount, "
                    "fee, balance_after, channel, ts) VALUES (%s, NULL, 'credit', 'p2p', %s, 0, "
                    "%s, 'app', %s) RETURNING txn_id;",
                    (receiver, value, balances[receiver] + value, now))
                receiver_txn = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO p2p_transfers (sender_id, receiver_id, amount, sender_txn_id, "
                    "receiver_txn_id, reference, warning_level, warning_acknowledged, source, "
                    "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "RETURNING transfer_id;",
                    (sender_id, receiver, value, sender_txn, receiver_txn,
                     (reference or "").strip()[:80] or None, check["warning_level"],
                     bool(acknowledged), source, now))
                transfer_id = cur.fetchone()[0]
        try:
            self.evaluate([receiver])
        except Exception:
            pass  # risk scoring must never undo a completed transfer
        return {"transfer_id": transfer_id, "amount": float(value), "to": check["masked"],
                "balance_after": float(balances[sender_id] - value), "ts": now.isoformat(),
                "warning_level": check["warning_level"]}

    # ------------------------------------------------------------------ staff views
    def flagged(self, level: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        where = "WHERE f.level = %s" if level else ""
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT f.user_id, u.msisdn, f.score, f.level, f.reasons, f.features, f.case_id, "
                "f.first_flagged_at, f.updated_at, c.status FROM receiver_flags f "
                "JOIN users u USING (user_id) LEFT JOIN cases c ON c.case_id = f.case_id "
                f"{where} ORDER BY f.score DESC, f.updated_at DESC LIMIT %s;",
                ((level, limit) if level else (limit,)))
            rows = cur.fetchall()
        return [{"user_id": r[0], "upay_number": mask_msisdn(r[1] or ""), "score": float(r[2]),
                 "level": r[3], "reasons": r[4], "features": r[5], "case_id": r[6],
                 "case_status": r[9], "first_flagged_at": r[7].isoformat(),
                 "updated_at": r[8].isoformat()} for r in rows]


def get_scam_service() -> ScamService:
    from app.mandates.router import get_mandate_service

    return ScamService(get_mandate_service().get_connection)
