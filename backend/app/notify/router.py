"""Notification inbox: customers see their own SMS; analysts see recent messages."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.mandates.router import get_mandate_service
from app.notify.service import NotificationService, sms_provider_from_env

router = APIRouter(prefix="/api/v1", tags=["notifications"])

_service: NotificationService | None = None
_injected = False
_fingerprint = ""
SMS_ENV_NAMES = ("SATHI_SMS_PROVIDER", "ALPHA_SMS_API_KEY", "ALPHA_SMS_SENDER_ID",
                 "SATHI_VOICE_PHONE_BOOK")


def get_notification_service() -> NotificationService:
    """SMS provider follows the runtime setting."""
    global _service
    if _injected and _service is not None:
        return _service
    from app.settings.credentials import fingerprint, runtime_env
    from app.settings.router import get_settings
    from app.voice.service import load_phone_book

    global _fingerprint
    connection = get_mandate_service().get_connection
    env = runtime_env(connection)
    env["SATHI_SMS_PROVIDER"] = get_settings().get("sms.provider")
    current = fingerprint(env, SMS_ENV_NAMES)
    if _service is None or _fingerprint != current or _service._conn != connection:
        _service = NotificationService(connection, sms_provider_from_env(env),
                                       load_phone_book(env))
        _fingerprint = current
    return _service


def set_notification_service(service: NotificationService | None) -> None:
    global _service, _injected
    _service = service
    _injected = service is not None


@router.get("/notifications")
def list_notifications(
    principal: Annotated[AuthenticatedPrincipal,
                         Depends(require_roles("customer_channel", "analyst"))],
) -> Any:
    service = get_notification_service()
    user = None if principal.role == "analyst" else principal.subject
    return {"provider": service.provider.name, "items": service.list_for_user(user)}
