"""Deterministic rule-based baseline implementations for Sathi.

Implements:
1. AssistedUserRuleBaseline: Classifies customer as assisted if:
   top_agent_share >= top_agent_share_min AND
   credit_to_cashout_hours_mean <= hours_credit_to_cashout_max.
2. AgentAnomalyRuleBaseline: Flags agent as anomalous/skimmer if:
   agent_fee_ratio_over_official >= fee_ratio_over_official_min.

Both read defaults from data/config.yaml using app.data.config.load_config
and verify against the feature guard.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    auc,
    brier_score_loss,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
)

from app.data.config import ConfigError, load_config
from app.features.guard import assert_feature_columns


def load_config_baselines(
    config_path: str | Path | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load baseline configurations from data/config.yaml using shared loader."""
    if config is not None:
        from app.data.config import validate_config

        cfg = validate_config(config)
    else:
        cfg = load_config(config_path)

    if isinstance(cfg, dict) and "models" in cfg and "baselines" in cfg["models"]:
        return cfg["models"]["baselines"]

    raise ConfigError("models.baselines mapping not found in configuration.")


class AssistedUserRuleBaseline:
    """Deterministic rule-based baseline for assisted-user detection."""

    def __init__(
        self,
        top_agent_share_min: float | None = None,
        hours_credit_to_cashout_max: float | None = None,
        config: dict[str, Any] | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        bl_cfg = load_config_baselines(config_path=config_path, config=config)
        cfg = bl_cfg.get("assisted_rule")
        if not isinstance(cfg, dict):
            raise ConfigError("Missing models.baselines.assisted_rule mapping in configuration.")

        if top_agent_share_min is not None:
            if (
                isinstance(top_agent_share_min, bool)
                or not isinstance(top_agent_share_min, (int, float))
                or not math.isfinite(top_agent_share_min)
                or not (0.0 <= top_agent_share_min <= 1.0)
            ):
                raise ValueError("top_agent_share_min must be a probability in [0.0, 1.0].")
            self.top_agent_share_min = float(top_agent_share_min)
        elif "top_agent_share_min" in cfg:
            self.top_agent_share_min = float(cfg["top_agent_share_min"])
        else:
            raise ConfigError(
                "models.baselines.assisted_rule.top_agent_share_min is required in config."
            )

        if hours_credit_to_cashout_max is not None:
            if (
                isinstance(hours_credit_to_cashout_max, bool)
                or not isinstance(hours_credit_to_cashout_max, (int, float))
                or not math.isfinite(hours_credit_to_cashout_max)
                or hours_credit_to_cashout_max <= 0.0
            ):
                raise ValueError("hours_credit_to_cashout_max must be a positive finite number.")
            self.hours_credit_to_cashout_max = float(hours_credit_to_cashout_max)
        elif "hours_credit_to_cashout_max" in cfg:
            self.hours_credit_to_cashout_max = float(cfg["hours_credit_to_cashout_max"])
        else:
            raise ConfigError(
                "models.baselines.assisted_rule.hours_credit_to_cashout_max is required in config."
            )

    def _validate_input(self, X: pd.DataFrame) -> None:
        if not isinstance(X, pd.DataFrame):
            raise ValueError(f"X must be a pandas DataFrame, got {type(X).__name__}")
        assert_feature_columns(X)
        for col in ("top_agent_share", "credit_to_cashout_hours_mean"):
            if col not in X.columns:
                raise ValueError(f"Missing required feature column '{col}'")
        arr = X[["top_agent_share", "credit_to_cashout_hours_mean"]].to_numpy()
        if not np.all(np.isfinite(arr)):
            raise ValueError("Feature matrix contains NaN or infinite values.")

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Predict binary classification (1=assisted, 0=independent)."""
        self._validate_input(X)
        top_share = X["top_agent_share"].to_numpy(dtype=float)
        delays = X["credit_to_cashout_hours_mean"].to_numpy(dtype=float)

        mask = (top_share >= self.top_agent_share_min) & (
            delays <= self.hours_credit_to_cashout_max
        )
        return mask.astype(int)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Return pseudo-probabilities based on actual binary rule prediction."""
        self._validate_input(X)
        preds = self.predict(X)
        p1 = preds.astype(float)
        p0 = 1.0 - p1
        return np.column_stack([p0, p1])

    def evaluate(
        self,
        X: pd.DataFrame,
        y: pd.Series | np.ndarray,
        slices: pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        """Compute performance metrics and fairness breakdown."""
        self._validate_input(X)
        y_true = np.asarray(y, dtype=int)
        y_pred = self.predict(X)
        y_proba = y_pred.astype(float)

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
        config: dict[str, Any] | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        bl_cfg = load_config_baselines(config_path=config_path, config=config)
        cfg = bl_cfg.get("agent_rule")
        if not isinstance(cfg, dict):
            raise ConfigError("Missing models.baselines.agent_rule mapping in configuration.")

        if fee_ratio_over_official_min is not None:
            if (
                isinstance(fee_ratio_over_official_min, bool)
                or not isinstance(fee_ratio_over_official_min, (int, float))
                or not math.isfinite(fee_ratio_over_official_min)
                or fee_ratio_over_official_min < 1.0
            ):
                raise ValueError("fee_ratio_over_official_min must be a finite number >= 1.0.")
            self.fee_ratio_min = float(fee_ratio_over_official_min)
        elif "fee_ratio_over_official_min" in cfg:
            val = cfg["fee_ratio_over_official_min"]
            if (
                isinstance(val, bool)
                or not isinstance(val, (int, float))
                or not math.isfinite(val)
                or val < 1.0
            ):
                raise ConfigError(
                    "models.baselines.agent_rule.fee_ratio_over_official_min must be >= 1.0."
                )
            self.fee_ratio_min = float(val)
        else:
            raise ConfigError(
                "models.baselines.agent_rule.fee_ratio_over_official_min is required in config."
            )

    def _validate_input(self, X: pd.DataFrame) -> None:
        if not isinstance(X, pd.DataFrame):
            raise ValueError(f"X must be a pandas DataFrame, got {type(X).__name__}")
        assert_feature_columns(X)
        if "agent_fee_ratio_over_official" not in X.columns:
            raise ValueError("Missing required feature column 'agent_fee_ratio_over_official'")
        arr = X["agent_fee_ratio_over_official"].to_numpy()
        if not np.all(np.isfinite(arr)):
            raise ValueError("Feature matrix contains NaN or infinite values.")

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Flag agent as anomalous (1) or normal (0)."""
        self._validate_input(X)
        ratios = X["agent_fee_ratio_over_official"].to_numpy(dtype=float)
        return (ratios >= self.fee_ratio_min).astype(int)

    def score(self, X: pd.DataFrame) -> np.ndarray:
        """Continuous anomaly score (higher means more suspicious)."""
        self._validate_input(X)
        return X["agent_fee_ratio_over_official"].to_numpy(dtype=float)

    def evaluate(
        self,
        X: pd.DataFrame,
        y: pd.Series | np.ndarray,
        agent_types: pd.Series | list[str] | None = None,
        top_k: int = 15,
    ) -> dict[str, Any]:
        """Evaluate agent detection precision, recall, and false-positive flags."""
        self._validate_input(X)
        y_true = np.asarray(y, dtype=int)
        y_pred = self.predict(X)
        scores = self.score(X)

        top_k_indices = np.argsort(scores)[::-1][:top_k]
        p_at_k = float(y_true[top_k_indices].sum()) / float(top_k) if top_k > 0 else 0.0

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
