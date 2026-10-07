"""FastAPI authentication and authorization dependencies.

Enforces:
- Scoped synthetic bearer token on every protected endpoint.
- Rejection of unauthenticated calls (401).
- Rejection of X-Actor header as an authentication bypass.
- Role-based access control and entity ownership validation (403).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt import (
    AuthSecurityError,
    SecretUnconfiguredError,
    TokenExpiredError,
    decode_access_token,
)
from app.auth.models import AuthenticatedPrincipal

# Optional bearer dependency so we can return custom envelope errors
bearer_scheme = HTTPBearer(auto_error=False)


STAFF_ROLES = ("supervisor", "analyst", "super_admin")


def _reject_deactivated_staff(claims: dict) -> None:
    """A deactivated staff member's already-issued token stops working immediately.

    Only staff roles are checked (one primary-key lookup). A subject that is not in the staff
    table (the configured demo principals) and an unreachable database do not block the
    request here; every data endpoint needs the database anyway.
    """
    if claims.get("role") not in STAFF_ROLES:
        return
    try:
        from app.staff.service import get_staff_service

        active = get_staff_service().is_active(str(claims.get("sub", "")))
    except Exception:
        return
    if active is False:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "ACCOUNT_DISABLED",
                              "message": "This staff account has been deactivated."}},
        )


def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> AuthenticatedPrincipal:
    """Verify short-lived bearer token and return AuthenticatedPrincipal.

    Explicitly prevents X-Actor header from acting as authentication.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "UNAUTHENTICATED",
                    "message": (
                        "Authorization Bearer token is required. "
                        "X-Actor cannot authenticate."
                    ),
                }
            },
        )

    token = credentials.credentials
    try:
        claims = decode_access_token(token)
    except SecretUnconfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "SECURITY_CONFIG_ERROR",
                    "message": str(exc),
                }
            },
        ) from exc
    except TokenExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "TOKEN_EXPIRED",
                    "message": "Bearer authentication token has expired.",
                }
            },
        ) from exc
    except AuthSecurityError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "INVALID_TOKEN",
                    "message": f"Bearer token verification failed: {exc}",
                }
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "INVALID_TOKEN",
                    "message": f"Malformed bearer token rejected: {exc}",
                }
            },
        ) from exc

    _reject_deactivated_staff(claims)
    return AuthenticatedPrincipal(
        subject=claims["sub"],
        role=claims["role"],
        principal_name=claims.get("principal", ""),
        allowed_users=claims.get("allowed_users", []),
        scope=claims.get("scope", "synthetic_demo"),
    )


def require_roles(*allowed_roles: str):
    """Dependency factory checking that authenticated principal possesses allowed roles."""

    def role_dependency(
        principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    ) -> AuthenticatedPrincipal:
        if principal.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "FORBIDDEN_ROLE",
                        "message": (
                            f"Principal role '{principal.role}' is not authorized. "
                            f"Required role(s): {list(allowed_roles)}."
                        ),
                    }
                },
            )
        return principal

    return role_dependency
