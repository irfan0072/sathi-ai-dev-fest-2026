"""Agent anomaly detector for Sathi using Peer Robust Z-Score and Isolation Forest.

Conforms strictly to docs/design-repair-proposal.md, docs/api-contracts.md, and tasks/T023:
- Fit uses X numeric behavior only; never uses peer_metadata region,
  agent_type, or generated volume_band.
- Learns volume-band boundaries from train agent_volume_daily_mean only
  using configured quantiles.
- Reference robust fee statistics (median, MAD) and Isolation Forest
  normalization bounds (min, max) are frozen from train.
- Changing protected metadata (region) or ground-truth labels never changes scores.
- Single-row versus batch scores are identical.
- Default weights, MAD floor, sigmoid parameters, contamination, and policy
  thresholds from config.
- Never fits on evaluated agents.
- Serialization (save/load) preserves all frozen train state for deterministic inference.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from app.data.config import ConfigError, load_config
from app.features.guard import assert_feature_columns


def load_agent_anomaly_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load agent anomaly config via shared config loader."""
    return load_config(config_path)


class AgentAnomalyDetector:
    """Agent anomaly detector combining peer-relative robust stats and Isolation Forest."""

    def __init__(
        self,
        n_estimators: int | None = None,
        contamination: float | None = None,
        peer_groups: list[str] | None = None,
        volume_quantiles: list[float] | tuple[float, float] | None = None,
        weight_z: float | None = None,
        weight_iforest: float | None = None,
        mad_floor: float | None = None,
        z_sigmoid_slope: float | None = None,
        z_sigmoid_midpoint: float | None = None,
        random_state: int = 42,
        config: dict[str, Any] | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        if config is not None:
            from app.data.config import validate_config

            self.config = validate_config(config)
        else:
            self.config = load_agent_anomaly_config(config_path)

        models_cfg = self.config.get("models", {})
        aa_cfg = models_cfg.get("agent_anomaly", {})
        policy_cfg = self.config.get("policy", {})

        # Config-driven parameter loading with constructor overrides
        if n_estimators is not None:
            if (
                isinstance(n_estimators, bool)
                or not isinstance(n_estimators, int)
                or n_estimators < 1
            ):
                raise ValueError("n_estimators must be an integer >= 1.")
            self.n_estimators = n_estimators
        elif "n_estimators" in aa_cfg:
            self.n_estimators = int(aa_cfg["n_estimators"])
        else:
            raise ConfigError("models.agent_anomaly.n_estimators is required in config.")

        if contamination is not None:
            if (
                isinstance(contamination, bool)
                or not isinstance(contamination, (int, float))
                or not math.isfinite(contamination)
                or not (0.0 < contamination <= 0.5)
            ):
                raise ValueError("contamination must be a number in (0, 0.5].")
            self.contamination = float(contamination)
        elif "contamination" in aa_cfg:
            self.contamination = float(aa_cfg["contamination"])
        else:
            raise ConfigError("models.agent_anomaly.contamination is required in config.")

        if peer_groups is not None:
            if peer_groups != ["volume_band"]:
                raise ValueError("peer_groups must equal ['volume_band'].")
            self.peer_groups = list(peer_groups)
        elif "peer_groups" in aa_cfg:
            self.peer_groups = list(aa_cfg["peer_groups"])
        else:
            raise ConfigError("models.agent_anomaly.peer_groups is required in config.")

        # Ensure protected attributes or labels never enter peer groups
        if "region" in self.peer_groups or "agent_type" in self.peer_groups:
            raise ConfigError(
                "Protected attributes ('region') and ground-truth labels ('agent_type') "
                "are strictly prohibited in agent_anomaly.peer_groups."
            )

        if volume_quantiles is not None:
            if (
                not isinstance(volume_quantiles, (list, tuple))
                or len(volume_quantiles) != 2
                or any(
                    isinstance(q, bool) or not isinstance(q, (int, float)) or not math.isfinite(q)
                    for q in volume_quantiles
                )
            ):
                raise ValueError("volume_quantiles must be a list or tuple of two finite numbers.")
            q1, q2 = float(volume_quantiles[0]), float(volume_quantiles[1])
            if not (0.0 < q1 < q2 < 1.0):
                raise ValueError("volume_quantiles must satisfy 0.0 < q1 < q2 < 1.0.")
            self.volume_quantiles = (q1, q2)
        elif "volume_quantiles" in aa_cfg:
            v_q = aa_cfg["volume_quantiles"]
            self.volume_quantiles = (float(v_q[0]), float(v_q[1]))
        else:
            raise ConfigError("models.agent_anomaly.volume_quantiles is required in config.")

        if weight_z is not None:
            if (
                isinstance(weight_z, bool)
                or not isinstance(weight_z, (int, float))
                or not math.isfinite(weight_z)
                or not (0.0 <= weight_z <= 1.0)
            ):
                raise ValueError("weight_z must be a finite number in [0.0, 1.0].")
            self.weight_z = float(weight_z)
        elif "weight_z" in aa_cfg:
            self.weight_z = float(aa_cfg["weight_z"])
        else:
            raise ConfigError("models.agent_anomaly.weight_z is required in config.")

        if weight_iforest is not None:
            if (
                isinstance(weight_iforest, bool)
                or not isinstance(weight_iforest, (int, float))
                or not math.isfinite(weight_iforest)
                or not (0.0 <= weight_iforest <= 1.0)
            ):
                raise ValueError("weight_iforest must be a finite number in [0.0, 1.0].")
            self.weight_iforest = float(weight_iforest)
        elif "weight_iforest" in aa_cfg:
            self.weight_iforest = float(aa_cfg["weight_iforest"])
        else:
            raise ConfigError("models.agent_anomaly.weight_iforest is required in config.")

        if abs(self.weight_z + self.weight_iforest - 1.0) > 1e-4:
            raise ValueError(f"weights must sum to 1.0, got {self.weight_z + self.weight_iforest}")

        if mad_floor is not None:
            if (
                isinstance(mad_floor, bool)
                or not isinstance(mad_floor, (int, float))
                or not math.isfinite(mad_floor)
                or mad_floor <= 0.0
            ):
                raise ValueError("mad_floor must be a positive finite number.")
            self.mad_floor = float(mad_floor)
        elif "mad_floor" in aa_cfg:
            self.mad_floor = float(aa_cfg["mad_floor"])
        else:
            raise ConfigError("models.agent_anomaly.mad_floor is required in config.")

        if z_sigmoid_slope is not None:
            if (
                isinstance(z_sigmoid_slope, bool)
                or not isinstance(z_sigmoid_slope, (int, float))
                or not math.isfinite(z_sigmoid_slope)
                or z_sigmoid_slope <= 0.0
            ):
                raise ValueError("z_sigmoid_slope must be a positive finite number.")
            self.z_sigmoid_slope = float(z_sigmoid_slope)
        elif "z_sigmoid_slope" in aa_cfg:
            self.z_sigmoid_slope = float(aa_cfg["z_sigmoid_slope"])
        else:
            raise ConfigError("models.agent_anomaly.z_sigmoid_slope is required in config.")

        if z_sigmoid_midpoint is not None:
            if (
                isinstance(z_sigmoid_midpoint, bool)
                or not isinstance(z_sigmoid_midpoint, (int, float))
                or not math.isfinite(z_sigmoid_midpoint)
            ):
                raise ValueError("z_sigmoid_midpoint must be a finite number.")
            self.z_sigmoid_midpoint = float(z_sigmoid_midpoint)
        elif "z_sigmoid_midpoint" in aa_cfg:
            self.z_sigmoid_midpoint = float(aa_cfg["z_sigmoid_midpoint"])
        else:
            raise ConfigError("models.agent_anomaly.z_sigmoid_midpoint is required in config.")

        if "review_top_k" in aa_cfg:
            self.review_top_k: int = int(aa_cfg["review_top_k"])
        else:
            raise ConfigError("models.agent_anomaly.review_top_k is required in config.")

        if "agent_risk_high" in policy_cfg:
            self.high_risk_threshold: float = float(policy_cfg["agent_risk_high"])
        else:
            raise ConfigError("policy.agent_risk_high is required in config.")

        if "agent_risk_medium" in policy_cfg:
            self.medium_risk_threshold: float = float(policy_cfg["agent_risk_medium"])
        else:
            raise ConfigError("policy.agent_risk_medium is required in config.")

        if isinstance(random_state, bool) or not isinstance(random_state, int):
            raise ValueError("random_state must be an integer.")
        self.random_state = random_state

        # Learned and frozen attributes on train
        self.iforest: IsolationForest | None = None
        self.volume_band_thresholds_: tuple[float, float] = (0.0, 0.0)
        self.peer_stats_: dict[str, dict[str, float]] = {}
        self.global_stats_: dict[str, float] = {}
        self.if_min_: float = 0.0
        self.if_max_: float = 1.0
        self.feature_names_: list[str] = []

    def _validate_input_matrix(self, X: pd.DataFrame, is_fitting: bool = False) -> None:
        """Validate input feature matrix: approved numeric behavioral columns, finite values."""
        if not isinstance(X, pd.DataFrame):
            raise ValueError(f"X must be a pandas DataFrame, got {type(X).__name__}")
        assert_feature_columns(X)
        if is_fitting:
            if X.empty:
                raise ValueError("Feature matrix cannot be empty.")
            for req in ("agent_fee_ratio_over_official", "agent_volume_daily_mean"):
                if req not in X.columns:
                    raise ValueError(f"Missing required behavioral feature '{req}'.")
        else:
            if not self.feature_names_:
                raise RuntimeError("Detector must be fitted before scoring.")
            if list(X.columns) != self.feature_names_:
                raise ValueError(
                    f"Column mismatch: expected trained columns {self.feature_names_}, "
                    f"got {list(X.columns)}"
                )

        arr = X.to_numpy()
        if not np.issubdtype(arr.dtype, np.number):
            raise ValueError("Feature matrix must contain purely numeric data.")
        if not np.all(np.isfinite(arr)):
            raise ValueError("Feature matrix contains NaN, infinite, or non-finite values.")

    def _compute_volume_band(self, vol: float) -> str:
        """Determine volume band from agent_volume_daily_mean using learned train thresholds."""
        low_th, high_th = self.volume_band_thresholds_
        if vol < low_th:
            return "low"
        if vol < high_th:
            return "medium"
        return "high"

    def fit(
        self,
        X: pd.DataFrame,
        peer_metadata: pd.DataFrame | None = None,
    ) -> AgentAnomalyDetector:
        """Fit Isolation Forest and freeze robust baseline statistics on train agents only.

        peer_metadata is strictly ignored to guarantee protected metadata and ground-truth
        labels never influence scores or volume bands.
        """
        self._validate_input_matrix(X, is_fitting=True)
        proposed_feature_names = list(X.columns)

        # 1. Learn volume band thresholds from train agent_volume_daily_mean only
        vols = X["agent_volume_daily_mean"].to_numpy(dtype=float)
        q_low = float(np.quantile(vols, self.volume_quantiles[0]))
        q_high = float(np.quantile(vols, self.volume_quantiles[1]))
        volume_band_thresholds = (q_low, q_high)

        # 2. Compute reference robust statistics on train fee ratios
        fee_ratios = X["agent_fee_ratio_over_official"].to_numpy(dtype=float)
        glob_med = min(float(np.median(fee_ratios)), 1.00)
        glob_mad = max(float(np.median(np.abs(fee_ratios - glob_med))), self.mad_floor)
        global_stats = {
            "median": glob_med,
            "mad": glob_mad,
        }

        # 3. Compute volume-band cohort statistics frozen from train
        peer_stats: dict[str, dict[str, float]] = {}

        def _compute_band_local(vol: float) -> str:
            if vol < q_low:
                return "low"
            if vol < q_high:
                return "medium"
            return "high"

        derived_bands = np.array([_compute_band_local(v) for v in vols])
        for band in ("low", "medium", "high"):
            mask = derived_bands == band
            sub_ratios = fee_ratios[mask]
            if len(sub_ratios) >= 3:
                b_med = min(float(np.median(sub_ratios)), 1.00)
                b_mad = max(float(np.median(np.abs(sub_ratios - b_med))), self.mad_floor)
                peer_stats[band] = {
                    "median": b_med,
                    "mad": b_mad,
                    "count": len(sub_ratios),
                }

        # 4. Fit Isolation Forest on train numeric features only
        new_iforest = IsolationForest(
            n_estimators=self.n_estimators,
            contamination=self.contamination,
            random_state=self.random_state,
        )
        new_iforest.fit(X)

        # 5. Freeze Isolation Forest normalization bounds from train
        train_raw_scores = -new_iforest.score_samples(X)
        if_min = float(train_raw_scores.min())
        if_max = float(train_raw_scores.max())

        # Atomically publish fitted state on success
        self.feature_names_ = proposed_feature_names
        self.volume_band_thresholds_ = volume_band_thresholds
        self.global_stats_ = global_stats
        self.peer_stats_ = peer_stats
        self.iforest = new_iforest
        self.if_min_ = if_min
        self.if_max_ = if_max

        return self

    def score_peer_robust_zscore(
        self,
        X: pd.DataFrame,
        peer_metadata: pd.DataFrame | None = None,
    ) -> tuple[np.ndarray, list[dict[str, Any]]]:
        """Compute peer-relative robust Z-scores using learned volume bands.

        peer_metadata is never used in scoring; protected metadata invariance is absolute.
        """
        self._validate_input_matrix(X, is_fitting=False)
        fee_ratios = X["agent_fee_ratio_over_official"].to_numpy(dtype=float)
        vols = X["agent_volume_daily_mean"].to_numpy(dtype=float)
        n = len(X)
        z_scores = np.zeros(n, dtype=float)
        contexts: list[dict[str, Any]] = []

        for i in range(n):
            val = float(fee_ratios[i])
            vol = float(vols[i])
            band = self._compute_volume_band(vol)

            stats = self.peer_stats_.get(band)
            if stats and stats["count"] >= 3:
                med = stats["median"]
                mad = stats["mad"]
                p_desc = f"volume_band={band}"
            else:
                med = self.global_stats_["median"]
                mad = self.global_stats_["mad"]
                p_desc = "global_anchored"

            # 1.4826 normal consistency factor for MAD
            scale = max(mad * 1.4826, self.mad_floor)
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

        # Heuristic smooth sigmoid mapping using configured slope and midpoint
        # (not fitted calibration)
        risk = 1.0 / (1.0 + np.exp(-self.z_sigmoid_slope * (z_scores - self.z_sigmoid_midpoint)))
        return np.asarray(risk, dtype=float), contexts

    def score_isolation_forest(self, X: pd.DataFrame) -> np.ndarray:
        """Compute Isolation Forest anomaly score normalized against train-frozen bounds.

        Guarantees single-row scores are strictly identical to batch scores.
        """
        self._validate_input_matrix(X, is_fitting=False)
        if self.iforest is None:
            raise RuntimeError("Model must be fitted before scoring.")

        raw = -self.iforest.score_samples(X)
        if self.if_max_ > self.if_min_:
            norm = np.clip((raw - self.if_min_) / (self.if_max_ - self.if_min_), 0.0, 1.0)
        else:
            norm = np.zeros_like(raw)
        return norm

    def score_combined(
        self,
        X: pd.DataFrame,
        peer_metadata: pd.DataFrame | None = None,
        weight_z: float | None = None,
        weight_iforest: float | None = None,
    ) -> tuple[np.ndarray, list[dict[str, Any]]]:
        """Compute ensembled anomaly risk score using configured weights."""
        w_z = weight_z if weight_z is not None else self.weight_z
        w_if = weight_iforest if weight_iforest is not None else self.weight_iforest

        z_risk, contexts = self.score_peer_robust_zscore(X, peer_metadata)
        if_risk = self.score_isolation_forest(X)
        combined = w_z * z_risk + w_if * if_risk
        return np.clip(combined, 0.0, 1.0), contexts

    def get_risk_level(self, risk: float) -> str:
        """Categorize risk level according to policy thresholds from config."""
        if risk >= self.high_risk_threshold:
            return "HIGH"
        if risk >= self.medium_risk_threshold:
            return "MEDIUM"
        return "LOW"

    def explain(
        self,
        agent_id: str,
        X_row: pd.Series | dict[str, Any],
        peer_row: pd.Series | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate structured risk explanation conforming to docs/api-contracts.md."""
        if isinstance(X_row, dict):
            df_x = pd.DataFrame([X_row])
        elif isinstance(X_row, pd.Series):
            df_x = pd.DataFrame([X_row.to_dict()])
        elif isinstance(X_row, pd.DataFrame):
            df_x = X_row
        else:
            raise ValueError(f"Unsupported row type: {type(X_row)}")

        if len(df_x) != 1:
            raise ValueError(f"explain requires exactly 1 row, got {len(df_x)} rows.")

        risk_arr, contexts = self.score_combined(df_x, None)
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

        allowance_vol_threshold = (
            self.config.get("models", {})
            .get("agent_anomaly", {})
            .get("allowance_volume_threshold")
        )
        if (
            allowance_vol_threshold is not None
            and "agent_allowance_day_volume_ratio" in df_x.columns
        ):
            vol_val = float(df_x["agent_allowance_day_volume_ratio"].iloc[0])
            if vol_val > float(allowance_vol_threshold):
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
        peer_metadata: pd.DataFrame | None = None,
        agent_types: pd.Series | list[str] | None = None,
        top_k: int = 15,
    ) -> dict[str, Any]:
        """Evaluate precision@k, recall on skimmers, and false-flag rate on honest agents."""
        self._validate_input_matrix(X, is_fitting=False)
        y_true = np.asarray(y, dtype=int)

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

            flagged = (scores >= self.high_risk_threshold).astype(int)
            recall = (
                float((flagged & y_true).sum()) / float(y_true.sum()) if y_true.sum() > 0 else 0.0
            )

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

    def save(self, filepath: str | Path) -> None:
        """Serialize model artifact to disk preserving all frozen train statistics and config."""
        if self.iforest is None or not self.feature_names_:
            raise ValueError(
                "Cannot save unfitted model artifact: requires fitted estimator and schema."
            )
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "iforest": self.iforest,
            "volume_band_thresholds": self.volume_band_thresholds_,
            "peer_stats": self.peer_stats_,
            "global_stats": self.global_stats_,
            "if_min": self.if_min_,
            "if_max": self.if_max_,
            "feature_names": self.feature_names_,
            "config": self.config,
            "n_estimators": self.n_estimators,
            "contamination": self.contamination,
            "peer_groups": self.peer_groups,
            "volume_quantiles": self.volume_quantiles,
            "weight_z": self.weight_z,
            "weight_iforest": self.weight_iforest,
            "mad_floor": self.mad_floor,
            "z_sigmoid_slope": self.z_sigmoid_slope,
            "z_sigmoid_midpoint": self.z_sigmoid_midpoint,
            "review_top_k": self.review_top_k,
            "high_risk_threshold": self.high_risk_threshold,
            "medium_risk_threshold": self.medium_risk_threshold,
            "random_state": self.random_state,
        }
        joblib.dump(payload, path)

    @classmethod
    def load(cls, filepath: str | Path) -> AgentAnomalyDetector:
        """Deserialize model artifact from disk with frozen train state restored."""
        payload = joblib.load(filepath)
        detector = cls(
            n_estimators=payload["n_estimators"],
            contamination=payload["contamination"],
            peer_groups=payload["peer_groups"],
            volume_quantiles=payload["volume_quantiles"],
            weight_z=payload["weight_z"],
            weight_iforest=payload["weight_iforest"],
            mad_floor=payload["mad_floor"],
            z_sigmoid_slope=payload["z_sigmoid_slope"],
            z_sigmoid_midpoint=payload["z_sigmoid_midpoint"],
            random_state=payload["random_state"],
            config=payload["config"],
        )
        detector.iforest = payload["iforest"]
        detector.volume_band_thresholds_ = payload["volume_band_thresholds"]
        detector.peer_stats_ = payload["peer_stats"]
        detector.global_stats_ = payload["global_stats"]
        detector.if_min_ = payload["if_min"]
        detector.if_max_ = payload["if_max"]
        detector.feature_names_ = payload["feature_names"]
        detector.review_top_k = payload["review_top_k"]
        detector.high_risk_threshold = payload["high_risk_threshold"]
        detector.medium_risk_threshold = payload["medium_risk_threshold"]
        return detector
