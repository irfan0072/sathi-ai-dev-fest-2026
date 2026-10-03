"""Fraud operations APIs for analysts: command center, case timeline, agent watchlist.

All numbers come from the live PostgreSQL runtime (synthetic demo namespace), not from the
frozen evaluation snapshot. Nothing here authorizes, denies or reverses money movement.
"""

from __future__ import annotations

import datetime
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.mandates.router import get_mandate_service

router = APIRouter(prefix="/api/v1", tags=["fraud-ops"])

# Response-time targets per case reason (minutes). ASSUMPTIONS for the pilot playbook.
PRIORITY = {
    "duress_signal": ("urgent", 15),
    "customer_denied_request": ("high", 60),
    "high_risk_request": ("high", 60),
    "cash_gap_tolerance_exceeded": ("high", 240),
    "repeated_code_failures_lockout": ("normal", 480),
    "stated_amount_mismatch": ("normal", 480),
}
DEFAULT_PRIORITY = ("normal", 1440)


def case_priority(reason: str | None) -> tuple[str, int]:
    return PRIORITY.get(reason or "", DEFAULT_PRIORITY)


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


@router.get("/ops/overview")
def overview(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("analyst"))],
) -> Any:
    service = get_mandate_service()
    now = datetime.datetime.now(datetime.timezone.utc)
    out: dict[str, Any] = {"generated_at": now.isoformat(), "window_hours": 24}
    with service.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status, count(*), COALESCE(sum(amount_cap), 0) FROM mandates "
            "WHERE created_at > now() - interval '24 hours' GROUP BY status;"
        )
        by_status = {r[0]: {"count": r[1], "amount_bdt": float(r[2])} for r in cur.fetchall()}
        out["mandates"] = by_status
        total = sum(v["count"] for v in by_status.values())
        confirmed = sum(by_status.get(s, {}).get("count", 0)
                        for s in ("verified", "active", "redeemed"))
        out["totals"] = {
            "mandates": total,
            "confirmation_rate": round(confirmed / total, 4) if total else None,
            "redeemed_bdt": by_status.get("redeemed", {}).get("amount_bdt", 0.0),
            "held_bdt": by_status.get("rejected", {}).get("amount_bdt", 0.0),
        }

        cur.execute(
            "SELECT status, count(*) FROM voice_calls "
            "WHERE created_at > now() - interval '24 hours' GROUP BY status;"
        )
        out["calls"] = dict(cur.fetchall())

        cur.execute(
            "SELECT band, count(*) FROM mandate_risk "
            "WHERE created_at > now() - interval '24 hours' GROUP BY band;"
        )
        out["risk_bands"] = dict(cur.fetchall())

        cur.execute(
            "SELECT case_id, reason, status, created_at, agent_id FROM cases "
            "WHERE status IN ('open', 'escalated');"
        )
        open_cases = cur.fetchall()
        breaches, by_reason = 0, {}
        for _cid, reason, _status, created, _agent in open_cases:
            _priority, sla = case_priority(reason)
            if (now - created).total_seconds() / 60 > sla:
                breaches += 1
            by_reason[reason] = by_reason.get(reason, 0) + 1
        out["cases"] = {
            "open": len(open_cases),
            "urgent": sum(1 for c in open_cases if case_priority(c[1])[0] == "urgent"),
            "sla_breached": breaches,
            "by_reason": by_reason,
        }

        cur.execute(
            """
            SELECT c.agent_id, count(*) AS cases,
                   count(*) FILTER (WHERE c.reason = 'duress_signal') AS duress,
                   EXISTS(SELECT 1 FROM agent_watchlist w WHERE w.agent_id = c.agent_id)
            FROM cases c WHERE c.agent_id IS NOT NULL
              AND c.created_at > now() - interval '7 days'
            GROUP BY c.agent_id ORDER BY duress DESC, cases DESC LIMIT 8;
            """
        )
        out["agents"] = [
            {"agent_id": r[0], "cases_7d": r[1], "duress_7d": r[2], "watchlisted": r[3]}
            for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT date_trunc('hour', created_at) AS h, count(*), "
            "count(*) FILTER (WHERE status IN ('verified','active','redeemed')) "
            "FROM mandates WHERE created_at > now() - interval '24 hours' "
            "GROUP BY h ORDER BY h;"
        )
        out["hourly"] = [
            {"hour": r[0].isoformat(), "mandates": r[1], "confirmed": r[2]}
            for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT actor, action, entity_id, ts FROM audit_log ORDER BY ts DESC LIMIT 15;"
        )
        out["events"] = [
            {"actor": r[0], "action": r[1], "entity_id": r[2], "at": r[3].isoformat()}
            for r in cur.fetchall()
        ]
    return out


@router.get("/ops/cases")
def prioritized_cases(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("analyst"))],
) -> Any:
    """Open cases ordered by priority, then by remaining time to the response target."""
    service = get_mandate_service()
    now = datetime.datetime.now(datetime.timezone.utc)
    with service.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT case_id, mandate_id, agent_id, reason, evidence, status, created_at "
            "FROM cases ORDER BY created_at DESC LIMIT 200;"
        )
        rows = cur.fetchall()
    rank = {"urgent": 0, "high": 1, "normal": 2}
    items = []
    for r in rows:
        priority, sla = case_priority(r[3])
        age = (now - r[6]).total_seconds() / 60
        items.append({
            "case_id": r[0], "mandate_id": str(r[1]) if r[1] else None, "agent_id": r[2],
            "reason": r[3], "evidence": _json(r[4]), "status": r[5],
            "created_at": r[6].isoformat(), "priority": priority, "sla_minutes": sla,
            "age_minutes": round(age, 1),
            "sla_breached": r[5] in ("open", "escalated") and age > sla,
        })
    items.sort(key=lambda c: (c["status"] not in ("open", "escalated"), rank[c["priority"]],
                              c["sla_minutes"] - c["age_minutes"]))
    return {"cases": items}


@router.get("/cases/{case_id}/timeline")
def case_timeline(
    case_id: int,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("analyst"))],
) -> Any:
    service = get_mandate_service()
    with service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT mandate_id, created_at, reason FROM cases WHERE case_id = %s;",
                    (case_id,))
        case = cur.fetchone()
        if not case:
            return JSONResponse(status_code=404, content={
                "error": {"code": "CASE_NOT_FOUND", "message": f"Case {case_id} not found"}})
        events = [{"at": case[1].isoformat(), "kind": "case", "label": f"Case opened: {case[2]}",
                   "actor": "system"}]
        if case[0]:
            cur.execute(
                "SELECT ts, action, actor, detail FROM audit_log "
                "WHERE entity = 'mandate' AND entity_id = %s ORDER BY ts;",
                (str(case[0]),),
            )
            events += [{"at": r[0].isoformat(), "kind": "audit", "label": r[1],
                        "actor": r[2], "detail": _json(r[3])} for r in cur.fetchall()]
            cur.execute(
                "SELECT created_at, status, provider FROM voice_calls WHERE mandate_id = %s;",
                (case[0],),
            )
            events += [{"at": r[0].isoformat(), "kind": "call",
                        "label": f"Verification call ({r[2]}): {r[1]}", "actor": "server"}
                       for r in cur.fetchall()]
            cur.execute(
                "SELECT created_at, template, status FROM notifications WHERE mandate_id = %s;",
                (case[0],),
            )
            events += [{"at": r[0].isoformat(), "kind": "sms",
                        "label": f"SMS {r[1]}: {r[2]}", "actor": "server"}
                       for r in cur.fetchall()]
        cur.execute(
            "SELECT ts, reviewer, decision, note FROM review_actions WHERE case_id = %s;",
            (case_id,),
        )
        events += [{"at": r[0].isoformat(), "kind": "review", "label": f"Decision: {r[2]}",
                    "actor": r[1], "detail": {"note": r[3]}} for r in cur.fetchall()]
    events.sort(key=lambda e: e["at"])
    return {"case_id": case_id, "events": events}


class WatchlistRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)
    case_id: int | None = None


@router.get("/watchlist")
def list_watchlist(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("analyst"))],
) -> Any:
    service = get_mandate_service()
    with service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT agent_id, reason, added_by, case_id, created_at FROM agent_watchlist "
                    "ORDER BY created_at DESC;")
        return {"agents": [
            {"agent_id": r[0], "reason": r[1], "added_by": r[2], "case_id": r[3],
             "created_at": r[4].isoformat()} for r in cur.fetchall()]}


@router.put("/watchlist/{agent_id}")
def add_watchlist(
    agent_id: str,
    body: WatchlistRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("analyst"))],
) -> Any:
    """Analyst puts an agent on enhanced verification. Their mandates then need a call."""
    service = get_mandate_service()
    with service.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM agents WHERE agent_id = %s;", (agent_id,))
            if not cur.fetchone():
                return JSONResponse(status_code=404, content={
                    "error": {"code": "AGENT_NOT_FOUND", "message": "Unknown agent"}})
            cur.execute(
                """
                INSERT INTO agent_watchlist (agent_id, reason, added_by, case_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (agent_id) DO UPDATE SET reason = EXCLUDED.reason,
                    added_by = EXCLUDED.added_by, case_id = EXCLUDED.case_id, created_at = now();
                """,
                (agent_id, body.reason, principal.subject, body.case_id),
            )
        conn.commit()
    service.log_audit(principal.subject, "agent_watchlisted", "agent", agent_id,
                      {"reason": body.reason, "case_id": body.case_id})
    return {"agent_id": agent_id, "watchlisted": True,
            "effect": "Mandates from this agent require a verification call."}


@router.delete("/watchlist/{agent_id}")
def remove_watchlist(
    agent_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("analyst"))],
) -> Any:
    service = get_mandate_service()
    with service.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agent_watchlist WHERE agent_id = %s;", (agent_id,))
            removed = cur.rowcount
        conn.commit()
    if removed:
        service.log_audit(principal.subject, "agent_unwatchlisted", "agent", agent_id, {})
    return {"agent_id": agent_id, "watchlisted": False, "removed": bool(removed)}
