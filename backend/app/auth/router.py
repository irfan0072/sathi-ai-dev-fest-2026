"""FastAPI router for synthetic demo authentication."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.auth.jwt import (
    SecretUnconfiguredError,
    create_access_token,
    is_jwt_secret_configured,
)
from app.auth.models import DemoLoginRequest, DemoLoginResponse
from app.data.config import load_config

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post(
    "/demo-login",
    response_model=DemoLoginResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Invalid synthetic demo credentials"},
        403: {"description": "Demo authentication disabled"},
        503: {"description": "Signing secret unconfigured or invalid (fail-closed)"},
    },
)
def demo_login(body: DemoLoginRequest) -> Any:
    """Authenticate synthetic demo principal and issue scoped bearer token."""
    # 1. Verify signing secret is configured fail-closed
    if not is_jwt_secret_configured():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": {
                    "code": "SECURITY_CONFIG_ERROR",
                    "message": "Server signing secret JWT_SECRET is unconfigured or placeholder.",
                }
            },
        )

    # 2. Load auth configuration
    cfg = load_config()
    auth_cfg = cfg.get("auth", {})

    if not auth_cfg.get("demo_enabled", False):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": {
                    "code": "DEMO_AUTH_DISABLED",
                    "message": "Synthetic demo authentication is disabled.",
                }
            },
        )

    principals = auth_cfg.get("principals", {})
    token_ttl_minutes = int(auth_cfg.get("token_ttl_minutes", 30))
    ttl_seconds = token_ttl_minutes * 60

    # 3. Resolve requested principal
    req_key = body.principal or body.username
    req_sub = body.subject

    target_key = None
    target_info = None

    if req_key and req_key in principals:
        target_key = req_key
        target_info = principals[req_key]
    elif req_sub:
        for k, info in principals.items():
            if info.get("subject") == req_sub:
                target_key = k
                target_info = info
                break
    elif req_key:
        for k, info in principals.items():
            if info.get("subject") == req_key:
                target_key = k
                target_info = info
                break

    if target_info is None or target_key is None:
        staff = _staff_login(req_key or req_sub, body.pin)
        if staff is not None:
            return _issue(staff["staff_id"], staff["role"], staff["staff_id"], [], ttl_seconds,
                          display_name=staff["display_name"])
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": {
                    "code": "INVALID_CREDENTIALS",
                    "message": "Invalid synthetic demo principal or subject identifier.",
                }
            },
        )

    # 4. Constant-time PIN validation
    expected_pin = str(target_info.get("pin", ""))
    submitted_pin = str(body.pin).strip()

    if not secrets.compare_digest(submitted_pin, expected_pin):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": {
                    "code": "INVALID_CREDENTIALS",
                    "message": "Invalid synthetic demo PIN.",
                }
            },
        )

    # 5. Build scoped synthetic claims and sign token
    role = target_info.get("role", "")
    subject = target_info.get("subject", "")
    allowed_users = target_info.get("allowed_users", [])
    if role in ("supervisor", "super_admin") and _staff_disabled(subject):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": {"code": "ACCOUNT_DISABLED",
                               "message": "This staff account has been deactivated."}},
        )
    return _issue(subject, role, target_key, allowed_users, ttl_seconds)


def _staff_login(staff_id: str | None, pin: str) -> dict[str, Any] | None:
    """Staff accounts created by a super admin live in the database, not in config."""
    if not staff_id:
        return None
    try:
        from app.staff.service import get_staff_service

        return get_staff_service().authenticate(staff_id.strip().lower(), str(pin).strip())
    except Exception:
        return None


def _staff_disabled(subject: str) -> bool:
    try:
        from app.staff.service import get_staff_service

        return get_staff_service().is_active(subject) is False
    except Exception:
        return False


def _issue(subject: str, role: str, principal: str, allowed_users: list[str],
           ttl_seconds: int, display_name: str = "") -> Any:
    token_claims = {
        "sub": subject,
        "role": role,
        "principal": principal,
        "allowed_users": allowed_users,
        "scope": "synthetic_demo",
    }

    try:
        token = create_access_token(token_claims, expires_in_seconds=ttl_seconds)
    except SecretUnconfiguredError as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": {
                    "code": "SECURITY_CONFIG_ERROR",
                    "message": str(exc),
                }
            },
        )

    return DemoLoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=ttl_seconds,
        role=role,
        subject=subject,
        allowed_users=allowed_users,
        display_name=display_name or principal,
    )
