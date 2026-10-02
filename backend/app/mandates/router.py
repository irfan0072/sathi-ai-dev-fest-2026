"""FastAPI router for Sathi Mandates API conforming to docs/api-contracts.md."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, status
from fastapi.responses import JSONResponse

from app.mandates.models import (
    ErrorResponse,
    MandateConfirmCashRequest,
    MandateConfirmCashResponse,
    MandateRedeemRequest,
    MandateRedeemResponse,
    MandateRequest,
    MandateRequestResponse,
    MandateRevokeResponse,
    MandateVerifyRequest,
    MandateVerifyResponse,
)
from app.mandates.service import MandateError, MandateService

router = APIRouter(prefix="/api/v1/mandates", tags=["mandates"])

# Singleton instance for application lifecycle
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
        404: {"model": ErrorResponse, "description": "Unknown user or agent"},
        409: {"model": ErrorResponse, "description": "Active mandate already exists"},
        422: {"model": ErrorResponse, "description": "Amount invalid or exceeds cap"},
    },
)
def request_mandate(
    body: MandateRequest,
    service: Annotated[MandateService, Depends(get_mandate_service)],
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> Any:
    """Agent requests a cash-out mandate for a customer."""
    try:
        result = service.request_mandate(
            user_id=body.user_id,
            agent_id=body.agent_id,
            amount=body.amount,
            purpose=body.purpose,
            actor=x_actor or body.agent_id,
        )
        return MandateRequestResponse(**result)
    except MandateError as err:
        return _handle_mandate_error(err)


@router.post(
    "/{mandate_id}/verify",
    response_model=MandateVerifyResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"model": ErrorResponse, "description": "Mandate not found"},
        409: {"model": ErrorResponse, "description": "Mandate already verified or invalid state"},
        410: {"model": ErrorResponse, "description": "Mandate expired"},
        422: {"model": ErrorResponse, "description": "Max attempts exceeded"},
    },
)
def verify_mandate(
    mandate_id: str,
    body: MandateVerifyRequest,
    service: Annotated[MandateService, Depends(get_mandate_service)],
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> Any:
    """Submit stated amount via keypad or voice for mandate verification."""
    try:
        result = service.verify_mandate(
            mandate_id=mandate_id,
            mode=body.mode,
            stated_amount=body.stated_amount,
            attempt=body.attempt,
            actor=x_actor or "customer_channel",
        )
        return MandateVerifyResponse(**result)
    except MandateError as err:
        return _handle_mandate_error(err)


@router.post(
    "/{mandate_id}/redeem",
    response_model=MandateRedeemResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Invalid one-time code"},
        404: {"model": ErrorResponse, "description": "Mandate not found"},
        409: {"model": ErrorResponse, "description": "Already redeemed or invalid state"},
        410: {"model": ErrorResponse, "description": "Mandate expired"},
        423: {"model": ErrorResponse, "description": "Locked after repeated failures"},
    },
)
def redeem_mandate(
    mandate_id: str,
    body: MandateRedeemRequest,
    service: Annotated[MandateService, Depends(get_mandate_service)],
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> Any:
    """Redeem an active mandate using the one-time code."""
    try:
        result = service.redeem_mandate(
            mandate_id=mandate_id,
            code=body.code,
            actor=x_actor,
        )
        return MandateRedeemResponse(**result)
    except MandateError as err:
        return _handle_mandate_error(err)


@router.post(
    "/{mandate_id}/confirm-cash",
    response_model=MandateConfirmCashResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"model": ErrorResponse, "description": "Mandate not found"},
    },
)
def confirm_cash(
    mandate_id: str,
    body: MandateConfirmCashRequest,
    service: Annotated[MandateService, Depends(get_mandate_service)],
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> Any:
    """Customer reports physical cash received to detect discrepancies."""
    try:
        result = service.confirm_cash(
            mandate_id=mandate_id,
            cash_received=body.cash_received,
            actor=x_actor or "customer_channel",
        )
        return MandateConfirmCashResponse(**result)
    except MandateError as err:
        return _handle_mandate_error(err)


@router.post(
    "/{mandate_id}/revoke",
    response_model=MandateRevokeResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"model": ErrorResponse, "description": "Mandate not found"},
        409: {"model": ErrorResponse, "description": "Mandate already redeemed"},
    },
)
def revoke_mandate(
    mandate_id: str,
    service: Annotated[MandateService, Depends(get_mandate_service)],
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> Any:
    """Revoke an active or requested mandate."""
    try:
        result = service.revoke_mandate(
            mandate_id=mandate_id,
            actor=x_actor or "customer_channel",
        )
        return MandateRevokeResponse(**result)
    except MandateError as err:
        return _handle_mandate_error(err)
