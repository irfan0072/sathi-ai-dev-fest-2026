"""FastAPI router for Sathi Intelligence, Cases, Receipts, and Metrics endpoints.

Conforms strictly to docs/api-contracts.md and authenticated role policies:
- GET  /api/v1/users/{id}/assisted-score (live, analyst / super_admin)
- GET  /api/v1/agents/risk-board, /agents/{id}/risk (live, analyst / super_admin)
- GET  /api/v1/outreach (live, analyst / super_admin)
- GET  /api/v1/cases (Role: analyst)
- POST /api/v1/cases/{id}/decision (Role: analyst)
- GET  /api/v1/receipts/{txn_id} (Role: customer_channel, agent, analyst)
- GET  /api/v1/metrics/summary (Role: analyst)
"""

from __future__ import annotations

from typing import Annotated, Any

from app.analytics.service import AnalyticsService, ClearanceBlockedError
from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.evaluation.artifacts import ArtifactError
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
    reviewer: str | None = Field(default=None, description="Reviewer identifier")
    note: str = Field(default="", description="Review note explaining reasoning")


def _artifact_query(operation, *args) -> dict[str, Any]:
    try:
        return operation(*args)
    except KeyError:
        raise HTTPException(status_code=404, detail="Subject absent from synthetic snapshot")
    except (ArtifactError, OSError, ValueError, TypeError):
        raise HTTPException(status_code=503, detail="Verified synthetic artifacts unavailable")


def _live_query(operation, *args) -> dict[str, Any]:
    """Live AI over the current database; 404 when the subject has no recent activity."""
    from app.live.intelligence import WarmingUp

    try:
        return operation(*args)
    except WarmingUp as exc:
        raise HTTPException(status_code=503, detail=str(exc).strip("'\""))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'"))
    except (ArtifactError, OSError) as exc:
        raise HTTPException(status_code=503, detail=f"Trained model unavailable: {exc}")


def _live():
    from app.live.intelligence import get_live

    return get_live()


@router.get("/users/{user_id}/assisted-score")
def get_user_assisted_score(
    user_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("analyst", "super_admin"))],
) -> dict[str, Any]:
    """Assisted-customer score from the customer's live last-30-day activity, with SHAP."""
    return _live_query(_live().user_score, user_id)


@router.get("/agents/risk-board")
def get_agent_risk_board(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("analyst", "super_admin"))],
    level: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Every agent with activity in the last 30 days, ranked by live anomaly risk."""
    board = _live_query(_live().agent_board)
    agents = board["agents"]
    if level:
        agents = [a for a in agents if a["level"] == level.lower()]
    slim = [{k: v for k, v in a.items() if k != "features"} for a in agents[:max(1, min(limit,
                                                                                       1000))]]
    return {**board, "agents": slim, "total": len(board["agents"])}


@router.get("/agents/{agent_id}/risk")
def get_agent_risk(
    agent_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("analyst", "super_admin"))],
) -> dict[str, Any]:
    """Live agent anomaly risk, risk level and peer comparison (last 30 days)."""
    return _live_query(_live().agent_risk, agent_id)


@router.get("/outreach")
def get_outreach_list(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("analyst", "super_admin"))],
) -> dict[str, Any]:
    """Customers active in the last 30 days, ranked by the live assisted-customer score."""
    return _live_query(_live().outreach)


@router.get("/cases")
def list_cases(
    principal: Annotated[AuthenticatedPrincipal,
                         Depends(require_roles("analyst", "super_admin", "supervisor"))],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
) -> dict[str, Any]:
    """Retrieve analyst review queue cases (also readable by supervisor and super_admin)."""
    try:
        return service.list_cases()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cases unavailable",
        )


@router.post("/cases/{case_id}/decision", status_code=status.HTTP_200_OK)
def decide_case(
    case_id: int,
    body: CaseDecisionRequest,
    principal: Annotated[AuthenticatedPrincipal,
                         Depends(require_roles("analyst", "super_admin", "supervisor"))],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
) -> dict[str, Any]:
    """Human decision on a case. Supervisors may decide only cases assigned to them."""
    if principal.role == "supervisor":
        with service.mandate_service.get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT assigned_to FROM cases WHERE case_id = %s;", (case_id,))
            row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
        if row[0] != principal.subject:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": {
                "code": "NOT_YOURS",
                "message": "Take this case from the pending list before deciding it."}})
    reviewer = principal.subject or body.reviewer or "analyst"
    try:
        return service.decide_case(
            case_id=case_id,
            decision=body.decision,
            reviewer=reviewer,
            note=body.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ClearanceBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": {
            "code": "INDEPENDENT_CONTACT_REQUIRED", "message": str(exc),
            "followup_status": exc.followup_status}})
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("/receipts/{txn_id}")
def get_receipt(
    txn_id: int,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles("customer_channel", "agent", "analyst", "super_admin",
                              "supervisor")),
    ],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
) -> dict[str, Any]:
    """Retrieve plain-language Bangla receipt with verified numbers."""
    try:
        receipt = service.get_receipt(txn_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction {txn_id} not found in database ledger",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Receipt lookup unavailable",
        )

    # Ownership checks
    if principal.role == "customer_channel" and receipt["user_id"] != principal.subject:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Customer '{principal.subject}' is not authorized to view receipt "
                f"for user '{receipt['user_id']}'"
            ),
        )
    if principal.role == "agent" and receipt["agent_id"] != principal.subject:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Agent '{principal.subject}' is not authorized to view receipt "
                f"for agent '{receipt['agent_id']}'"
            ),
        )

    return receipt


@router.get("/metrics/summary")
def get_metrics_summary(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("analyst", "super_admin"))],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
) -> dict[str, Any]:
    """Retrieve comprehensive evaluation metrics and fairness audit summary."""
    return _artifact_query(service.get_metrics_summary)
