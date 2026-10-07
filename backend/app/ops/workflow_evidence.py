"""Workflow evidence summary computed from the events in THIS database.

What it is: counts, numerators and denominators of what the confirmation workflow actually did
in this environment (calls attempted, answered, completed, unclear, retried, handed to a
person, cases and their resolution, independent follow-up, delivery failures), with timestamps.

What it is not: field impact. Unless the database holds real partner data, every row here is
synthetic or simulated, the provider is the simulated one, and no money was recovered or
prevented. The report says so in its own fields (`source`, `field_impact`). A closed case is
not a recovered taka and a flagged cash gap is not a prevented loss, so neither is counted as
one anywhere in this summary.
"""

from __future__ import annotations

import datetime
from typing import Any, Callable

ANSWERED = ("verified", "mismatch", "duress", "rejected", "unclear", "completed")
CLEAR = ("verified", "mismatch", "duress", "rejected")


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {"numerator": int(numerator), "denominator": int(denominator),
            "rate": round(numerator / denominator, 4) if denominator else None}


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def summarize(get_connection: Callable,
              environment: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the evidence summary. `environment` adds deployment and provider labels."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*), min(created_at), max(created_at), "
                    "count(*) FILTER (WHERE source = 'simulator'), "
                    "count(*) FILTER (WHERE source = 'agent') FROM txn_checks;")
        checks, first_ts, last_ts, sim_checks, agent_checks = cur.fetchone()
        cur.execute("SELECT status, count(*) FROM txn_checks GROUP BY status;")
        check_status = dict(cur.fetchall())

        cur.execute("SELECT count(*), count(DISTINCT check_id), "
                    "count(*) FILTER (WHERE status = ANY(%s)), "
                    "count(*) FILTER (WHERE status = ANY(%s)), "
                    "count(*) FILTER (WHERE status = 'unclear'), "
                    "count(*) FILTER (WHERE status = 'no_answer'), "
                    "count(*) FILTER (WHERE status = 'failed'), "
                    "count(*) FILTER (WHERE status IN ('queued','ringing','in_progress')), "
                    "count(DISTINCT provider) , array_agg(DISTINCT provider) "
                    "FROM voice_calls WHERE check_id IS NOT NULL;",
                    (list(ANSWERED), list(CLEAR)))
        (attempts, called_checks, answered, clear, unclear, no_answer, failed, live,
         _providers, provider_names) = cur.fetchone()

        cur.execute("SELECT count(*) FILTER (WHERE n > 1), count(*) FILTER (WHERE n > 2), "
                    "COALESCE(sum(n - 1) FILTER (WHERE n > 1), 0), COALESCE(max(n), 0) "
                    "FROM (SELECT check_id, count(*) n FROM voice_calls "
                    "WHERE check_id IS NOT NULL GROUP BY check_id) t;")
        retried_checks, three_plus, retry_calls, max_calls = cur.fetchone()

        cur.execute("SELECT status, count(*) FROM call_tasks GROUP BY status;")
        task_status = dict(cur.fetchall())
        cur.execute("SELECT manual_reason, count(*) FROM call_tasks "
                    "WHERE manual_reason IS NOT NULL GROUP BY manual_reason;")
        manual_reasons = dict(cur.fetchall())
        cur.execute("SELECT count(*), COALESCE(sum(placement_failures), 0), "
                    "count(*) FILTER (WHERE placement_failures > 0), "
                    "count(*) FILTER (WHERE manual_reason = 'provider_failure') FROM call_tasks;")
        tasks, placement_failures, tasks_with_failure, tasks_to_person = cur.fetchone()
        cur.execute("SELECT followup_status, count(*) FROM call_tasks GROUP BY followup_status;")
        followup = dict(cur.fetchall())
        cur.execute(
            "SELECT count(*) FILTER (WHERE resolved_by IS NOT NULL "
            "AND resolved_by NOT LIKE 'sathi%%'), "
            "percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM resolved_at - "
            "created_at)) FILTER (WHERE resolved_by IS NOT NULL "
            "AND resolved_by NOT LIKE 'sathi%%') "
            "FROM call_tasks WHERE status = 'resolved';")
        human_resolved, median_manual_seconds = cur.fetchone()

        cur.execute("SELECT count(*), count(*) FILTER (WHERE status = 'open'), "
                    "count(*) FILTER (WHERE status = 'escalated'), "
                    "count(*) FILTER (WHERE status IN ('approved','denied')), "
                    "count(*) FILTER (WHERE status = 'approved'), "
                    "count(*) FILTER (WHERE status = 'denied'), "
                    "percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM closed_at - "
                    "created_at)) FILTER (WHERE closed_at IS NOT NULL) "
                    "FROM cases;")
        (cases, open_cases, escalated, decided, cleared, confirmed,
         median_case_seconds) = cur.fetchone()
        cur.execute("SELECT count(*) FROM cases c JOIN txn_checks k ON k.case_id = c.case_id;")
        txn_cases = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM review_actions;")
        review_actions = cur.fetchone()[0]
        cur.execute("SELECT action, count(*) FROM audit_log GROUP BY action "
                    "ORDER BY count(*) DESC LIMIT 12;")
        audit_top = dict(cur.fetchall())
        cur.execute("SELECT count(*), min(ts), max(ts) FROM audit_log;")
        audit_total, audit_first, audit_last = cur.fetchone()
        cur.execute("SELECT count(*) FILTER (WHERE raw_input IS NOT NULL), count(*) "
                    "FROM call_responses;")
        transcripts_held, responses = cur.fetchone()

    suspicious = check_status.get("suspicious", 0)
    unresolved_followups = sum(followup.get(k, 0) for k in
                               ("required", "attempted", "uncertain", "unreachable"))
    return {
        "source": "this database (synthetic or simulated unless real partner data was loaded)",
        "environment": environment or {},
        "window": {"first_check_at": _iso(first_ts), "last_check_at": _iso(last_ts),
                   "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()},
        "field_impact": None,
        "field_impact_note": "No real pilot data. Nothing here measures recovered funds, "
                             "prevented loss, fraud confirmed in the field or customer harm.",
        "checks": {"total": checks, "by_status": check_status,
                   "from_agent_api": agent_checks, "from_traffic_simulator": sim_checks},
        "calls": {
            "attempted": attempts, "checks_called": called_checks,
            "answered": _rate(answered, attempts),
            "completed_with_a_clear_outcome": _rate(clear, attempts),
            "completed_of_answered": _rate(clear, answered),
            "unclear": _rate(unclear, attempts), "no_answer": _rate(no_answer, attempts),
            "failed_to_place": _rate(failed, attempts), "still_live": live,
            "providers_seen": provider_names or [],
            "definition": "attempted = call rows for post-cash-out checks; answered = the "
                          "customer reached an answer step; completed = a clear outcome "
                          "(match, mismatch, denial or help signal)",
        },
        "retries": {"checks_with_more_than_one_call": retried_checks,
                    "checks_with_three_or_more_calls": three_plus,
                    "extra_calls_total": int(retry_calls), "max_calls_for_one_check": max_calls,
                    "of_checks_called": _rate(retried_checks, called_checks)},
        "delivery_recovery": {
            "tasks": tasks, "placement_failures_total": int(placement_failures),
            "tasks_with_a_placement_failure": _rate(tasks_with_failure, tasks),
            "handed_to_a_person_after_provider_failure": tasks_to_person},
        "manual_handling": {
            "task_status": task_status, "manual_reasons": manual_reasons,
            "resolved_by_a_person": human_resolved,
            "median_seconds_to_resolve_manual_task":
                round(float(median_manual_seconds), 1) if median_manual_seconds else None},
        "cases": {
            "total": cases, "from_post_cash_out_checks": txn_cases,
            "open": open_cases, "escalated": escalated, "decided_by_a_person": decided,
            "cleared_no_wrongdoing_found": cleared, "confirmed_problem": confirmed,
            "median_seconds_to_close":
                round(float(median_case_seconds), 1) if median_case_seconds else None,
            "suspicious_checks": suspicious,
            "suspicious_checks_with_case": _rate(txn_cases, suspicious),
            "review_actions_logged": review_actions,
            "meaning": "A closed case is a human decision recorded in the audit trail. It is "
                       "not recovered money and not proof of fraud.",
        },
        "independent_followup": {
            "by_status": followup, "unresolved": unresolved_followups,
            "suspicious_checks_needing_followup": suspicious,
            "note": "Registered-number contact never counts as independent; 'uncertain' and "
                    "'unreachable' keep a case from being cleared."},
        "privacy": {"transcripts_held": transcripts_held, "responses_total": responses,
                    "audio_stored": False},
        "audit_trail": {"events": audit_total, "first_at": _iso(audit_first),
                        "last_at": _iso(audit_last), "most_common": audit_top},
    }
