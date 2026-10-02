"""Assisted-user classifier for Sathi using LightGBM, calibration, and SHAP.

Conforms strictly to docs/design-repair-proposal.md and tasks/T023:
- LightGBM gradient boosted trees on approved numeric behavioral features.
- Fits one base estimator on X_train/y_train; wraps fitted model with sklearn FrozenEstimator
  and sigmoid calibration on separate disjoint X_val/y_val.
- Never refits base model on validation.
- Zero feature leakage: rigorously enforces feature guard allowlist.
- Input matrices require exact trained columns in order, finite numeric only;
  target length/classes valid.
- SHAP TreeExplainer explains THAT base estimator, explicitly raw log-odds
  (not calibrated probability), with raw-score additivity verification.
- Predictions calibrated; save/load preserves fitted calibration + base +
  configuration and schema.
- No silent uncalibrated fallback.
- Demographic slice fairness auditing.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
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

try:
    from sklearn.frozen import FrozenEstimator
except ImportError:
    from sklearn.calibration import FrozenEstimator


def load_model_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load model and fairness configs via shared config loader."""
    return load_config(config_path)


class AssistedUserClassifier:
    """Production assisted-user classifier with calibration and SHAP explanations."""

    def __init__(
        self,
        n_estimators: int | None = None,
        learning_rate: float | None = None,
        max_depth: int | None = None,
        classification_threshold: float | None = None,
        calibration_method: str | None = None,
        calibrate: bool | None = None,
        random_state: int = 42,
        config: dict[str, Any] | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        if config is not None:
            from app.data.config import validate_config

            self.config = validate_config(config)
        else:
            self.config = load_model_config(config_path)

        models_cfg = self.config.get("models", {})
        ac_cfg = models_cfg.get("assisted_classifier", {})

        # Use constructor explicit override if provided; otherwise required from config
        if n_estimators is not None:
            if (
                isinstance(n_estimators, bool)
                or not isinstance(n_estimators, int)
                or n_estimators < 1
            ):
                raise ValueError("n_estimators must be an integer >= 1.")
            self.n_estimators = n_estimators
        elif "n_estimators" in ac_cfg:
            self.n_estimators = int(ac_cfg["n_estimators"])
        else:
            raise ConfigError("models.assisted_classifier.n_estimators is required in config.")

        if learning_rate is not None:
            if (
                isinstance(learning_rate, bool)
                or not isinstance(learning_rate, (int, float))
                or not math.isfinite(learning_rate)
                or learning_rate <= 0.0
            ):
                raise ValueError("learning_rate must be a positive finite number.")
            self.learning_rate = float(learning_rate)
        elif "learning_rate" in ac_cfg:
            self.learning_rate = float(ac_cfg["learning_rate"])
        else:
            raise ConfigError("models.assisted_classifier.learning_rate is required in config.")

        if max_depth is not None:
            if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 1:
                raise ValueError("max_depth must be an integer >= 1.")
            self.max_depth = max_depth
        elif "max_depth" in ac_cfg:
            self.max_depth = int(ac_cfg["max_depth"])
        else:
            raise ConfigError("models.assisted_classifier.max_depth is required in config.")

        if classification_threshold is not None:
            if (
                isinstance(classification_threshold, bool)
                or not isinstance(classification_threshold, (int, float))
                or not math.isfinite(classification_threshold)
                or not (0.0 <= classification_threshold <= 1.0)
            ):
                raise ValueError("classification_threshold must be a probability in [0.0, 1.0].")
            self.classification_threshold = float(classification_threshold)
        elif "classification_threshold" in ac_cfg:
            self.classification_threshold = float(ac_cfg["classification_threshold"])
        else:
            raise ConfigError(
                "models.assisted_classifier.classification_threshold is required in config."
            )

        if calibration_method is not None:
            if (
                not isinstance(calibration_method, str)
                or calibration_method not in ("sigmoid", "isotonic")
            ):
                raise ValueError("calibration_method must be 'sigmoid' or 'isotonic'.")
            self.calibration_method = str(calibration_method)
        elif "calibration_method" in ac_cfg:
            self.calibration_method = str(ac_cfg["calibration_method"])
        else:
            raise ConfigError(
                "models.assisted_classifier.calibration_method is required in config."
            )

        if calibrate is not None:
            if not isinstance(calibrate, bool):
                raise ValueError("calibrate must be a boolean.")
            self.calibrate = calibrate
        elif "calibrate" in ac_cfg:
            self.calibrate = bool(ac_cfg["calibrate"])
        else:
            raise ConfigError("models.assisted_classifier.calibrate is required in config.")

        if isinstance(random_state, bool) or not isinstance(random_state, int):
            raise ValueError("random_state must be an integer.")
        self.random_state = random_state

        sanity_cfg = models_cfg.get("sanity", {})
        if "max_pr_auc" in sanity_cfg:
            self.max_pr_auc_sanity: float = float(sanity_cfg["max_pr_auc"])
        else:
            raise ConfigError("models.sanity.max_pr_auc is required in config.")

        fairness_cfg = self.config.get("fairness", {})
        if "max_tpr_gap" in fairness_cfg:
            self.max_tpr_gap_target: float = float(fairness_cfg["max_tpr_gap"])
        else:
            raise ConfigError("fairness.max_tpr_gap is required in config.")

        self.lgbm_model: lgb.LGBMClassifier | None = None
        self.calibrated_model: CalibratedClassifierCV | None = None
        self.feature_names_: list[str] = []
        self._explainer: Any = None

    def _validate_input_matrix(
        self,
        X: pd.DataFrame,
        is_fitting: bool = False,
        expected_columns: list[str] | None = None,
    ) -> None:
        """Validate input feature matrix: exact trained columns in order, finite numeric only."""
        if not isinstance(X, pd.DataFrame):
            raise ValueError(f"Feature matrix must be a pandas DataFrame, got {type(X).__name__}")
        assert_feature_columns(X)
        if is_fitting:
            if X.empty or len(X.columns) == 0:
                raise ValueError("Feature matrix cannot be empty.")
        else:
            cols = expected_columns if expected_columns is not None else self.feature_names_
            if not cols:
                raise RuntimeError("Model has not been fitted yet.")
            if list(X.columns) != cols:
                raise ValueError(
                    f"Column mismatch: expected trained columns {cols}, "
                    f"got {list(X.columns)}"
                )

        arr = X.to_numpy()
        if not np.issubdtype(arr.dtype, np.number):
            raise ValueError("Feature matrix must contain purely numeric data.")
        if not np.all(np.isfinite(arr)):
            raise ValueError("Feature matrix contains NaN, infinite, or non-finite values.")

    def _validate_target(self, y: pd.Series | np.ndarray, expected_len: int) -> np.ndarray:
        """Validate binary target vector: length matches X, finite integers in {0, 1}."""
        y_arr = np.asarray(y)
        if y_arr.ndim != 1:
            raise ValueError(f"Target must be a 1D array, got {y_arr.ndim}D.")
        if len(y_arr) != expected_len:
            raise ValueError(
                f"Target length ({len(y_arr)}) does not match feature rows ({expected_len})."
            )
        if not np.issubdtype(y_arr.dtype, np.number):
            raise ValueError("Target must contain numeric values.")
        if not np.all(np.isfinite(y_arr)):
            raise ValueError("Target contains NaN or non-finite values.")
        unique_vals = set(np.unique(y_arr))
        if not unique_vals.issubset({0, 1}):
            raise ValueError(f"Target classes must be strictly binary {0, 1}, got {unique_vals}")
        return y_arr.astype(int)

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series | np.ndarray,
        X_val: pd.DataFrame | None = None,
        y_val: pd.Series | np.ndarray | None = None,
    ) -> AssistedUserClassifier:
        """Fit one LightGBM on X_train/y_train; if calibrated, require separate X_val/y_val."""
        # 1. Validate ALL inputs before any state changes or fitting
        if self.calibrate:
            if X_val is None or y_val is None:
                raise ValueError(
                    "Calibrated classifier requires separate X_val and y_val; "
                    "no silent uncalibrated fallback allowed."
                )
            if X_val is X_train or y_val is y_train:
                raise ValueError(
                    "X_val and y_val must be separate disjoint validation objects, "
                    "not the same train object."
                )

        self._validate_input_matrix(X_train, is_fitting=True)
        proposed_feature_names = list(X_train.columns)
        y_t = self._validate_target(y_train, len(X_train))

        if len(np.unique(y_t)) < 2:
            raise ValueError("y_train must contain both positive (1) and negative (0) classes.")

        if self.calibrate:
            assert X_val is not None
            assert y_val is not None
            self._validate_input_matrix(
                X_val, is_fitting=False, expected_columns=proposed_feature_names
            )
            y_v = self._validate_target(y_val, len(X_val))
            if len(np.unique(y_v)) < 2:
                raise ValueError(
                    "y_val must contain both positive (1) and negative (0) classes."
                )

        # 2. Fit new models in local variables
        new_lgbm = lgb.LGBMClassifier(
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            max_depth=self.max_depth,
            random_state=self.random_state,
            verbosity=-1,
        )
        new_lgbm.fit(X_train, y_t)

        if self.calibrate:
            frozen_base = FrozenEstimator(new_lgbm)
            new_calibrated = CalibratedClassifierCV(
                estimator=frozen_base,
                method=self.calibration_method,
            )
            new_calibrated.fit(X_val, y_v)
        else:
            new_calibrated = None

        # 3. Atomically publish matching base, calibration, schema, and reset explainer on success
        self.feature_names_ = proposed_feature_names
        self.lgbm_model = new_lgbm
        self.calibrated_model = new_calibrated
        self._explainer = None
        return self

    def predict(self, X: pd.DataFrame, threshold: float | None = None) -> np.ndarray:
        """Predict binary class (1=assisted, 0=independent) using configured threshold."""
        th = threshold if threshold is not None else self.classification_threshold
        proba = self.predict_proba(X)[:, 1]
        return (proba >= th).astype(int)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Return calibrated prediction probabilities. Fails closed with no silent fallback."""
        self._validate_input_matrix(X, is_fitting=False)
        if self.calibrate:
            if self.calibrated_model is None:
                raise RuntimeError(
                    "Model is configured to be calibrated, but no calibrated model is fitted. "
                    "No silent uncalibrated fallback permitted."
                )
            return self.calibrated_model.predict_proba(X)

        if self.lgbm_model is not None:
            return self.lgbm_model.predict_proba(X)
        raise RuntimeError("Model has not been fitted yet.")

    def evaluate(
        self,
        X: pd.DataFrame,
        y: pd.Series | np.ndarray,
        slices: pd.DataFrame | None = None,
        check_sanity: bool = True,
    ) -> dict[str, Any]:
        """Compute performance metrics, verify sanity constraint, and evaluate fairness."""
        self._validate_input_matrix(X, is_fitting=False)
        y_true = self._validate_target(y, len(X))
        y_pred = self.predict(X)
        y_proba = self.predict_proba(X)[:, 1]

        # PR-AUC
        precision_pts, recall_pts, _ = precision_recall_curve(y_true, y_proba)
        pr_auc = float(auc(recall_pts, precision_pts))

        # Sanity check: Ensure PR-AUC <= 0.98 on validation split
        sanity_passed = True
        if check_sanity and pr_auc > self.max_pr_auc_sanity:
            sanity_passed = False

        metrics: dict[str, Any] = {
            "model": "assisted_user_lightgbm",
            "accuracy": float(accuracy_score(y_true, y_pred)),
            "precision": float(precision_score(y_true, y_pred, zero_division=0)),
            "recall": float(recall_score(y_true, y_pred, zero_division=0)),
            "f1": float(f1_score(y_true, y_pred, zero_division=0)),
            "pr_auc": pr_auc,
            "brier_score": float(brier_score_loss(y_true, y_proba)),
            "pr_auc_sanity_passed": sanity_passed,
            "max_pr_auc_sanity_threshold": self.max_pr_auc_sanity,
            "classification_threshold": self.classification_threshold,
            "calibrated": self.calibrate,
        }

        # Demographic / fairness slice breakdown
        if slices is not None:
            slice_results: dict[str, Any] = {}
            exceeded_gaps: list[dict[str, Any]] = []

            for col in ("gender", "age_band", "region", "urban_rural"):
                if col in slices.columns:
                    slice_results[col] = {}
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
                            slice_results[col][str(cat)] = tpr
                            if sub_y_true.sum() > 0:
                                tprs.append(tpr)

                    if tprs:
                        gap = float(max(tprs) - min(tprs))
                        slice_results[col]["max_tpr_gap"] = gap
                        if gap > self.max_tpr_gap_target:
                            exceeded_gaps.append(
                                {
                                    "slice": col,
                                    "observed_gap": gap,
                                    "target": self.max_tpr_gap_target,
                                }
                            )

            metrics["slices"] = slice_results
            metrics["fairness_compliant"] = len(exceeded_gaps) == 0
            metrics["fairness_gaps_exceeded"] = exceeded_gaps

        return metrics

    def _get_explainer(self) -> Any:
        """Lazy-initialize SHAP TreeExplainer for the underlying base LightGBM estimator."""
        if self.lgbm_model is None:
            raise RuntimeError("Base model must be fitted before explaining.")
        if self._explainer is None:
            import shap

            self._explainer = shap.TreeExplainer(self.lgbm_model)
        return self._explainer

    def explain_raw(
        self,
        X_row: pd.Series | dict[str, Any] | pd.DataFrame,
    ) -> tuple[np.ndarray, float, float]:
        """Compute raw SHAP attributions, expected base value, and base raw margin prediction.

        Guarantees:
            np.sum(shap_values) + expected_value == raw_score (within float precision).
        """
        if isinstance(X_row, dict):
            df_row = pd.DataFrame([X_row])
        elif isinstance(X_row, pd.Series):
            df_row = pd.DataFrame([X_row.to_dict()])
        elif isinstance(X_row, pd.DataFrame):
            df_row = X_row
        else:
            raise ValueError(f"Unsupported row type: {type(X_row)}")

        if len(df_row) != 1:
            raise ValueError(f"explain_raw requires exactly 1 row, got {len(df_row)} rows.")

        self._validate_input_matrix(df_row, is_fitting=False)
        explainer = self._get_explainer()

        shap_values = explainer.shap_values(df_row)
        if isinstance(shap_values, list) and len(shap_values) == 2:
            vals = np.asarray(shap_values[1][0], dtype=float)
        elif isinstance(shap_values, np.ndarray):
            if shap_values.ndim == 3:
                vals = np.asarray(shap_values[0, :, 1], dtype=float)
            elif shap_values.ndim == 2:
                vals = np.asarray(shap_values[0], dtype=float)
            else:
                vals = np.asarray(shap_values, dtype=float).flatten()
        else:
            vals = np.asarray(shap_values, dtype=float).flatten()

        exp_val = explainer.expected_value
        if isinstance(exp_val, (list, np.ndarray)) and len(exp_val) == 2:
            base_val = float(exp_val[1])
        elif isinstance(exp_val, (list, np.ndarray)):
            base_val = float(np.asarray(exp_val).flatten()[0])
        else:
            base_val = float(exp_val)

        # Base LightGBM model raw log-odds margin
        raw_margin = float(self.lgbm_model.predict(df_row, raw_score=True)[0])
        return vals, base_val, raw_margin

    def explain(
        self,
        X_row: pd.Series | dict[str, Any] | pd.DataFrame,
        top_k: int = 4,
    ) -> list[dict[str, Any]]:
        """Explain individual customer prediction using SHAP TreeExplainer on base estimator.

        Attributions are explicitly raw log-odds contributions, not calibrated probabilities.
        """
        if isinstance(X_row, dict):
            df_row = pd.DataFrame([X_row])
        elif isinstance(X_row, pd.Series):
            df_row = pd.DataFrame([X_row.to_dict()])
        elif isinstance(X_row, pd.DataFrame):
            df_row = X_row
        else:
            raise ValueError(f"Unsupported row type: {type(X_row)}")

        if len(df_row) != 1:
            raise ValueError(f"explain requires exactly 1 row, got {len(df_row)} rows.")

        vals, _, _ = self.explain_raw(df_row)

        reasons = []
        for feat_name, attr in zip(df_row.columns, vals):
            val = float(df_row[feat_name].iloc[0])
            reasons.append(
                {
                    "feature": feat_name,
                    "value": val,
                    "attribution": float(attr),
                    "attribution_unit": "log_odds",
                    "abs_attribution": abs(float(attr)),
                }
            )

        reasons.sort(key=lambda r: r["abs_attribution"], reverse=True)
        top_reasons = reasons[:top_k]

        return [
            {
                "feature": r["feature"],
                "value": r["value"],
                "attribution": r["attribution"],
                "attribution_unit": r["attribution_unit"],
            }
            for r in top_reasons
        ]

    def save(self, filepath: str | Path) -> None:
        """Serialize model artifact to disk preserving calibration, base model, and schema."""
        if self.lgbm_model is None or not self.feature_names_ or (
            self.calibrate and self.calibrated_model is None
        ):
            raise ValueError(
                "Cannot save unfitted model artifact: requires fitted estimator and schema."
            )
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "lgbm_model": self.lgbm_model,
            "calibrated_model": self.calibrated_model,
            "feature_names": self.feature_names_,
            "config": self.config,
            "calibrate": self.calibrate,
            "classification_threshold": self.classification_threshold,
            "calibration_method": self.calibration_method,
            "n_estimators": self.n_estimators,
            "learning_rate": self.learning_rate,
            "max_depth": self.max_depth,
            "random_state": self.random_state,
            "max_pr_auc_sanity": self.max_pr_auc_sanity,
            "max_tpr_gap_target": self.max_tpr_gap_target,
        }
        joblib.dump(payload, path)

    @classmethod
    def load(cls, filepath: str | Path) -> AssistedUserClassifier:
        """Deserialize model artifact from disk preserving fitted calibration + base + schema."""
        payload = joblib.load(filepath)
        clf = cls(
            n_estimators=payload["n_estimators"],
            learning_rate=payload["learning_rate"],
            max_depth=payload["max_depth"],
            classification_threshold=payload["classification_threshold"],
            calibration_method=payload["calibration_method"],
            calibrate=payload["calibrate"],
            random_state=payload["random_state"],
            config=payload["config"],
        )
        clf.lgbm_model = payload["lgbm_model"]
        clf.calibrated_model = payload["calibrated_model"]
        clf.feature_names_ = payload["feature_names"]
        clf.max_pr_auc_sanity = payload["max_pr_auc_sanity"]
        clf.max_tpr_gap_target = payload["max_tpr_gap_target"]
        return clf
