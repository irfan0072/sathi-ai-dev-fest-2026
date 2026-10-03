"""Send money, recipient safety check, community reports and receiver-risk views."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.mandates.router import get_mandate_service
from app.scam.community import CommunityError, CommunityService
from app.scam.service import ScamService, TransferError

router = APIRouter(prefix="/api/v1", tags=["scam-protection"])
Customer = Annotated[AuthenticatedPrincipal, Depends(require_roles("customer_channel"))]
Staff = Annotated[AuthenticatedPrincipal,
                  Depends(require_roles("supervisor", "super_admin", "analyst"))]


def _scam() -> ScamService:
    return ScamService(get_mandate_service().get_connection)


def _community() -> CommunityService:
    return CommunityService(get_mandate_service().get_connection)


def _err(code: str, message: str, status: int, extra: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message, **(extra or {})}})


# ---------------------------------------------------------------------------- payments
class RecipientCheck(BaseModel):
    number: str = Field(..., max_length=20)


@router.post("/payments/check-recipient")
def check_recipient(body: RecipientCheck, principal: Customer) -> Any:
    try:
        return _scam().check_recipient(principal.subject, body.number)
    except TransferError as err:
        return _err(err.code, err.message, err.status_code)


class SendMoney(BaseModel):
    number: str = Field(..., max_length=20)
    amount: Any
    reference: str | None = Field(default=None, max_length=80)
    acknowledged_warning: bool = False


@router.post("/payments/send", status_code=201)
def send_money(body: SendMoney, principal: Customer) -> Any:
    try:
        return _scam().send(principal.subject, body.number, body.amount, body.reference,
                            body.acknowledged_warning)
    except TransferError as err:
        return _err(err.code, err.message, err.status_code, err.extra)


@router.get("/me/wallet")
def my_wallet(principal: Customer) -> Any:
    from app.scam.identifiers import mask_msisdn

    service = _scam()
    msisdn = service.msisdn_of(principal.subject)
    with get_mandate_service().get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT p.transfer_id, p.amount, p.created_at, p.reference, "
            "CASE WHEN p.sender_id = %s THEN 'sent' ELSE 'received' END, "
            "CASE WHEN p.sender_id = %s THEN r.msisdn ELSE s.msisdn END "
            "FROM p2p_transfers p JOIN users s ON s.user_id = p.sender_id "
            "JOIN users r ON r.user_id = p.receiver_id "
            "WHERE p.sender_id = %s OR p.receiver_id = %s ORDER BY p.created_at DESC LIMIT 20;",
            (principal.subject,) * 4)
        transfers = [{"transfer_id": r[0], "amount": float(r[1]), "at": r[2].isoformat(),
                      "reference": r[3], "direction": r[4], "other": mask_msisdn(r[5] or "")}
                     for r in cur.fetchall()]
    return {"upay_number": msisdn, "transfers": transfers}


# ---------------------------------------------------------------------------- community
class ReportCreate(BaseModel):
    identifier: str = Field(..., min_length=3, max_length=200)
    identifier_type: Literal["upay_number", "facebook", "instagram", "whatsapp", "telegram",
                             "website", "other"] | None = None
    category: str
    description: str = Field(..., min_length=10, max_length=1000)
    amount_lost: Any = None
    incident_date: str | None = None
    paid_via_upay: bool = False


@router.get("/community/feed")
def community_feed(principal: Customer) -> Any:
    return _community().feed(principal.subject)


@router.get("/community/search")
def community_search(q: str, principal: Customer) -> Any:
    try:
        return _community().search(q, principal.subject)
    except CommunityError as err:
        return _err(err.code, err.message, err.status_code)


@router.post("/community/reports", status_code=201)
def community_report(body: ReportCreate, principal: Customer) -> Any:
    try:
        return _community().create(principal.subject, body.identifier_type, body.identifier,
                                   body.category, body.description, body.amount_lost,
                                   body.incident_date, body.paid_via_upay)
    except CommunityError as err:
        return _err(err.code, err.message, err.status_code)


@router.get("/community/mine")
def community_mine(principal: Customer) -> Any:
    return {"reports": _community().mine(principal.subject)}


@router.post("/community/reports/{report_id}/me-too")
def community_me_too(report_id: int, principal: Customer) -> Any:
    try:
        return _community().me_too(report_id, principal.subject)
    except CommunityError as err:
        return _err(err.code, err.message, err.status_code)


# ---------------------------------------------------------------------------- staff
@router.get("/community/moderation")
def moderation(principal: Staff, status: str = "published") -> Any:
    if status not in ("published", "verified", "rejected", "hidden"):
        return _err("INVALID_STATUS", "Unknown status.", 422)
    return {"reports": _community().moderation_queue(status)}


class Moderate(BaseModel):
    decision: Literal["verified", "rejected", "hidden", "published"]
    note: str | None = Field(default=None, max_length=500)


@router.post("/community/reports/{report_id}/moderate")
def moderate(report_id: int, body: Moderate,
             principal: Annotated[AuthenticatedPrincipal,
                                  Depends(require_roles("supervisor", "super_admin"))]) -> Any:
    try:
        return _community().moderate(report_id, body.decision, principal.subject, body.note)
    except CommunityError as err:
        return _err(err.code, err.message, err.status_code)


@router.get("/p2p/flagged")
def flagged_receivers(principal: Staff, level: str | None = None) -> Any:
    service = _scam()
    with get_mandate_service().get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*), COALESCE(sum(amount), 0), count(DISTINCT receiver_id) "
                    "FROM p2p_transfers WHERE created_at > now() - interval '24 hours';")
        n, total, receivers = cur.fetchone()
        cur.execute("SELECT level, count(*) FROM receiver_flags GROUP BY level;")
        levels = dict(cur.fetchall())
    return {"receivers": service.flagged(level), "levels": levels,
            "p2p_24h": {"transfers": n, "amount": float(total), "receivers": receivers}}


@router.post("/p2p/rescore")
def rescore(principal: Annotated[AuthenticatedPrincipal,
                                 Depends(require_roles("super_admin"))]) -> Any:
    return {"flags": _scam().evaluate()}
