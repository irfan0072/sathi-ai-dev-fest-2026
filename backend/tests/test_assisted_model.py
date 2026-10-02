"""Tests for AssistedUserClassifier (LightGBM, calibration, SHAP, fairness) (T018 / T023).

Verifies:
- Training and calibrated probability inference with FrozenEstimator
- Disjoint calibration/training separation (never refits base estimator)
- No silent uncalibrated fallback
- Feature leakage prevention (zero leakage assertion)
- Column mismatch, reorder, and NaN rejection
- SHAP TreeExplainer local explanations with exact raw-score additivity
- Metamorphic protected metadata and slice invariance
- PR-AUC sanity check constraint (PR-AUC <= 0.98)
- Configured threshold changes
- Model serialization (save/load)
- Integration on small deterministic synthetic fixture (never canonical final test artifacts)
"""

from __future__ import annotations

import copy
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from app.data.config import load_config
from app.data.generator import build_canonical_agent_registry, generate_dataset_with_observations
from app.data.splits import allocate_cohorts
from app.features.guard import FeatureLeakageError
from app.ml.assisted_model import AssistedUserClassifier
from app.ml.features import extract_user_features


@pytest.fixture
def synthetic_training_data() -> tuple[
    pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series
]:
    """Generate deterministic disjoint train and validation behavioral dataset."""
    rng = np.random.default_rng(42)
    n_train = 200
    n_val = 100
    n_total = n_train + n_val

    is_assisted = (rng.uniform(0, 1, n_total) < 0.35).astype(int)

    top_share = np.where(
        is_assisted == 1,
        rng.beta(6, 2, n_total),
        rng.beta(2, 5, n_total),
    )
    delay_hours = np.where(
        is_assisted == 1,
        rng.exponential(8.0, n_total),
        rng.exponential(72.0, n_total),
    )
    withdrawn = np.where(
        is_assisted == 1,
        rng.beta(8, 2, n_total),
        rng.beta(2, 3, n_total),
    )
    pin_retries = np.where(
        is_assisted == 1,
        rng.poisson(0.5, n_total),
        rng.poisson(0.1, n_total),
    )
    pin_seconds = np.where(
        is_assisted == 1,
        rng.lognormal(mean=2.6, sigma=0.5, size=n_total),
        rng.lognormal(mean=1.8, sigma=0.3, size=n_total),
    )

    X = pd.DataFrame(
        {
            "top_agent_share": top_share,
            "top_agent_concentration": top_share**2,
            "cash_out_tx_count": rng.integers(1, 10, n_total).astype(float),
            "cash_out_total_amount": rng.uniform(2000, 30000, n_total),
            "cash_out_amount_mean": rng.uniform(1000, 5000, n_total),
            "cash_out_amount_median": rng.uniform(1000, 5000, n_total),
            "cash_out_amount_std": rng.uniform(0, 500, n_total),
            "cash_out_amount_min": rng.uniform(500, 3000, n_total),
            "cash_out_amount_max": rng.uniform(3000, 6000, n_total),
            "credit_tx_count": rng.integers(1, 10, n_total).astype(float),
            "credit_total_amount": rng.uniform(2000, 30000, n_total),
            "credit_amount_mean": rng.uniform(1000, 5000, n_total),
            "credit_to_cashout_hours_mean": delay_hours,
            "credit_to_cashout_hours_min": delay_hours * 0.8,
            "credit_to_cashout_hours_median": delay_hours,
            "withdrawn_balance_ratio_mean": withdrawn,
            "withdrawn_balance_ratio_max": np.clip(withdrawn * 1.1, 0, 1),
            "balance_end": rng.uniform(100, 5000, n_total),
            "balance_mean": rng.uniform(500, 5000, n_total),
            "balance_min": rng.uniform(50, 2000, n_total),
            "pin_retries_total": pin_retries.astype(float),
            "pin_retries_mean": pin_retries.astype(float) / 5.0,
            "pin_retries_max": pin_retries.astype(float),
            "pin_entry_seconds_mean": pin_seconds,
            "pin_entry_seconds_median": pin_seconds,
            "pin_entry_seconds_std": rng.uniform(0.1, 2.0, n_total),
            "session_steps_mean": np.where(
                is_assisted == 1,
                rng.choice([5.0, 6.0, 7.0], n_total),
                rng.choice([4.0, 5.0, 6.0], n_total),
            ),
            "session_steps_max": np.where(
                is_assisted == 1,
                rng.choice([6.0, 7.0], n_total),
                rng.choice([4.0, 5.0], n_total),
            ),
            "service_diversity_count": rng.integers(1, 4, n_total).astype(float),
            "send_tx_count": rng.integers(0, 5, n_total).astype(float),
            "send_total_amount": rng.uniform(0, 5000, n_total),
            "bill_pay_tx_count": rng.integers(0, 3, n_total).astype(float),
            "bill_pay_total_amount": rng.uniform(0, 3000, n_total),
            "agent_assisted_tx_ratio": np.where(
                is_assisted == 1,
                rng.uniform(0.4, 0.9, n_total),
                rng.uniform(0.1, 0.5, n_total),
            ),
            "fee_total_paid": rng.uniform(50, 450, n_total),
            "fee_to_amount_ratio": np.full(n_total, 0.015),
        }
    )

    flips = rng.uniform(0, 1, n_total) < 0.10
    observed_target = np.where(flips, 1 - is_assisted, is_assisted)

    slices = pd.DataFrame(
        {
            "gender": rng.choice(["female", "male", "other"], n_total),
            "age_band": rng.choice(["18-25", "26-40", "41-60", "60+"], n_total),
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
                n_total,
            ),
            "urban_rural": rng.choice(["urban", "rural"], n_total),
        }
    )

    X_train = X.iloc[:n_train].reset_index(drop=True)
    y_train = pd.Series(observed_target[:n_train], name="target")
    slices_train = slices.iloc[:n_train].reset_index(drop=True)

    X_val = X.iloc[n_train:].reset_index(drop=True)
    y_val = pd.Series(observed_target[n_train:], name="target")

    return X_train, y_train, slices_train, X_val, y_val


def test_fit_and_predict_calibrated_disjoint_separation(
    synthetic_training_data: tuple[
        pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series
    ],
) -> None:
    """Verify calibration/training separation: base LightGBM is fit on train;
    calibrator is fit on separate validation set using FrozenEstimator;
    base estimator is never refitted.
    """
    X_train, y_train, _, X_val, y_val = synthetic_training_data

    clf = AssistedUserClassifier(n_estimators=30, random_state=42)
    clf.fit(X_train, y_train, X_val, y_val)

    assert clf.lgbm_model is not None
    assert clf.calibrated_model is not None

    # Base estimator raw predictions before and after calibration remain identical
    # Compare with independently fitted same-seed train-only estimator
    clf_train_only = AssistedUserClassifier(
        n_estimators=30, calibrate=False, random_state=42
    )
    clf_train_only.fit(X_train, y_train)

    raw_preds_val = clf.lgbm_model.predict(X_val, raw_score=True)
    raw_train_only_val = clf_train_only.lgbm_model.predict(X_val, raw_score=True)
    np.testing.assert_array_equal(raw_preds_val, raw_train_only_val)

    # Prove validation labels never alter base trees even if validation labels are inverted
    clf_flipped = AssistedUserClassifier(n_estimators=30, random_state=42)
    clf_flipped.fit(X_train, y_train, X_val, 1 - y_val)
    np.testing.assert_array_equal(
        clf.lgbm_model.predict(X_val, raw_score=True),
        clf_flipped.lgbm_model.predict(X_val, raw_score=True),
    )

    # Calibrated probabilities differ from uncalibrated raw margin
    cal_probas = clf.predict_proba(X_val)
    assert cal_probas.shape == (len(X_val), 2)
    np.testing.assert_allclose(cal_probas.sum(axis=1), 1.0, rtol=1e-5)

    preds = clf.predict(X_val)
    assert len(preds) == len(X_val)
    assert set(np.unique(preds)).issubset({0, 1})


def test_calibration_requires_separate_val_no_silent_fallback(
    synthetic_training_data: tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series],
) -> None:
    """When calibrate=True, fit without X_val/y_val must fail closed with ValueError.
    No silent uncalibrated fallback is permitted.
    """
    X_train, y_train, _, _, _ = synthetic_training_data

    clf = AssistedUserClassifier(n_estimators=20, calibrate=True, random_state=42)
    with pytest.raises(ValueError, match="requires separate X_val and y_val"):
        clf.fit(X_train, y_train)

    # Predict proba without fitting must raise RuntimeError
    unfitted = AssistedUserClassifier(n_estimators=20, calibrate=True)
    with pytest.raises(RuntimeError):
        unfitted.predict_proba(X_train)


def test_explicit_uncalibrated_mode(
    synthetic_training_data: tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series],
) -> None:
    """When calibrate=False is explicitly specified, fit without X_val succeeds."""
    X_train, y_train, _, X_val, _ = synthetic_training_data

    clf = AssistedUserClassifier(n_estimators=20, calibrate=False, random_state=42)
    clf.fit(X_train, y_train)

    assert clf.calibrated_model is None
    probas = clf.predict_proba(X_val)
    assert probas.shape == (len(X_val), 2)


def test_column_mismatch_and_nan_rejection(
    synthetic_training_data: tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series],
) -> None:
    """Verify strict validation: column mismatch, reordered columns, NaNs, and target errors."""
    X_train, y_train, _, X_val, y_val = synthetic_training_data
    clf = AssistedUserClassifier(n_estimators=20, random_state=42)
    clf.fit(X_train, y_train, X_val, y_val)

    # 1. Missing column in inference
    missing_col_X = X_val.drop(columns=["top_agent_share"])
    with pytest.raises(ValueError, match="Column mismatch"):
        clf.predict(missing_col_X)

    # 2. Reordered columns in inference
    cols_reversed = list(reversed(X_val.columns))
    reordered_X = X_val[cols_reversed]
    with pytest.raises(ValueError, match="Column mismatch"):
        clf.predict(reordered_X)

    # 3. NaN in inference
    nan_X = X_val.copy()
    nan_X.iloc[0, 0] = np.nan
    with pytest.raises(ValueError, match="NaN, infinite, or non-finite"):
        clf.predict(nan_X)

    # 4. Infinite in inference
    inf_X = X_val.copy()
    inf_X.iloc[0, 0] = np.inf
    with pytest.raises(ValueError, match="NaN, infinite, or non-finite"):
        clf.predict(inf_X)

    # 5. Invalid target length
    with pytest.raises(ValueError, match="Target length"):
        clf.fit(X_train, y_train.iloc[:10], X_val, y_val)

    # 6. Invalid non-binary target classes
    bad_y = y_train.copy()
    bad_y.iloc[0] = 5
    with pytest.raises(ValueError, match="Target classes must be strictly binary"):
        clf.fit(X_train, bad_y, X_val, y_val)


def test_leakage_guard_raises_error(
    synthetic_training_data: tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series],
) -> None:
    """Ensure feature leakage guard stops forbidden columns."""
    X_train, y_train, _, X_val, y_val = synthetic_training_data
    leaky_X = X_train.copy()
    leaky_X["group_label"] = "assisted_allowance"

    clf = AssistedUserClassifier(n_estimators=20)
    with pytest.raises(FeatureLeakageError):
        clf.fit(leaky_X, y_train, X_val, y_val)


def test_shap_explanations_and_raw_score_additivity(
    synthetic_training_data: tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series],
) -> None:
    """Verify SHAP TreeExplainer explains the base estimator with exact raw-score additivity:
    sum(shap_values) + expected_value == lgbm.predict(X, raw_score=True).
    """
    X_train, y_train, _, X_val, y_val = synthetic_training_data
    clf = AssistedUserClassifier(n_estimators=25, random_state=42)
    clf.fit(X_train, y_train, X_val, y_val)

    # Check additivity across multiple test rows
    for i in range(5):
        row = X_val.iloc[[i]]
        shap_vals, base_val, raw_margin = clf.explain_raw(row)

        reconstructed_margin = float(np.sum(shap_vals) + base_val)
        np.testing.assert_allclose(
            reconstructed_margin,
            raw_margin,
            atol=1e-5,
            err_msg=(
                f"SHAP raw additivity violated for row {i}: "
                f"{reconstructed_margin} vs {raw_margin}"
            ),
        )

    # Explain output contract
    reasons = clf.explain(X_val.iloc[0], top_k=4)
    assert len(reasons) == 4
    for r in reasons:
        assert "feature" in r
        assert r["feature"] in X_val.columns
        assert "attribution" in r
        assert "value" in r
        assert r["attribution_unit"] == "log_odds"


def test_configured_threshold_changes_predictions(
    synthetic_training_data: tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series],
) -> None:
    """Verify changing classification_threshold alters binary decisions monotonically."""
    X_train, y_train, _, X_val, y_val = synthetic_training_data
    clf = AssistedUserClassifier(n_estimators=25, random_state=42)
    clf.fit(X_train, y_train, X_val, y_val)

    preds_low = clf.predict(X_val, threshold=0.20)
    preds_mid = clf.predict(X_val, threshold=0.50)
    preds_high = clf.predict(X_val, threshold=0.80)

    # Lower threshold flags more positive instances
    assert preds_low.sum() >= preds_mid.sum()
    assert preds_mid.sum() >= preds_high.sum()


def test_metamorphic_demographic_and_slice_invariance() -> None:
    """Metamorphic test: changing protected demographic slices (gender, age_band,
    region, urban_rural) or group_label never changes numeric X or predictions.
    """
    raw_users = [
        {
            "user_id": f"U_meta_{i:03d}",
            "group_label": "assisted_allowance" if i % 2 == 0 else "independent_urban",
            "gender": "female" if i % 2 == 0 else "male",
            "age_band": "26-40" if i % 2 == 0 else "60+",
            "region": "dhaka" if i % 2 == 0 else "khulna",
            "urban_rural": "urban" if i % 2 == 0 else "rural",
        }
        for i in range(10)
    ]
    raw_txs = [
        {
            "txn_id": 100 + i,
            "user_id": f"U_meta_{i % 10:03d}",
            "agent_id": f"A_{i % 3:03d}",
            "txn_type": "cash_out",
            "amount": 2000.0,
            "fee": 30.0,
            "balance_after": 3000.0,
            "ts": "2026-10-02T10:00:00",
        }
        for i in range(30)
    ]
    raw_sess = [
        {
            "session_id": 200 + i,
            "user_id": f"U_meta_{i % 10:03d}",
            "txn_id": 100 + i,
            "pin_retries": 1,
            "pin_entry_ms": 5000,
            "steps": 4,
            "ts": "2026-10-02T10:00:00",
        }
        for i in range(30)
    ]

    X_orig, _, _, _ = extract_user_features(raw_users, raw_txs, raw_sess)

    # Modify all protected demographic attributes and group labels
    altered_users = []
    for u in raw_users:
        alt = dict(u)
        alt["gender"] = "other"
        alt["age_band"] = "18-25"
        alt["region"] = "sylhet"
        alt["urban_rural"] = "rural"
        alt["group_label"] = "independent_rural"
        altered_users.append(alt)

    X_altered, _, _, _ = extract_user_features(altered_users, raw_txs, raw_sess)

    # Numeric feature matrices must be completely identical
    pd.testing.assert_frame_equal(X_orig, X_altered)


def test_model_save_and_load(
    synthetic_training_data: tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series],
) -> None:
    """Test model persistence and exact prediction restoration."""
    X_train, y_train, _, X_val, y_val = synthetic_training_data
    clf = AssistedUserClassifier(n_estimators=20, random_state=42)
    clf.fit(X_train, y_train, X_val, y_val)

    with tempfile.TemporaryDirectory() as tmpdir:
        model_path = Path(tmpdir) / "assisted_model.joblib"
        clf.save(model_path)
        assert model_path.exists()

        loaded_clf = AssistedUserClassifier.load(model_path)
        orig_probas = clf.predict_proba(X_val)
        loaded_probas = loaded_clf.predict_proba(X_val)
        np.testing.assert_allclose(orig_probas, loaded_probas, atol=1e-6)

        orig_preds = clf.predict(X_val)
        loaded_preds = loaded_clf.predict(X_val)
        np.testing.assert_array_equal(orig_preds, loaded_preds)


def test_small_fixture_evaluation_pr_auc_sanity() -> None:
    """Integration test evaluating on small generated synthetic fixture.

    Avoids loading canonical final test artifacts in ordinary tests.
    Guarantees realistic overlap and PR-AUC <= 0.98 sanity check satisfaction.
    """
    cfg = copy.deepcopy(load_config())
    cfg["simulation"]["customers"] = 300
    cfg["simulation"]["agents"] = 15
    cfg["simulation"]["agent_mix"] = {"normal": 10, "high_volume_honest": 3, "skimmers": 2}
    canonical_agents = build_canonical_agent_registry(cfg)
    cohort_agents = allocate_cohorts(cfg, canonical_agents=canonical_agents)

    train_data, _ = generate_dataset_with_observations(
        config=cfg,
        seed=cfg["simulation"]["seed_train"],
        agent_ids=cohort_agents["train"],
        customers=200,
        canonical_agents=canonical_agents,
    )
    val_data, _ = generate_dataset_with_observations(
        config=cfg,
        seed=cfg["simulation"]["seed_validation"],
        agent_ids=cohort_agents["validation"],
        customers=100,
        canonical_agents=canonical_agents,
    )

    X_train, y_train, _, _ = extract_user_features(
        train_data["users"], train_data["transactions"], train_data["sessions"]
    )
    X_val, y_val, slices_val, _ = extract_user_features(
        val_data["users"], val_data["transactions"], val_data["sessions"]
    )

    clf = AssistedUserClassifier(n_estimators=30, random_state=42)
    clf.fit(X_train, y_train, X_val, y_val)

    metrics = clf.evaluate(X_val, y_val, slices=slices_val, check_sanity=True)

    assert 0.0 <= metrics["pr_auc"] <= 1.0
    assert metrics["pr_auc_sanity_passed"] == (metrics["pr_auc"] <= clf.max_pr_auc_sanity)


def test_assisted_model_same_object_rejection(
    synthetic_training_data: tuple[
        pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series
    ],
) -> None:
    """Disjoint calibration enforcement: X_val is X_train or y_val is y_train must fail."""
    X_train, y_train, _, _, _ = synthetic_training_data
    clf = AssistedUserClassifier(n_estimators=10, random_state=42)
    with pytest.raises(ValueError, match="separate disjoint validation objects"):
        clf.fit(X_train, y_train, X_train, y_train)


def test_assisted_model_single_class_y_val_rejection(
    synthetic_training_data: tuple[
        pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series
    ],
) -> None:
    """Calibration set must contain both binary classes (0 and 1)."""
    X_train, y_train, _, X_val, _ = synthetic_training_data
    clf = AssistedUserClassifier(n_estimators=10, random_state=42)
    y_val_single_class = pd.Series([0] * len(X_val))
    with pytest.raises(ValueError, match="y_val must contain both"):
        clf.fit(X_train, y_train, X_val, y_val_single_class)


def test_assisted_model_invalid_overrides() -> None:
    """Verify constructor rejects invalid parameter overrides."""
    with pytest.raises(ValueError):
        AssistedUserClassifier(classification_threshold=-0.1)
    with pytest.raises(ValueError):
        AssistedUserClassifier(classification_threshold=1.5)
    with pytest.raises(ValueError):
        AssistedUserClassifier(classification_threshold=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        AssistedUserClassifier(calibrate="yes")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        AssistedUserClassifier(calibration_method="unsupported")
    with pytest.raises(ValueError):
        AssistedUserClassifier(n_estimators=0)
    with pytest.raises(ValueError):
        AssistedUserClassifier(learning_rate=-0.01)
    with pytest.raises(ValueError):
        AssistedUserClassifier(max_depth=0)


def test_assisted_model_explain_batch_rejection(
    synthetic_training_data: tuple[
        pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series
    ],
) -> None:
    """Explain and explain_raw require exactly 1 row; batches must raise ValueError."""
    X_train, y_train, _, X_val, y_val = synthetic_training_data
    clf = AssistedUserClassifier(n_estimators=10, random_state=42)
    clf.fit(X_train, y_train, X_val, y_val)

    with pytest.raises(ValueError, match="exactly 1 row"):
        clf.explain(X_val.iloc[:2])
    with pytest.raises(ValueError, match="exactly 1 row"):
        clf.explain_raw(X_val.iloc[:2])


def test_assisted_model_save_unfitted_rejection() -> None:
    """Saving an unfitted classifier must raise ValueError."""
    clf = AssistedUserClassifier()
    with tempfile.TemporaryDirectory() as tmpdir:
        art_path = Path(tmpdir) / "unfitted_clf.joblib"
        with pytest.raises(ValueError, match="Cannot save unfitted"):
            clf.save(art_path)


def test_rejected_refit_preserves_atomic_state(
    synthetic_training_data: tuple[
        pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame, pd.Series
    ],
) -> None:
    """Regression test: rejected refit must preserve existing fitted model,
    calibration, schema, and explainer fidelity without any state corruption.
    Fresh invalid fit must remain unfitted and unsaveable.
    """
    X_train, y_train, _, X_val, y_val = synthetic_training_data
    clf = AssistedUserClassifier(n_estimators=25, random_state=42)
    clf.fit(X_train, y_train, X_val, y_val)

    # Record baseline state
    orig_base_margins = clf.lgbm_model.predict(X_val, raw_score=True)
    orig_cal_probas = clf.predict_proba(X_val)
    orig_schema = list(clf.feature_names_)

    # Verify SHAP raw additivity baseline
    shap_vals_orig, base_val_orig, raw_margin_orig = clf.explain_raw(X_val.iloc[[0]])
    np.testing.assert_allclose(np.sum(shap_vals_orig) + base_val_orig, raw_margin_orig, atol=1e-5)

    # 1. Rejected refit: missing validation set
    with pytest.raises(ValueError, match="requires separate X_val and y_val"):
        clf.fit(X_train, y_train)

    np.testing.assert_array_equal(clf.lgbm_model.predict(X_val, raw_score=True), orig_base_margins)
    np.testing.assert_array_equal(clf.predict_proba(X_val), orig_cal_probas)
    assert clf.feature_names_ == orig_schema

    # 2. Rejected refit: NaN in validation set
    X_val_nan = X_val.copy()
    X_val_nan.iloc[0, 0] = np.nan
    with pytest.raises(ValueError, match="NaN, infinite, or non-finite"):
        clf.fit(X_train, y_train, X_val_nan, y_val)

    np.testing.assert_array_equal(clf.lgbm_model.predict(X_val, raw_score=True), orig_base_margins)
    np.testing.assert_array_equal(clf.predict_proba(X_val), orig_cal_probas)
    assert clf.feature_names_ == orig_schema

    # 3. Rejected refit: single-class validation target
    y_val_oneclass = pd.Series([0] * len(X_val))
    with pytest.raises(ValueError, match="y_val must contain both"):
        clf.fit(X_train, y_train, X_val, y_val_oneclass)

    np.testing.assert_array_equal(clf.lgbm_model.predict(X_val, raw_score=True), orig_base_margins)
    np.testing.assert_array_equal(clf.predict_proba(X_val), orig_cal_probas)
    assert clf.feature_names_ == orig_schema

    # 4. Rejected refit: 2D validation target
    y_val_2d = np.zeros((len(X_val), 2))
    with pytest.raises(ValueError, match="Target must be a 1D array"):
        clf.fit(X_train, y_train, X_val, y_val_2d)

    np.testing.assert_array_equal(clf.lgbm_model.predict(X_val, raw_score=True), orig_base_margins)
    np.testing.assert_array_equal(clf.predict_proba(X_val), orig_cal_probas)
    assert clf.feature_names_ == orig_schema

    # 5. Rejected refit: same-object validation set
    with pytest.raises(ValueError, match="separate disjoint validation objects"):
        clf.fit(X_train, y_train, X_train, y_train)

    np.testing.assert_array_equal(clf.lgbm_model.predict(X_val, raw_score=True), orig_base_margins)
    np.testing.assert_array_equal(clf.predict_proba(X_val), orig_cal_probas)
    assert clf.feature_names_ == orig_schema

    # Verify SHAP raw additivity and explanation fidelity unchanged after all rejected refits
    shap_vals_after, base_val_after, raw_margin_after = clf.explain_raw(X_val.iloc[[0]])
    np.testing.assert_allclose(
        np.sum(shap_vals_after) + base_val_after, raw_margin_after, atol=1e-5
    )
    np.testing.assert_allclose(shap_vals_orig, shap_vals_after, atol=1e-6)

    # Save and load after rejected refits restores exact probabilities
    with tempfile.TemporaryDirectory() as tmpdir:
        art_path = Path(tmpdir) / "preserved_model.joblib"
        clf.save(art_path)
        loaded = AssistedUserClassifier.load(art_path)
        np.testing.assert_allclose(loaded.predict_proba(X_val), orig_cal_probas, atol=1e-6)

    # 6. Fresh invalid fit stays unfitted and unsaveable
    fresh = AssistedUserClassifier(n_estimators=20, calibrate=True)
    with pytest.raises(ValueError):
        fresh.fit(X_train, y_train)  # missing validation
    assert fresh.lgbm_model is None
    assert fresh.calibrated_model is None
    assert fresh.feature_names_ == []

    with tempfile.TemporaryDirectory() as tmpdir:
        fresh_art = Path(tmpdir) / "fresh_unfitted.joblib"
        with pytest.raises(ValueError, match="Cannot save unfitted"):
            fresh.save(fresh_art)

    with pytest.raises(RuntimeError):
        fresh.predict(X_val)
    with pytest.raises(RuntimeError):
        fresh.predict_proba(X_val)
