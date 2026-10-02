"""Assisted-user classifier for Sathi using LightGBM, calibration, and SHAP.

Conforms strictly to docs/evaluation-plan.md and tasks/T018:
- LightGBM gradient boosted trees on approved numeric behavioral features.
- Zero feature leakage: rigorously enforces feature guard allowlist.
- Probability calibration (Sigmoid / Platt scaling).
- SHAP TreeExplainer for feature importance and human-interpretable reasons.
- PR-AUC sanity check constraint (PR-AUC <= 0.98 on validation split).
- Fairness evaluation across demographic slices (gender, age_band, region, urban_rural).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml
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

from app.features.guard import assert_feature_columns


def load_model_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load model and fairness configs from data/config.yaml."""
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


class AssistedUserClassifier:
    """Production assisted-user classifier with calibration and SHAP explanations."""

    def __init__(
        self,
        n_estimators: int = 100,
        learning_rate: float = 0.05,
        max_depth: int = 5,
        random_state: int = 42,
        config_path: str | Path | None = None,
    ) -> None:
        self.config = load_model_config(config_path)
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.random_state = random_state

        sanity_cfg = self.config.get("models", {}).get("sanity", {})
        self.max_pr_auc_sanity: float = float(sanity_cfg.get("max_pr_auc", 0.98))

        fairness_cfg = self.config.get("fairness", {})
        self.max_tpr_gap_target: float = float(fairness_cfg.get("max_tpr_gap", 0.10))

        self.lgbm_model: lgb.LGBMClassifier | None = None
        self.calibrated_model: CalibratedClassifierCV | None = None
        self.feature_names_: list[str] = []
        self._explainer: Any = None

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series | np.ndarray,
        X_val: pd.DataFrame | None = None,
        y_val: pd.Series | np.ndarray | None = None,
    ) -> AssistedUserClassifier:
        """Fit LightGBM model and calibrate probabilities."""
        assert_feature_columns(X_train)
        self.feature_names_ = list(X_train.columns)

        y_t = np.asarray(y_train).astype(int)

        self.lgbm_model = lgb.LGBMClassifier(
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            max_depth=self.max_depth,
            random_state=self.random_state,
            verbosity=-1,
        )

        self.lgbm_model.fit(X_train, y_t)

        # Calibrate probabilities using cross-validation
        cv_folds = min(5, max(2, int(len(X_train) / 20)))
        self.calibrated_model = CalibratedClassifierCV(
            estimator=self.lgbm_model,
            method="sigmoid",
            cv=cv_folds,
        )
        self.calibrated_model.fit(X_train, y_t)

        return self

    def predict(self, X: pd.DataFrame, threshold: float = 0.5) -> np.ndarray:
        """Predict binary class (1=assisted, 0=independent)."""
        proba = self.predict_proba(X)[:, 1]
        return (proba >= threshold).astype(int)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Return calibrated prediction probabilities."""
        assert_feature_columns(X)
        if self.calibrated_model is not None:
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
        assert_feature_columns(X)
        y_true = np.asarray(y).astype(int)
        y_pred = self.predict(X)
        y_proba = self.predict_proba(X)[:, 1]

        # PR-AUC
        precision_pts, recall_pts, _ = precision_recall_curve(y_true, y_proba)
        pr_auc = float(auc(recall_pts, precision_pts))

        # Sanity check: Ensure PR-AUC <= 0.98 on validation split (realistic overlap constraint)
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

    def explain(
        self,
        X_row: pd.Series | dict[str, Any] | pd.DataFrame,
        top_k: int = 4,
    ) -> list[dict[str, Any]]:
        """Explain individual customer prediction using SHAP TreeExplainer.

        Returns top reasons contributing to the prediction.
        """
        if self.lgbm_model is None:
            raise RuntimeError("Model must be fitted before explaining.")

        if isinstance(X_row, dict):
            df_row = pd.DataFrame([X_row])
        elif isinstance(X_row, pd.Series):
            df_row = pd.DataFrame([X_row.to_dict()])
        elif isinstance(X_row, pd.DataFrame):
            df_row = X_row
        else:
            raise ValueError(f"Unsupported row type: {type(X_row)}")

        assert_feature_columns(df_row)

        # Lazy initialize SHAP TreeExplainer
        if self._explainer is None:
            import shap

            self._explainer = shap.TreeExplainer(self.lgbm_model)

        shap_values = self._explainer.shap_values(df_row)
        # For binary classification, shap_values is array or list of 2 arrays
        if isinstance(shap_values, list) and len(shap_values) == 2:
            vals = shap_values[1][0]
        elif isinstance(shap_values, np.ndarray) and shap_values.ndim == 2:
            vals = shap_values[0]
        else:
            vals = np.asarray(shap_values).flatten()

        reasons = []
        for feat_name, attr in zip(df_row.columns, vals):
            val = float(df_row[feat_name].iloc[0])
            reasons.append(
                {
                    "feature": feat_name,
                    "value": val,
                    "attribution": float(attr),
                    "abs_attribution": abs(float(attr)),
                }
            )

        # Sort by absolute attribution descending
        reasons.sort(key=lambda r: r["abs_attribution"], reverse=True)
        top_reasons = reasons[:top_k]

        return [
            {
                "feature": r["feature"],
                "value": r["value"],
                "attribution": r["attribution"],
            }
            for r in top_reasons
        ]

    def save(self, filepath: str | Path) -> None:
        """Serialize model artifact to disk."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "lgbm_model": self.lgbm_model,
            "calibrated_model": self.calibrated_model,
            "feature_names": self.feature_names_,
            "max_pr_auc_sanity": self.max_pr_auc_sanity,
            "max_tpr_gap_target": self.max_tpr_gap_target,
        }
        joblib.dump(payload, path)

    @classmethod
    def load(cls, filepath: str | Path) -> AssistedUserClassifier:
        """Deserialize model artifact from disk."""
        payload = joblib.load(filepath)
        clf = cls()
        clf.lgbm_model = payload["lgbm_model"]
        clf.calibrated_model = payload["calibrated_model"]
        clf.feature_names_ = payload["feature_names"]
        clf.max_pr_auc_sanity = payload.get("max_pr_auc_sanity", 0.98)
        clf.max_tpr_gap_target = payload.get("max_tpr_gap_target", 0.10)
        return clf
