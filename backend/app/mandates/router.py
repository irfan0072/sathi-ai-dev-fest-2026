"""FastAPI router for Sathi Mandates API conforming to docs/api-contracts.md."""

from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, status
from fastapi.responses import JSONResponse

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.mandates.models import (
    ErrorResponse,
    MandateConfirmCashRequest,
    MandateConfirmCashResponse,
    MandateIssueCodeResponse,
    MandateRedeemRequest,
    MandateRedeemResponse,
    MandateRequest,
    MandateRequestResponse,
    MandateRevokeResponse,
    MandateVerifyRequest,
    MandateVerifyResponse,
)
from app.mandates.service import MandateError, MandateService
from app.policy.risk import MandateRiskEngine
from app.verification.keypad import KeypadParseError

router = APIRouter(prefix="/api/v1/mandates", tags=["mandates"])

_mandate_service_instance: MandateService | None = None


def get_mandate_service() -> MandateService:
    """Dependency provider for MandateService."""
    global _mandate_service_instance
    if _mandate_service_instance is None:
        _mandate_service_instance = MandateService()
    return _mandate_service_instance


def set_mandate_service(service: MandateService | None) -> None:
    """Setter for testing or custom configuration injection."""
    global _mandate_service_instance
    _mandate_service_instance = service


def _agent_score(agent_id: str) -> float | None:
    """Saved agent anomaly score from the verified snapshot, when the agent is in it."""
    from app.analytics.service import AnalyticsService

    try:
        return float(AnalyticsService().get_agent_risk(agent_id)["risk"])
    except Exception:
        return None


def get_risk_engine(service: MandateService) -> MandateRiskEngine:
    return MandateRiskEngine(
        service.get_connection, agent_score_lookup=_agent_score, cap=service.user_cap_default
    )


def step_up_enforced() -> bool:
    return os.getenv("SATHI_STEP_UP_ENFORCED", "false").strip().lower() == "true"


def _send_receipt(user_id: str, mandate_id: str, result: dict[str, Any]) -> None:
    """Best-effort SMS receipt after redemption; never affects the ledger result."""
    from app.notify.router import get_notification_service

    try:
        get_notification_service().notify(
            user_id, "cashout_receipt", mandate_id=mandate_id,
            amount=float(result["amount"]), fee=float(result.get("fee", 0.0)),
        )
    except Exception:
        pass


def _handle_mandate_error(err: MandateError) -> JSONResponse:
    """Format domain error according to Sathi API contract envelope."""
    return JSONResponse(
        status_code=err.status_code,
        content={"error": {"code": err.code, "message": err.message}},
    )


@router.post(
    "/request",
    response_model=MandateRequestResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthenticated"},
        403: {"model": ErrorResponse, "description": "Forbidden role or scope"},
        404: {"model": ErrorResponse, "description": "Unknown user or agent"},
        409: {"model": ErrorResponse, "description": "Active mandate already exists"},
        422: {"model": ErrorResponse, "description": "Amount invalid or exceeds cap"},
    },
)
def request_mandate(
    body: MandateRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("agent"))],
    service: Annotated[MandateService, Depends(get_mandate_service)],
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> Any:
    """Agent requests a cash-out mandate for a customer.

    Enforces:
    - Authenticated agent role.
    - Bound agent ownership: token subject must match body.agent_id.
    - Principal customer scope: body.user_id must be in principal's allowed_users.
    """
    if principal.subject != body.agent_id:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": {
                    "code": "FORBIDDEN_OWNERSHIP",
                    "message": (
                        f"Authenticated agent '{principal.subject}' "
                        f"cannot request mandate for '{body.agent_id}'."
                    ),
                }
            },
        )

    if not principal.allowed_users or body.user_id not in principal.allowed_users:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": {
                    "code": "FORBIDDEN_SCOPE",
                    "message": (
                        f"Agent '{principal.subject}' is not authorized "
                        f"to operate on customer '{body.user_id}'."
                    ),
                }
            },
        )

    try:
        result = service.request_mandate(
            user_id=body.user_id,
            agent_id=body.agent_id,
            amount=body.amount,
            purpose=body.purpose,
            actor=principal.subject,
        )
        engine = get_risk_engine(service)
        try:
            risk = engine.assess(
                result["mandate_id"], body.user_id, body.agent_id, result["amount"]
            )
        except Exception:
            risk = engine.fail_safe(result["mandate_id"])
        # The agent learns how strong verification must be, not which signals fired,
        # so requests cannot be tuned around the rules. Analysts see the full trace.
        public_risk = {k: v for k, v in risk.to_dict().items() if k != "reasons"}
        return MandateRequestResponse(**result, risk=public_risk)
    except KeypadParseError as err:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": {"code": "INVALID_AMOUNT", "message": str(err)}},
        )
    except MandateError as err:
        return _handle_mandate_error(err)


@router.post(
    "/{mandate_id}/verify",
    response_model=MandateVerifyResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthenticated"},
        403: {"model": ErrorResponse, "description": "Customer channel subject mismatch"},
        404: {"model": ErrorResponse, "description": "Mandate not found"},
        409: {"model": ErrorResponse, "description": "Mandate already verified or invalid state"},
        410: {"model": ErrorResponse, "description": "Mandate expired"},
        422: {"model": ErrorResponse, "description": "Max attempts exceeded"},
    },
)
def verify_mandate(
    mandate_id: str,
    body: MandateVerifyRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("customer_channel"))],
    service: Annotated[MandateService, Depends(get_mandate_service)],
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> Any:
    """Submit stated amount via keypad or voice for mandate verification.

    Enforces customer channel ownership: token subject must match mandate user_id.
    """
    record = service.mandates.get(mandate_id)
    if not record:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "MANDATE_NOT_FOUND",
                    "message": f"Mandate {mandate_id} not found",
                }
            },
        )

    if principal.subject != record.user_id:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": {
                    "code": "FORBIDDEN_OWNERSHIP",
                    "message": (
                        f"Authenticated customer '{principal.subject}' "
                        f"does not own mandate '{mandate_id}'."
                    ),
                }
            },
        )

    if step_up_enforced():
        try:
            risk = get_risk_engine(service).load(mandate_id)
        except Exception:
            risk = None
        needs_call = risk is None or risk.step_up != "keypad_or_call"
        if needs_call:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "error": {
                        "code": "STEP_UP_REQUIRED",
                        "message": "This mandate must be confirmed on a call to the "
                        "customer's registered phone.",
                    }
                },
            )

    try:
        result = service.verify_mandate(
            mandate_id=mandate_id,
            mode=body.mode,
            stated_amount=body.stated_amount,
            attempt=body.attempt,
            actor=principal.subject,
        )
        return MandateVerifyResponse(**result)
    except KeypadParseError as err:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": {"code": "INVALID_AMOUNT", "message": str(err)}},
        )
    except MandateError as err:
        return _handle_mandate_error(err)


@router.post(
    "/{mandate_id}/issue-code",
    response_model=MandateIssueCodeResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthenticated"},
        403: {"model": ErrorResponse, "description": "Agent subject mismatch"},
        404: {"model": ErrorResponse, "description": "Mandate not found"},
        409: {"model": ErrorResponse, "description": "Mandate not verified or code already issued"},
        410: {"model": ErrorResponse, "description": "Mandate expired"},
    },
)
def issue_code(
    mandate_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("agent"))],
    service: Annotated[MandateService, Depends(get_mandate_service)],
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> Any:
    """Authenticated bound agent issues one-time code to terminal after customer verification."""
    record = service.mandates.get(mandate_id)
    if not record:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "MANDATE_NOT_FOUND",
                    "message": f"Mandate {mandate_id} not found",
                }
            },
        )

    if principal.subject != record.agent_id:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": {
                    "code": "FORBIDDEN_OWNERSHIP",
                    "message": (
                        f"Authenticated agent '{principal.subject}' "
                        f"does not own mandate '{mandate_id}'."
                    ),
                }
            },
        )

    if not principal.allowed_users or record.user_id not in principal.allowed_users:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": {
                    "code": "FORBIDDEN_SCOPE",
                    "message": (
                        f"Agent '{principal.subject}' is not authorized "
                        f"to operate on customer '{record.user_id}'."
                    ),
                }
            },
        )

    try:
        result = service.issue_code(
            mandate_id=mandate_id,
            actor=principal.subject,
        )
        return MandateIssueCodeResponse(**result)
    except MandateError as err:
        return _handle_mandate_error(err)


@router.post(
    "/{mandate_id}/redeem",
    response_model=MandateRedeemResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Invalid one-time code"},
        403: {"model": ErrorResponse, "description": "Agent subject mismatch"},
        404: {"model": ErrorResponse, "description": "Mandate not found"},
        409: {"model": ErrorResponse, "description": "Already redeemed or invalid state"},
        410: {"model": ErrorResponse, "description": "Mandate expired"},
        422: {"model": ErrorResponse, "description": "Insufficient balance"},
        423: {"model": ErrorResponse, "description": "Locked after repeated failures"},
    },
)
def redeem_mandate(
    mandate_id: str,
    body: MandateRedeemRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("agent"))],
    service: Annotated[MandateService, Depends(get_mandate_service)],
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> Any:
    """Redeem an active mandate using the one-time code."""
    record = service.mandates.get(mandate_id)
    if not record:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "MANDATE_NOT_FOUND",
                    "message": f"Mandate {mandate_id} not found",
                }
            },
        )

    if principal.subject != record.agent_id:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": {
                    "code": "FORBIDDEN_OWNERSHIP",
                    "message": (
                        f"Authenticated agent '{principal.subject}' "
                        f"does not own mandate '{mandate_id}'."
                    ),
                }
            },
        )

    if not principal.allowed_users or record.user_id not in principal.allowed_users:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": {
                    "code": "FORBIDDEN_SCOPE",
                    "message": (
                        f"Agent '{principal.subject}' is not authorized "
                        f"to operate on customer '{record.user_id}'."
                    ),
                }
            },
        )

    try:
        result = service.redeem_mandate(
            mandate_id=mandate_id,
            code=body.code,
            actor=principal.subject,
        )
        _send_receipt(record.user_id, mandate_id, result)
        return MandateRedeemResponse(**result)
    except MandateError as err:
        return _handle_mandate_error(err)


@router.post(
    "/{mandate_id}/confirm-cash",
    response_model=MandateConfirmCashResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthenticated"},
        403: {"model": ErrorResponse, "description": "Customer channel subject mismatch"},
        404: {"model": ErrorResponse, "description": "Mandate not found"},
        409: {"model": ErrorResponse, "description": "Invalid state or changed report conflict"},
    },
)
def confirm_cash(
    mandate_id: str,
    body: MandateConfirmCashRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("customer_channel"))],
    service: Annotated[MandateService, Depends(get_mandate_service)],
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> Any:
    """Customer reports physical cash received to detect discrepancies."""
    record = service.mandates.get(mandate_id)
    if not record:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "MANDATE_NOT_FOUND",
                    "message": f"Mandate {mandate_id} not found",
                }
            },
        )

    if principal.subject != record.user_id:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": {
                    "code": "FORBIDDEN_OWNERSHIP",
                    "message": (
                        f"Authenticated customer '{principal.subject}' "
                        f"does not own mandate '{mandate_id}'."
                    ),
                }
            },
        )

    try:
        result = service.confirm_cash(
            mandate_id=mandate_id,
            cash_received=body.cash_received,
            actor=principal.subject,
        )
        return MandateConfirmCashResponse(**result)
    except KeypadParseError as err:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": {"code": "INVALID_AMOUNT", "message": str(err)}},
        )
    except MandateError as err:
        return _handle_mandate_error(err)


@router.post(
    "/{mandate_id}/revoke",
    response_model=MandateRevokeResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthenticated"},
        403: {"model": ErrorResponse, "description": "Subject not authorized to revoke"},
        404: {"model": ErrorResponse, "description": "Mandate not found"},
        409: {"model": ErrorResponse, "description": "Mandate already redeemed"},
    },
)
def revoke_mandate(
    mandate_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles("customer_channel", "agent", "analyst")),
    ],
    service: Annotated[MandateService, Depends(get_mandate_service)],
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> Any:
    """Revoke an active or requested mandate."""
    record = service.mandates.get(mandate_id)
    if not record:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "MANDATE_NOT_FOUND",
                    "message": f"Mandate {mandate_id} not found",
                }
            },
        )

    if principal.role == "customer_channel" and principal.subject != record.user_id:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": {
                    "code": "FORBIDDEN_OWNERSHIP",
                    "message": (
                        f"Authenticated customer '{principal.subject}' cannot revoke "
                        f"mandate belonging to '{record.user_id}'."
                    ),
                }
            },
        )

    if principal.role == "agent" and principal.subject != record.agent_id:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": {
                    "code": "FORBIDDEN_OWNERSHIP",
                    "message": (
                        f"Authenticated agent '{principal.subject}' cannot revoke "
                        f"mandate belonging to '{record.agent_id}'."
                    ),
                }
            },
        )

    try:
        result = service.revoke_mandate(
            mandate_id=mandate_id,
            actor=principal.subject,
        )
        return MandateRevokeResponse(**result)
    except MandateError as err:
        return _handle_mandate_error(err)
