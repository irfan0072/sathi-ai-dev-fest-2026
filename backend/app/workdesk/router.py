"""Case work for supervisors and super admins.

Suspicious checks open cases automatically. Supervisors pick cases from the shared pending
list (or a super admin assigns them), write typed notes (message or critical), and close
each case with an audit report that records the decision. Supervisors can act only on
cases assigned to them; a super admin can act on any case.
"""

from __future__ import annotations

import datetime
import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.mandates.router import get_mandate_service
from app.ops.router import REASON_TEXT, case_priority, response_targets

router = APIRouter(prefix="/api/v1", tags=["workdesk"])

Staff = Annotated[AuthenticatedPrincipal,
                  Depends(require_roles("supervisor", "super_admin", "analyst"))]
Admin = Annotated[AuthenticatedPrincipal, Depends(require_roles("super_admin"))]
OPEN = ("open", "escalated")
RANK = {"urgent": 0, "high": 1, "normal": 2}


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _conn():
    return get_mandate_service().get_connection()


def _audit(cur: Any, actor: str, action: str, case_id: int, detail: dict) -> None:
    cur.execute(
        "INSERT INTO audit_log (actor, action, entity, entity_id, policy_version, detail, ts) "
        "VALUES (%s, %s, 'case', %s, 'v1.0', %s::jsonb, now());",
        (actor, action, str(case_id), json.dumps(detail)))


_CASE_SELECT = """
    SELECT c.case_id, c.mandate_id, c.agent_id, c.reason, c.evidence, c.status, c.created_at,
           c.assigned_to, c.assigned_by, c.assigned_at, c.closed_at, s.display_name,
           (SELECT count(*) FROM case_notes n WHERE n.case_id = c.case_id),
           (SELECT count(*) FROM case_notes n WHERE n.case_id = c.case_id
              AND n.note_type = 'critical'),
           k.check_id, k.user_id, k.amount
    FROM cases c
    LEFT JOIN staff s ON s.staff_id = c.assigned_to
    LEFT JOIN txn_checks k ON k.case_id = c.case_id
"""


def _case_row(r: tuple, targets: dict[str, int], now: datetime.datetime) -> dict[str, Any]:
    priority, sla = case_priority(r[3], targets)
    evidence = _json(r[4]) or {}
    if evidence.get("priority") == "urgent":
        priority = "urgent"
    age = (now - r[6]).total_seconds() / 60
    return {
        "case_id": r[0], "mandate_id": str(r[1]) if r[1] else None, "agent_id": r[2],
        "reason": r[3], "reason_text": REASON_TEXT.get(r[3], r[3]), "evidence": evidence,
        "status": r[5], "created_at": _iso(r[6]), "assigned_to": r[7], "assigned_by": r[8],
        "assigned_at": _iso(r[9]), "closed_at": _iso(r[10]), "assignee_name": r[11],
        "notes": r[12], "critical_notes": r[13], "check_id": r[14], "user_id": r[15],
        "amount": float(r[16]) if r[16] is not None else None,
        "priority": priority, "sla_minutes": sla, "age_minutes": round(age, 1),
        "sla_breached": r[5] in OPEN and age > sla,
    }


@router.get("/workdesk/cases")
def case_queue(principal: Staff, scope: str = "pending", before_id: int | None = None,
               limit: int = 100) -> Any:
    admin = principal.role in ("super_admin", "analyst")
    scopes = {
        "pending": "c.status IN ('open','escalated') AND c.assigned_to IS NULL",
        "mine": "c.status IN ('open','escalated') AND c.assigned_to = %(me)s",
        "my_closed": "c.status NOT IN ('open','escalated') AND c.assigned_to = %(me)s",
    }
    if admin:
        scopes.update({
            "open": "c.status IN ('open','escalated')",
            "assigned": "c.status IN ('open','escalated') AND c.assigned_to IS NOT NULL",
            "closed": "c.status NOT IN ('open','escalated')",
            "all": "TRUE",
        })
    if scope not in scopes:
        return _err(403, "SCOPE_NOT_ALLOWED", f"Case list '{scope}' is not available.")
    where = scopes[scope]
    params: dict[str, Any] = {"me": principal.subject, "limit": max(1, min(limit, 300)) + 1}
    if before_id:
        where += " AND c.case_id < %(before)s"
        params["before"] = before_id
    now = datetime.datetime.now(datetime.timezone.utc)
    targets = response_targets()
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(_CASE_SELECT + f" WHERE {where} ORDER BY c.case_id DESC "
                    "LIMIT %(limit)s;", params)
        rows = [_case_row(r, targets, now) for r in cur.fetchall()]
        cur.execute(
            "SELECT count(*) FILTER (WHERE assigned_to IS NULL), "
            "count(*) FILTER (WHERE assigned_to = %s) FROM cases "
            "WHERE status IN ('open','escalated');", (principal.subject,))
        pending, mine = cur.fetchone()
    more = len(rows) > params["limit"] - 1
    rows = rows[: params["limit"] - 1]
    if scope in ("pending", "mine", "open", "assigned"):
        rows.sort(key=lambda c: (RANK[c["priority"]], c["sla_minutes"] - c["age_minutes"]))
    return {"cases": rows, "counts": {"pending": pending, "mine": mine},
            "next_before_id": rows[-1]["case_id"] if more and rows else None}


def _load_case(cur: Any, case_id: int) -> tuple | None:
    cur.execute("SELECT case_id, status, assigned_to FROM cases WHERE case_id = %s FOR UPDATE;",
                (case_id,))
    return cur.fetchone()


def _can_act(principal: AuthenticatedPrincipal, assigned_to: str | None) -> bool:
    return principal.role in ("super_admin", "analyst") or assigned_to == principal.subject


@router.post("/cases/{case_id}/claim")
def claim_case(case_id: int, principal: Annotated[AuthenticatedPrincipal,
                                                  Depends(require_roles("supervisor"))]) -> Any:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE cases SET assigned_to = %s, assigned_by = %s, assigned_at = now() "
            "WHERE case_id = %s AND assigned_to IS NULL AND status IN ('open','escalated');",
            (principal.subject, principal.subject, case_id))
        if cur.rowcount == 0:
            return _err(409, "ALREADY_TAKEN",
                        "Another supervisor already took this case, or it is closed.")
        _audit(cur, principal.subject, "case_claimed", case_id, {})
        cur.execute("INSERT INTO case_notes (case_id, author, note_type, body) "
                    "VALUES (%s, %s, 'system', %s);",
                    (case_id, principal.subject, f"{principal.subject} took this case."))
        conn.commit()
    return {"case_id": case_id, "assigned_to": principal.subject}


class AssignCase(BaseModel):
    staff_id: str = Field(..., min_length=3, max_length=41)


@router.post("/cases/{case_id}/assign")
def assign_case(case_id: int, body: AssignCase, principal: Admin) -> Any:
    from app.staff.service import StaffError, get_staff_service

    try:
        get_staff_service().require_active_supervisor(body.staff_id)
    except StaffError as err:
        return _err(err.status_code, err.code, err.message)
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE cases SET assigned_to = %s, assigned_by = %s, assigned_at = now() "
            "WHERE case_id = %s AND status IN ('open','escalated');",
            (body.staff_id, principal.subject, case_id))
        if cur.rowcount == 0:
            return _err(409, "CASE_CLOSED", "Case not found or already closed.")
        _audit(cur, principal.subject, "case_assigned", case_id, {"to": body.staff_id})
        cur.execute("INSERT INTO case_notes (case_id, author, note_type, body) "
                    "VALUES (%s, %s, 'system', %s);",
                    (case_id, principal.subject, f"Assigned to {body.staff_id}."))
        conn.commit()
    return {"case_id": case_id, "assigned_to": body.staff_id}


@router.post("/cases/{case_id}/release")
def release_case(case_id: int, principal: Staff) -> Any:
    with _conn() as conn:
        with conn.transaction(), conn.cursor() as cur:
            row = _load_case(cur, case_id)
            if not row or row[1] not in OPEN:
                return _err(409, "CASE_CLOSED", "Case not found or already closed.")
            if not _can_act(principal, row[2]):
                return _err(403, "NOT_YOURS", "This case is assigned to someone else.")
            cur.execute("UPDATE cases SET assigned_to = NULL, assigned_by = NULL, "
                        "assigned_at = NULL WHERE case_id = %s;", (case_id,))
            _audit(cur, principal.subject, "case_released", case_id, {})
    return {"case_id": case_id, "assigned_to": None}


@router.post("/cases/distribute")
def distribute_cases(principal: Admin) -> Any:
    from app.staff.service import get_staff_service

    supervisors = get_staff_service().active_supervisors()
    if not supervisors:
        return _err(409, "NO_SUPERVISORS", "There is no active supervisor.")
    assigned: dict[str, int] = {}
    targets = response_targets()
    with _conn() as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT assigned_to, count(*) FROM cases WHERE status IN "
                        "('open','escalated') AND assigned_to = ANY(%s) GROUP BY assigned_to;",
                        (supervisors,))
            load = {s: 0 for s in supervisors}
            load.update(dict(cur.fetchall()))
            cur.execute("SELECT case_id, reason FROM cases WHERE status IN ('open','escalated') "
                        "AND assigned_to IS NULL ORDER BY case_id FOR UPDATE SKIP LOCKED;")
            todo = sorted(cur.fetchall(), key=lambda r: RANK[case_priority(r[1], targets)[0]])
            for case_id, _reason in todo:
                who = min(load, key=lambda s: (load[s], s))
                cur.execute("UPDATE cases SET assigned_to = %s, assigned_by = %s, "
                            "assigned_at = now() WHERE case_id = %s;",
                            (who, principal.subject, case_id))
                _audit(cur, principal.subject, "case_assigned", case_id,
                       {"to": who, "auto": True})
                load[who] += 1
                assigned[who] = assigned.get(who, 0) + 1
    return {"assigned": assigned, "total": sum(assigned.values())}


# ---------------------------------------------------------------------------- notes
class NoteRequest(BaseModel):
    note_type: Literal["message", "critical", "call_log"] = "message"
    body: str = Field(..., min_length=1, max_length=4000)


def _notes(cur: Any, case_id: int) -> list[dict[str, Any]]:
    cur.execute("SELECT n.note_id, n.author, n.note_type, n.body, n.created_at, s.display_name "
                "FROM case_notes n LEFT JOIN staff s ON s.staff_id = n.author "
                "WHERE n.case_id = %s ORDER BY n.created_at, n.note_id;", (case_id,))
    return [{"note_id": r[0], "author": r[1], "note_type": r[2], "body": r[3],
             "at": _iso(r[4]), "author_name": r[5]} for r in cur.fetchall()]


@router.get("/cases/{case_id}/notes")
def list_notes(case_id: int, principal: Staff) -> Any:
    with _conn() as conn, conn.cursor() as cur:
        return {"case_id": case_id, "notes": _notes(cur, case_id)}


@router.post("/cases/{case_id}/notes", status_code=201)
def add_note(case_id: int, body: NoteRequest, principal: Staff) -> Any:
    with _conn() as conn:
        with conn.transaction(), conn.cursor() as cur:
            row = _load_case(cur, case_id)
            if not row:
                return _err(404, "CASE_NOT_FOUND", f"Case {case_id} not found")
            if not _can_act(principal, row[2]):
                return _err(403, "NOT_YOURS", "Take this case before adding notes.")
            cur.execute("INSERT INTO case_notes (case_id, author, note_type, body) "
                        "VALUES (%s, %s, %s, %s) RETURNING note_id;",
                        (case_id, principal.subject, body.note_type, body.body.strip()))
            note_id = cur.fetchone()[0]
            if body.note_type == "critical":
                _audit(cur, principal.subject, "case_critical_note", case_id,
                       {"note_id": note_id})
    return {"note_id": note_id, "case_id": case_id, "note_type": body.note_type}


# ---------------------------------------------------------------------------- audit report
class AuditReportRequest(BaseModel):
    decision: Literal["approved", "denied", "escalated"]
    risk_level: Literal["low", "medium", "high", "critical"]
    customer_contacted: bool = False
    findings: str = Field(..., min_length=10, max_length=4000)
    action_taken: str = Field(..., min_length=3, max_length=2000)
    recommendation: str | None = Field(default=None, max_length=2000)


DECISION_TEXT = {"approved": "Cleared: no wrongdoing found",
                 "denied": "Confirmed problem: action against agent",
                 "escalated": "Escalated to fraud investigations"}


@router.post("/cases/{case_id}/audit-report", status_code=201)
def submit_audit_report(case_id: int, body: AuditReportRequest, principal: Staff) -> Any:
    with _conn() as conn:
        with conn.transaction(), conn.cursor() as cur:
            row = _load_case(cur, case_id)
            if not row:
                return _err(404, "CASE_NOT_FOUND", f"Case {case_id} not found")
            if row[1] not in OPEN:
                return _err(409, "CASE_CLOSED", "This case already has a final decision.")
            if not _can_act(principal, row[2]):
                return _err(403, "NOT_YOURS", "Take this case before writing its report.")
            if body.decision == "approved":
                from app.callcenter.service import CallCenterService

                blocked = CallCenterService.clearance_block(cur, case_id)
                if blocked:
                    return _err(409, "INDEPENDENT_CONTACT_REQUIRED",
                                "An independent customer contact is required before this case "
                                f"can be cleared (follow-up status: {blocked}).")
            cur.execute(
                "INSERT INTO audit_reports (case_id, author, decision, risk_level, "
                "customer_contacted, findings, action_taken, recommendation) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING report_id, created_at;",
                (case_id, principal.subject, body.decision, body.risk_level,
                 body.customer_contacted, body.findings.strip(), body.action_taken.strip(),
                 (body.recommendation or "").strip() or None))
            report_id, created = cur.fetchone()
            final = body.decision != "escalated"
            cur.execute("UPDATE cases SET status = %s, closed_at = CASE WHEN %s THEN now() "
                        "ELSE closed_at END, assigned_to = COALESCE(assigned_to, %s) "
                        "WHERE case_id = %s;",
                        (body.decision, final, principal.subject, case_id))
            cur.execute("INSERT INTO review_actions (case_id, reviewer, decision, note, ts) "
                        "VALUES (%s, %s, %s, %s, now());",
                        (case_id, principal.subject, body.decision,
                         f"Audit report #{report_id}: {body.findings.strip()[:400]}"))
            cur.execute("INSERT INTO case_notes (case_id, author, note_type, body) "
                        "VALUES (%s, %s, 'audit', %s);",
                        (case_id, principal.subject,
                         f"Audit report #{report_id} - {DECISION_TEXT[body.decision]} "
                         f"(risk {body.risk_level})."))
            _audit(cur, principal.subject, "case_audit_report", case_id,
                   {"report_id": report_id, "decision": body.decision,
                    "risk_level": body.risk_level})
    return {"report_id": report_id, "case_id": case_id, "decision": body.decision,
            "status": body.decision, "created_at": _iso(created)}


def _reports(cur: Any, where: str, params: tuple, limit: int = 100) -> list[dict[str, Any]]:
    cur.execute(
        "SELECT r.report_id, r.case_id, r.author, s.display_name, r.decision, r.risk_level, "
        "r.customer_contacted, r.findings, r.action_taken, r.recommendation, r.created_at, "
        "c.reason, c.agent_id FROM audit_reports r JOIN cases c USING (case_id) "
        f"LEFT JOIN staff s ON s.staff_id = r.author WHERE {where} "
        "ORDER BY r.created_at DESC LIMIT %s;", (*params, limit))
    return [{"report_id": r[0], "case_id": r[1], "author": r[2], "author_name": r[3],
             "decision": r[4], "decision_text": DECISION_TEXT[r[4]], "risk_level": r[5],
             "customer_contacted": r[6], "findings": r[7], "action_taken": r[8],
             "recommendation": r[9], "created_at": _iso(r[10]), "reason": r[11],
             "reason_text": REASON_TEXT.get(r[11], r[11]), "agent_id": r[12]}
            for r in cur.fetchall()]


@router.get("/cases/{case_id}/audit-reports")
def case_reports(case_id: int, principal: Staff) -> Any:
    with _conn() as conn, conn.cursor() as cur:
        return {"reports": _reports(cur, "r.case_id = %s", (case_id,))}


@router.get("/workdesk/reports")
def report_list(principal: Staff, limit: int = 100) -> Any:
    with _conn() as conn, conn.cursor() as cur:
        if principal.role == "supervisor":
            return {"reports": _reports(cur, "r.author = %s", (principal.subject,), limit)}
        return {"reports": _reports(cur, "TRUE", (), min(limit, 500))}


# ---------------------------------------------------------------------------- case file
@router.get("/cases/{case_id}/file")
def case_file(case_id: int, principal: Staff) -> Any:
    """Everything a supervisor needs on one screen."""
    now = datetime.datetime.now(datetime.timezone.utc)
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(_CASE_SELECT + " WHERE c.case_id = %s;", (case_id,))
        row = cur.fetchone()
        if not row:
            return _err(404, "CASE_NOT_FOUND", f"Case {case_id} not found")
        case = _case_row(row, response_targets(), now)
        case["notes_list"] = _notes(cur, case_id)
        case["reports"] = _reports(cur, "r.case_id = %s", (case_id,))
        case["can_act"] = _can_act(principal, case["assigned_to"]) and case["status"] in OPEN
        if case["check_id"]:
            cur.execute("SELECT channel, raw_input, interpreted, amount, confidence, "
                        "recorded_by, created_at FROM call_responses WHERE check_id = %s "
                        "ORDER BY created_at;", (case["check_id"],))
            case["responses"] = [
                {"channel": r[0], "raw_input": r[1], "interpreted": r[2],
                 "amount": float(r[3]) if r[3] is not None else None,
                 "confidence": float(r[4]) if r[4] is not None else None,
                 "recorded_by": r[5], "at": _iso(r[6])} for r in cur.fetchall()]
        cur.execute("SELECT t.followup_status, t.followup_attempts FROM call_tasks t "
                    "JOIN txn_checks c USING (check_id) WHERE c.case_id = %s;", (case_id,))
        fu = cur.fetchone()
        case["followup"] = ({"status": fu[0], "attempts": fu[1],
                             "blocks_clearing": fu[0] in ("required", "attempted", "uncertain",
                                                          "unreachable")} if fu else None)
        if case["agent_id"]:
            cur.execute(
                "SELECT count(*) FILTER (WHERE status = 'suspicious'), count(*), "
                "EXISTS(SELECT 1 FROM agent_watchlist w WHERE w.agent_id = %s) "
                "FROM txn_checks WHERE agent_id = %s AND created_at > now() - interval '30 days';",
                (case["agent_id"], case["agent_id"]))
            sus, total, watch = cur.fetchone()
            case["agent_profile"] = {"suspicious_30d": sus, "checks_30d": total,
                                     "watchlisted": watch}
    return case


# ---------------------------------------------------------------------------- desk summary
@router.get("/workdesk/summary")
def desk_summary(principal: Staff) -> Any:
    me = principal.subject
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FILTER (WHERE status = 'needs_manual' AND assigned_to IS NULL), "
            "count(*) FILTER (WHERE assigned_to = %s AND status IN ('assigned','in_progress')), "
            "count(*) FILTER (WHERE resolved_by = %s "
            "AND resolved_at > now() - interval '24 hours') "
            "FROM call_tasks;", (me, me))
        calls_pending, calls_mine, calls_done = cur.fetchone()
        cur.execute(
            "SELECT count(*) FILTER (WHERE status IN ('open','escalated') "
            "AND assigned_to IS NULL), "
            "count(*) FILTER (WHERE status IN ('open','escalated') AND assigned_to = %s), "
            "count(*) FILTER (WHERE assigned_to = %s AND closed_at > now() - interval '24 hours') "
            "FROM cases;", (me, me))
        cases_pending, cases_mine, cases_done = cur.fetchone()
        cur.execute("SELECT count(*) FROM audit_reports WHERE author = %s "
                    "AND created_at > now() - interval '24 hours';", (me,))
        reports = cur.fetchone()[0]
        cur.execute(
            "SELECT n.case_id, n.author, n.body, n.created_at FROM case_notes n "
            "JOIN cases c USING (case_id) WHERE n.note_type = 'critical' "
            "AND c.status IN ('open','escalated') ORDER BY n.created_at DESC LIMIT 6;")
        critical = [{"case_id": r[0], "author": r[1], "body": r[2], "at": _iso(r[3])}
                    for r in cur.fetchall()]
        cur.execute("SELECT display_name FROM staff WHERE staff_id = %s;", (me,))
        name = cur.fetchone()
    return {
        "staff_id": me, "display_name": name[0] if name else me,
        "calls": {"pending": calls_pending, "mine": calls_mine, "resolved_24h": calls_done},
        "cases": {"pending": cases_pending, "mine": cases_mine, "closed_24h": cases_done},
        "reports_24h": reports, "critical_notes": critical,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
