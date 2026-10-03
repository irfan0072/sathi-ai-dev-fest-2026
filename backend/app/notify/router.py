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


def get_notification_service() -> NotificationService:
    global _service
    if _service is None:
        _service = NotificationService(get_mandate_service().get_connection,
                                       sms_provider_from_env())
    return _service


def set_notification_service(service: NotificationService | None) -> None:
    global _service
    _service = service


@router.get("/notifications")
def list_notifications(
    principal: Annotated[AuthenticatedPrincipal,
                         Depends(require_roles("customer_channel", "analyst"))],
) -> Any:
    service = get_notification_service()
    user = None if principal.role == "analyst" else principal.subject
    return {"provider": service.provider.name, "items": service.list_for_user(user)}
