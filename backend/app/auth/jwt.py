"""Cryptographic JWT token signing and verification for Sathi.

Conforms to HS256 standard and RFC 7519. Validates server-generated secret
JWT_SECRET fail-closed without ever printing or logging credentials.
Uses vetted PyJWT exclusively without homemade crypto fallbacks.
"""

from __future__ import annotations

import math
import os
import time
from typing import Any

import jwt

PLACEHOLDER_SECRETS = {
    "",
    "CHANGE_ME",
    "YOUR_SECRET_HERE",
    "YOUR_KEY_HERE",
    "CHANGEME",
}
MIN_SECRET_LENGTH = 32
ALLOWED_ROLES = {"agent", "customer_channel", "analyst"}
ALLOWED_SCOPES = {"synthetic_demo"}


class AuthSecurityError(Exception):
    """Base exception for authentication failures."""


class SecretUnconfiguredError(AuthSecurityError):
    """Raised when server signing secret is missing, short, or placeholder."""


class TokenExpiredError(AuthSecurityError):
    """Raised when token expiration timestamp is in the past."""


class InvalidTokenError(AuthSecurityError):
    """Raised when token signature, scope, or claims structure is invalid."""


def is_jwt_secret_configured(secret: str | None = None) -> bool:
    """Diagnostic check returning True if valid non-placeholder signing secret is present."""
    sec = secret if secret is not None else os.environ.get("JWT_SECRET")
    if not sec:
        return False
    sec_str = sec.strip()
    if sec_str in PLACEHOLDER_SECRETS:
        return False
    if len(sec_str) < MIN_SECRET_LENGTH:
        return False
    return True


def get_jwt_secret() -> str:
    """Retrieve server signing secret fail-closed. Never prints or logs the secret."""
    sec = os.environ.get("JWT_SECRET")
    if not is_jwt_secret_configured(sec):
        raise SecretUnconfiguredError(
            "Server signing secret JWT_SECRET is missing, short (< 32 chars), or unconfigured. "
            "Business endpoints are disabled (fail-closed)."
        )
    return sec.strip() if sec else ""


def create_access_token(
    payload: dict[str, Any],
    expires_in_seconds: int = 1800,
    secret: str | None = None,
) -> str:
    """Sign short-lived HS256 JWT bearer token containing synthetic claims using PyJWT."""
    if secret is not None:
        if not is_jwt_secret_configured(secret):
            raise SecretUnconfiguredError("Provided signing secret is unconfigured or too short.")
        signing_secret = secret.strip()
    else:
        signing_secret = get_jwt_secret()

    now = int(time.time())
    full_payload = dict(payload)
    full_payload["iat"] = now
    full_payload["exp"] = now + expires_in_seconds

    try:
        return jwt.encode(full_payload, signing_secret, algorithm="HS256")
    except Exception as exc:
        raise AuthSecurityError(f"Failed to encode JWT token: {exc}") from exc


def decode_access_token(token: str, secret: str | None = None) -> dict[str, Any]:
    """Verify and decode HS256 JWT token claims fail-closed using PyJWT exclusively."""
    if secret is not None:
        if not is_jwt_secret_configured(secret):
            raise SecretUnconfiguredError("Provided signing secret is unconfigured or too short.")
        signing_secret = secret.strip()
    else:
        signing_secret = get_jwt_secret()

    if not isinstance(token, str) or not token.strip():
        raise InvalidTokenError("Bearer token must be a non-empty string.")

    try:
        claims = jwt.decode(
            token,
            signing_secret,
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "iat"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError(f"Bearer token verification failed: {exc}") from exc
    except Exception as exc:
        raise InvalidTokenError(f"Bearer token decode failure: {exc}") from exc

    # Validate claim types and scope
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub.strip():
        raise InvalidTokenError("Missing or invalid subject claim 'sub'.")

    role = claims.get("role")
    if not isinstance(role, str) or role not in ALLOWED_ROLES:
        raise InvalidTokenError(f"Unauthorized or invalid role claim: {role!r}.")

    scope = claims.get("scope")
    if not isinstance(scope, str) or scope not in ALLOWED_SCOPES:
        raise InvalidTokenError(f"Unauthorized or missing scope claim: {scope!r}.")

    allowed_users = claims.get("allowed_users")
    if allowed_users is not None and not isinstance(allowed_users, list):
        raise InvalidTokenError("Claim 'allowed_users' must be a list.")

    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or not math.isfinite(exp):
        raise InvalidTokenError("Claim 'exp' must be a finite numeric timestamp.")

    iat = claims.get("iat")
    if not isinstance(iat, (int, float)) or not math.isfinite(iat):
        raise InvalidTokenError("Claim 'iat' must be a finite numeric timestamp.")

    return claims
