"""Liquidity forecast (Track 05) and uplift campaign (Track 04) APIs, computed live."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.intelligence.uplift import optimize_budget


class IntelligenceArtifactError(Exception):
    """Live computation could not run (no data yet or a model error)."""


def load_artifact(name: str) -> dict[str, Any]:
    """Live replacement for the old frozen artifacts: re-trained on the current ledger."""
    from app.live.intelligence import get_live

    live = get_live()
    try:
        return live.liquidity() if name == "liquidity" else live.uplift()
    except Exception as exc:
        raise IntelligenceArtifactError(f"Live {name} model is not ready: {exc}") from exc

router = APIRouter(prefix="/api/v1", tags=["intelligence"])


def _unavailable(exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=503, content={
        "error": {"code": "LIVE_MODEL_UNAVAILABLE", "message": str(exc)}})


@router.get("/liquidity/overview")
def liquidity_overview(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("analyst", "super_admin"))],
) -> Any:
    try:
        data = load_artifact("liquidity")
    except IntelligenceArtifactError as exc:
        return _unavailable(exc)
    return {
        key: data[key]
        for key in ("model", "horizon_days", "forecast_origin", "train_origins",
                    "test_origins", "evaluation", "feature_importance", "cohorts",
                    "assumptions", "provenance", "computed_at")
    } | {"agents": data["agents"][:15], "total_agents": len(data["agents"]),
         "agents_under_pressure": sum(1 for a in data["agents"] if a["exceeds_recent_max"])}


@router.get("/liquidity/agents/{agent_id}")
def agent_liquidity(
    agent_id: str,
    principal: Annotated[AuthenticatedPrincipal,
                         Depends(require_roles("agent", "analyst", "super_admin"))],
) -> Any:
    if principal.role == "agent" and principal.subject != agent_id:
        return JSONResponse(status_code=403, content={
            "error": {"code": "FORBIDDEN_OWNERSHIP",
                      "message": "Agents see only their own forecast."}})
    try:
        data = load_artifact("liquidity")
    except IntelligenceArtifactError as exc:
        return _unavailable(exc)
    own = next((a for a in data["agents"] if a["agent_id"] == agent_id), None)
    if own is not None:
        return {**own, "basis": "own live cash-out history (last 90 days)",
                "model": data["model"], "computed_at": data.get("computed_at"),
                "forecast_origin": data["forecast_origin"], "provenance": data["provenance"]}
    cohort = data["cohorts"].get("medium") or next(iter(data["cohorts"].values()))
    peak = max(cohort["days"], key=lambda d: d["p90_bdt"])
    return {
        "agent_id": agent_id,
        "basis": "peer cohort forecast (medium-volume agents); this agent has no history yet",
        "days": cohort["days"],
        "peak_date": peak["date"],
        "peak_p90_bdt": peak["p90_bdt"],
        "recommended_opening_float_bdt": float(-(-peak["p90_bdt"] // 500) * 500),
        "pressure_ratio": None,
        "typical_daily_bdt": None,
        "max_daily_35d_bdt": None,
        "exceeds_recent_max": False,
        "headroom_needed_bdt": None,
        "model": data["model"],
        "forecast_origin": data["forecast_origin"],
        "provenance": data["provenance"],
    }


@router.get("/campaigns/uplift")
def uplift_summary(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("analyst", "super_admin"))],
) -> Any:
    try:
        data = load_artifact("uplift")
    except IntelligenceArtifactError as exc:
        return _unavailable(exc)
    return {
        key: data[key]
        for key in ("model", "experiment", "uplift_truth_correlation", "policies",
                    "feature_importance", "channels", "assumptions", "provenance",
                    "computed_at")
    } | {"top_candidates": data["candidates"][:20], "total_candidates": len(data["candidates"])}


class BudgetRequest(BaseModel):
    budget_bdt: float = Field(..., ge=10, le=1_000_000)


@router.post("/campaigns/optimize")
def optimize(
    body: BudgetRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("analyst", "super_admin"))],
) -> Any:
    try:
        data = load_artifact("uplift")
    except IntelligenceArtifactError as exc:
        return _unavailable(exc)
    plan = optimize_budget(data["candidates"], body.budget_bdt, data["channels"])
    # Same budget spent by the response model, to show what correlation-only targeting buys.
    by_response = sorted(data["candidates"], key=lambda c: -c["p_if_contacted"])
    cost = data["channels"]["ivr_call"]["cost_bdt"]
    n = int(body.budget_bdt // cost)
    naive_gain = sum(max(c["predicted_uplift"], -1.0) for c in by_response[:n])
    plan["comparison_response_model_ivr_only"] = {
        "contacts": min(n, len(by_response)),
        "expected_incremental_enrollments": round(naive_gain, 1),
    }
    plan["population"] = "held-out live customers (last 30 days of activity)"
    return plan
