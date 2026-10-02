"""FastAPI router for Sathi Intelligence, Cases, Receipts, and Metrics endpoints.

Conforms strictly to docs/api-contracts.md:
- GET  /api/v1/users/{id}/assisted-score
- GET  /api/v1/agents/{id}/risk
- GET  /api/v1/outreach
- GET  /api/v1/cases
- POST /api/v1/cases/{id}/decision
- GET  /api/v1/receipts/{txn_id}
- GET  /api/v1/metrics/summary
"""

from __future__ import annotations

from typing import Annotated, Any

from app.analytics.service import AnalyticsService
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1", tags=["analytics"])

_analytics_service_instance: AnalyticsService | None = None


def get_analytics_service() -> AnalyticsService:
    """Dependency provider for AnalyticsService."""
    global _analytics_service_instance
    if _analytics_service_instance is None:
        _analytics_service_instance = AnalyticsService()
    return _analytics_service_instance


def set_analytics_service(service: AnalyticsService | None) -> None:
    """Setter for testing injection."""
    global _analytics_service_instance
    _analytics_service_instance = service


class CaseDecisionRequest(BaseModel):
    decision: str = Field(..., description="Decision: approved, denied, or escalated")
    reviewer: str = Field(..., description="Reviewer identifier")
    note: str = Field(default="", description="Review note explaining reasoning")


@router.get("/users/{user_id}/assisted-score")
def get_user_assisted_score(
    user_id: str,
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
) -> dict[str, Any]:
    """Retrieve calibrated assisted score and local SHAP explanations for customer."""
    return service.get_user_assisted_score(user_id)


@router.get("/agents/{agent_id}/risk")
def get_agent_risk(
    agent_id: str,
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
) -> dict[str, Any]:
    """Retrieve agent anomaly risk, risk level, and peer cohort comparison."""
    return service.get_agent_risk(agent_id)


@router.get("/outreach")
def get_outreach_list(
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
) -> dict[str, Any]:
    """Retrieve ranked list of likely assisted beneficiaries for proactive onboarding."""
    return service.get_outreach_list()


@router.get("/cases")
def list_cases(
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
) -> dict[str, Any]:
    """Retrieve analyst review queue cases."""
    return service.list_cases()


@router.post("/cases/{case_id}/decision", status_code=status.HTTP_200_OK)
def decide_case(
    case_id: int,
    body: CaseDecisionRequest,
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
) -> dict[str, Any]:
    """Submit human analyst decision for review queue case."""
    try:
        return service.decide_case(
            case_id=case_id,
            decision=body.decision,
            reviewer=body.reviewer,
            note=body.note,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/receipts/{txn_id}")
def get_receipt(
    txn_id: int,
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
) -> dict[str, Any]:
    """Retrieve plain-language Bangla receipt with verified numbers."""
    try:
        return service.get_receipt(txn_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction {txn_id} not found in runtime mandate store",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e) or "Receipt lookup unavailable",
        )


@router.get("/metrics/summary")
def get_metrics_summary(
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
) -> dict[str, Any]:
    """Retrieve comprehensive evaluation metrics and fairness audit summary."""
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Evaluation metrics unavailable until model evaluation artifacts are wired",
    )
