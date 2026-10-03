"""Live verification call API and provider webhooks."""

from __future__ import annotations

import json
import os
import urllib.parse
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.mandates.router import get_mandate_service
from app.voice import twiml
from app.voice.providers import BdHttpIvrProvider, VoiceProviderError, provider_from_env
from app.voice.service import VoiceError, VoiceService, load_phone_book

router = APIRouter(prefix="/api/v1", tags=["voice"])

_voice_service: VoiceService | None = None


def get_voice_service() -> VoiceService:
    global _voice_service
    if _voice_service is None:
        _voice_service = VoiceService(
            get_mandate_service(),
            provider_from_env(),
            public_base_url=os.getenv("SATHI_PUBLIC_API_URL", ""),
            phone_book=load_phone_book(),
        )
    return _voice_service


def set_voice_service(service: VoiceService | None) -> None:
    global _voice_service
    _voice_service = service


def _error(err: VoiceError) -> JSONResponse:
    return JSONResponse(status_code=err.status_code,
                        content={"error": {"code": err.code, "message": err.message}})


def _xml(body: str) -> Response:
    return Response(content=body, media_type="application/xml")


def _voice() -> VoiceService | JSONResponse:
    try:
        return get_voice_service()
    except VoiceProviderError as exc:
        return JSONResponse(status_code=503, content={
            "error": {"code": "VOICE_NOT_CONFIGURED", "message": str(exc)}})


class SimulatedAnswer(BaseModel):
    digits: str = Field(default="", max_length=12, description="Keys pressed before #")


@router.get("/voice/config")
def voice_config(
    principal: Annotated[AuthenticatedPrincipal,
                         Depends(require_roles("agent", "customer_channel", "analyst"))],
) -> Any:
    """Which channel is live. Never returns credentials or phone numbers."""
    provider = os.getenv("SATHI_VOICE_PROVIDER", "simulated").strip().lower()
    return {
        "provider": provider,
        "live_calls": provider in ("twilio", "bd_http_ivr"),
        "public_webhook_configured": os.getenv("SATHI_PUBLIC_API_URL", "").startswith("https://"),
        "step_up_enforced": os.getenv("SATHI_STEP_UP_ENFORCED", "false").lower() == "true",
        "language": twiml.LANGUAGE,
        "sms_provider": os.getenv("SATHI_SMS_PROVIDER", "simulated").strip().lower(),
    }


@router.post("/mandates/{mandate_id}/call", status_code=201)
def place_call(
    mandate_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("agent"))],
) -> Any:
    """Bound agent asks the server to call the customer's registered phone."""
    service = _voice()
    if isinstance(service, JSONResponse):
        return service
    try:
        return service.start_call(mandate_id, principal.subject)
    except VoiceError as err:
        return _error(err)


@router.get("/mandates/{mandate_id}/call")
def latest_call(
    mandate_id: str,
    principal: Annotated[AuthenticatedPrincipal,
                         Depends(require_roles("agent", "customer_channel", "analyst"))],
) -> Any:
    service = _voice()
    if isinstance(service, JSONResponse):
        return service
    record = service.mandates.mandates.get(mandate_id)
    if record is None:
        return _error(VoiceError("MANDATE_NOT_FOUND", "Mandate not found.", 404))
    owner = {"agent": record.agent_id, "customer_channel": record.user_id}.get(principal.role)
    if principal.role != "analyst" and owner != principal.subject:
        return _error(VoiceError("FORBIDDEN_OWNERSHIP", "Not your mandate.", 403))
    call = service.latest_for_mandate(mandate_id)
    if call is None:
        return _error(VoiceError("CALL_NOT_FOUND", "No call placed for this mandate.", 404))
    call.pop("user_id", None)
    if principal.role != "analyst" and call["status"] in ("duress", "rejected", "mismatch"):
        # Agent and customer screens learn only that verification did not complete, so a
        # person watching either screen cannot tell a duress signal from a refusal.
        call["status"] = "not_verified"
    return call


@router.get("/voice/incoming")
def incoming_calls(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("customer_channel"))],
) -> Any:
    """Simulated handset: calls ringing for the signed-in customer."""
    service = _voice()
    if isinstance(service, JSONResponse):
        return service
    return {"calls": service.incoming_for_user(principal.subject)}


@router.post("/voice/calls/{call_id}/simulated-answer")
def simulated_answer(
    call_id: str,
    body: SimulatedAnswer,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("customer_channel"))],
) -> Any:
    """Customer answers a simulated call. Uses the same digit logic as a real call."""
    service = _voice()
    if isinstance(service, JSONResponse):
        return service
    try:
        call = service.get_call(call_id)
    except VoiceError as err:
        return _error(err)
    if call["provider"] != "simulated" or call["user_id"] != principal.subject:
        return _error(VoiceError("FORBIDDEN_OWNERSHIP", "Not your simulated call.", 403))
    result = service.handle_digits(call_id, body.digits, gather_url="")
    # Like a real call, the handset only hears speech: outcome stays hidden from bystanders.
    return {"call_ended": result.call_status != "in_progress", "spoken_bn": result.spoken}


# ------------------------------------------------------------------- provider webhooks
async def _provider_request(request: Request, call_id: str) -> tuple[VoiceService, dict[str, str]]:
    service = get_voice_service()
    service.check_token(call_id, request.query_params.get("t"))
    params = dict(urllib.parse.parse_qsl((await request.body()).decode(), keep_blank_values=True))
    url = f"{service.public_base_url}{request.url.path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"
    signature = request.headers.get("X-Twilio-Signature")
    if not service.provider.validate_request(url, params, signature):
        raise VoiceError("INVALID_SIGNATURE", "Webhook signature rejected.", 403)
    return service, params


def _after_status(service: VoiceService, call_id: str, call: dict[str, Any]) -> None:
    """A missed verification call gets a follow-up SMS (no amount, best-effort)."""
    if call.get("status") != "no_answer":
        return
    from app.notify.router import get_notification_service

    try:
        get_notification_service().notify(call["user_id"], "verification_call_missed",
                                           mandate_id=call["mandate_id"])
    except Exception:
        pass


def _gather_url(service: VoiceService, call_id: str, request: Request) -> str:
    token = urllib.parse.quote(request.query_params.get("t", ""))
    return f"{service.public_base_url}/api/v1/voice/calls/{call_id}/gather?t={token}"


@router.post("/voice/calls/{call_id}/answer", include_in_schema=False)
async def provider_answer(call_id: str, request: Request) -> Any:
    try:
        service, _ = await _provider_request(request, call_id)
        return _xml(service.answer(call_id, _gather_url(service, call_id, request)))
    except (VoiceError, VoiceProviderError):
        return Response(status_code=403)


@router.post("/voice/calls/{call_id}/gather", include_in_schema=False)
async def provider_gather(call_id: str, request: Request) -> Any:
    try:
        service, params = await _provider_request(request, call_id)
        result = service.handle_digits(call_id, params.get("Digits", ""),
                                       _gather_url(service, call_id, request))
        return _xml(result.twiml)
    except (VoiceError, VoiceProviderError):
        return Response(status_code=403)


@router.post("/voice/calls/{call_id}/status", include_in_schema=False)
async def provider_status(call_id: str, request: Request) -> Any:
    try:
        service, params = await _provider_request(request, call_id)
        _after_status(service, call_id, service.provider_status(call_id,
                                                               params.get("CallStatus", "")))
        return Response(status_code=204)
    except (VoiceError, VoiceProviderError):
        return Response(status_code=403)


# ------------------------------------------------------- Bangladesh JSON IVR gateway
@router.post("/voice/ivr/{call_id}/events", include_in_schema=False)
async def bd_ivr_event(call_id: str, request: Request) -> Any:
    """Signed JSON events from a Bangladesh IVR gateway.

    Event body: {"event": "answered" | "digits" | "status", "digits": "...",
    "status": "no-answer" | "busy" | "failed" | "completed"}.
    Reply: {"action": "gather" | "hangup", "say": "<Bangla text>", "language": "bn-BD",
    "gather": {...}} so the gateway knows what to play next.
    """
    try:
        service = get_voice_service()
        provider = service.provider
        body = await request.body()
        if not isinstance(provider, BdHttpIvrProvider) or not provider.validate_body(
            body, request.headers.get(BdHttpIvrProvider.signature_header)
        ):
            raise VoiceError("INVALID_SIGNATURE", "Webhook signature rejected.", 403)
        service.check_token(call_id, request.query_params.get("t"))
        event = json.loads(body.decode() or "{}")
    except (VoiceError, VoiceProviderError, ValueError):
        return Response(status_code=403)

    gather = {"max_digits": 8, "finish_on_key": "#", "timeout_seconds": 12}
    kind = event.get("event")
    if kind == "answered":
        if service.mark_answered(call_id):
            return {"action": "gather", "say": twiml.PROMPT, "language": provider.language,
                    "gather": gather}
        return {"action": "hangup", "say": twiml.NEUTRAL_CLOSE, "language": provider.language}
    if kind == "digits":
        result = service.handle_digits(call_id, str(event.get("digits", "")), gather_url="")
        if result.call_status == "in_progress":
            return {"action": "gather", "say": result.spoken[0], "language": provider.language,
                    "gather": gather}
        return {"action": "hangup", "say": result.spoken[0], "language": provider.language}
    if kind == "status":
        _after_status(service, call_id,
                      service.provider_status(call_id, str(event.get("status", ""))))
        return Response(status_code=204)
    return Response(status_code=400)
