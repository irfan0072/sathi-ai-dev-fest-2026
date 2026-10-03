"""Analytics, intelligence, and review case service for Sathi.

Provides:
- User assisted scoring and SHAP explanation generation.
- Agent anomaly risk assessment with peer comparisons.
- High-priority outreach ranking for assisted beneficiaries.
- Durable human review queue management and analyst case adjudication.
- Database ledger-backed Bangla receipts with exact numerical integrity.
- System-wide evaluation metrics summary conforming to docs/evaluation-results.md.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.copilot.receipts import generate_bangla_receipt
from app.data.config import load_config, validate_config
from app.evaluation.artifacts import ArtifactLoader, ArtifactVerificationError
from app.mandates.router import get_mandate_service
from app.mandates.service import MandateService


class AnalyticsService:
    """Verified offline evidence and durable runtime records, with separate provenance."""

    def __init__(
        self,
        mandate_service: MandateService | None = None,
        artifact_dir: str | Path | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._mandate_service = mandate_service
        self._artifact_dir = artifact_dir
        self._config = validate_config(config) if config is not None else None

    @property
    def mandate_service(self) -> MandateService:
        if self._mandate_service is None:
            self._mandate_service = get_mandate_service()
        return self._mandate_service

    def _bundle(self) -> dict[str, Any]:
        """Verify every request; changed/tampered files never reuse a cached good result."""
        config = self._config if self._config is not None else load_config()
        directory = self._artifact_dir or os.getenv(
            "SATHI_ARTIFACTS_DIR", "data/artifacts/deployment"
        )
        try:
            bundle = ArtifactLoader.load_deployment_bundle_json(directory)
            config_hash = hashlib.sha256(
                json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if bundle["manifest"]["config_sha256"] != config_hash:
                raise ArtifactVerificationError("Configuration differs from frozen artifact")
            return bundle
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ArtifactVerificationError("Invalid local artifact bundle") from exc

    @staticmethod
    def _provenance(bundle: dict[str, Any]) -> dict[str, Any]:
        meta = bundle["metrics_provenance"]
        return {
            key: meta[key]
            for key in (
                "git_revision",
                "config_sha256",
                "final_run_timestamp",
                "as_of",
                "cutoff",
                "window_days",
            )
        }

    def get_user_assisted_score(self, user_id: str) -> dict[str, Any]:
        bundle = self._bundle()
        rows = bundle["synthetic_inference_snapshot"]["customers"]
        row = next((item for item in rows if item["user_id"] == user_id), None)
        if row is None:
            raise KeyError("Subject absent from bounded synthetic snapshot")
        return {
            "user_id": user_id,
            "score": row["predicted_probability"],
            "assisted": bool(row["predicted_class"]),
            "is_sample": False,
            "synthetic": True,
            "provenance": "verified synthetic simulation snapshot",
            "model_version": bundle["manifest"]["git_revision"],
            "top_reasons": row["explanations"],
            "features": row["features"],
            "explanation_unit": "base-model raw log-odds, not calibrated probability",
            "run_provenance": self._provenance(bundle),
        }

    def get_agent_risk(self, agent_id: str) -> dict[str, Any]:
        bundle = self._bundle()
        rows = bundle["synthetic_inference_snapshot"]["agents"]
        row = next((item for item in rows if item["agent_id"] == agent_id), None)
        if row is None:
            raise KeyError("Subject absent from bounded synthetic snapshot")
        return {
            "agent_id": agent_id,
            "risk": row["risk_score"],
            "level": row["risk_level"],
            "is_sample": False,
            "synthetic": True,
            "provenance": "verified synthetic simulation snapshot",
            "model_version": bundle["manifest"]["git_revision"],
            "reasons": row["reasons"],
            "features": row["features"],
            "peer_group": "train-derived volume peers",
            "run_provenance": self._provenance(bundle),
        }

    def get_outreach_list(self) -> dict[str, Any]:
        bundle = self._bundle()
        rows = sorted(
            bundle["synthetic_inference_snapshot"]["customers"],
            key=lambda row: (-row["predicted_probability"], row["user_id"]),
        )
        return {
            "total": len(rows),
            "items": [
                {
                    "user_id": row["user_id"],
                    "assisted_score": row["predicted_probability"],
                    "is_sample": False,
                    "provenance": "verified synthetic simulation snapshot",
                }
                for row in rows
            ],
            "synthetic": True,
            "is_sample": False,
            "provenance": "verified synthetic simulation snapshot",
            "selection": bundle["synthetic_inference_snapshot"]["selection"],
            "run_provenance": self._provenance(bundle),
        }

    def list_cases(self) -> dict[str, Any]:
        """Return durable review cases from PostgreSQL cases store."""
        with self.mandate_service.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT case_id, mandate_id, agent_id, reason, evidence, status, created_at
                    FROM cases ORDER BY case_id ASC;
                    """
                )
                rows = cur.fetchall()
                service_cases = []
                for r in rows:
                    ev = r[4] if isinstance(r[4], dict) else json.loads(r[4] or "{}")
                    service_cases.append(
                        {
                            "case_id": r[0],
                            "mandate_id": str(r[1]) if r[1] else None,
                            "agent_id": r[2],
                            "reason": r[3],
                            "evidence": ev,
                            "status": r[5],
                            "created_at": (
                                r[6].isoformat() if hasattr(r[6], "isoformat") else str(r[6])
                            ),
                            "is_sample": False,
                            "provenance": "runtime_record",
                        }
                    )
                return {"total": len(service_cases), "cases": service_cases}

    def decide_case(
        self,
        case_id: int,
        decision: str,
        reviewer: str,
        note: str = "",
    ) -> dict[str, Any]:
        """Record human review decision in review_actions and update case status in PostgreSQL.

        Human review updates case status and audit only; never automatically redeems
        or alters transaction balances. Unknown cases return 404.
        """
        valid_decisions = {"approved", "denied", "escalated"}
        if decision not in valid_decisions:
            raise ValueError(f"Invalid decision '{decision}'. Must be one of {valid_decisions}.")

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        conn = self.mandate_service.get_connection()
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT case_id, status FROM cases WHERE case_id = %s FOR UPDATE;",
                        (case_id,),
                    )
                    row = cur.fetchone()

                    if row is None:
                        raise KeyError(f"Case {case_id} not found in durable database cases store.")

                    cur.execute(
                        "UPDATE cases SET status = %s WHERE case_id = %s;",
                        (decision, case_id),
                    )

                    cur.execute(
                        """
                        INSERT INTO review_actions (case_id, reviewer, decision, note, ts)
                        VALUES (%s, %s, %s, %s, now());
                        """,
                        (case_id, reviewer, decision, note),
                    )

                    cur.execute(
                        """
                        INSERT INTO audit_log (
                            actor, action, entity, entity_id, policy_version, detail, ts
                        )
                        VALUES (%s, %s, 'case', %s, 'v1.0', %s::jsonb, now());
                        """,
                        (
                            reviewer,
                            f"CASE_DECISION_{decision.upper()}",
                            str(case_id),
                            json.dumps({"decision": decision, "note": note}),
                        ),
                    )

            return {
                "case_id": case_id,
                "status": decision,
                "decision": decision,
                "reviewer": reviewer,
                "resolved_at": now_iso,
            }
        finally:
            conn.close()

    def get_receipt(self, txn_id: int) -> dict[str, Any]:
        """Retrieve verified plain-language Bangla receipt from durable PostgreSQL transaction.

        Validates all numbers against actual ledger values to prevent numerical hallucination.
        Receipts join redeemed mandates and cash_out transaction, never arbitrary rows.
        """
        conn = self.mandate_service.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT t.txn_id, t.user_id, t.agent_id, t.amount, t.fee,
                           t.balance_after, t.ts
                    FROM transactions t
                    JOIN mandates m ON m.redeemed_txn_id = t.txn_id
                    WHERE t.txn_id = %s
                      AND t.txn_type = 'cash_out'
                      AND m.status = 'redeemed';
                    """,
                    (txn_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise KeyError(
                        f"Redeemed cash-out transaction {txn_id} not found in database ledger."
                    )

                t_id, user_id, agent_id, amount, fee, balance_after, ts = row

                amount_bdt = float(Decimal(str(amount)))
                fee_bdt = float(Decimal(str(fee or 0.0)))
                payout_bdt = amount_bdt
                ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

                receipt = generate_bangla_receipt(
                    txn_id=t_id,
                    user_id=user_id or "unknown",
                    agent_id=agent_id or "unknown",
                    amount_bdt=amount_bdt,
                    fee_bdt=fee_bdt,
                    payout_bdt=payout_bdt,
                    ts_iso=ts_iso,
                )
                receipt["provenance"] = "database ledger transaction"
                return receipt
        finally:
            conn.close()

    def get_metrics_summary(self) -> dict[str, Any]:
        bundle = self._bundle()
        return {
            "schema_version": 1,
            "synthetic": True,
            "status": "verified",
            "results": bundle["results"],
            "provenance": self._provenance(bundle),
            "seeds": bundle["manifest"]["seeds"],
            "cohorts": bundle["manifest"]["cohorts"],
            "snapshot_agent_ids": [
                row["agent_id"] for row in bundle["synthetic_inference_snapshot"]["agents"]
            ],
        }
