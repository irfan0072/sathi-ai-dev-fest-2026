"""Deterministic rule-based baseline implementations for Sathi.

Implements:
1. AssistedUserRuleBaseline: Classifies customer as assisted if:
   top_agent_share >= 0.70 AND credit_to_cashout_hours_mean <= 24.0.
2. AgentAnomalyRuleBaseline: Flags agent as anomalous/skimmer if:
   agent_fee_ratio_over_official >= 1.2.

Both read defaults from data/config.yaml and verify against the feature guard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import (
    accuracy_score,
    auc,
    brier_score_loss,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
)

from app.features.guard import assert_feature_columns


def load_config_baselines(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load baseline configurations from data/config.yaml."""
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
                if isinstance(cfg, dict) and "models" in cfg and "baselines" in cfg["models"]:
                    return cfg["models"]["baselines"]
            except Exception:
                continue

    return {
        "assisted_rule": {"top_agent_share_min": 0.7, "hours_credit_to_cashout_max": 24.0},
        "agent_rule": {"fee_ratio_over_official_min": 1.2},
    }


class AssistedUserRuleBaseline:
    """Deterministic rule-based baseline for assisted-user detection."""

    def __init__(
        self,
        top_agent_share_min: float | None = None,
        hours_credit_to_cashout_max: float | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        cfg = load_config_baselines(config_path).get("assisted_rule", {})
        self.top_agent_share_min = (
            float(top_agent_share_min)
            if top_agent_share_min is not None
            else float(cfg.get("top_agent_share_min", 0.7))
        )
        self.hours_credit_to_cashout_max = (
            float(hours_credit_to_cashout_max)
            if hours_credit_to_cashout_max is not None
            else float(cfg.get("hours_credit_to_cashout_max", 24.0))
        )

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Predict binary classification (1=assisted, 0=independent)."""
        assert_feature_columns(X)
        top_share = X["top_agent_share"].to_numpy()
        delays = X["credit_to_cashout_hours_mean"].to_numpy()

        mask = (top_share >= self.top_agent_share_min) & (
            delays <= self.hours_credit_to_cashout_max
        )
        return mask.astype(int)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Return pseudo-probabilities based on rule confidence."""
        assert_feature_columns(X)
        preds = self.predict(X)
        # Score proportional to top_agent_share if matching, else 0.1
        scores = np.where(preds == 1, np.clip(X["top_agent_share"].to_numpy(), 0.6, 1.0), 0.1)
        p1 = np.clip(scores, 0.0, 1.0)
        p0 = 1.0 - p1
        return np.column_stack([p0, p1])

    def evaluate(
        self,
        X: pd.DataFrame,
        y: pd.Series | np.ndarray,
        slices: pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        """Compute performance metrics and fairness breakdown."""
        assert_feature_columns(X)
        y_true = np.asarray(y)
        y_pred = self.predict(X)
        y_proba = self.predict_proba(X)[:, 1]

        # PR-AUC
        precision_pts, recall_pts, _ = precision_recall_curve(y_true, y_proba)
        pr_auc = float(auc(recall_pts, precision_pts))

        metrics = {
            "model": "assisted_rule_baseline",
            "accuracy": float(accuracy_score(y_true, y_pred)),
            "precision": float(precision_score(y_true, y_pred, zero_division=0)),
            "recall": float(recall_score(y_true, y_pred, zero_division=0)),
            "f1": float(f1_score(y_true, y_pred, zero_division=0)),
            "pr_auc": pr_auc,
            "brier_score": float(brier_score_loss(y_true, y_proba)),
        }

        # Slices breakdown
        if slices is not None:
            slice_metrics: dict[str, dict[str, float]] = {}
            for col in ("gender", "age_band", "region", "urban_rural"):
                if col in slices.columns:
                    slice_metrics[col] = {}
                    categories = slices[col].unique()
                    tprs: list[float] = []
                    for cat in categories:
                        idx = (slices[col] == cat).to_numpy()
                        if idx.sum() > 0:
                            sub_y_true = y_true[idx]
                            sub_y_pred = y_pred[idx]
                            tpr = (
                                float(recall_score(sub_y_true, sub_y_pred, zero_division=0))
                                if sub_y_true.sum() > 0
                                else 0.0
                            )
                            slice_metrics[col][str(cat)] = tpr
                            if sub_y_true.sum() > 0:
                                tprs.append(tpr)
                    if tprs:
                        slice_metrics[col]["max_tpr_gap"] = float(max(tprs) - min(tprs))
            metrics["slices"] = slice_metrics

        return metrics


class AgentAnomalyRuleBaseline:
    """Deterministic rule-based baseline for agent skimming detection."""

    def __init__(
        self,
        fee_ratio_over_official_min: float | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        cfg = load_config_baselines(config_path).get("agent_rule", {})
        self.fee_ratio_min = (
            float(fee_ratio_over_official_min)
            if fee_ratio_over_official_min is not None
            else float(cfg.get("fee_ratio_over_official_min", 1.2))
        )

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Flag agent as anomalous (1) or normal (0)."""
        assert_feature_columns(X)
        ratios = X["agent_fee_ratio_over_official"].to_numpy()
        return (ratios >= self.fee_ratio_min).astype(int)

    def score(self, X: pd.DataFrame) -> np.ndarray:
        """Continuous anomaly score (higher means more suspicious)."""
        assert_feature_columns(X)
        return X["agent_fee_ratio_over_official"].to_numpy()

    def evaluate(
        self,
        X: pd.DataFrame,
        y: pd.Series | np.ndarray,
        agent_types: pd.Series | list[str] | None = None,
        top_k: int = 15,
    ) -> dict[str, Any]:
        """Evaluate agent detection precision, recall, and false-positive flags."""
        assert_feature_columns(X)
        y_true = np.asarray(y)
        y_pred = self.predict(X)
        scores = self.score(X)

        # Precision at top-K
        top_k_indices = np.argsort(scores)[::-1][:top_k]
        p_at_k = float(y_true[top_k_indices].sum()) / float(top_k) if top_k > 0 else 0.0

        # False-flag rate on honest high volume
        false_flag_rate_honest = 0.0
        if agent_types is not None:
            types_arr = np.asarray(agent_types)
            honest_idx = types_arr == "high_volume_honest"
            if honest_idx.sum() > 0:
                false_flag_rate_honest = float(y_pred[honest_idx].sum()) / float(honest_idx.sum())

        return {
            "model": "agent_rule_baseline",
            "accuracy": float(accuracy_score(y_true, y_pred)),
            "precision": float(precision_score(y_true, y_pred, zero_division=0)),
            "recall": float(recall_score(y_true, y_pred, zero_division=0)),
            "recall_on_skimmers": float(recall_score(y_true, y_pred, zero_division=0)),
            "f1": float(f1_score(y_true, y_pred, zero_division=0)),
            f"precision_at_{top_k}": p_at_k,
            "flagged_count": int(y_pred.sum()),
            "false_flag_rate_honest_high_volume": false_flag_rate_honest,
            "total_agents": len(y_true),
        }
