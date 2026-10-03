"""Analyst-only AI case brief endpoints."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.copilot.investigator import CaseInvestigator, clients_from_env
from app.mandates.router import get_mandate_service
from app.mandates.service import MandateService

router = APIRouter(prefix="/api/v1/cases", tags=["investigation"])

_investigator: CaseInvestigator | None = None


def get_investigator() -> CaseInvestigator:
    """Injected investigator (tests) or one built from the runtime AI settings."""
    if _investigator is not None:
        return _investigator
    from app.settings.credentials import runtime_env
    from app.settings.router import get_settings

    v = get_settings().values()
    env = runtime_env(get_mandate_service().get_connection)
    return CaseInvestigator(clients_from_env(env, order=v["ai.provider_order"],
                                             gemini_model=v["ai.gemini_model"],
                                             openai_model=v["ai.openai_model"]))


def set_investigator(investigator: CaseInvestigator | None) -> None:
    global _investigator
    _investigator = investigator


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def collect_case_evidence(service: MandateService, case_id: int) -> dict[str, Any] | None:
    """Structured evidence for one case. No ground-truth labels or demographics."""
    with service.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT case_id, mandate_id, agent_id, reason, evidence, status, created_at "
                "FROM cases WHERE case_id = %s;",
                (case_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            evidence: dict[str, Any] = {"case": {
                "case_id": row[0], "reason": row[3], "status": row[5],
                "opened_at": row[6].isoformat(), "details": _json(row[4]) or {},
            }}
            mandate_id, agent_id = row[1], row[2]
            if mandate_id:
                cur.execute(
                    "SELECT amount_cap, status, created_at, verification_attempts, "
                    "redemption_attempts FROM mandates WHERE mandate_id = %s;",
                    (mandate_id,),
                )
                m = cur.fetchone()
                if m:
                    evidence["mandate"] = {
                        "requested_amount_bdt": float(m[0]), "status": m[1],
                        "requested_at": m[2].isoformat(), "verification_attempts": m[3],
                        "redemption_attempts": m[4],
                    }
                cur.execute(
                    "SELECT score, band, step_up, reasons FROM mandate_risk WHERE mandate_id = %s;",
                    (mandate_id,),
                )
                r = cur.fetchone()
                if r:
                    evidence["risk"] = {"score": float(r[0]), "band": r[1], "step_up": r[2],
                                        "reasons": _json(r[3])}
                cur.execute(
                    "SELECT mode, stated_amount, outcome, cash_received_reported, ts "
                    "FROM verification_events WHERE mandate_id = %s ORDER BY ts;",
                    (mandate_id,),
                )
                evidence["verification_events"] = [
                    {"mode": e[0], "stated_amount": float(e[1]) if e[1] is not None else None,
                     "outcome": e[2],
                     "cash_reported": float(e[3]) if e[3] is not None else None,
                     "at": e[4].isoformat()}
                    for e in cur.fetchall()
                ]
                cur.execute(
                    "SELECT provider, status, digit_attempts, created_at FROM voice_calls "
                    "WHERE mandate_id = %s ORDER BY created_at;",
                    (mandate_id,),
                )
                evidence["calls"] = [
                    {"provider": c[0], "status": c[1], "digit_attempts": c[2],
                     "at": c[3].isoformat()}
                    for c in cur.fetchall()
                ]
            cur.execute(
                "SELECT c.txn_id, c.amount, c.stated_amount, c.outcome, c.attempts, "
                "c.recommendation, t.ts FROM txn_checks c JOIN transactions t USING (txn_id) "
                "WHERE c.case_id = %s;",
                (case_id,),
            )
            check = cur.fetchone()
            if check:
                evidence["transaction"] = {
                    "txn_id": check[0], "ledger_amount_bdt": float(check[1]),
                    "customer_typed_bdt": float(check[2]) if check[2] is not None else None,
                    "call_outcome": check[3], "attempts": check[4],
                    "completed_at": check[6].isoformat(),
                }
                rec = _json(check[5]) or {}
                evidence["ai_recommendation"] = {
                    "label": rec.get("label"), "reasons": [r.get("text") for r in
                                                           rec.get("reasons", [])]}
            if agent_id:
                cur.execute(
                    "SELECT count(*), count(*) FILTER (WHERE status = 'open') FROM cases "
                    "WHERE agent_id = %s AND created_at > now() - interval '7 days';",
                    (agent_id,),
                )
                total, open_cases = cur.fetchone()
                evidence["agent"] = {"agent_id": agent_id, "cases_7d": total,
                                     "open_cases_7d": open_cases}
    return evidence


@router.post("/{case_id}/brief")
def generate_brief(
    case_id: int,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles("analyst"))],
) -> Any:
    service = get_mandate_service()
    evidence = collect_case_evidence(service, case_id)
    if evidence is None:
        return JSONResponse(status_code=404, content={
            "error": {"code": "CASE_NOT_FOUND", "message": f"Case {case_id} not found"}})
    result = get_investigator().brief(evidence)
    with service.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO case_briefs (case_id, provider, model, brief, evidence_sha256) "
                "VALUES (%s, %s, %s, %s::jsonb, %s) RETURNING created_at;",
                (case_id, result["provider"], result["model"],
                 json.dumps({"brief": result["brief"], "facts": result["facts"]},
                            ensure_ascii=False),
                 result["evidence_sha256"]),
            )
            created = cur.fetchone()[0]
        conn.commit()
    service.log_audit(principal.subject, "case_brief_generated", "case", str(case_id),
                      {"provider": result["provider"], "model": result["model"]})
    return {"case_id": case_id, **result, "created_at": created.isoformat(),
            "disclaimer": "Generated explanation grounded in the listed facts. "
            "It is not a decision; the analyst decides."}
