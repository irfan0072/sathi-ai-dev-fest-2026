"""Tests for AssistedUserClassifier (LightGBM, calibration, SHAP, fairness) (T018).

Verifies:
- Training and calibrated probability inference
- Feature leakage prevention (zero leakage assertion)
- SHAP TreeExplainer local explanations and top reasons
- PR-AUC sanity check constraint (PR-AUC <= 0.98)
- Fairness evaluation across slices (gender, age_band, region, urban_rural)
- Model serialization (save/load)
- End-to-end integration test on generated validation split
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from app.features.guard import FeatureLeakageError
from app.ml.assisted_model import AssistedUserClassifier
from app.ml.features import extract_user_features


@pytest.fixture
def synthetic_training_data() -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Generate synthetic behavioral dataset conforming to feature allowlist."""
    rng = np.random.default_rng(42)
    n = 200

    # 35% assisted
    is_assisted = (rng.uniform(0, 1, n) < 0.35).astype(int)

    # Simulated behavioral features with realistic overlap and noise
    top_share = np.where(
        is_assisted == 1,
        rng.beta(6, 2, n),
        rng.beta(2, 5, n),
    )
    delay_hours = np.where(
        is_assisted == 1,
        rng.exponential(8.0, n),
        rng.exponential(72.0, n),
    )
    withdrawn = np.where(
        is_assisted == 1,
        rng.beta(8, 2, n),
        rng.beta(2, 3, n),
    )
    pin_retries = np.where(
        is_assisted == 1,
        rng.poisson(0.5, n),
        rng.poisson(0.1, n),
    )
    pin_seconds = np.where(
        is_assisted == 1,
        rng.lognormal(mean=2.6, sigma=0.5, size=n),
        rng.lognormal(mean=1.8, sigma=0.3, size=n),
    )

    X = pd.DataFrame(
        {
            "top_agent_share": top_share,
            "top_agent_concentration": top_share**2,
            "cash_out_tx_count": rng.integers(1, 10, n).astype(float),
            "cash_out_total_amount": rng.uniform(2000, 30000, n),
            "cash_out_amount_mean": rng.uniform(1000, 5000, n),
            "cash_out_amount_median": rng.uniform(1000, 5000, n),
            "cash_out_amount_std": rng.uniform(0, 500, n),
            "cash_out_amount_min": rng.uniform(500, 3000, n),
            "cash_out_amount_max": rng.uniform(3000, 6000, n),
            "credit_tx_count": rng.integers(1, 10, n).astype(float),
            "credit_total_amount": rng.uniform(2000, 30000, n),
            "credit_amount_mean": rng.uniform(1000, 5000, n),
            "credit_to_cashout_hours_mean": delay_hours,
            "credit_to_cashout_hours_min": delay_hours * 0.8,
            "credit_to_cashout_hours_median": delay_hours,
            "withdrawn_balance_ratio_mean": withdrawn,
            "withdrawn_balance_ratio_max": np.clip(withdrawn * 1.1, 0, 1),
            "balance_end": rng.uniform(100, 5000, n),
            "balance_mean": rng.uniform(500, 5000, n),
            "balance_min": rng.uniform(50, 2000, n),
            "pin_retries_total": pin_retries.astype(float),
            "pin_retries_mean": pin_retries.astype(float) / 5.0,
            "pin_retries_max": pin_retries.astype(float),
            "pin_entry_seconds_mean": pin_seconds,
            "pin_entry_seconds_median": pin_seconds,
            "pin_entry_seconds_std": rng.uniform(0.1, 2.0, n),
            "session_steps_mean": np.where(
                is_assisted == 1,
                rng.choice([5.0, 6.0, 7.0], n),
                rng.choice([4.0, 5.0, 6.0], n),
            ),
            "session_steps_max": np.where(
                is_assisted == 1,
                rng.choice([6.0, 7.0], n),
                rng.choice([4.0, 5.0], n),
            ),
            "service_diversity_count": rng.integers(1, 4, n).astype(float),
            "send_tx_count": rng.integers(0, 5, n).astype(float),
            "send_total_amount": rng.uniform(0, 5000, n),
            "bill_pay_tx_count": rng.integers(0, 3, n).astype(float),
            "bill_pay_total_amount": rng.uniform(0, 3000, n),
            "agent_assisted_tx_ratio": np.where(
                is_assisted == 1,
                rng.uniform(0.4, 0.9, n),
                rng.uniform(0.1, 0.5, n),
            ),
            "fee_total_paid": rng.uniform(50, 450, n),
            "fee_to_amount_ratio": np.full(n, 0.015),
        }
    )

    # 10% label noise conforming to simulation config
    flips = rng.uniform(0, 1, n) < 0.10
    observed_target = np.where(flips, 1 - is_assisted, is_assisted)

    slices = pd.DataFrame(
        {
            "gender": rng.choice(["female", "male", "other"], n),
            "age_band": rng.choice(["18-25", "26-40", "41-60", "60+"], n),
            "region": rng.choice(
                [
                    "dhaka",
                    "chittagong",
                    "rajshahi",
                    "khulna",
                    "barishal",
                    "sylhet",
                    "rangpur",
                    "mymensingh",
                ],
                n,
            ),
            "urban_rural": rng.choice(["urban", "rural"], n),
        }
    )

    return X, pd.Series(observed_target, name="target"), slices


def test_fit_and_predict_calibrated(
    synthetic_training_data: tuple[pd.DataFrame, pd.Series, pd.DataFrame]
) -> None:
    """Test model training and calibrated probability generation."""
    X, y, slices = synthetic_training_data
    n_train = 140
    X_train, y_train = X.iloc[:n_train], y.iloc[:n_train]
    X_val, y_val = X.iloc[n_train:], y.iloc[n_train:]

    clf = AssistedUserClassifier(n_estimators=30, random_state=42)
    clf.fit(X_train, y_train, X_val, y_val)

    # Predictions
    preds = clf.predict(X_val)
    probas = clf.predict_proba(X_val)

    assert len(preds) == len(X_val)
    assert probas.shape == (len(X_val), 2)
    # Probabilities must sum to 1.0
    np.testing.assert_allclose(probas.sum(axis=1), 1.0, rtol=1e-5)
    # Predictions in {0, 1}
    assert set(np.unique(preds)).issubset({0, 1})


def test_leakage_guard_raises_error(
    synthetic_training_data: tuple[pd.DataFrame, pd.Series, pd.DataFrame]
) -> None:
    """Ensure feature leakage guard stops forbidden columns."""
    X, y, _ = synthetic_training_data
    leaky_X = X.copy()
    leaky_X["group_label"] = "assisted_allowance"

    clf = AssistedUserClassifier()
    with pytest.raises(FeatureLeakageError):
        clf.fit(leaky_X, y)


def test_shap_explanations(
    synthetic_training_data: tuple[pd.DataFrame, pd.Series, pd.DataFrame]
) -> None:
    """Test SHAP TreeExplainer feature attributions for individual users."""
    X, y, _ = synthetic_training_data
    clf = AssistedUserClassifier(n_estimators=20, random_state=42)
    clf.fit(X, y)

    row = X.iloc[0]
    reasons = clf.explain(row, top_k=3)

    assert len(reasons) == 3
    for r in reasons:
        assert "feature" in r
        assert r["feature"] in X.columns
        assert "attribution" in r
        assert "value" in r


def test_pr_auc_sanity_and_fairness(
    synthetic_training_data: tuple[pd.DataFrame, pd.Series, pd.DataFrame]
) -> None:
    """Test PR-AUC evaluation, sanity check constraint, and fairness slice reporting."""
    X, y, slices = synthetic_training_data
    n_train = 120
    X_train, y_train = X.iloc[:n_train], y.iloc[:n_train]
    X_test, y_test, slices_test = (
        X.iloc[n_train:],
        y.iloc[n_train:],
        slices.iloc[n_train:],
    )

    clf = AssistedUserClassifier(n_estimators=30, random_state=42)
    clf.fit(X_train, y_train)

    metrics = clf.evaluate(X_test, y_test, slices=slices_test, check_sanity=True)

    assert "pr_auc" in metrics
    assert "accuracy" in metrics
    assert "brier_score" in metrics
    # Sanity constraint: PR-AUC <= 0.98 must pass on realistic noisy simulation
    assert metrics["pr_auc_sanity_passed"] is True
    assert metrics["pr_auc"] <= 0.98
    assert "slices" in metrics
    assert "gender" in metrics["slices"]
    assert "max_tpr_gap" in metrics["slices"]["gender"]


def test_model_save_and_load(
    synthetic_training_data: tuple[pd.DataFrame, pd.Series, pd.DataFrame]
) -> None:
    """Test model persistence and exact prediction restoration."""
    X, y, _ = synthetic_training_data
    clf = AssistedUserClassifier(n_estimators=20, random_state=42)
    clf.fit(X, y)

    with tempfile.TemporaryDirectory() as tmpdir:
        model_path = Path(tmpdir) / "assisted_model.joblib"
        clf.save(model_path)
        assert model_path.exists()

        loaded_clf = AssistedUserClassifier.load(model_path)
        orig_probas = clf.predict_proba(X)
        loaded_probas = loaded_clf.predict_proba(X)
        np.testing.assert_allclose(orig_probas, loaded_probas, atol=1e-6)


def test_validation_split_evaluation_pr_auc_sanity() -> None:
    """End-to-end integration test extracting features from train & validation splits.

    Guarantees:
    - Feature extraction from split succeeds with 0 leakage.
    - Model achieves high performance while strictly satisfying PR-AUC <= 0.98 sanity constraint.
    """
    train_path = Path("data/generated/splits/train.json")
    val_path = Path("data/generated/splits/validation.json")
    if not train_path.exists() or not val_path.exists():
        pytest.skip("train.json or validation.json split not found locally")

    with open(train_path, "r", encoding="utf-8") as f:
        train_data = json.load(f)
    with open(val_path, "r", encoding="utf-8") as f:
        val_data = json.load(f)

    # Use representative subsets for fast test execution
    train_users = train_data["users"][:1000]
    train_uids = {u["user_id"] for u in train_users}
    train_tx = [t for t in train_data["transactions"] if t["user_id"] in train_uids]
    train_sess = [s for s in train_data["sessions"] if s["user_id"] in train_uids]

    val_users = val_data["users"][:500]
    val_uids = {u["user_id"] for u in val_users}
    val_tx = [t for t in val_data["transactions"] if t["user_id"] in val_uids]
    val_sess = [s for s in val_data["sessions"] if s["user_id"] in val_uids]

    X_train, y_train, _, _ = extract_user_features(train_users, train_tx, train_sess)
    X_val, y_val, slices_val, _ = extract_user_features(val_users, val_tx, val_sess)

    clf = AssistedUserClassifier(n_estimators=30, random_state=42)
    clf.fit(X_train, y_train)

    metrics = clf.evaluate(X_val, y_val, slices=slices_val, check_sanity=True)

    assert metrics["pr_auc"] >= 0.50
    # Sanity constraint: PR-AUC must be <= 0.98 on out-of-fold validation data
    assert metrics["pr_auc"] <= 0.98
    assert metrics["pr_auc_sanity_passed"] is True
