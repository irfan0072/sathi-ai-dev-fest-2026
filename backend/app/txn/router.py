"""Cash-out recording, transaction history and post-transaction checks."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.mandates.router import _agent_score, get_mandate_service
from app.txn.service import CheckError, TxnCheckService
from app.voice.providers import VoiceProviderError
from app.voice.service import VoiceError

router = APIRouter(prefix="/api/v1", tags=["transactions"])


def get_checks() -> TxnCheckService:
    return TxnCheckService(get_mandate_service(), agent_score=_agent_score)


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _public(item: dict[str, Any], role: str) -> dict[str, Any]:
    """What agents and customers may see: never the check result itself."""
    state = {"pending": "waiting", "calling": "waiting", "no_answer": "missed"}.get(
        item["status"], "done")
    out = {"txn_id": item["txn_id"], "amount": item["amount"], "fee": item["fee"],
           "ts": item["ts"], "check": state}
    if role == "agent":
        out["user_id"] = item["user_id"]
    else:
        out["agent_id"] = item["agent_id"]
        out["balance_after"] = item["balance_after"]
    return out


def _call_customer(check_id: int, actor: str, automatic: bool = True) -> str | None:
    """Start the confirmation call. Returns an error message instead of raising."""
    from app.voice.router import get_voice_service

    try:
        get_voice_service().start_check_call(check_id, actor, automatic=automatic)
        return None
    except (VoiceError, VoiceProviderError) as exc:
        message = getattr(exc, "message", str(exc))
        get_checks().set_error(check_id, message)
        return message


class CashoutRequest(BaseModel):
    user_id: str = Field(..., max_length=64)
    amount: Any


@router.post("/cashouts", status_code=201)
def record_cashout(
    body: CashoutRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("agent"))],
) -> Any:
    if body.user_id not in (principal.allowed_users or []):
        return _err(403, "FORBIDDEN_SCOPE", "You can only serve your own customers.")
    checks = get_checks()
    try:
        txn = checks.record_cashout(principal.subject, body.user_id, body.amount)
    except CheckError as err:
        return _err(err.status_code, err.code, err.message)

    from app.notify.router import get_notification_service

    try:
        # No amount in this SMS: the customer states the cash received before seeing the ledger.
        get_notification_service().notify(body.user_id, "cashout_notice")
    except Exception:
        pass
    _call_customer(txn["check_id"], principal.subject)
    item = checks.get(txn["check_id"])
    return {**_public(item, "agent"),
            "message": "Cash-out recorded. Sathi is now calling the customer to confirm."}


@router.get("/transactions")
def my_transactions(
    principal: Annotated[AuthenticatedPrincipal,
                         Depends(require_roles("agent", "customer_channel"))],
) -> Any:
    checks = get_checks()
    if principal.role == "agent":
        items = checks.list(agent_id=principal.subject, limit=50)
        return {"items": [_public(i, "agent") for i in items]}
    items = checks.list(user_id=principal.subject, limit=50)
    return {"items": [_public(i, "customer") for i in items],
            "balance": checks.balance(principal.subject)}


@router.get("/transaction-checks")
def list_checks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("analyst", "super_admin"))],
    status: str | None = None,
) -> Any:
    if status and status not in ("pending", "calling", "verified", "suspicious", "no_answer",
                                 "manual_review", "unreachable"):
        return _err(422, "INVALID_STATUS", "Unknown status filter.")
    checks = get_checks()
    return {"items": checks.list(status=status, limit=200), "summary": checks.summary()}


@router.get("/transaction-checks/{check_id}")
def check_detail(
    check_id: int,
    principal: Annotated[AuthenticatedPrincipal,
                         Depends(require_roles("analyst", "super_admin", "supervisor"))],
) -> Any:
    item = get_checks().get(check_id)
    if item is None:
        return _err(404, "CHECK_NOT_FOUND", "Transaction check not found.")
    with get_mandate_service().get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT provider, status, digit_attempts, created_at FROM voice_calls "
            "WHERE check_id = %s ORDER BY created_at;",
            (check_id,),
        )
        item["calls"] = [{"provider": r[0], "status": r[1], "digit_attempts": r[2],
                          "at": r[3].isoformat()} for r in cur.fetchall()]
    return item


@router.post("/transaction-checks/{check_id}/call")
def call_again(
    check_id: int,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("analyst", "super_admin"))],
) -> Any:
    checks = get_checks()
    item = checks.get(check_id)
    if item is None:
        return _err(404, "CHECK_NOT_FOUND", "Transaction check not found.")
    if item["status"] not in ("pending", "no_answer", "calling"):
        return _err(409, "CHECK_CLOSED", "This transaction is already confirmed.")
    error = _call_customer(check_id, principal.subject, automatic=False)
    if error:
        return _err(502, "CALL_FAILED", error)
    return checks.get(check_id)
