"""Pydantic schemas and domain models for synthetic authentication."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DemoLoginRequest(BaseModel):
    """Synthetic public demo credentials submission."""

    principal: str | None = Field(
        default=None, description="Principal identifier (e.g. demo_agent)"
    )
    username: str | None = Field(default=None, description="Alias for principal")
    subject: str | None = Field(
        default=None, description="Explicit subject identifier (e.g. A_777_000001)"
    )
    pin: str = Field(..., description="Synthetic public demo PIN")
    account_type: Literal["customer", "agent"] | None = Field(
        default=None, description="Sign in to a registered account with its phone number"
    )


class DemoLoginResponse(BaseModel):
    """Bearer access token and scoped claims response."""

    access_token: str = Field(..., description="Signed short-lived JWT token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="TTL in seconds")
    role: str = Field(
        ..., description="agent | customer_channel | analyst | supervisor | super_admin"
    )
    subject: str = Field(..., description="Bound subject identifier")
    allowed_users: list[str] = Field(
        default_factory=list, description="Bound customers allowed for this agent"
    )
    display_name: str = Field(default="", description="Human-readable name for the console")


class AuthenticatedPrincipal(BaseModel):
    """Authenticated subject context parsed from verified bearer token."""

    subject: str
    role: str
    principal_name: str = ""
    allowed_users: list[str] = Field(default_factory=list)
    scope: str = "synthetic_demo"
