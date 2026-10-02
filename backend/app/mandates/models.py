"""Pydantic schemas for Sathi Mandate Service conforming to docs/api-contracts.md."""

from pydantic import BaseModel, Field


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
    amount: float = Field(..., gt=0, description="Requested cash-out amount in BDT")
    purpose: str = Field(default="cash_out", description="Purpose of mandate")


class MandateRequestResponse(BaseModel):
    """Response returned upon successful mandate creation."""

    mandate_id: str
    status: str = "requested"
    next: str = "verify"
    verification_modes: list[str] = ["keypad", "voice"]


class MandateVerifyRequest(BaseModel):
    """Customer verification submission."""

    mode: str = Field(default="keypad", description="Verification channel: keypad | voice")
    stated_amount: float = Field(..., description="Amount confirmed by the customer")
    attempt: int = Field(default=1, ge=1, le=5, description="Verification attempt count")


class MandateVerifyResponse(BaseModel):
    """Outcome of customer mandate verification."""

    outcome: str = Field(..., description="match | mismatch | no_answer")
    decision: str = Field(..., description="ISSUE_MANDATE | REVIEW | DENY")
    status: str = Field(..., description="active | rejected")
    expires_at: str
    code_delivery: str = "agent_terminal"
    one_time_code: str | None = None
    case_id: int | None = None


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

    cash_received: float = Field(..., ge=0, description="Actual physical cash received by customer")


class MandateConfirmCashResponse(BaseModel):
    """Cash gap calculation and anomaly flag status."""

    gap: float
    flagged: bool
    case_id: int | None = None


class MandateRevokeResponse(BaseModel):
    """Revocation response."""

    mandate_id: str
    status: str = "revoked"
