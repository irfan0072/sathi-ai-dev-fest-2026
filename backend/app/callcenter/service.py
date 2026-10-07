"""Call management: automatic retries, the manual supervisor queue and response records.

Lifecycle of one call task (one per post-cash-out check):

    auto ──no answer──▶ retry_scheduled ──(delay)──▶ auto ...   (up to N automatic calls)
      │                      └── N attempts used ──▶ ignored     (customer unreachable)
      ├──answer not understood twice──▶ needs_manual ──claim/assign──▶ assigned
      │                                                              └─▶ in_progress ─▶ resolved
      └──clear answer──▶ resolved

A call that could not be placed (provider down, no registered number) is counted as an
attempt and retried with the same back-off; after the last attempt it goes to the manual queue
with reason `provider_failure`, so a committed check is never stranded. If the provider may
have accepted the call (timeout), no second call is placed: the live-call guard holds until the
provider reports or the ring timeout fires.

A suspicious check also needs an independent follow-up (`followup_status`): calling the same
handset again does not prove the customer is free to speak. A case cannot be cleared until a
supervisor records `reached_independently` through an in-person channel; `uncertain` and
`unreachable` keep it open.

A super admin can push an ignored task back to the manual queue, assign any task to a
supervisor, or spread the pending queue evenly across active supervisors. Supervisors
claim from the shared pending list; a claim is a single conditional UPDATE, so two
supervisors can never take the same call.
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Any, Callable

from app.mandates.service import MandateService

MANUAL_RESULTS = {
    "confirmed": "match",
    "amount_mismatch": "mismatch",
    "denied": "denied",
    "duress": "duress",
}
OTHER_RESULTS = ("unreachable", "callback")
FOLLOWUP_OPEN = ("required", "attempted", "uncertain", "unreachable")
FOLLOWUP_OUTCOMES = ("attempted", "reached_independently", "uncertain", "unreachable")
# registered_number is the KYC handset: it may be the very phone the agent holds, so reaching
# it never proves independence. Only an in-person (supervised) contact can.
FOLLOWUP_CHANNELS = ("registered_number", "in_person")
OPEN_TASK_STATUSES = ("auto", "retry_scheduled", "needs_manual", "assigned", "in_progress")
TRANSCRIPT_RETENTION_DAYS = int(os.environ.get("SATHI_TRANSCRIPT_RETENTION_DAYS", "30") or 30)
DEFAULT_POLICY = {"max_auto_attempts": 3, "retry_delay_seconds": 120,
                  "ring_timeout_seconds": 45, "unclear_confidence": 0.6}


class CallCenterError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _float(value: Any) -> float | None:
    return float(value) if value is not None else None


class CallCenterService:
    def __init__(self, mandates: MandateService,
                 policy: Callable[[], dict[str, Any]] | None = None) -> None:
        self.mandates = mandates
        self._policy = policy

    def _conn(self):
        return self.mandates.get_connection()

    def policy(self) -> dict[str, Any]:
        if self._policy is not None:
            return {**DEFAULT_POLICY, **self._policy()}
        try:
            from app.settings.router import get_settings

            values = get_settings().values()
            return {
                "max_auto_attempts": int(values["calls.max_auto_attempts"]),
                "retry_delay_seconds": int(values["calls.retry_delay_seconds"]),
                "ring_timeout_seconds": int(values["calls.ring_timeout_seconds"]),
                "unclear_confidence": float(values["calls.unclear_confidence"]),
            }
        except Exception:
            return dict(DEFAULT_POLICY)

    # ------------------------------------------------------------------ hooks
    @staticmethod
    def _ensure(cur: Any, check_id: int) -> None:
        cur.execute(
            "INSERT INTO call_tasks (check_id, user_id, agent_id) "
            "SELECT check_id, user_id, agent_id FROM txn_checks WHERE check_id = %s "
            "ON CONFLICT (check_id) DO NOTHING;",
            (check_id,),
        )

    def record_response(self, check_id: int, interpreted: str, channel: str = "ivr",
                        call_id: str | None = None, raw: str | None = None,
                        amount: Any = None, confidence: float | None = None,
                        recorded_by: str = "sathi-ivr") -> None:
        # Transcript text is the only free text we keep from a call (audio is never stored).
        # It is redacted of phone numbers, identifiers and long digit runs, capped, and purged
        # after the retention period (`purge_transcripts`).
        from app.copilot.guard import redact_value

        text = redact_value((raw or "").strip())[:200] or None
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO call_responses (check_id, call_id, channel, raw_input, "
                "interpreted, amount, confidence, recorded_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s);",
                (check_id, call_id, channel, text, interpreted, amount,
                 confidence, recorded_by),
            )
            conn.commit()

    def purge_transcripts(self, retention_days: int = TRANSCRIPT_RETENTION_DAYS) -> int:
        """Erase stored transcript text older than the retention period. The parsed outcome
        (interpreted, amount, confidence) stays for the audit trail. Returns rows cleared."""
        retention_days = max(1, int(retention_days))
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE call_responses SET raw_input = NULL WHERE raw_input IS NOT NULL "
                "AND created_at < now() - make_interval(days => %s);", (retention_days,))
            cleared = cur.rowcount
            if cleared:
                cur.execute(
                    "INSERT INTO audit_log (actor, action, entity, entity_id, policy_version, "
                    "detail, ts) VALUES ('sathi-scheduler', 'transcripts_purged', "
                    "'call_responses', 'retention', 'v1.0', %s::jsonb, now());",
                    (json.dumps({"cleared": cleared, "retention_days": retention_days}),))
            conn.commit()
        return cleared

    def on_call_placed(self, check_id: int, automatic: bool = True) -> None:
        """A call went out. Staff-triggered re-calls do not use up automatic retries."""
        with self._conn() as conn, conn.cursor() as cur:
            self._ensure(cur, check_id)
            cur.execute(
                "UPDATE call_tasks SET status = CASE WHEN status IN ('auto','retry_scheduled') "
                "THEN 'auto' ELSE status END, "
                "auto_attempts = auto_attempts + %s, next_attempt_at = NULL, "
                "last_outcome = 'calling', updated_at = now() WHERE check_id = %s;",
                (1 if automatic else 0, check_id),
            )
            conn.commit()

    def on_no_answer(self, check_id: int, call_id: str | None = None) -> str:
        """Schedule the next automatic try, or give up and mark the task ignored."""
        policy = self.policy()
        self.record_response(check_id, "no_answer", call_id=call_id)
        with self._conn() as conn:
            with conn.transaction(), conn.cursor() as cur:
                self._ensure(cur, check_id)
                cur.execute("SELECT status, auto_attempts FROM call_tasks WHERE check_id = %s "
                            "FOR UPDATE;", (check_id,))
                status, attempts = cur.fetchone()
                if status not in ("auto", "retry_scheduled"):
                    cur.execute("UPDATE call_tasks SET last_outcome = 'no_answer', "
                                "updated_at = now() WHERE check_id = %s;", (check_id,))
                    return status
                if attempts >= policy["max_auto_attempts"]:
                    cur.execute(
                        "UPDATE call_tasks SET status = 'ignored', last_outcome = 'no_answer', "
                        "manual_reason = 'retries_exhausted', next_attempt_at = NULL, "
                        "resolution = 'unreachable', resolved_by = 'sathi-scheduler', "
                        "resolved_at = now(), updated_at = now() WHERE check_id = %s;",
                        (check_id,))
                    cur.execute("UPDATE txn_checks SET status = 'unreachable', updated_at = now() "
                                "WHERE check_id = %s AND status IN "
                                "('pending','calling','no_answer');", (check_id,))
                    self._audit(cur, "sathi-scheduler", "call_task_ignored", check_id,
                                {"attempts": attempts})
                    return "ignored"
                delay = policy["retry_delay_seconds"] * (2 ** max(0, attempts - 1))
                cur.execute(
                    "UPDATE call_tasks SET status = 'retry_scheduled', last_outcome = 'no_answer', "
                    "next_attempt_at = now() + make_interval(secs => %s), updated_at = now() "
                    "WHERE check_id = %s;",
                    (delay, check_id))
                return "retry_scheduled"

    def on_placement_failed(self, check_id: int, code: str, message: str,
                            automatic: bool = True, uncertain: bool = False) -> str:
        """The call could not be placed. Retry a bounded number of times, then a person.

        `uncertain` means the provider may have accepted the call: nothing is rescheduled and
        no duplicate is placed. The ring-timeout worker settles the live call later.
        """
        policy = self.policy()
        with self._conn() as conn:
            with conn.transaction(), conn.cursor() as cur:
                self._ensure(cur, check_id)
                cur.execute("SELECT status, auto_attempts FROM call_tasks WHERE check_id = %s "
                            "FOR UPDATE;", (check_id,))
                status, attempts = cur.fetchone()
                cur.execute(
                    "UPDATE call_tasks SET placement_failures = placement_failures + 1, "
                    "last_placement_error = %s, updated_at = now() WHERE check_id = %s;",
                    (f"{code}: {message}"[:300], check_id))
                if status not in ("auto", "retry_scheduled"):
                    return status  # already with a person or finished: just keep the evidence
                if uncertain:
                    cur.execute("UPDATE call_tasks SET last_outcome = 'placement_uncertain' "
                                "WHERE check_id = %s;", (check_id,))
                    self._audit(cur, "sathi-scheduler", "call_task_placement_uncertain",
                                check_id, {"code": code})
                    return status
                attempts += 1 if automatic else 0
                if attempts >= policy["max_auto_attempts"]:
                    cur.execute(
                        "UPDATE call_tasks SET status = 'needs_manual', "
                        "manual_reason = 'provider_failure', auto_attempts = %s, "
                        "priority = CASE WHEN priority = 'urgent' THEN 'urgent' ELSE 'high' END, "
                        "last_outcome = 'placement_failed', next_attempt_at = NULL, "
                        "updated_at = now() WHERE check_id = %s;", (attempts, check_id))
                    cur.execute("UPDATE txn_checks SET status = 'manual_review', "
                                "updated_at = now() WHERE check_id = %s AND status IN "
                                "('pending','calling','no_answer');", (check_id,))
                    self._audit(cur, "sathi-scheduler", "call_task_needs_manual", check_id,
                                {"reason": "provider_failure", "attempts": attempts,
                                 "code": code})
                    return "needs_manual"
                delay = policy["retry_delay_seconds"] * (2 ** max(0, attempts - 1))
                cur.execute(
                    "UPDATE call_tasks SET status = 'retry_scheduled', auto_attempts = %s, "
                    "last_outcome = 'placement_failed', "
                    "next_attempt_at = now() + make_interval(secs => %s), updated_at = now() "
                    "WHERE check_id = %s;", (attempts, delay, check_id))
                self._audit(cur, "sathi-scheduler", "call_task_placement_retry", check_id,
                            {"code": code, "attempts": attempts, "delay_seconds": delay})
                return "retry_scheduled"

    def on_unclear(self, check_id: int, call_id: str | None, raw: str,
                   confidence: float | None, final: bool, reason: str = "") -> None:
        self.record_response(check_id, "unclear", call_id=call_id, raw=raw,
                             confidence=confidence)
        if not final:
            return
        with self._conn() as conn, conn.cursor() as cur:
            self._ensure(cur, check_id)
            cur.execute(
                "UPDATE call_tasks SET status = 'needs_manual', "
                "manual_reason = 'unclear_response', "
                "last_outcome = 'unclear', next_attempt_at = NULL, updated_at = now() "
                "WHERE check_id = %s AND status IN ('auto','retry_scheduled');",
                (check_id,))
            self._audit(cur, "sathi-ivr", "call_task_needs_manual", check_id,
                        {"reason": "unclear_response", "unclear_reason": reason or None})
            conn.commit()

    def on_resolved(self, check_id: int, check_status: str, actor: str = "sathi-ivr") -> None:
        if check_status not in ("verified", "suspicious"):
            return
        with self._conn() as conn, conn.cursor() as cur:
            self._ensure(cur, check_id)
            cur.execute(
                "UPDATE call_tasks SET status = 'resolved', resolution = %s, resolved_by = %s, "
                "resolved_at = now(), next_attempt_at = NULL, last_outcome = 'answered', "
                "priority = CASE WHEN %s = 'suspicious' THEN 'high' ELSE priority END, "
                "updated_at = now() WHERE check_id = %s AND status <> 'resolved';",
                (check_status, actor, check_status, check_id))
            conn.commit()

    def request_human(self, check_id: int, reason: str = "customer_requested_human",
                      note: str | None = None) -> None:
        """The customer asked for a person (key 9, or the assistant). High priority."""
        with self._conn() as conn:
            with conn.transaction(), conn.cursor() as cur:
                self._ensure(cur, check_id)
                cur.execute(
                    "UPDATE call_tasks SET status = 'needs_manual', manual_reason = %s, "
                    "priority = CASE WHEN priority = 'urgent' THEN 'urgent' ELSE 'high' END, "
                    "next_attempt_at = NULL, last_outcome = 'human_requested', updated_at = now() "
                    "WHERE check_id = %s AND status IN ('auto','retry_scheduled','ignored');",
                    (reason, check_id))
                cur.execute("UPDATE txn_checks SET status = 'manual_review', updated_at = now() "
                            "WHERE check_id = %s AND status IN "
                            "('pending','calling','no_answer','unreachable');", (check_id,))
                self._audit(cur, "customer", "call_task_human_requested", check_id,
                            {"reason": reason, "note": (note or "")[:300] or None})

    # ------------------------------------------------------------------ scheduler
    LEASE_SECONDS = 300

    def claim_due_retries(self, limit: int = 20) -> list[int]:
        """Atomically take due retries. SKIP LOCKED keeps several API workers from colliding.

        A task left in `auto` with no live call for longer than the lease (the process died
        after committing the cash-out or after claiming a retry, before the call went out) is
        claimed again, so no committed check waits forever. Tasks that already used every
        automatic attempt go to a person instead.
        """
        max_attempts = self.policy()["max_auto_attempts"]
        with self._conn() as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE call_tasks SET status = 'auto', updated_at = now()
                    WHERE task_id IN (
                        SELECT task_id FROM call_tasks
                        WHERE status = 'retry_scheduled' AND next_attempt_at <= now()
                        ORDER BY next_attempt_at LIMIT %s FOR UPDATE SKIP LOCKED)
                    RETURNING check_id;
                    """,
                    (limit,),
                )
                due = [r[0] for r in cur.fetchall()]
                stuck_filter = """
                    status = 'auto' AND updated_at < now() - make_interval(secs => %s)
                    AND check_id IN (SELECT check_id FROM txn_checks
                                     WHERE status IN ('pending','calling','no_answer'))
                    AND NOT EXISTS (SELECT 1 FROM voice_calls v
                                    WHERE v.check_id = call_tasks.check_id
                                      AND v.status IN ('queued','ringing','in_progress'))
                """
                cur.execute(
                    f"""
                    UPDATE call_tasks SET status = 'needs_manual',
                        manual_reason = 'provider_failure', last_outcome = 'placement_failed',
                        priority = CASE WHEN priority = 'urgent' THEN 'urgent' ELSE 'high' END,
                        updated_at = now()
                    WHERE {stuck_filter} AND auto_attempts >= %s
                    RETURNING check_id;
                    """,
                    (self.LEASE_SECONDS, max_attempts))
                for (check_id,) in cur.fetchall():
                    cur.execute("UPDATE txn_checks SET status = 'manual_review', "
                                "updated_at = now() WHERE check_id = %s;", (check_id,))
                    self._audit(cur, "sathi-scheduler", "call_task_needs_manual", check_id,
                                {"reason": "provider_failure", "stuck": True})
                cur.execute(
                    f"""
                    UPDATE call_tasks SET updated_at = now()
                    WHERE task_id IN (SELECT task_id FROM call_tasks WHERE {stuck_filter}
                                      AND auto_attempts < %s
                                      ORDER BY updated_at LIMIT %s FOR UPDATE SKIP LOCKED)
                    RETURNING check_id;
                    """,
                    (self.LEASE_SECONDS, max_attempts, limit))
                return due + [r[0] for r in cur.fetchall() if r[0] not in due]

    def stale_ringing_calls(self, ring_timeout_seconds: int, limit: int = 50) -> list[str]:
        """Simulated calls nobody picked up, real calls stuck without a provider update, and
        answered calls the customer abandoned mid-way (no answer for 3 minutes)."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT call_id FROM voice_calls
                WHERE (status IN ('queued','ringing')
                       AND ((provider = 'simulated'
                             AND created_at < now() - make_interval(secs => %s))
                            OR created_at < now() - interval '10 minutes'))
                   OR (status = 'in_progress'
                       AND updated_at < now() - interval '3 minutes')
                ORDER BY created_at LIMIT %s;
                """,
                (ring_timeout_seconds, limit),
            )
            return [str(r[0]) for r in cur.fetchall()]

    # ------------------------------------------------------------------ queue reads
    _SELECT = """
        SELECT t.task_id, t.check_id, t.user_id, t.agent_id, t.status, t.priority,
               t.auto_attempts, t.manual_attempts, t.next_attempt_at, t.last_outcome,
               t.manual_reason, t.assigned_to, t.assigned_by, t.assigned_at, t.started_at,
               t.resolved_at, t.resolved_by, t.resolution, t.created_at, t.updated_at,
               c.amount, c.status, c.txn_id, c.case_id, c.source,
               s.display_name,
               t.followup_status, t.followup_channel, t.followup_assigned_to,
               t.followup_attempts, t.placement_failures, t.last_placement_error
        FROM call_tasks t
        JOIN txn_checks c USING (check_id)
        LEFT JOIN staff s ON s.staff_id = t.assigned_to
    """

    @staticmethod
    def _row(r: tuple) -> dict[str, Any]:
        return {
            "task_id": r[0], "check_id": r[1], "user_id": r[2], "agent_id": r[3],
            "status": r[4], "priority": r[5], "auto_attempts": r[6], "manual_attempts": r[7],
            "next_attempt_at": _iso(r[8]), "last_outcome": r[9], "manual_reason": r[10],
            "assigned_to": r[11], "assigned_by": r[12], "assigned_at": _iso(r[13]),
            "started_at": _iso(r[14]), "resolved_at": _iso(r[15]), "resolved_by": r[16],
            "resolution": r[17], "created_at": _iso(r[18]), "updated_at": _iso(r[19]),
            "amount": _float(r[20]), "check_status": r[21], "txn_id": r[22],
            "case_id": r[23], "source": r[24], "assignee_name": r[25],
            "followup_status": r[26], "followup_channel": r[27],
            "followup_assigned_to": r[28], "followup_attempts": r[29],
            "placement_failures": r[30], "last_placement_error": r[31],
        }

    def queue(self, scope: str, actor: str, status: str | None = None,
              assignee: str | None = None, before_id: int | None = None,
              limit: int = 50, followup_actor: str | None = None) -> dict[str, Any]:
        where, params = [], []
        if scope == "followup":
            where.append("t.followup_status IN ('required','attempted','uncertain',"
                         "'unreachable')")
            if followup_actor:  # a supervisor sees the unassigned list and their own work
                where.append("(t.followup_assigned_to IS NULL OR t.followup_assigned_to = %s)")
                params.append(followup_actor)
        elif scope == "pending":
            where.append("t.status = 'needs_manual' AND t.assigned_to IS NULL")
        elif scope == "mine":
            where.append("t.assigned_to = %s AND t.status IN ('assigned','in_progress')")
            params.append(actor)
        elif scope == "manual":
            where.append("t.status IN ('needs_manual','assigned','in_progress')")
        elif scope == "retrying":
            where.append("t.status IN ('auto','retry_scheduled')")
        elif scope == "ignored":
            where.append("t.status = 'ignored'")
        elif scope == "resolved":
            where.append("t.status = 'resolved'")
        elif scope == "my_history":
            where.append("t.resolved_by = %s")
            params.append(actor)
        if status:
            where.append("t.status = %s")
            params.append(status)
        if assignee:
            where.append("t.assigned_to = %s")
            params.append(assignee)
        if before_id:
            where.append("t.task_id < %s")
            params.append(before_id)
        order = ("CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END, t.task_id"
                 if scope in ("pending", "mine", "manual", "followup") else "t.task_id DESC")
        sql = self._SELECT + (" WHERE " + " AND ".join(where) if where else "")
        sql += f" ORDER BY {order} LIMIT %s;"
        limit = max(1, min(limit, 200))
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(sql, (*params, limit + 1))
            rows = [self._row(r) for r in cur.fetchall()]
        more = len(rows) > limit
        rows = rows[:limit]
        return {"items": rows,
                "next_before_id": rows[-1]["task_id"] if more and order.endswith("DESC")
                else None}

    def get(self, task_id: int) -> dict[str, Any] | None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(self._SELECT + " WHERE t.task_id = %s;", (task_id,))
            row = cur.fetchone()
        return self._row(row) if row else None

    def detail(self, task_id: int) -> dict[str, Any] | None:
        task = self.get(task_id)
        if task is None:
            return None
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT response_id, call_id, channel, raw_input, interpreted, amount, "
                "confidence, recorded_by, created_at FROM call_responses "
                "WHERE check_id = %s ORDER BY created_at, response_id;",
                (task["check_id"],))
            task["responses"] = [
                {"response_id": r[0], "call_id": str(r[1]) if r[1] else None,
                 "channel": r[2], "raw_input": r[3], "interpreted": r[4],
                 "amount": _float(r[5]), "confidence": _float(r[6]), "recorded_by": r[7],
                 "at": _iso(r[8])} for r in cur.fetchall()]
            cur.execute(
                "SELECT call_id, provider, status, to_masked, digit_attempts, created_at, "
                "updated_at FROM voice_calls WHERE check_id = %s ORDER BY created_at;",
                (task["check_id"],))
            task["calls"] = [
                {"call_id": str(r[0]), "provider": r[1], "status": r[2], "to": r[3],
                 "digit_attempts": r[4], "at": _iso(r[5]), "updated_at": _iso(r[6])}
                for r in cur.fetchall()]
            cur.execute(
                "SELECT u.region, u.urban_rural, u.age_band, t.fee, t.ts, "
                "(SELECT balance_after FROM transactions b WHERE b.user_id = u.user_id "
                " ORDER BY b.ts DESC, b.txn_id DESC LIMIT 1) "
                "FROM txn_checks c JOIN users u USING (user_id) "
                "JOIN transactions t ON t.txn_id = c.txn_id WHERE c.check_id = %s;",
                (task["check_id"],))
            r = cur.fetchone()
            if r:
                task["customer"] = {"region": r[0], "area": r[1], "age_band": r[2]}
                task["transaction"] = {"fee": _float(r[3]), "ts": _iso(r[4]),
                                       "balance_after": _float(r[5])}
            cur.execute(
                "SELECT actor, action, detail, ts FROM audit_log "
                "WHERE entity = 'call_task' AND entity_id = %s ORDER BY ts;",
                (str(task_id),))
            task["history"] = [
                {"actor": r[0], "action": r[1],
                 "detail": json.loads(r[2]) if isinstance(r[2], str) else r[2],
                 "at": _iso(r[3])} for r in cur.fetchall()]
        return task

    # ------------------------------------------------------------------ queue actions
    def claim(self, task_id: int, staff_id: str) -> dict[str, Any]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE call_tasks SET status = 'assigned', assigned_to = %s, assigned_by = %s, "
                "assigned_at = now(), updated_at = now() "
                "WHERE task_id = %s AND status = 'needs_manual' AND assigned_to IS NULL;",
                (staff_id, staff_id, task_id))
            if cur.rowcount == 0:
                raise CallCenterError("ALREADY_TAKEN",
                                      "Another supervisor already took this call, or it is no "
                                      "longer waiting.", 409)
            self._audit_task(cur, staff_id, "call_task_claimed", task_id, {})
            conn.commit()
        return self.get(task_id) or {}

    def assign(self, task_id: int, staff_id: str, admin: str) -> dict[str, Any]:
        from app.staff.service import StaffError, StaffService

        try:
            StaffService(self._conn).require_active_supervisor(staff_id)
        except StaffError as err:
            raise CallCenterError(err.code, err.message, err.status_code) from None
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE call_tasks SET status = 'assigned', assigned_to = %s, assigned_by = %s, "
                "assigned_at = now(), next_attempt_at = NULL, "
                "manual_reason = COALESCE(manual_reason, 'admin_escalated'), updated_at = now() "
                "WHERE task_id = %s AND status IN "
                "('needs_manual','assigned','retry_scheduled','ignored','auto');",
                (staff_id, admin, task_id))
            if cur.rowcount == 0:
                raise CallCenterError("NOT_ASSIGNABLE",
                                      "This call is already being handled or is finished.", 409)
            cur.execute("UPDATE txn_checks SET status = 'manual_review', updated_at = now() "
                        "WHERE check_id = (SELECT check_id FROM call_tasks WHERE task_id = %s) "
                        "AND status IN ('pending','calling','no_answer','unreachable');",
                        (task_id,))
            self._audit_task(cur, admin, "call_task_assigned", task_id, {"to": staff_id})
            conn.commit()
        return self.get(task_id) or {}

    def release(self, task_id: int, staff_id: str, is_admin: bool) -> dict[str, Any]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE call_tasks SET status = 'needs_manual', assigned_to = NULL, "
                "assigned_by = NULL, assigned_at = NULL, started_at = NULL, updated_at = now() "
                "WHERE task_id = %s AND status IN ('assigned','in_progress') "
                "AND (assigned_to = %s OR %s);",
                (task_id, staff_id, is_admin))
            if cur.rowcount == 0:
                raise CallCenterError("NOT_YOURS", "This call is not assigned to you.", 409)
            self._audit_task(cur, staff_id, "call_task_released", task_id, {})
            conn.commit()
        return self.get(task_id) or {}

    def start(self, task_id: int, staff_id: str) -> dict[str, Any]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE call_tasks SET status = 'in_progress', started_at = now(), "
                "manual_attempts = manual_attempts + 1, updated_at = now() "
                "WHERE task_id = %s AND assigned_to = %s AND status IN ('assigned','in_progress');",
                (task_id, staff_id))
            if cur.rowcount == 0:
                raise CallCenterError("NOT_YOURS", "Claim this call before starting it.", 409)
            self._audit_task(cur, staff_id, "call_task_started", task_id, {})
            conn.commit()
        return self.get(task_id) or {}

    def escalate(self, task_id: int, admin: str) -> dict[str, Any]:
        """Admin pushes a retrying or ignored call into the manual queue."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE call_tasks SET status = 'needs_manual', manual_reason = 'admin_escalated', "
                "next_attempt_at = NULL, resolved_at = NULL, resolved_by = NULL, "
                "resolution = NULL, updated_at = now() "
                "WHERE task_id = %s AND status IN ('retry_scheduled','ignored','auto');",
                (task_id,))
            if cur.rowcount == 0:
                raise CallCenterError("NOT_ESCALATABLE",
                                      "Only retrying or ignored calls can be escalated.", 409)
            cur.execute("UPDATE txn_checks SET status = 'manual_review', updated_at = now() "
                        "WHERE check_id = (SELECT check_id FROM call_tasks WHERE task_id = %s) "
                        "AND status IN ('pending','calling','no_answer','unreachable');",
                        (task_id,))
            self._audit_task(cur, admin, "call_task_escalated", task_id, {})
            conn.commit()
        return self.get(task_id) or {}

    def auto_distribute(self, admin: str) -> dict[str, Any]:
        """Give each unassigned manual call to the active supervisor with the least work."""
        from app.staff.service import StaffService

        supervisors = StaffService(self._conn).active_supervisors()
        if not supervisors:
            raise CallCenterError("NO_SUPERVISORS", "There is no active supervisor.", 409)
        assigned: dict[str, int] = {}
        with self._conn() as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(
                    "SELECT assigned_to, count(*) FROM call_tasks "
                    "WHERE status IN ('assigned','in_progress') AND assigned_to = ANY(%s) "
                    "GROUP BY assigned_to;", (supervisors,))
                load = {s: 0 for s in supervisors}
                load.update(dict(cur.fetchall()))
                cur.execute(
                    "SELECT task_id FROM call_tasks WHERE status = 'needs_manual' "
                    "AND assigned_to IS NULL ORDER BY CASE priority WHEN 'urgent' THEN 0 "
                    "WHEN 'high' THEN 1 ELSE 2 END, task_id FOR UPDATE SKIP LOCKED;")
                for (task_id,) in cur.fetchall():
                    who = min(load, key=lambda s: (load[s], s))
                    cur.execute(
                        "UPDATE call_tasks SET status = 'assigned', assigned_to = %s, "
                        "assigned_by = %s, assigned_at = now(), updated_at = now() "
                        "WHERE task_id = %s;", (who, admin, task_id))
                    self._audit_task(cur, admin, "call_task_assigned", task_id,
                                     {"to": who, "auto": True})
                    load[who] += 1
                    assigned[who] = assigned.get(who, 0) + 1
        return {"assigned": assigned, "total": sum(assigned.values())}

    def record_outcome(self, task_id: int, staff_id: str, is_admin: bool, result: str,
                       stated_amount: Any = None, note: str | None = None,
                       callback_minutes: int | None = None) -> dict[str, Any]:
        """Supervisor logs what happened on the manual call."""
        from app.txn.service import CheckError, TxnCheckService

        task = self.get(task_id)
        if task is None:
            raise CallCenterError("TASK_NOT_FOUND", "Call task not found.", 404)
        if task["status"] not in ("assigned", "in_progress"):
            raise CallCenterError("NOT_ACTIVE", "Claim this call before recording an outcome.",
                                  409)
        if task["assigned_to"] != staff_id and not is_admin:
            raise CallCenterError("NOT_YOURS", "This call is assigned to someone else.", 403)
        note = (note or "").strip() or None
        checks = TxnCheckService(self.mandates)

        if result in MANUAL_RESULTS:
            try:
                check_status = checks.apply_manual_outcome(
                    task["check_id"], MANUAL_RESULTS[result], stated_amount, staff_id, note)
            except CheckError as err:
                raise CallCenterError(err.code, err.message, err.status_code) from None
            if check_status == "suspicious" and not is_admin:
                # The supervisor who spoke to the customer keeps the case they opened.
                with self._conn() as conn, conn.cursor() as cur:
                    cur.execute(
                        "UPDATE cases SET assigned_to = %s, assigned_by = %s, assigned_at = now() "
                        "WHERE case_id = (SELECT case_id FROM txn_checks WHERE check_id = %s) "
                        "AND assigned_to IS NULL;", (staff_id, staff_id, task["check_id"]))
                    conn.commit()
            interpreted = "amount" if result in ("confirmed", "amount_mismatch") else result
            self.record_response(task["check_id"], interpreted, channel="manual",
                                 raw=note, amount=stated_amount or None, recorded_by=staff_id)
            resolution = check_status
        elif result == "unreachable":
            self.record_response(task["check_id"], "unreachable", channel="manual", raw=note,
                                 recorded_by=staff_id)
            checks.set_status(task["check_id"], "unreachable",
                              ("pending", "calling", "no_answer", "manual_review"))
            resolution = "unreachable"
        elif result == "callback":
            minutes = max(5, min(int(callback_minutes or 30), 7 * 24 * 60))
            self.record_response(task["check_id"], "callback", channel="manual", raw=note,
                                 recorded_by=staff_id)
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE call_tasks SET status = 'retry_scheduled', "
                    "manual_reason = 'customer_callback', assigned_to = NULL, "
                    "next_attempt_at = now() + make_interval(mins => %s), "
                    "last_outcome = 'callback', updated_at = now() WHERE task_id = %s;",
                    (minutes, task_id))
                self._audit_task(cur, staff_id, "call_task_callback", task_id,
                                 {"minutes": minutes, "note": note})
                conn.commit()
            return self.get(task_id) or {}
        else:
            raise CallCenterError("INVALID_RESULT", "Unknown call result.", 422)

        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE call_tasks SET status = 'resolved', resolution = %s, resolved_by = %s, "
                "resolved_at = now(), last_outcome = %s, updated_at = now() "
                "WHERE task_id = %s;",
                (resolution, staff_id, result, task_id))
            self._audit_task(cur, staff_id, "call_task_resolved", task_id,
                             {"result": result, "resolution": resolution, "note": note})
            conn.commit()
        return self.get(task_id) or {}

    # ------------------------------------------------------------------ independent follow-up
    @staticmethod
    def clearance_block(cur: Any, case_id: int) -> str | None:
        """The follow-up status that stops a case being cleared, or None when it may be.

        A case tied to a suspicious check can only be cleared (decision "approved") after an
        independent contact reached the customer. `uncertain` and `unreachable` stay open.
        """
        cur.execute(
            "SELECT t.followup_status FROM call_tasks t JOIN txn_checks c USING (check_id) "
            "WHERE c.case_id = %s;", (case_id,))
        row = cur.fetchone()
        return row[0] if row and row[0] in FOLLOWUP_OPEN else None

    def claim_followup(self, task_id: int, staff_id: str) -> dict[str, Any]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE call_tasks SET followup_assigned_to = %s, updated_at = now() "
                "WHERE task_id = %s AND followup_assigned_to IS NULL "
                "AND followup_status IN ('required','attempted','uncertain','unreachable');",
                (staff_id, task_id))
            if cur.rowcount == 0:
                raise CallCenterError("FOLLOWUP_NOT_AVAILABLE",
                                      "This follow-up is already taken or not required.", 409)
            self._audit_task(cur, staff_id, "followup_claimed", task_id, {})
            conn.commit()
        return self.get(task_id) or {}

    def assign_followup(self, task_id: int, staff_id: str, admin: str) -> dict[str, Any]:
        from app.staff.service import StaffError, StaffService

        try:
            StaffService(self._conn).require_active_supervisor(staff_id)
        except StaffError as err:
            raise CallCenterError(err.code, err.message, err.status_code) from None
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE call_tasks SET followup_assigned_to = %s, updated_at = now() "
                "WHERE task_id = %s AND followup_status IN "
                "('required','attempted','uncertain','unreachable');", (staff_id, task_id))
            if cur.rowcount == 0:
                raise CallCenterError("FOLLOWUP_NOT_AVAILABLE",
                                      "No follow-up is required for this call.", 409)
            self._audit_task(cur, admin, "followup_assigned", task_id, {"to": staff_id})
            conn.commit()
        return self.get(task_id) or {}

    def record_followup(self, task_id: int, staff_id: str, is_admin: bool, outcome: str,
                        channel: str, note: str | None = None) -> dict[str, Any]:
        """Log one independent-contact attempt. The system never accepts a phone number here:
        an agent-supplied number or the same handset cannot prove independence."""
        if outcome not in FOLLOWUP_OUTCOMES or channel not in FOLLOWUP_CHANNELS:
            raise CallCenterError("INVALID_FOLLOWUP", "Unknown outcome or channel.", 422)
        if outcome == "reached_independently" and channel != "in_person":
            raise CallCenterError(
                "SAME_HANDSET_NOT_INDEPENDENT",
                "Reaching the registered handset does not prove the customer is free to speak. "
                "Record 'attempted' or 'uncertain', or confirm through an in-person contact.",
                422)
        note = (note or "").strip()[:1000] or None
        with self._conn() as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("SELECT followup_status, followup_assigned_to, check_id FROM "
                            "call_tasks WHERE task_id = %s FOR UPDATE;", (task_id,))
                row = cur.fetchone()
                if row is None:
                    raise CallCenterError("TASK_NOT_FOUND", "Call task not found.", 404)
                current, assigned, check_id = row
                if current == "not_required":
                    raise CallCenterError("NO_FOLLOWUP_REQUIRED",
                                          "No independent follow-up is required here.", 409)
                if current == "reached_independently" and not is_admin:
                    raise CallCenterError("FOLLOWUP_DONE", "This follow-up is already done.", 409)
                if assigned is None:
                    raise CallCenterError("CLAIM_FIRST", "Claim this follow-up first.", 409)
                if assigned != staff_id and not is_admin:
                    raise CallCenterError("NOT_YOURS",
                                          "This follow-up is assigned to someone else.", 403)
                cur.execute(
                    "UPDATE call_tasks SET followup_status = %s, followup_channel = %s, "
                    "followup_attempts = followup_attempts + 1, followup_updated_by = %s, "
                    "followup_updated_at = now(), updated_at = now() WHERE task_id = %s;",
                    (outcome, channel, staff_id, task_id))
                cur.execute("SELECT case_id FROM txn_checks WHERE check_id = %s;", (check_id,))
                case_row = cur.fetchone()
                if case_row and case_row[0]:
                    cur.execute(
                        "INSERT INTO case_notes (case_id, author, note_type, body) "
                        "VALUES (%s, %s, 'call_log', %s);",
                        (case_row[0], staff_id,
                         f"Independent follow-up: {outcome} via {channel}."
                         + (f" {note}" if note else "")))
                self._audit_task(cur, staff_id, "followup_recorded", task_id,
                                 {"outcome": outcome, "channel": channel, "note": note})
        return self.get(task_id) or {}

    # ------------------------------------------------------------------ stats
    def stats(self) -> dict[str, Any]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT status, count(*) FROM call_tasks GROUP BY status;")
            by_status = dict(cur.fetchall())
            cur.execute(
                """
                SELECT count(*) FILTER (WHERE status IN ('verified','mismatch','duress',
                                                         'rejected','unclear')),
                       count(*) FILTER (WHERE status = 'no_answer'),
                       count(*) FILTER (WHERE status = 'unclear'),
                       count(*) FILTER (WHERE status = 'failed'),
                       count(*)
                FROM voice_calls WHERE created_at > now() - interval '24 hours';
                """)
            answered, missed, unclear, failed, total = cur.fetchone()
            cur.execute(
                "SELECT COALESCE(avg(auto_attempts), 0), "
                "count(*) FILTER (WHERE status = 'resolved' AND auto_attempts > 1) "
                "FROM call_tasks WHERE created_at > now() - interval '24 hours';")
            avg_attempts, recovered = cur.fetchone()
            cur.execute(
                "SELECT COALESCE(avg(EXTRACT(EPOCH FROM resolved_at - created_at)), 0) "
                "FROM call_tasks WHERE status = 'resolved' AND resolved_by NOT LIKE 'sathi%%' "
                "AND resolved_at > now() - interval '24 hours';")
            manual_seconds = float(cur.fetchone()[0] or 0)
            cur.execute("SELECT min(next_attempt_at) FROM call_tasks "
                        "WHERE status = 'retry_scheduled';")
            next_retry = cur.fetchone()[0]
            cur.execute(
                "SELECT date_trunc('hour', created_at) h, "
                "count(*) FILTER (WHERE status IN ('verified','mismatch','duress','rejected')), "
                "count(*) FILTER (WHERE status = 'no_answer'), "
                "count(*) FILTER (WHERE status = 'unclear') "
                "FROM voice_calls WHERE created_at > now() - interval '24 hours' "
                "GROUP BY h ORDER BY h;")
            hourly = [{"hour": _iso(r[0]), "answered": r[1], "missed": r[2], "unclear": r[3]}
                      for r in cur.fetchall()]
        return {
            "by_status": by_status,
            "manual_waiting": by_status.get("needs_manual", 0),
            "manual_active": by_status.get("assigned", 0) + by_status.get("in_progress", 0),
            "retrying": by_status.get("retry_scheduled", 0) + by_status.get("auto", 0),
            "ignored": by_status.get("ignored", 0),
            "calls_24h": {"total": total, "answered": answered, "missed": missed,
                          "unclear": unclear, "failed": failed,
                          "answer_rate": round(answered / total, 4) if total else None},
            "avg_auto_attempts": round(float(avg_attempts), 2),
            "recovered_by_retry_24h": recovered,
            "avg_manual_resolution_minutes": round(manual_seconds / 60, 1),
            "next_retry_at": _iso(next_retry),
            "hourly": hourly,
            "policy": self.policy(),
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------ audit
    @staticmethod
    def _audit(cur: Any, actor: str, action: str, check_id: int, detail: dict) -> None:
        cur.execute(
            "INSERT INTO audit_log (actor, action, entity, entity_id, policy_version, detail, ts) "
            "SELECT %s, %s, 'call_task', task_id::text, 'v1.0', %s::jsonb, now() "
            "FROM call_tasks WHERE check_id = %s;",
            (actor, action, json.dumps({**detail, "check_id": check_id}), check_id))

    @staticmethod
    def _audit_task(cur: Any, actor: str, action: str, task_id: int, detail: dict) -> None:
        cur.execute(
            "INSERT INTO audit_log (actor, action, entity, entity_id, policy_version, detail, ts) "
            "VALUES (%s, %s, 'call_task', %s, 'v1.0', %s::jsonb, now());",
            (actor, action, str(task_id), json.dumps(detail)))


def get_callcenter() -> CallCenterService:
    from app.mandates.router import get_mandate_service

    return CallCenterService(get_mandate_service())
