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

    token_claims = {
        "sub": subject,
        "role": role,
        "principal": target_key,
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
    )
