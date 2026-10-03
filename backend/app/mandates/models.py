"""Pydantic schemas for Sathi Mandate Service conforming to docs/api-contracts.md."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.verification.keypad import parse_keypad_amount

try:
    from pydantic import field_validator

    def _before_validator(field_name: str):
        return field_validator(field_name, mode="before")

    def _plain_validator(field_name: str):
        return field_validator(field_name)

except ImportError:
    from pydantic import validator

    def _before_validator(field_name: str):
        return validator(field_name, pre=True)

    def _plain_validator(field_name: str):
        return validator(field_name)


class ErrorDetail(BaseModel):
    """Detailed error object in standard Sathi envelope."""

    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error description")


class ErrorResponse(BaseModel):
    """Global error response envelope."""

    error: ErrorDetail


class MandateRequest(BaseModel):
    """Agent request to initiate a cash-out mandate."""

    user_id: str = Field(..., description="Identifier of the customer")
    agent_id: str = Field(..., description="Identifier of the assisting agent")
    amount: Any = Field(..., description="Requested cash-out amount in BDT")
    purpose: str = Field(default="cash_out", description="Purpose of mandate")

    @_before_validator("amount")
    @classmethod
    def validate_amount(cls, v: Any) -> float:
        if isinstance(v, bool):
            raise ValueError("Boolean values are not accepted as numeric amounts.")
        dec = parse_keypad_amount(v)
        return float(dec)

    @_plain_validator("purpose")
    @classmethod
    def validate_purpose(cls, v: str) -> str:
        if v != "cash_out":
            raise ValueError(f"Unsupported purpose '{v}'. Only 'cash_out' is supported.")
        return v


class MandateRequestResponse(BaseModel):
    """Response returned upon successful mandate creation."""

    mandate_id: str
    status: str = "requested"
    next: str = "verify"
    verification_modes: list[str] = ["keypad", "voice"]
    amount: float = Field(..., description="Requested cash-out amount in BDT")
    fee: float = Field(default=0.0, description="Planned service fee in BDT")
    payout: float = Field(default=0.0, description="Full cash amount delivered to customer in BDT")
    total_debit: float = Field(
        default=0.0, description="Total user balance debit in BDT (amount + fee)"
    )
    risk: dict[str, Any] | None = Field(
        default=None, description="Real-time risk assessment; sets verification strength only"
    )


class MandateVerifyRequest(BaseModel):
    """Customer verification submission."""

    mode: str = Field(default="keypad", description="Verification channel: keypad | voice")
    stated_amount: Any = Field(
        ..., description="Amount confirmed by customer (Bangla/Western text or number)"
    )
    attempt: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Verification attempt count (compatibility metadata)",
    )

    @_plain_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v not in ("keypad", "voice"):
            raise ValueError(f"Unsupported verification mode '{v}'. Must be 'keypad' or 'voice'.")
        return v

    @_before_validator("stated_amount")
    @classmethod
    def validate_stated_amount(cls, v: Any) -> Any:
        if isinstance(v, bool):
            raise ValueError("Boolean values are not accepted as numeric amounts.")
        parse_keypad_amount(v)
        return v


class MandateVerifyResponse(BaseModel):
    """Outcome of customer mandate verification."""

    outcome: str = Field(..., description="match | mismatch | no_answer")
    decision: str = Field(..., description="ISSUE_MANDATE | REVIEW | DENY")
    status: str = Field(..., description="verified | rejected")
    expires_at: str
    code_delivery: str = "agent_terminal"
    one_time_code: str | None = None
    case_id: int | None = None


class MandateIssueCodeResponse(BaseModel):
    """Terminal code issued exactly once to authenticated bound agent."""

    mandate_id: str
    status: str = "active"
    code: str = Field(..., description="Cryptographic 6-digit one-time code")
    one_time_code: str = Field(..., description="Alias for compatibility")
    expires_at: str


class MandateRedeemRequest(BaseModel):
    """Agent redemption request."""

    code: str = Field(..., min_length=4, max_length=8, description="One-time redemption code")


class MandateRedeemResponse(BaseModel):
    """Response returned upon successful redemption."""

    txn_id: int | None = None
    amount: float
    fee: float = 0.0
    status: str = "redeemed"


class MandateConfirmCashRequest(BaseModel):
    """Post-redemption cash confirmation from customer."""

    cash_received: Any = Field(..., description="Actual physical cash received by customer")

    @_before_validator("cash_received")
    @classmethod
    def validate_cash_received(cls, v: Any) -> Any:
        if isinstance(v, bool):
            raise ValueError("Boolean values are not accepted as numeric amounts.")
        parse_keypad_amount(v)
        return v


class MandateConfirmCashResponse(BaseModel):
    """Cash gap calculation and anomaly flag status."""

    gap: float
    flagged: bool
    case_id: int | None = None


class MandateRevokeResponse(BaseModel):
    """Revocation response."""

    mandate_id: str
    status: str = "revoked"
