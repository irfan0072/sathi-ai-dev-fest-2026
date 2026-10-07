"""Call management API.

Supervisors: see the shared pending list, claim calls one by one, log what the customer
said. Super admins: see every queue, assign calls to a named supervisor, spread the queue
evenly, push ignored calls back for a human, and watch call statistics.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.callcenter.service import CallCenterError, get_callcenter

router = APIRouter(prefix="/api/v1/callcenter", tags=["call-center"])

Staff = Annotated[AuthenticatedPrincipal, Depends(require_roles("supervisor", "super_admin"))]
Admin = Annotated[AuthenticatedPrincipal, Depends(require_roles("super_admin"))]

SUPERVISOR_SCOPES = ("pending", "mine", "my_history", "followup")
ADMIN_SCOPES = ("pending", "mine", "manual", "retrying", "ignored", "resolved", "all",
                "my_history", "followup")


def _err(err: CallCenterError) -> JSONResponse:
    return JSONResponse(status_code=err.status_code,
                        content={"error": {"code": err.code, "message": err.message}})


def _visible(task: dict[str, Any], principal: AuthenticatedPrincipal) -> bool:
    """Supervisors see the shared pending list and their own work, nothing else."""
    if principal.role == "super_admin":
        return True
    return (task["status"] == "needs_manual" and task["assigned_to"] is None) or (
        task["assigned_to"] == principal.subject) or task["resolved_by"] == principal.subject or (
        task["followup_status"] in ("required", "attempted", "uncertain", "unreachable")
        and task["followup_assigned_to"] in (None, principal.subject))


@router.get("/queue")
def queue(principal: Staff, scope: str = "pending", status: str | None = None,
          assignee: str | None = None, before_id: int | None = None,
          limit: int = 50) -> Any:
    allowed = ADMIN_SCOPES if principal.role == "super_admin" else SUPERVISOR_SCOPES
    if scope not in allowed:
        return JSONResponse(status_code=403 if scope in ADMIN_SCOPES else 422, content={
            "error": {"code": "SCOPE_NOT_ALLOWED", "message": f"Queue '{scope}' is not "
                      "available for your role."}})
    if principal.role != "super_admin":
        status, assignee = None, None
    center = get_callcenter()
    out = center.queue(scope, principal.subject, status=status, assignee=assignee,
                       before_id=before_id, limit=limit,
                       followup_actor=principal.subject if principal.role != "super_admin"
                       else None)
    with center._conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FILTER (WHERE status = 'needs_manual' AND assigned_to IS NULL), "
            "count(*) FILTER (WHERE assigned_to = %s AND status IN ('assigned','in_progress')) "
            "FROM call_tasks WHERE status IN ('needs_manual','assigned','in_progress');",
            (principal.subject,))
        pending, mine = cur.fetchone()
    out["counts"] = {"pending": pending, "mine": mine}
    return out


@router.get("/stats")
def stats(principal: Admin) -> Any:
    return get_callcenter().stats()


@router.get("/tasks/{task_id}")
def task_detail(task_id: int, principal: Staff) -> Any:
    task = get_callcenter().detail(task_id)
    if task is None or not _visible(task, principal):
        return JSONResponse(status_code=404, content={
            "error": {"code": "TASK_NOT_FOUND", "message": "Call task not found."}})
    return task


@router.post("/tasks/{task_id}/claim")
def claim(task_id: int, principal: Annotated[AuthenticatedPrincipal,
                                             Depends(require_roles("supervisor"))]) -> Any:
    try:
        return get_callcenter().claim(task_id, principal.subject)
    except CallCenterError as err:
        return _err(err)


class AssignRequest(BaseModel):
    staff_id: str = Field(..., min_length=3, max_length=41)


@router.post("/tasks/{task_id}/assign")
def assign(task_id: int, body: AssignRequest, principal: Admin) -> Any:
    try:
        return get_callcenter().assign(task_id, body.staff_id, principal.subject)
    except CallCenterError as err:
        return _err(err)


@router.post("/tasks/{task_id}/release")
def release(task_id: int, principal: Staff) -> Any:
    try:
        return get_callcenter().release(task_id, principal.subject,
                                        principal.role == "super_admin")
    except CallCenterError as err:
        return _err(err)


@router.post("/tasks/{task_id}/start")
def start(task_id: int, principal: Annotated[AuthenticatedPrincipal,
                                             Depends(require_roles("supervisor"))]) -> Any:
    try:
        return get_callcenter().start(task_id, principal.subject)
    except CallCenterError as err:
        return _err(err)


@router.post("/tasks/{task_id}/escalate")
def escalate(task_id: int, principal: Admin) -> Any:
    try:
        return get_callcenter().escalate(task_id, principal.subject)
    except CallCenterError as err:
        return _err(err)


@router.post("/distribute")
def distribute(principal: Admin) -> Any:
    try:
        return get_callcenter().auto_distribute(principal.subject)
    except CallCenterError as err:
        return _err(err)


class FollowupRequest(BaseModel):
    """Deliberately has no phone-number field: an agent-supplied or alternate number is never
    accepted, and unknown fields are rejected."""

    model_config = {"extra": "forbid"}
    outcome: Literal["attempted", "reached_independently", "uncertain", "unreachable"]
    channel: Literal["registered_number", "in_person"]
    note: str | None = Field(default=None, max_length=1000)


@router.post("/tasks/{task_id}/followup/claim")
def followup_claim(task_id: int, principal: Annotated[
        AuthenticatedPrincipal, Depends(require_roles("supervisor"))]) -> Any:
    try:
        return get_callcenter().claim_followup(task_id, principal.subject)
    except CallCenterError as err:
        return _err(err)


@router.post("/tasks/{task_id}/followup/assign")
def followup_assign(task_id: int, body: AssignRequest, principal: Admin) -> Any:
    try:
        return get_callcenter().assign_followup(task_id, body.staff_id, principal.subject)
    except CallCenterError as err:
        return _err(err)


@router.post("/tasks/{task_id}/followup")
def followup_record(task_id: int, body: FollowupRequest, principal: Staff) -> Any:
    try:
        return get_callcenter().record_followup(
            task_id, principal.subject, principal.role == "super_admin", body.outcome,
            body.channel, body.note)
    except CallCenterError as err:
        return _err(err)


class OutcomeRequest(BaseModel):
    result: Literal["confirmed", "amount_mismatch", "denied", "duress", "unreachable",
                    "callback"]
    stated_amount: Any = None
    note: str | None = Field(default=None, max_length=4000)
    callback_minutes: int | None = Field(default=None, ge=5, le=10080)


@router.post("/tasks/{task_id}/outcome")
def outcome(task_id: int, body: OutcomeRequest, principal: Staff) -> Any:
    try:
        return get_callcenter().record_outcome(
            task_id, principal.subject, principal.role == "super_admin", body.result,
            stated_amount=body.stated_amount, note=body.note,
            callback_minutes=body.callback_minutes)
    except CallCenterError as err:
        return _err(err)
