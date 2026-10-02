"""Agent anomaly detector for Sathi using Peer Robust Z-Score and Isolation Forest.

Conforms strictly to docs/api-contracts.md, docs/evaluation-plan.md, and tasks/T019:
- Peer robust Z-score grouping by peer cohorts (region, volume_band) using median & MAD.
- Unsupervised Isolation Forest on approved behavioral features.
- Combined ensemble score distinguishing skimmers from honest high-volume agents.
- Explainability conforming to GET /agents/{id}/risk schema.
- Precision@K, recall on skimmers, and false-flag evaluation on high-volume honest agents.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from sklearn.ensemble import IsolationForest

from app.features.guard import assert_feature_columns


def load_agent_anomaly_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load agent anomaly config from data/config.yaml."""
    search_paths = []
    if config_path:
        search_paths.append(Path(config_path))

    cwd = Path.cwd()
    search_paths.extend(
        [
            cwd / "data" / "config.yaml",
            cwd.parent / "data" / "config.yaml",
            Path(__file__).resolve().parent.parent.parent.parent / "data" / "config.yaml",
        ]
    )

    for path in search_paths:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                return cfg or {}
            except Exception:
                continue

    return {}


class AgentAnomalyDetector:
    """Agent anomaly detector combining peer-relative robust stats and Isolation Forest."""

    def __init__(
        self,
        contamination: float = 0.05,
        random_state: int = 42,
        config_path: str | Path | None = None,
    ) -> None:
        self.config = load_agent_anomaly_config(config_path)
        self.contamination = contamination
        self.random_state = random_state

        models_cfg = self.config.get("models", {}).get("agent_anomaly", {})
        self.peer_group_cols: list[str] = models_cfg.get("peer_groups", ["region", "volume_band"])
        self.review_top_k: int = int(models_cfg.get("review_top_k", 15))

        policy_cfg = self.config.get("policy", {})
        self.high_risk_threshold: float = float(policy_cfg.get("agent_risk_high", 0.8))

        self.iforest: IsolationForest | None = None
        self.peer_stats_: dict[tuple[str, ...], dict[str, float]] = {}
        self.global_stats_: dict[str, float] = {}

    def fit(
        self,
        X: pd.DataFrame,
        peer_metadata: pd.DataFrame,
    ) -> AgentAnomalyDetector:
        """Fit Isolation Forest and compute peer group baseline distributions."""
        assert_feature_columns(X)

        # 1. Fit Isolation Forest on pure numeric features
        self.iforest = IsolationForest(
            n_estimators=100,
            contamination=self.contamination,
            random_state=self.random_state,
        )
        self.iforest.fit(X)

        # 2. Compute peer statistics (Median and MAD) for robust Z-score
        fee_ratios = X["agent_fee_ratio_over_official"].to_numpy()
        self.global_stats_ = {
            "median": min(float(np.median(fee_ratios)), 1.00),
            "mad": max(float(np.median(np.abs(fee_ratios - np.median(fee_ratios)))), 0.02),
        }

        self.peer_stats_ = {}
        # Ensure peer grouping columns exist
        group_cols = [c for c in self.peer_group_cols if c in peer_metadata.columns]
        if group_cols:
            grouped = peer_metadata.groupby(group_cols)
            for key, group_idx in grouped.groups.items():
                if not isinstance(key, tuple):
                    key = (key,)
                sub_ratios = fee_ratios[group_idx]
                med = float(np.median(sub_ratios))
                mad = float(np.median(np.abs(sub_ratios - med)))
                # Anchor reference median to official regulated rate (1.00)
                # and apply MAD floor (0.02) to prevent peer-cohort skewing
                self.peer_stats_[tuple(str(k) for k in key)] = {
                    "median": min(med, 1.00),
                    "mad": max(mad, 0.02),
                    "count": len(sub_ratios),
                }

        return self

    def score_peer_robust_zscore(
        self,
        X: pd.DataFrame,
        peer_metadata: pd.DataFrame,
    ) -> tuple[np.ndarray, list[dict[str, Any]]]:
        """Compute peer-relative robust Z-scores and peer median context."""
        assert_feature_columns(X)
        fee_ratios = X["agent_fee_ratio_over_official"].to_numpy()
        n = len(X)
        z_scores = np.zeros(n, dtype=float)
        contexts: list[dict[str, Any]] = []

        group_cols = [c for c in self.peer_group_cols if c in peer_metadata.columns]

        for i in range(n):
            val = float(fee_ratios[i])
            if group_cols:
                key = tuple(str(peer_metadata[c].iloc[i]) for c in group_cols)
                stats = self.peer_stats_.get(key)
                if stats and stats["count"] >= 5:
                    med = stats["median"]
                    mad = stats["mad"]
                    p_desc = ",".join(f"{c}={peer_metadata[c].iloc[i]}" for c in group_cols)
                else:
                    med = self.global_stats_.get("median", 1.00)
                    mad = self.global_stats_.get("mad", 0.02)
                    p_desc = "global_anchored"
            else:
                med = self.global_stats_.get("median", 1.00)
                mad = self.global_stats_.get("mad", 0.02)
                p_desc = "global_anchored"

            # 1.4826 normal consistency factor for MAD
            scale = max(mad * 1.4826, 0.02)
            z = max(0.0, (val - med) / scale)
            z_scores[i] = z
            contexts.append(
                {
                    "peer_median": med,
                    "peer_mad": mad,
                    "peer_group": p_desc,
                    "z_score": float(z),
                }
            )

        # Calibrated smooth sigmoid:
        # z = 0.0 (fee ratio 1.00) -> risk ~ 0.023
        # z = 1.5 (moderate overcharge ~4%) -> risk ~ 0.50
        # z >= 2.5 (skimmer overcharge >= 7%) -> risk >= 0.92
        risk = 1.0 / (1.0 + np.exp(-2.5 * (z_scores - 1.5)))
        return risk, contexts

    def score_isolation_forest(self, X: pd.DataFrame) -> np.ndarray:
        """Compute Isolation Forest anomaly risk score in [0, 1]."""
        assert_feature_columns(X)
        if self.iforest is None:
            raise RuntimeError("Model must be fitted first.")
        # Invert score: raw negative score indicates anomalousness
        raw = -self.iforest.score_samples(X)
        # Normalize into [0, 1]
        r_min, r_max = raw.min(), raw.max()
        if r_max > r_min:
            norm = (raw - r_min) / (r_max - r_min)
        else:
            norm = np.zeros_like(raw)
        return norm

    def score_combined(
        self,
        X: pd.DataFrame,
        peer_metadata: pd.DataFrame,
        weight_z: float = 0.70,
        weight_iforest: float = 0.30,
    ) -> tuple[np.ndarray, list[dict[str, Any]]]:
        """Compute ensembled anomaly risk score."""
        z_risk, contexts = self.score_peer_robust_zscore(X, peer_metadata)
        if_risk = self.score_isolation_forest(X)
        combined = weight_z * z_risk + weight_iforest * if_risk
        return np.clip(combined, 0.0, 1.0), contexts

    def get_risk_level(self, risk: float) -> str:
        """Categorize risk level according to policy thresholds."""
        if risk >= self.high_risk_threshold:
            return "HIGH"
        if risk >= 0.50:
            return "MEDIUM"
        return "LOW"

    def explain(
        self,
        agent_id: str,
        X_row: pd.Series | dict[str, Any],
        peer_row: pd.Series | dict[str, Any],
    ) -> dict[str, Any]:
        """Generate structured risk explanation conforming to docs/api-contracts.md."""
        if isinstance(X_row, dict):
            df_x = pd.DataFrame([X_row])
        else:
            df_x = pd.DataFrame([X_row.to_dict()])
        assert_feature_columns(df_x)

        if isinstance(peer_row, dict):
            df_peer = pd.DataFrame([peer_row])
        else:
            df_peer = pd.DataFrame([peer_row.to_dict()])

        risk_arr, contexts = self.score_combined(df_x, df_peer)
        risk = float(risk_arr[0])
        ctx = contexts[0]
        level = self.get_risk_level(risk)

        fee_val = float(df_x["agent_fee_ratio_over_official"].iloc[0])
        reasons = [
            {
                "feature": "fee_ratio_vs_official",
                "value": round(fee_val, 3),
                "peer_median": round(ctx["peer_median"], 3),
            }
        ]

        # Additional anomaly indicator if allowance volume is elevated
        if "agent_allowance_day_volume_ratio" in df_x.columns:
            vol_val = float(df_x["agent_allowance_day_volume_ratio"].iloc[0])
            if vol_val > 1.5:
                reasons.append(
                    {
                        "feature": "allowance_day_volume_spike",
                        "value": round(vol_val, 2),
                        "peer_median": 1.0,
                    }
                )

        return {
            "agent_id": str(agent_id),
            "risk": round(risk, 2),
            "level": level,
            "reasons": reasons,
            "peer_group": ctx["peer_group"],
            "model_version": "agent_anomaly_v1",
        }

    def evaluate(
        self,
        X: pd.DataFrame,
        y: pd.Series | np.ndarray,
        peer_metadata: pd.DataFrame,
        agent_types: pd.Series | list[str] | None = None,
        top_k: int = 15,
    ) -> dict[str, Any]:
        """Evaluate precision@k, recall on skimmers, and false-flag rate on honest agents."""
        assert_feature_columns(X)
        y_true = np.asarray(y).astype(int)

        z_risk, _ = self.score_peer_robust_zscore(X, peer_metadata)
        if_risk = self.score_isolation_forest(X)
        combined_risk, _ = self.score_combined(X, peer_metadata)

        def _metrics_for_scores(scores: np.ndarray, model_name: str) -> dict[str, Any]:
            top_k_actual = min(top_k, len(scores))
            top_k_indices = np.argsort(scores)[::-1][:top_k_actual]
            precision_at_k = (
                float(y_true[top_k_indices].sum()) / float(top_k_actual)
                if top_k_actual > 0
                else 0.0
            )

            # High risk binary flags
            flagged = (scores >= self.high_risk_threshold).astype(int)
            recall = (
                float((flagged & y_true).sum()) / float(y_true.sum()) if y_true.sum() > 0 else 0.0
            )

            # False flag rate on honest high volume agents
            false_flag_rate_honest = 0.0
            if agent_types is not None:
                types_arr = np.asarray(agent_types)
                honest_idx = types_arr == "high_volume_honest"
                if honest_idx.sum() > 0:
                    false_flag_rate_honest = float(flagged[honest_idx].sum()) / float(
                        honest_idx.sum()
                    )

            return {
                "model": model_name,
                f"precision_at_{top_k}": precision_at_k,
                "recall_on_skimmers": recall,
                "flagged_high_risk_count": int(flagged.sum()),
                "false_flag_rate_honest_high_volume": false_flag_rate_honest,
            }

        return {
            "peer_robust_zscore": _metrics_for_scores(z_risk, "peer_robust_zscore"),
            "isolation_forest": _metrics_for_scores(if_risk, "isolation_forest"),
            "combined": _metrics_for_scores(combined_risk, "combined_ensemble"),
            "total_agents": len(y_true),
            "total_skimmers": int(y_true.sum()),
        }
