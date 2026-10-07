"""Post-transaction confirmation (the main Sathi flow).

1. An agent records a completed cash-out. The ledger is debited and a check is opened.
2. The system calls the customer. The call never says the amount; the customer types the
   cash they received.
3. Same amount -> the transaction is "verified".
   Different amount (after one retry), "I did not do this" (# alone) or the secret help
   signal (amount typed with a leading 0) -> "suspicious" by fixed rules, with a plain-language
   rule-based recommendation and a case for a human supervisor. Nothing is ever labelled fraud.
4. No answer -> "no_answer"; a supervisor can call again.

Agents and customers only ever see neutral states ("checked" / "waiting"), so nobody near the
customer can learn that a transaction was flagged.
"""

from __future__ import annotations

import datetime
import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable

from app.mandates.service import MandateError, MandateService
from app.verification.keypad import KeypadParseError, parse_keypad_amount

OPEN_STATUSES = ("pending", "calling", "no_answer")
MAX_ATTEMPTS = 2

REASON_BY_OUTCOME = {
    "mismatch": "post_txn_amount_mismatch",
    "denied": "customer_denied_transaction",
    "duress": "duress_signal",
}


class CheckError(MandateError):
    pass


def _money(value: Any) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01")))


class TxnCheckService:
    def __init__(self, mandates: MandateService,
                 agent_score: Callable[[str], float | None] | None = None) -> None:
        self.mandates = mandates
        self._agent_score = agent_score

    def _conn(self):
        return self.mandates.get_connection()

    # ------------------------------------------------------------------ record cash-out
    def record_cashout(self, agent_id: str, user_id: str, amount: Any,
                       source: str = "agent") -> dict[str, Any]:
        try:
            value = parse_keypad_amount(amount)
        except KeypadParseError as exc:
            raise CheckError("INVALID_AMOUNT", f"Amount is not valid: {exc}", 422) from None
        if value <= 0:
            raise CheckError("INVALID_AMOUNT", "Amount must be more than zero.", 422)
        if value > self.mandates.user_cap_default:
            raise CheckError("AMOUNT_EXCEEDS_CAP",
                             f"The most one cash-out can be is "
                             f"৳{self.mandates.user_cap_default:,.0f}.", 422)
        fee = (value * self.mandates.official_fee_rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        now = datetime.datetime.now(datetime.timezone.utc)
        conn = self._conn()
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM users WHERE user_id = %s FOR UPDATE;", (user_id,))
                    if not cur.fetchone():
                        raise CheckError("USER_NOT_FOUND", "Customer not found.", 404)
                    cur.execute("SELECT 1 FROM agents WHERE agent_id = %s;", (agent_id,))
                    if not cur.fetchone():
                        raise CheckError("AGENT_NOT_FOUND", "Agent not found.", 404)
                    cur.execute(
                        """
                        SELECT COALESCE(SUM(amount), 0) FROM transactions
                        WHERE user_id = %s AND txn_type = 'cash_out'
                          AND (ts AT TIME ZONE 'Asia/Dhaka')::date =
                              (%s::timestamptz AT TIME ZONE 'Asia/Dhaka')::date;
                        """,
                        (user_id, now),
                    )
                    today = Decimal(str(cur.fetchone()[0]))
                    if today + value > self.mandates.daily_cash_out_limit:
                        raise CheckError(
                            "DAILY_LIMIT", "This customer has reached today's cash-out limit "
                            f"(৳{self.mandates.daily_cash_out_limit:,.0f}).", 422)
                    cur.execute(
                        "SELECT balance_after FROM transactions WHERE user_id = %s "
                        "ORDER BY ts DESC, txn_id DESC LIMIT 1;",
                        (user_id,),
                    )
                    row = cur.fetchone()
                    balance = Decimal(str(row[0])) if row and row[0] is not None else Decimal(0)
                    if balance < value + fee:
                        raise CheckError("INSUFFICIENT_BALANCE",
                                         "The customer does not have enough balance.", 422)
                    new_balance = balance - value - fee
                    cur.execute(
                        """
                        INSERT INTO transactions (
                            user_id, agent_id, txn_type, credit_source, amount, fee,
                            balance_after, channel, ts
                        ) VALUES (%s, %s, 'cash_out', NULL, %s, %s, %s, 'agent_initiated', %s)
                        RETURNING txn_id;
                        """,
                        (user_id, agent_id, value, fee, new_balance, now),
                    )
                    txn_id = cur.fetchone()[0]
                    cur.execute(
                        "INSERT INTO txn_checks (txn_id, user_id, agent_id, amount, status, "
                        "source) VALUES (%s, %s, %s, %s, 'pending', %s) RETURNING check_id;",
                        (txn_id, user_id, agent_id, value, source),
                    )
                    check_id = cur.fetchone()[0]
                    cur.execute(
                        "INSERT INTO call_tasks (check_id, user_id, agent_id) "
                        "VALUES (%s, %s, %s);",
                        (check_id, user_id, agent_id),
                    )
                    cur.execute(
                        """
                        INSERT INTO audit_log (
                            actor, action, entity, entity_id, policy_version, detail, ts
                        ) VALUES (%s, 'cashout_recorded', 'transaction', %s, 'v1.0',
                                  %s::jsonb, %s);
                        """,
                        (agent_id, str(txn_id), json.dumps(
                            {"user_id": user_id, "amount": float(value), "fee": float(fee),
                             "check_id": check_id}), now),
                    )
        finally:
            conn.close()
        return {"txn_id": txn_id, "check_id": check_id, "user_id": user_id,
                "agent_id": agent_id, "amount": float(value), "fee": float(fee),
                "balance_after": float(new_balance), "ts": now.isoformat()}

    # ------------------------------------------------------------------ reading
    _SELECT = """
        SELECT c.check_id, c.txn_id, c.user_id, c.agent_id, c.amount, c.status, c.outcome,
               c.stated_amount, c.attempts, c.recommendation, c.case_id, c.last_error,
               c.created_at, c.updated_at, t.fee, t.ts, t.balance_after, c.source
        FROM txn_checks c JOIN transactions t USING (txn_id)
    """

    @staticmethod
    def _row(r: tuple) -> dict[str, Any]:
        rec = r[9]
        return {
            "check_id": r[0], "txn_id": r[1], "user_id": r[2], "agent_id": r[3],
            "amount": _money(r[4]), "status": r[5], "outcome": r[6],
            "stated_amount": _money(r[7]) if r[7] is not None else None,
            "attempts": r[8],
            "recommendation": json.loads(rec) if isinstance(rec, str) else rec,
            "case_id": r[10], "last_error": r[11],
            "created_at": r[12].isoformat(), "updated_at": r[13].isoformat(),
            "fee": _money(r[14] or 0), "ts": r[15].isoformat(),
            "balance_after": _money(r[16]) if r[16] is not None else None,
            "source": r[17],
        }

    def get(self, check_id: int) -> dict[str, Any] | None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(self._SELECT + " WHERE c.check_id = %s;", (check_id,))
            row = cur.fetchone()
        return self._row(row) if row else None

    def list(self, status: str | None = None, user_id: str | None = None,
             agent_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        where, params = [], []
        if status:
            where.append("c.status = %s")
            params.append(status)
        if user_id:
            where.append("c.user_id = %s")
            params.append(user_id)
        if agent_id:
            where.append("c.agent_id = %s")
            params.append(agent_id)
        sql = self._SELECT + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY c.created_at DESC LIMIT %s;"
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(sql, (*params, limit))
            return [self._row(r) for r in cur.fetchall()]

    def balance(self, user_id: str) -> float | None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT balance_after FROM transactions WHERE user_id = %s "
                        "ORDER BY ts DESC, txn_id DESC LIMIT 1;", (user_id,))
            row = cur.fetchone()
        return _money(row[0]) if row and row[0] is not None else None

    def summary(self, hours: int = 24) -> dict[str, Any]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT status, count(*), COALESCE(sum(amount), 0) FROM txn_checks "
                "WHERE created_at > now() - make_interval(hours => %s) GROUP BY status;",
                (hours,),
            )
            rows = {r[0]: {"count": r[1], "amount": _money(r[2])} for r in cur.fetchall()}
        total = sum(v["count"] for v in rows.values())
        done = rows.get("verified", {}).get("count", 0) + rows.get("suspicious", {}).get(
            "count", 0)
        return {"by_status": rows, "total": total,
                "verified_rate": round(rows.get("verified", {}).get("count", 0) / done, 4)
                if done else None}

    # ------------------------------------------------------------------ call outcomes
    def set_calling(self, check_id: int) -> None:
        self._update(check_id, "UPDATE txn_checks SET status = 'calling', last_error = NULL, "
                               "updated_at = now() WHERE check_id = %s AND status IN "
                               "('pending','calling','no_answer');")

    def set_no_answer(self, check_id: int) -> None:
        self._update(check_id, "UPDATE txn_checks SET status = 'no_answer', updated_at = now() "
                               "WHERE check_id = %s AND status IN ('pending','calling');")

    def set_error(self, check_id: int, message: str) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE txn_checks SET last_error = %s, updated_at = now() "
                        "WHERE check_id = %s;", (message[:300], check_id))
            conn.commit()

    def _update(self, check_id: int, sql: str) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(sql, (check_id,))
            conn.commit()

    def handle_answer(self, check_id: int, digits: str) -> str:
        """Apply the customer's keypad answer. Returns 'retry' or the final status."""
        conn = self._conn()
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT txn_id, user_id, agent_id, amount, status, attempts "
                        "FROM txn_checks WHERE check_id = %s FOR UPDATE;",
                        (check_id,),
                    )
                    row = cur.fetchone()
                    if not row or row[4] not in OPEN_STATUSES:
                        return row[4] if row else "missing"
                    txn_id, user_id, agent_id, amount, _status, attempts = row
                    amount = Decimal(str(amount))
                    attempts += 1
                    stated: Decimal | None = None
                    if digits == "":
                        outcome = "denied"
                    elif len(digits) > 1 and digits.startswith("0"):
                        outcome = "duress"
                        stated = Decimal(int(digits))
                    else:
                        stated = Decimal(int(digits))
                        if stated == amount:
                            outcome = "match"
                        elif attempts < MAX_ATTEMPTS:
                            cur.execute(
                                "UPDATE txn_checks SET attempts = %s, stated_amount = %s, "
                                "status = 'calling', updated_at = now() WHERE check_id = %s;",
                                (attempts, stated, check_id),
                            )
                            return "retry"
                        else:
                            outcome = "mismatch"

                    return self._finalize(cur, check_id, txn_id, user_id, agent_id, amount,
                                          outcome, stated, attempts, actor=user_id,
                                          channel="phone call after cash-out")
        finally:
            conn.close()

    def _finalize(self, cur: Any, check_id: int, txn_id: int, user_id: str,
                  agent_id: str | None, amount: Decimal, outcome: str,
                  stated: Decimal | None, attempts: int, actor: str, channel: str,
                  note: str | None = None) -> str:
        """Close a check as verified or suspicious; suspicious opens a case automatically."""
        context = self._agent_context(cur, agent_id)
        rec = recommendation(outcome, amount, stated, context)
        status = "verified" if outcome == "match" else "suspicious"
        case_id = None
        if status == "suspicious":
            evidence = {
                "txn_id": txn_id, "check_id": check_id,
                "ledger_amount": float(amount),
                "stated_amount": float(stated) if stated is not None else None,
                "difference": float(amount - stated) if stated is not None
                and outcome == "mismatch" else None,
                "channel": channel,
                "recommendation": rec["label"],
                "reasons": [r["text"] for r in rec["reasons"]],
            }
            if note:
                evidence["supervisor_note"] = note
            if outcome == "duress":
                evidence["priority"] = "urgent"
                evidence["guidance"] = ("Customer used the secret help signal. Call "
                                        "them on the registered number, away from "
                                        "the agent.")
            cur.execute(
                """
                INSERT INTO cases (mandate_id, agent_id, reason, evidence, status,
                                   created_at)
                VALUES (NULL, %s, %s, %s::jsonb, 'open', now()) RETURNING case_id;
                """,
                (agent_id, REASON_BY_OUTCOME[outcome], json.dumps(evidence)),
            )
            case_id = cur.fetchone()[0]
            # The call may have come from the handset the agent holds, so this answer alone
            # cannot clear the case: it needs an independent follow-up (see CallCenterService).
            cur.execute("UPDATE call_tasks SET followup_status = 'required', "
                        "priority = CASE WHEN priority = 'urgent' THEN 'urgent' ELSE 'high' END,"
                        " updated_at = now() WHERE check_id = %s "
                        "AND followup_status = 'not_required';", (check_id,))
            if note:
                cur.execute(
                    "INSERT INTO case_notes (case_id, author, note_type, body) "
                    "VALUES (%s, %s, 'call_log', %s);",
                    (case_id, actor, note[:4000]),
                )
        cur.execute(
            """
            UPDATE txn_checks SET status = %s, outcome = %s, stated_amount = %s,
                attempts = %s, recommendation = %s::jsonb, case_id = %s,
                updated_at = now()
            WHERE check_id = %s;
            """,
            (status, outcome, stated, attempts, json.dumps(rec), case_id, check_id),
        )
        cur.execute(
            """
            INSERT INTO audit_log (
                actor, action, entity, entity_id, policy_version, detail, ts
            ) VALUES (%s, %s, 'transaction', %s, 'v1.0', %s::jsonb, now());
            """,
            (actor, f"txn_check_{status}", str(txn_id),
             json.dumps({"check_id": check_id, "case_id": case_id, "channel": channel})),
        )
        return status

    def handle_unclear(self, check_id: int) -> str:
        """The answer could not be understood. Re-ask once, then hand to a person."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT status, attempts FROM txn_checks WHERE check_id = %s FOR UPDATE;",
                (check_id,),
            )
            row = cur.fetchone()
            if not row or row[0] not in OPEN_STATUSES:
                return row[0] if row else "missing"
            attempts = row[1] + 1
            if attempts < MAX_ATTEMPTS:
                cur.execute("UPDATE txn_checks SET attempts = %s, status = 'calling', "
                            "updated_at = now() WHERE check_id = %s;", (attempts, check_id))
                conn.commit()
                return "retry"
            cur.execute("UPDATE txn_checks SET attempts = %s, status = 'manual_review', "
                        "updated_at = now() WHERE check_id = %s;", (attempts, check_id))
            conn.commit()
            return "manual_review"

    def set_status(self, check_id: int, status: str, from_statuses: tuple[str, ...]) -> bool:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE txn_checks SET status = %s, updated_at = now() "
                        "WHERE check_id = %s AND status = ANY(%s);",
                        (status, check_id, list(from_statuses)))
            conn.commit()
            return cur.rowcount > 0

    def apply_manual_outcome(self, check_id: int, outcome: str, stated: Any,
                             actor: str, note: str | None) -> str:
        """A supervisor spoke to the customer and records what they said."""
        if outcome not in ("match", "mismatch", "denied", "duress"):
            raise CheckError("INVALID_OUTCOME", "Unknown outcome.", 422)
        conn = self._conn()
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT txn_id, user_id, agent_id, amount, status, attempts "
                        "FROM txn_checks WHERE check_id = %s FOR UPDATE;",
                        (check_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise CheckError("CHECK_NOT_FOUND", "Transaction check not found.", 404)
                    if row[4] in ("verified", "suspicious"):
                        raise CheckError("CHECK_CLOSED", "This transaction is already closed.",
                                         409)
                    txn_id, user_id, agent_id, amount, _status, attempts = row
                    amount = Decimal(str(amount))
                    stated_value: Decimal | None = None
                    if stated not in (None, ""):
                        try:
                            stated_value = parse_keypad_amount(stated)
                        except KeypadParseError as exc:
                            raise CheckError("INVALID_AMOUNT", f"Amount is not valid: {exc}",
                                             422) from None
                    if outcome in ("match", "mismatch") and stated_value is None:
                        raise CheckError("AMOUNT_REQUIRED",
                                         "Type the amount the customer said they received.", 422)
                    if outcome == "match" and stated_value != amount:
                        outcome = "mismatch"
                    if outcome == "mismatch" and stated_value == amount:
                        outcome = "match"
                    return self._finalize(cur, check_id, txn_id, user_id, agent_id, amount,
                                          outcome, stated_value, attempts, actor=actor,
                                          channel="supervisor call", note=note)
        finally:
            conn.close()

    def _agent_context(self, cur: Any, agent_id: str | None) -> dict[str, Any]:
        if not agent_id:
            return {}
        cur.execute(
            "SELECT count(*) FROM txn_checks WHERE agent_id = %s AND status = 'suspicious' "
            "AND created_at > now() - interval '30 days';",
            (agent_id,),
        )
        flagged = int(cur.fetchone()[0])
        cur.execute(
            "SELECT 1 FROM agent_watchlist WHERE agent_id = %s;", (agent_id,))
        watch = cur.fetchone() is not None
        score = None
        if self._agent_score is not None:
            try:
                score = self._agent_score(agent_id)
            except Exception:
                score = None
        return {"agent_id": agent_id, "flagged_30d": flagged, "watchlisted": watch,
                "agent_score": score}


def recommendation(outcome: str, amount: Decimal, stated: Decimal | None,
                   context: dict[str, Any]) -> dict[str, Any]:
    """Plain-language, rule-based recommendation (not a model output). It never says 'fraud'; a
    person decides."""
    reasons: list[dict[str, Any]] = []
    if outcome == "match":
        label, headline = "verified", "Customer confirmed the same amount"
        reasons.append({"signal": "amount_match",
                        "text": f"The customer typed ৳{amount:,.0f}, the same as the "
                                "transaction."})
    else:
        label = "suspicious"
        if outcome == "mismatch":
            diff = amount - stated
            headline = "Customer typed a different amount"
            reasons.append({"signal": "amount_mismatch",
                            "text": f"The transaction says ৳{amount:,.0f} but the customer "
                                    f"typed ৳{stated:,.0f} twice "
                                    f"({'less' if diff > 0 else 'more'} by ৳{abs(diff):,.0f})."})
        elif outcome == "denied":
            headline = "Customer says they did not make this cash-out"
            reasons.append({"signal": "customer_denied",
                            "text": "The customer pressed # without an amount, meaning they "
                                    "did not ask for this cash-out."})
        else:
            headline = "Customer asked for help secretly"
            reasons.append({"signal": "secret_help",
                            "text": "The customer typed 0 before the amount, the secret help "
                                    "signal. Contact them away from the agent."})
    if label == "verified":
        context = {}  # agent history only matters when something looks wrong
    if context.get("flagged_30d"):
        reasons.append({"signal": "agent_history",
                        "text": f"This agent had {context['flagged_30d']} other suspicious "
                                "transaction(s) in the last 30 days."})
    if context.get("watchlisted"):
        reasons.append({"signal": "agent_watchlisted",
                        "text": "This agent is already under extra checks."})
    score = context.get("agent_score")
    if score is not None and score > 0.5:
        reasons.append({"signal": "agent_unusual",
                        "text": f"This agent's activity looks unusual compared with similar "
                                f"agents (score {score * 100:.0f}%)."})
    return {
        "label": label,
        "headline": headline,
        "reasons": reasons,
        "next_step": None if label == "verified" else (
            "Call the customer away from the agent first." if outcome == "duress"
            else "Check with the customer and review the agent's recent cash-outs."),
        "note": "This is a recommendation for a person to check. It is not a fraud decision.",
    }
