"""Sathi scoped synthetic authentication package."""

from app.auth.dependencies import get_current_principal, require_roles
from app.auth.jwt import (
    AuthSecurityError,
    InvalidTokenError,
    SecretUnconfiguredError,
    TokenExpiredError,
    create_access_token,
    decode_access_token,
    get_jwt_secret,
    is_jwt_secret_configured,
)
from app.auth.models import (
    AuthenticatedPrincipal,
    DemoLoginRequest,
    DemoLoginResponse,
)
from app.auth.router import router

__all__ = [
    "AuthSecurityError",
    "AuthenticatedPrincipal",
    "DemoLoginRequest",
    "DemoLoginResponse",
    "InvalidTokenError",
    "SecretUnconfiguredError",
    "TokenExpiredError",
    "create_access_token",
    "decode_access_token",
    "get_current_principal",
    "get_jwt_secret",
    "is_jwt_secret_configured",
    "require_roles",
    "router",
]
