"""Align the synthetic history with the real clock.

The generated cohorts (U_42_, U_4242_, U_2026_) were simulated on a 90-day timeline that
starts at simulation.start_timestamp, so most of their rows were dated in the future.
Live windows ("last 24 hours", "last 30 days") then saw almost nothing. This moves those
historical rows back by a whole number of days, so the history ends today. Whole days
keep weekdays and the allowance cycle intact; the shift is recorded once in the audit log
and later reads use it to locate allowance days.

Only the generated cohorts move. Live rows (cash-outs recorded by agents, the scale
population and the demo fixtures) are never touched. Idempotent: runs again only if new
future-dated cohort rows appear.
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Callable

COHORT_REGEX = r"^U_(42|4242|2026)_[0-9]{6}$"


def ledger_shift_days(cur: Any) -> int:
    cur.execute("SELECT COALESCE(sum((detail->>'shift_days')::int), 0) FROM audit_log "
                "WHERE action = 'ledger_rebased';")
    return int(cur.fetchone()[0] or 0)


def rebase_ledger(get_connection: Callable) -> dict[str, Any]:
    with get_connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(4242007);")
            cur.execute(
                "SELECT max(ts) FROM transactions WHERE user_id ~ %s "
                "AND txn_id NOT IN (SELECT txn_id FROM txn_checks);", (COHORT_REGEX,))
            latest = cur.fetchone()[0]
            now = datetime.datetime.now(datetime.timezone.utc)
            if latest is None or latest <= now:
                return {"shift_days": 0, "total_shift_days": ledger_shift_days(cur)}
            days = (latest - now).days + 1
            cur.execute(
                "UPDATE transactions SET ts = ts - make_interval(days => %s) "
                "WHERE user_id ~ %s AND txn_id NOT IN (SELECT txn_id FROM txn_checks);",
                (days, COHORT_REGEX))
            moved = cur.rowcount
            cur.execute("UPDATE sessions SET ts = ts - make_interval(days => %s) "
                        "WHERE user_id ~ %s;", (days, COHORT_REGEX))
            sessions = cur.rowcount
            cur.execute(
                "INSERT INTO audit_log (actor, action, entity, entity_id, policy_version, "
                "detail, ts) VALUES ('system', 'ledger_rebased', 'ledger', 'synthetic_cohorts', "
                "'v1.0', %s::jsonb, now());",
                (json.dumps({"shift_days": days, "transactions": moved,
                             "sessions": sessions}),))
            return {"shift_days": days, "transactions": moved, "sessions": sessions,
                    "total_shift_days": ledger_shift_days(cur)}
