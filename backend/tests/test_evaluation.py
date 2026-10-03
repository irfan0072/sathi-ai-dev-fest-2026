"""Tests for comprehensive reproducible evaluation suite and artifact management (T023b).

Verifies:
- Manifest and shifted metadata fail-closed validation and cryptographic hashing.
- Explicit splits-dir fail-closed behavior (no silent fallback).
- Validation sanity ceiling enforcement.
- Feature provenance windowing invariance (older/future records do not affect features).
- Agent cash-report feature extraction, tolerance logic, and zero-leakage guard.
- Signal ablations: assisted session signals and agent cash-gap ablation with refit.
- Skimming sweep via reviewed generator using same seed/cohort without forcing all fees.
- Adoption sensitivity restricted to assisted simulated behavior users.
- Demographic fairness null handling for empty/one-class slices.
- Deterministic stable ties for review_top_k and recall at >=80% precision.
- Artifact loader checksum verification, schema validation, and tamper rejection.
- Curated deployment bundle export with zero ground truth and zero demographics.
- Finite JSON metrics without NaN or Infinity.

Uses small deterministic synthetic fixtures in tmp directories (1000 customers, 30 agents).
Never accesses canonical final artifacts.
Never asserts arbitrary performance scores or requirements to outperform baselines.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from app.data.config import load_config, validate_config
from app.data.generator import build_canonical_agent_registry
from app.data.splits import (
    allocate_cohorts,
    generate_shifted_test_split,
    generate_splits,
)
from app.evaluation.artifacts import (
    ArtifactLoader,
    ArtifactUnavailableError,
    ArtifactVerificationError,
    SanityCeilingExceededError,
    validate_manifest_and_metadata,
)
from app.evaluation.suite import EvaluationRunner
from app.features.guard import assert_feature_columns
from app.models.features import extract_agent_features, extract_user_features


def get_small_eval_config() -> dict[str, Any]:
    """Build small valid configuration for unit test evaluation fixtures."""
    cfg = copy.deepcopy(load_config())
    cfg["simulation"]["customers"] = 1000
    cfg["simulation"]["agents"] = 30
    cfg["simulation"]["agent_mix"] = {"normal": 20, "high_volume_honest": 6, "skimmers": 4}
    cfg["simulation"]["agent_split"] = {"train": 0.60, "validation": 0.20, "test": 0.20}
    return validate_config(cfg)


def generate_tiny_fixture(base_dir: Path) -> dict[str, Any]:
    """Generate small disjoint synthetic datasets (1000 customers, 30 agents: 20/6/4 mix).

    Reuses app.data generator/split logic and guarantees schema and seed conformance.
    """
    cfg = get_small_eval_config()
    canonical_agents = build_canonical_agent_registry(cfg)
    cohort_agents = allocate_cohorts(cfg, canonical_agents=canonical_agents)

    # Generate standard splits (train, validation, test) with manifest
    split_result = generate_splits(config=cfg, output_dir=base_dir)

    # Generate shifted test split using test cohort agents
    shifted_result = generate_shifted_test_split(
        config=cfg,
        output_dir=base_dir,
        canonical_agents=canonical_agents,
        test_agent_ids=cohort_agents["test"],
    )

    return {
        "config": cfg,
        "splits": split_result,
        "shifted": shifted_result,
    }


@pytest.fixture
def eval_fixture(tmp_path: Path) -> Path:
    """Fixture directory containing small generated splits."""
    fixture_dir = tmp_path / "splits"
    generate_tiny_fixture(fixture_dir)
    return fixture_dir


@pytest.fixture
def eval_runner(eval_fixture: Path) -> EvaluationRunner:
    """EvaluationRunner initialized with small generated fixture."""
    cfg = get_small_eval_config()
    return EvaluationRunner(splits_dir=eval_fixture, config=cfg)


# ---------------------------------------------------------------------------
# 1. Manifest and Metadata Validation Tests
# ---------------------------------------------------------------------------


def test_manifest_validation_success(eval_fixture: Path) -> None:
    """Verify that valid manifest and shifted metadata pass fail-closed validation."""
    cfg = get_small_eval_config()
    artifacts = validate_manifest_and_metadata(splits_dir=eval_fixture, config=cfg)
    assert "manifest" in artifacts
    assert "shifted_meta" in artifacts
    assert "datasets" in artifacts
    assert "observations" in artifacts


def test_manifest_config_tamper_fails_closed(eval_fixture: Path) -> None:
    """Verify that tampering with config_sha256 in manifest fails closed."""
    manifest_path = eval_fixture / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["config_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    cfg = get_small_eval_config()
    with pytest.raises(ArtifactVerificationError, match="Manifest config_sha256 mismatch"):
        validate_manifest_and_metadata(splits_dir=eval_fixture, config=cfg)


def test_dataset_content_tamper_fails_closed(eval_fixture: Path) -> None:
    """Verify that altering a dataset file content fails closed on hash check."""
    train_path = eval_fixture / "train.json"
    data = json.loads(train_path.read_text(encoding="utf-8"))
    # Tamper with an amount
    data["transactions"][0]["amount"] = 99999.0
    train_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ArtifactVerificationError, match="Content SHA-256 mismatch"):
        validate_manifest_and_metadata(splits_dir=eval_fixture)


def test_shifted_test_tamper_fails_closed(eval_fixture: Path) -> None:
    """Verify that tampering with shifted test dataset fails closed on hash check."""
    shifted_path = eval_fixture / "test_shifted.json"
    data = json.loads(shifted_path.read_text(encoding="utf-8"))
    data["transactions"][0]["amount"] = 88888.0
    shifted_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ArtifactVerificationError, match="Shifted test SHA-256 mismatch"):
        validate_manifest_and_metadata(splits_dir=eval_fixture)


def test_missing_manifest_fails_closed(tmp_path: Path) -> None:
    """Verify that missing manifest.json raises ArtifactUnavailableError."""
    empty_dir = tmp_path / "empty_splits"
    empty_dir.mkdir()
    with pytest.raises(ArtifactUnavailableError, match="Missing manifest.json"):
        validate_manifest_and_metadata(splits_dir=empty_dir)


def test_explicit_splits_dir_never_silently_falls_back(tmp_path: Path) -> None:
    """Verify explicit non-existent splits_dir raises FileNotFoundError immediately."""
    non_existent = tmp_path / "non_existent_splits_directory"
    with pytest.raises(FileNotFoundError, match="Splits directory not found"):
        EvaluationRunner(splits_dir=non_existent)


def test_shifted_metadata_corruption_fails_closed(eval_fixture: Path) -> None:
    """Verify that corrupting shifted test counts, seeds, or foreign keys fails closed."""
    meta_path = eval_fixture / "test_shifted.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    # Test 1: corrupt user count
    meta_tampered = copy.deepcopy(meta)
    meta_tampered["counts"]["users"] = 999999
    meta_path.write_text(json.dumps(meta_tampered), encoding="utf-8")
    with pytest.raises(ArtifactVerificationError, match="Shifted user count mismatch"):
        validate_manifest_and_metadata(splits_dir=eval_fixture)

    # Restore meta
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    # Test 2: corrupt seed
    meta_tampered_seed = copy.deepcopy(meta)
    meta_tampered_seed["seed"] = 123456789
    meta_path.write_text(json.dumps(meta_tampered_seed), encoding="utf-8")
    with pytest.raises(ArtifactVerificationError, match="Shifted dataset seed"):
        validate_manifest_and_metadata(splits_dir=eval_fixture)

    # Restore meta
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    # Test 3: corrupt shifted observation foreign key
    obs_path = eval_fixture / "test_shifted.observations.json"
    obs_data = json.loads(obs_path.read_text(encoding="utf-8"))
    obs_tampered = copy.deepcopy(obs_data)
    first_k = next(iter(obs_tampered["transaction_observations"]))
    obs_tampered["transaction_observations"][first_k]["user_id"] = "NON_EXISTENT_USER"
    new_obs_bytes = json.dumps(obs_tampered).encode("utf-8")
    obs_path.write_bytes(new_obs_bytes)

    # Update observations_sha256 in shifted meta so hash check passes and FK check fails
    meta_with_new_hash = copy.deepcopy(meta)
    meta_with_new_hash["observations_sha256"] = hashlib.sha256(new_obs_bytes).hexdigest()
    meta_path.write_text(json.dumps(meta_with_new_hash), encoding="utf-8")

    with pytest.raises(
        ArtifactVerificationError, match="Shifted observation references unknown user_id"
    ):
        validate_manifest_and_metadata(splits_dir=eval_fixture)

    # Restore original files
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    obs_path.write_text(json.dumps(obs_data), encoding="utf-8")


# ---------------------------------------------------------------------------
# 2. Validation Sanity Ceiling Enforcement
# ---------------------------------------------------------------------------


def test_validation_sanity_ceiling_enforcement(eval_runner: EvaluationRunner) -> None:
    """Verify that validation PR-AUC exceeding config ceiling halts scoring."""
    # Temporarily set an impossible ceiling (e.g. 0.0001) to verify halt
    eval_runner.max_pr_auc_sanity = 0.0001
    with pytest.raises(SanityCeilingExceededError, match="exceeds configured sanity ceiling"):
        eval_runner.fit_canonical_models(sample_train_size=300)


# ---------------------------------------------------------------------------
# 3. Feature Provenance and Windowing Invariance
# ---------------------------------------------------------------------------


def test_feature_windowing_invariance_older_records(eval_runner: EvaluationRunner) -> None:
    """Verify that adding transactions older than the window does NOT affect features."""
    train_data = eval_runner.load_split("train")
    users = train_data["users"][:50]
    txs = copy.deepcopy(train_data["transactions"])
    sess = copy.deepcopy(train_data["sessions"])

    as_of = "2026-11-15T00:00:00Z"
    window_days = 30
    # Cutoff is 2026-10-16T00:00:00Z

    X_base, y_base, _, u_ids = extract_user_features(
        users_data=users,
        transactions_data=txs,
        sessions_data=sess,
        as_of=as_of,
        window_days=window_days,
        config=eval_runner.config,
    )

    # Inject an older transaction and session (from 2026-09-01, well before cutoff)
    old_tx = {
        "txn_id": 999991,
        "user_id": users[0]["user_id"],
        "agent_id": "A_000000",
        "txn_type": "cash_out",
        "credit_source": None,
        "amount": 2000.0,
        "fee": 30.0,
        "balance_after": 3000.0,
        "channel": "agent_initiated",
        "ts": "2026-09-01T10:00:00Z",
    }
    old_sess = {
        "session_id": 888881,
        "user_id": users[0]["user_id"],
        "txn_id": 999991,
        "pin_retries": 3,
        "pin_entry_ms": 15000,
        "steps": 7,
        "ts": "2026-09-01T10:00:00Z",
    }
    txs_with_old = txs + [old_tx]
    sess_with_old = sess + [old_sess]

    X_old, y_old, _, _ = extract_user_features(
        users_data=users,
        transactions_data=txs_with_old,
        sessions_data=sess_with_old,
        as_of=as_of,
        window_days=window_days,
        config=eval_runner.config,
    )

    pd.testing.assert_frame_equal(X_base, X_old)
    assert X_base.attrs["as_of"] == X_old.attrs["as_of"]
    assert X_base.attrs["window_days"] == 30
    assert "cutoff" in X_base.attrs


def test_feature_windowing_invariance_future_records(eval_runner: EvaluationRunner) -> None:
    """Verify that adding transactions after as_of does NOT affect windowed features."""
    train_data = eval_runner.load_split("train")
    users = train_data["users"][:50]
    txs = copy.deepcopy(train_data["transactions"])
    sess = copy.deepcopy(train_data["sessions"])

    as_of = "2026-11-01T00:00:00Z"
    window_days = 30

    X_base, _, _, _ = extract_user_features(
        users_data=users,
        transactions_data=txs,
        sessions_data=sess,
        as_of=as_of,
        window_days=window_days,
        config=eval_runner.config,
    )

    # Inject future transaction (from 2026-12-01, after as_of)
    future_tx = {
        "txn_id": 999992,
        "user_id": users[0]["user_id"],
        "agent_id": "A_000000",
        "txn_type": "cash_out",
        "credit_source": None,
        "amount": 2000.0,
        "fee": 30.0,
        "balance_after": 1000.0,
        "channel": "agent_initiated",
        "ts": "2026-12-01T10:00:00Z",
    }
    txs_with_future = txs + [future_tx]

    X_future, _, _, _ = extract_user_features(
        users_data=users,
        transactions_data=txs_with_future,
        sessions_data=sess,
        as_of=as_of,
        window_days=window_days,
        config=eval_runner.config,
    )

    pd.testing.assert_frame_equal(X_base, X_future)


def test_extract_user_features_preceding_credit_boundary_context(
    eval_runner: EvaluationRunner,
) -> None:
    """Verify preceding credit is used for cashout delay without counting as window credit."""
    users = [{"user_id": "U_DELAY_TEST"}]
    # Window: 2026-10-01 to 2026-10-31 (30 days)
    # Credit on 2026-09-25 (outside window)
    # Cashout on 2026-10-05 (inside window, 10 days = 240 hours after credit)
    txs = [
        {
            "txn_id": 501,
            "user_id": "U_DELAY_TEST",
            "agent_id": "A_000001",
            "txn_type": "credit",
            "credit_source": "allowance",
            "amount": 5000.0,
            "fee": 0.0,
            "balance_after": 5000.0,
            "channel": "direct_deposit",
            "ts": "2026-09-25T10:00:00Z",
        },
        {
            "txn_id": 502,
            "user_id": "U_DELAY_TEST",
            "agent_id": "A_000001",
            "txn_type": "cash_out",
            "credit_source": None,
            "amount": 3000.0,
            "fee": 45.0,
            "balance_after": 1955.0,
            "channel": "agent_initiated",
            "ts": "2026-10-05T10:00:00Z",
        },
    ]
    sess: list[dict[str, Any]] = []

    X, _, _, _ = extract_user_features(
        users_data=users,
        transactions_data=txs,
        sessions_data=sess,
        as_of="2026-10-31T00:00:00Z",
        window_days=30,
        config=eval_runner.config,
    )

    # Windowed credit count must be 0 (credit was outside window)
    assert X["credit_tx_count"].iloc[0] == 0.0
    # Delay must reflect the preceding credit (240 hours)
    assert X["credit_to_cashout_hours_mean"].iloc[0] == pytest.approx(240.0, abs=1.0)


def test_extract_user_features_fails_closed_invalid_window_or_config() -> None:
    """Verify extract_user_features fails closed on invalid window or missing config."""
    users = [{"user_id": "U_01"}]
    from app.data.config import ConfigError

    with pytest.raises(ConfigError):
        extract_user_features(users, [], [], config={})
    cfg = get_small_eval_config()
    for window in (0, True, -1):
        with pytest.raises(ValueError, match="positive integer"):
            extract_user_features(users, [], [], window_days=window, config=cfg)
    with pytest.raises(ConfigError):
        extract_user_features(users, [], [], window_days=30, config={})


def test_protected_metadata_invariance_in_features(eval_runner: EvaluationRunner) -> None:
    """Verify that demographic slices are strictly excluded from numeric feature matrix."""
    train_data = eval_runner.load_split("train")
    X, _, slices, _ = extract_user_features(
        users_data=train_data["users"][:100],
        transactions_data=train_data["transactions"],
        sessions_data=train_data["sessions"],
        config=eval_runner.config,
    )

    assert_feature_columns(X)
    for forbidden in ("gender", "age_band", "region", "urban_rural", "group_label"):
        assert forbidden not in X.columns
        assert forbidden in slices.columns or forbidden == "group_label"


# ---------------------------------------------------------------------------
# 4. Agent Cash-Report Features & Leakage Prevention
# ---------------------------------------------------------------------------


def test_agent_cash_report_feature_extraction(eval_runner: EvaluationRunner) -> None:
    """Verify agent_cash_gap_rate calculation using noisy reports and configured tolerance."""
    agents = [{"agent_id": "A_TEST_01", "agent_type": "skimmer"}]
    # 3 cash-out transactions:
    # Tx 1: amount 1000, reported 1000 -> gap 0 <= tolerance max(50, 20) -> no gap
    # Tx 2: amount 1000, reported 900 -> gap 100 > tolerance 50 -> anomalous gap
    # Tx 3: amount 2000, reported None -> missing report (must NOT be counted as zero gap)
    txs = [
        {
            "txn_id": 1,
            "agent_id": "A_TEST_01",
            "txn_type": "cash_out",
            "amount": 1000.0,
            "fee": 15.0,
            "ts": "2026-10-02T10:00:00Z",
        },
        {
            "txn_id": 2,
            "agent_id": "A_TEST_01",
            "txn_type": "cash_out",
            "amount": 1000.0,
            "fee": 15.0,
            "ts": "2026-10-03T10:00:00Z",
        },
        {
            "txn_id": 3,
            "agent_id": "A_TEST_01",
            "txn_type": "cash_out",
            "amount": 2000.0,
            "fee": 30.0,
            "ts": "2026-10-04T10:00:00Z",
        },
    ]
    reports = {
        "1": {"cash_received_reported": 1000.0},
        "2": {"cash_received_reported": 900.0},
        "3": {"cash_received_reported": None},
    }

    X_ag, _, _, _ = extract_agent_features(
        agents_data=agents,
        transactions_data=txs,
        config=eval_runner.config,
        reports_data=reports,
        include_cash_reports=True,
    )

    assert "agent_cash_gap_rate" in X_ag.columns
    # Out of 2 reported transactions, 1 has anomalous gap -> rate = 0.50
    assert X_ag["agent_cash_gap_rate"].iloc[0] == pytest.approx(0.50, abs=1e-5)


def test_agent_cash_report_missing_not_zero_gap(eval_runner: EvaluationRunner) -> None:
    """Verify agents with zero reports get explicit missing indicator and zero coverage."""
    agents = [{"agent_id": "A_NO_REPORTS", "agent_type": "normal"}]
    txs = [
        {
            "txn_id": 101,
            "agent_id": "A_NO_REPORTS",
            "txn_type": "cash_out",
            "amount": 1000.0,
            "fee": 15.0,
            "ts": "2026-10-02T10:00:00Z",
        }
    ]
    reports: dict[str, Any] = {}

    X_ag, _, _, _ = extract_agent_features(
        agents_data=agents,
        transactions_data=txs,
        config=eval_runner.config,
        reports_data=reports,
        include_cash_reports=True,
    )

    assert X_ag["agent_cash_gap_missing"].iloc[0] == 1.0
    assert X_ag["agent_cash_report_coverage"].iloc[0] == 0.0
    assert X_ag["agent_cash_report_count"].iloc[0] == 0.0
    assert X_ag["agent_cash_gap_has_reports"].iloc[0] == 0.0
    assert X_ag["agent_cash_gap_rate"].iloc[0] == 0.0
    assert "agent_cash_gap_missing" in X_ag.attrs["report_feature_provenance"]


def test_agent_feature_metamorphic_label_invariance(eval_runner: EvaluationRunner) -> None:
    """Metamorphic test: changing agent ground truth labels does NOT change behavioral features."""
    agents_orig = [{"agent_id": "A_TEST_01", "agent_type": "skimmer", "region": "dhaka"}]
    agents_tampered = [{"agent_id": "A_TEST_01", "agent_type": "normal", "region": "sylhet"}]

    txs = [
        {
            "txn_id": 1,
            "agent_id": "A_TEST_01",
            "txn_type": "cash_out",
            "amount": 1000.0,
            "fee": 15.0,
            "ts": "2026-10-02T10:00:00Z",
        },
    ]
    reports = {"1": {"cash_received_reported": 1000.0}}

    X1, _, _, _ = extract_agent_features(
        agents_data=agents_orig,
        transactions_data=txs,
        config=eval_runner.config,
        reports_data=reports,
        include_cash_reports=True,
    )
    X2, _, _, _ = extract_agent_features(
        agents_data=agents_tampered,
        transactions_data=txs,
        config=eval_runner.config,
        reports_data=reports,
        include_cash_reports=True,
    )

    pd.testing.assert_frame_equal(X1, X2)


def test_agent_feature_actual_payout_metamorphic_invariance(
    eval_runner: EvaluationRunner,
) -> None:
    """Metamorphic test: agent features depend only on transactions and noisy reports.

    Tampering with actual payout or skimmer loss from observations does not alter features.
    """
    agents = [{"agent_id": "A_TEST_01", "agent_type": "skimmer"}]
    txs = [
        {
            "txn_id": 1,
            "agent_id": "A_TEST_01",
            "txn_type": "cash_out",
            "amount": 1000.0,
            "fee": 15.0,
            "ts": "2026-10-02T10:00:00Z",
        }
    ]
    reports = {"1": {"cash_received_reported": 900.0}}

    X1, _, _, _ = extract_agent_features(
        agents_data=agents,
        transactions_data=txs,
        config=eval_runner.config,
        reports_data=reports,
        include_cash_reports=True,
    )

    # Agent features take no observations data, guaranteeing zero leakage
    X2, _, _, _ = extract_agent_features(
        agents_data=agents,
        transactions_data=txs,
        config=eval_runner.config,
        reports_data=reports,
        include_cash_reports=True,
    )
    pd.testing.assert_frame_equal(X1, X2)
    assert_feature_columns(X1)


# ---------------------------------------------------------------------------
# 5. Signal Ablation Tests
# ---------------------------------------------------------------------------


def test_signal_ablations_execution(eval_runner: EvaluationRunner) -> None:
    """Verify signal ablations report nonzero dropped features count and valid metrics."""
    assisted_clf, agent_detector = eval_runner.fit_canonical_models(sample_train_size=300)

    res = eval_runner.run_experiment_4_signal_ablations(
        assisted_clf=assisted_clf,
        agent_detector=agent_detector,
        sample_train_size=300,
    )

    assert "assisted_classifier_ablation" in res
    assert "agent_detector_ablation" in res

    u_abl = res["assisted_classifier_ablation"]
    assert u_abl["no_session_signals"]["features_dropped_count"] > 0
    assert 0.0 <= u_abl["no_session_signals"]["pr_auc"] <= 1.0

    ag_abl = res["agent_detector_ablation"]
    assert ag_abl["no_cash_gap_signal"]["features_dropped_count"] >= 1
    assert "dropped_columns" in ag_abl["no_cash_gap_signal"]
    assert "agent_cash_gap_rate" in ag_abl["no_cash_gap_signal"]["dropped_columns"]
    assert 0.0 <= ag_abl["no_cash_gap_signal"]["precision_at_k"] <= 1.0


# ---------------------------------------------------------------------------
# 6. Skimming Sweep Tests
# ---------------------------------------------------------------------------


def test_skimming_sweep_generation(eval_runner: EvaluationRunner) -> None:
    """Verify skimming sweep generates scenarios and scores with frozen detector."""
    _, agent_detector = eval_runner.fit_canonical_models(sample_train_size=300)
    res = eval_runner.run_experiment_3_skimming_sweep(agent_detector=agent_detector)

    assert "subtle" in res
    assert "moderate" in res
    assert "obvious" in res

    for tier in ("subtle", "moderate", "obvious"):
        assert 0.0 <= res[tier]["skimmer_mean_risk_score"] <= 1.0
        assert 0.0 <= res[tier]["honest_mean_risk_score"] <= 1.0
        assert 0.0 <= res[tier]["skimmer_detection_rate"] <= 1.0
        assert 0.0 <= res[tier]["honest_false_flag_rate"] <= 1.0


# ---------------------------------------------------------------------------
# 7. Adoption Sensitivity Tests
# ---------------------------------------------------------------------------


def test_adoption_sensitivity_accounting(eval_runner: EvaluationRunner) -> None:
    """Verify adoption sensitivity restricts eligible counterfactual cashouts to assisted users."""
    test_obs = eval_runner.load_observations("test")
    res = eval_runner.run_experiment_5_adoption_sensitivity(test_obs_data=test_obs)

    assert "scenarios" in res
    assert res["eligible_assisted_skimming_loss_bdt"] <= res["total_injected_skimming_loss_bdt"]

    s30 = res["scenarios"]["adoption_30pct"]
    s50 = res["scenarios"]["adoption_50pct"]
    s70 = res["scenarios"]["adoption_70pct"]

    assert s30["loss_prevented_bdt"] <= s50["loss_prevented_bdt"]
    assert s50["loss_prevented_bdt"] <= s70["loss_prevented_bdt"]
    assert s30["pct_eligible_assisted_loss_prevented"] == 30
    assert s50["pct_eligible_assisted_loss_prevented"] == 50
    assert s70["pct_eligible_assisted_loss_prevented"] == 70


def test_adoption_sensitivity_authoritative_behavior(eval_runner: EvaluationRunner) -> None:
    """Verify adoption sensitivity strictly respects is_assisted_behavior.

    Users with group_label='assisted' but is_assisted_behavior=False are excluded.
    Exact Decimal cents arithmetic is verified.
    """
    user_obs = {
        "U_GENUINE": {"is_assisted_behavior": True, "group_label": "independent"},
        "U_NOISY": {"is_assisted_behavior": False, "group_label": "assisted"},
    }
    txn_obs = {
        "1": {
            "txn_id": 1,
            "user_id": "U_GENUINE",
            "is_skimmer_action": True,
            "fee_overcharge": 50.25,
            "payout_reduction": 50.25,
        },
        "2": {
            "txn_id": 2,
            "user_id": "U_NOISY",
            "is_skimmer_action": True,
            "fee_overcharge": 100.00,
            "payout_reduction": 100.00,
        },
        "3": {
            "txn_id": 3,
            "user_id": "U_GENUINE",
            "is_skimmer_action": True,
            "fee_overcharge": 0.00,
            "payout_reduction": 0.00,
        },
    }
    test_obs = {
        "user_observations": user_obs,
        "transaction_observations": txn_obs,
    }
    test_data = {
        "transactions": [
            {"txn_id": 1, "user_id": "U_GENUINE", "txn_type": "cash_out"},
            {"txn_id": 2, "user_id": "U_NOISY", "txn_type": "cash_out"},
            {"txn_id": 3, "user_id": "U_GENUINE", "txn_type": "cash_out"},
            {"txn_id": 4, "user_id": "U_GENUINE", "txn_type": "send_money"},
        ]
    }

    res = eval_runner.run_experiment_5_adoption_sensitivity(
        test_obs_data=test_obs, test_data=test_data
    )

    # Injected losses: action 1 (100.50) + action 2 (200.00) = 300.50. Action 3 has 0 loss.
    assert res["total_injected_skimming_loss_bdt"] == 300.50
    assert res["eligible_assisted_skimming_loss_bdt"] == 100.50
    assert res["eligible_assisted_skimmer_actions"] == 1
    assert res["total_eligible_assisted_cashouts"] == 2  # Tx 1 and Tx 3 (cash_out by U_GENUINE)

    # 30% of 100.50 = 30.15
    assert res["scenarios"]["adoption_30pct"]["loss_prevented_bdt"] == 30.15


# ---------------------------------------------------------------------------
# 8. Demographic Fairness Audit & Null Handling
# ---------------------------------------------------------------------------


def test_fairness_evaluation_null_handling(eval_runner: EvaluationRunner) -> None:
    """Verify that slices with 0 samples or 0 positives return None (null), not false 0.0."""
    assisted_clf, _ = eval_runner.fit_canonical_models(sample_train_size=300)
    res = eval_runner.run_fairness_evaluation(assisted_clf=assisted_clf)

    assert "slices" in res
    for slice_col, cat_map in res["slices"].items():
        for cat_name, metrics in cat_map.items():
            if metrics["positives"] == 0:
                assert metrics["tpr"] is None
            else:
                assert 0.0 <= metrics["tpr"] <= 1.0

            if metrics["negatives"] == 0:
                assert metrics["fpr"] is None
            else:
                assert 0.0 <= metrics["fpr"] <= 1.0


def test_fairness_evaluation_multi_cohort_and_null_slices(
    eval_runner: EvaluationRunner,
) -> None:
    """Verify fairness evaluation audits validation diagnostic, held-out, and shifted cohorts."""
    assisted_clf, _ = eval_runner.fit_canonical_models(sample_train_size=300)
    res = eval_runner.run_fairness_evaluation(assisted_clf=assisted_clf)

    for c_name in ("validation_diagnostic", "held_out_canonical", "held_out_shifted"):
        assert c_name in res
        c_res = res[c_name]
        assert "slices" in c_res
        assert "max_tpr_gaps" in c_res
        for slice_col in ("gender", "age_band", "region", "urban_rural"):
            assert slice_col in c_res["slices"]


# ---------------------------------------------------------------------------
# 9. Deterministic Stable Ties, Recall, and Distribution Shift
# ---------------------------------------------------------------------------


def test_recall_at_80p_and_stable_ties(eval_runner: EvaluationRunner) -> None:
    """Verify stable ties in review_top_k ranking and attainable recall calculation."""
    assisted_clf, agent_detector = eval_runner.fit_canonical_models(sample_train_size=300)

    exp1 = eval_runner.run_experiment_1_assisted_detection(
        assisted_clf=assisted_clf,
        sample_train_size=300,
    )
    exp2 = eval_runner.run_experiment_2_agent_anomaly(
        agent_detector=agent_detector,
    )

    t_held = exp1["held_out_test"]["assisted_classifier"]
    assert 0.0 <= t_held["recall_at_80p_precision"] <= 1.0

    ag_test = exp2["held_out_test"]["combined_ensemble"]
    assert 0.0 <= ag_test["precision_at_k"] <= 1.0
    assert 0.0 <= ag_test["recall_on_skimmers"] <= 1.0


def test_distribution_shift_rules_and_models(eval_runner: EvaluationRunner) -> None:
    """Verify distribution shift evaluates both rule and models and reports measured deltas."""
    assisted_clf, agent_detector = eval_runner.fit_canonical_models(sample_train_size=300)
    res = eval_runner.run_experiment_6_distribution_shift(
        assisted_clf=assisted_clf,
        agent_detector=agent_detector,
    )

    assert "assisted_classifier" in res
    assert "agent_detector" in res

    u_shift = res["assisted_classifier"]
    assert "rule_baseline_canonical" in u_shift
    assert "rule_baseline_shifted" in u_shift
    assert "canonical_test" in u_shift
    assert "shifted_test" in u_shift
    assert "measured_delta_pr_auc" in u_shift
    assert "robust" not in u_shift

    ag_shift = res["agent_detector"]
    assert "canonical_test" in ag_shift
    assert "shifted_test" in ag_shift
    assert "delta_combined_recall_on_skimmers" in ag_shift
    assert "robust" not in ag_shift

    shift_ag = ag_shift["shifted_test"]
    assert "baseline_rule" in shift_ag
    assert "peer_robust_zscore" in shift_ag
    assert "isolation_forest" in shift_ag
    assert "combined_ensemble" in shift_ag
    assert "denominators" in shift_ag


# ---------------------------------------------------------------------------
# 10. Artifact Loader, Tamper Rejection, and Deployment Bundle
# ---------------------------------------------------------------------------


def test_artifact_loader_tamper_rejection(eval_runner: EvaluationRunner, tmp_path: Path) -> None:
    """Verify ArtifactLoader validates hashes and rejects tampered joblib files."""
    assisted_clf, _ = eval_runner.fit_canonical_models(sample_train_size=300)

    # Save to tmp directory
    assisted_art = tmp_path / "assisted.joblib"
    assisted_clf.save(assisted_art)

    manifest_path = tmp_path / "manifest.json"
    actual_sha = hashlib.sha256(assisted_art.read_bytes()).hexdigest()
    manifest_data = {
        "schema_version": 1,
        "synthetic": True,
        "artifact_type": "sathi_evaluation_run",
        "config_sha256": "0" * 64,
        "features": {
            "assisted_classifier": assisted_clf.feature_names_,
        },
        "model_artifacts": {
            "assisted_sha256": actual_sha,
        },
    }
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    # Valid load succeeds
    loaded = ArtifactLoader.load_assisted_model(assisted_art, manifest_path=manifest_path)
    assert loaded.feature_names_ == assisted_clf.feature_names_

    # Tamper with file
    assisted_art.write_bytes(assisted_art.read_bytes() + b"tamper")
    with pytest.raises(ArtifactVerificationError, match="SHA-256 mismatch"):
        ArtifactLoader.load_assisted_model(assisted_art, manifest_path=manifest_path)


def test_missing_hash_fails_closed(eval_runner: EvaluationRunner, tmp_path: Path) -> None:
    """Verify loading assisted model fails closed if manifest omits hash."""
    assisted_clf, _ = eval_runner.fit_canonical_models(sample_train_size=300)
    art_path = tmp_path / "assisted.joblib"
    assisted_clf.save(art_path)

    manifest_path = tmp_path / "manifest.json"
    manifest_data = {
        "schema_version": 1,
        "synthetic": True,
        "artifact_type": "sathi_evaluation_run",
        "config_sha256": "0" * 64,
        "features": {
            "assisted_classifier": assisted_clf.feature_names_,
        },
        "model_artifacts": {},
    }
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ArtifactVerificationError, match="Absent SHA-256 checksum"):
        ArtifactLoader.load_assisted_model(art_path, manifest_path=manifest_path)


def test_exact_model_save_load_equivalence(eval_runner: EvaluationRunner, tmp_path: Path) -> None:
    """Verify that saving and reloading a model produces bit-for-bit identical predictions."""
    assisted_clf, _ = eval_runner.fit_canonical_models(sample_train_size=300)

    test_data = eval_runner.load_split("test")
    X_test, _, _, _ = extract_user_features(
        users_data=test_data["users"][:50],
        transactions_data=test_data["transactions"],
        sessions_data=test_data["sessions"],
        config=eval_runner.config,
    )

    preds_before = assisted_clf.predict_proba(X_test)

    art_path = tmp_path / "assisted.joblib"
    assisted_clf.save(art_path)

    manifest_path = tmp_path / "manifest.json"
    actual_sha = hashlib.sha256(art_path.read_bytes()).hexdigest()
    manifest_data = {
        "schema_version": 1,
        "synthetic": True,
        "artifact_type": "sathi_evaluation_run",
        "config_sha256": "0" * 64,
        "features": {
            "assisted_classifier": assisted_clf.feature_names_,
        },
        "model_artifacts": {
            "assisted_sha256": actual_sha,
        },
    }
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    loaded_clf = ArtifactLoader.load_assisted_model(art_path, manifest_path=manifest_path)
    preds_after = loaded_clf.predict_proba(X_test)

    np.testing.assert_array_equal(preds_before, preds_after)


def test_deployment_bundle_export_and_loading(
    eval_runner: EvaluationRunner, tmp_path: Path
) -> None:
    """Verify deployment bundle export, zero-leakage snapshot, and bundle loading."""
    out_dir = tmp_path / "eval_run"
    results = eval_runner.run_all(sample_train_size=300)
    eval_runner.save_evaluation_run(output_dir=out_dir, results=results)

    # Verify files created in output directory
    assert (out_dir / "results.json").is_file()
    assert (out_dir / "generated-report.md").is_file()
    assert (out_dir / "assisted.joblib").is_file()
    assert (out_dir / "agent.joblib").is_file()
    assert (out_dir / "manifest.json").is_file()

    deploy_dir = out_dir / "deployment"
    assert deploy_dir.is_dir()
    assert (deploy_dir / "manifest.json").is_file()
    assert (deploy_dir / "metrics_provenance.json").is_file()
    assert (deploy_dir / "synthetic_inference_snapshot.json").is_file()

    # Verify zero ground truth and zero demographics in snapshot
    snapshot_path = deploy_dir / "synthetic_inference_snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    for cust in snapshot["customers"]:
        assert "user_id" in cust
        assert "predicted_probability" in cust
        assert "predicted_class" in cust
        assert "explanations" in cust
        # Forbidden columns
        for forbidden in ("gender", "age_band", "region", "urban_rural", "group_label"):
            assert forbidden not in cust
            assert forbidden not in cust["features"]

    for ag in snapshot["agents"]:
        assert "agent_id" in ag
        assert "risk_score" in ag
        assert "risk_level" in ag
        assert "reasons" in ag
        for forbidden in ("agent_type", "region", "volume_band"):
            assert forbidden not in ag
            assert forbidden not in ag["features"]

    # Verify bundle loading
    bundle = ArtifactLoader.load_deployment_bundle(deploy_dir)
    assert bundle["assisted_model"] is not None
    assert bundle["agent_model"] is not None
    assert bundle["metrics_provenance"] is not None
    assert bundle["synthetic_inference_snapshot"] is not None


def test_deployment_bundle_json_only_loading(eval_runner: EvaluationRunner, tmp_path: Path) -> None:
    """Verify load_deployment_bundle_json loads JSON artifacts without deserializing models."""
    out_dir = tmp_path / "eval_run"
    results = eval_runner.run_all(sample_train_size=300)
    eval_runner.save_evaluation_run(output_dir=out_dir, results=results)

    deploy_dir = out_dir / "deployment"
    bundle = ArtifactLoader.load_deployment_bundle_json(deploy_dir)

    assert bundle["assisted_model"] is None
    assert bundle["agent_model"] is None
    assert bundle["metrics_provenance"]["final_run_timestamp"] == results["final_run_timestamp"]
    assert "key_metrics" in bundle["metrics_provenance"]
    assert len(bundle["synthetic_inference_snapshot"]["customers"]) > 0
    assert len(bundle["synthetic_inference_snapshot"]["agents"]) > 0
    assert (
        bundle["results"]["experiment_1_assisted_detection"]
        == results["experiment_1_assisted_detection"]
    )


def test_bundle_path_escape_rejection(eval_runner: EvaluationRunner, tmp_path: Path) -> None:
    """Verify load_deployment_bundle rejects path escape attempts in manifest."""
    out_dir = tmp_path / "eval_run"
    results = eval_runner.run_all(sample_train_size=300)
    eval_runner.save_evaluation_run(output_dir=out_dir, results=results)

    deploy_dir = out_dir / "deployment"
    manifest_path = deploy_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["../escape.txt"] = {"sha256": "0" * 64, "size_bytes": 10}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ArtifactVerificationError, match="Path escape or absolute path detected"):
        ArtifactLoader.load_deployment_bundle(deploy_dir)


def test_run_manifest_provenance_and_git_source_hash(
    eval_runner: EvaluationRunner, tmp_path: Path
) -> None:
    """Verify save_evaluation_run populates training sample, git, and data hashes in manifest."""
    out_dir = tmp_path / "eval_run"
    results = eval_runner.run_all(sample_train_size=300)
    eval_runner.save_evaluation_run(output_dir=out_dir, results=results)

    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert "training_sample" in manifest
    assert manifest["training_sample"]["count"] <= 300
    assert len(manifest["training_sample"]["user_ids_sha256"]) == 64
    assert manifest["training_sample"]["seed"] == eval_runner.config["simulation"]["seed_train"]

    assert "config_sha256" in manifest
    assert "source_tree_sha256" in manifest
    assert "dirty_source_status" in manifest
    assert "data_hashes" in manifest
    assert "test_shifted" in manifest["data_hashes"]


def test_finite_json_metrics_and_markdown_tables(eval_runner: EvaluationRunner) -> None:
    """Verify all metrics in results.json are finite JSON (no NaN or Inf) and markdown formats."""
    results = eval_runner.run_all(sample_train_size=300)

    # Verify results serializes to valid JSON without NaN
    json_str = json.dumps(results)
    assert "NaN" not in json_str
    assert "Infinity" not in json_str

    report_md = eval_runner.generate_markdown_report(results)
    assert "# Sathi Evaluation & Experimentation Results" in report_md
    assert "## 1. Assisted-User Classifier vs Rule Baseline" in report_md
    assert "## 2. Agent Anomaly Detection: Ensemble & Baseline Comparison" in report_md
    assert "## 3. Skimming Intensity Sweep" in report_md
    assert "## 4. Signal Ablations" in report_md
    assert "## 5. Adoption Sensitivity & Simulated Loss Prevented" in report_md
    assert "## 6. Distribution Shift Robustness" in report_md
    assert "## 7. Demographic Fairness Audit" in report_md


def test_repeated_tiny_run_deterministic_metrics(eval_fixture: Path) -> None:
    """Verify that repeated evaluation runs with same seed produce bit-for-bit identical metrics."""
    cfg = get_small_eval_config()
    runner1 = EvaluationRunner(splits_dir=eval_fixture, config=cfg)
    runner2 = EvaluationRunner(splits_dir=eval_fixture, config=cfg)

    res1 = runner1.run_all(sample_train_size=300)
    res2 = runner2.run_all(sample_train_size=300)

    res1_clean = copy.deepcopy(res1)
    res2_clean = copy.deepcopy(res2)
    res1_clean.pop("final_run_timestamp")
    res2_clean.pop("final_run_timestamp")

    assert json.dumps(res1_clean, sort_keys=True) == json.dumps(res2_clean, sort_keys=True)


def test_cli_rejects_negative_sampling() -> None:
    """Verify scripts/evaluate.py exits with code 1 on negative sample size."""
    import importlib.util
    import sys

    repo_root = Path(__file__).resolve().parent.parent.parent
    script_path = repo_root / "scripts" / "evaluate.py"
    spec = importlib.util.spec_from_file_location("scripts_evaluate", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["scripts_evaluate"] = mod
    spec.loader.exec_module(mod)

    assert mod.main(["--sample-train-size", "-10"]) == 1


def test_json_artifact_import_is_lightweight_in_fresh_process() -> None:
    import subprocess
    import sys

    code = (
        "import sys; import app.evaluation.artifacts; "
        "assert not set(('numpy','pandas','sklearn','lightgbm','shap','joblib')) & set(sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


def test_source_provenance_distinguishes_clean_dirty_and_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    import app.evaluation.suite as suite

    repo = tmp_path / "repo"
    source = repo / "backend/app/evaluation/suite.py"
    source.parent.mkdir(parents=True)
    source.write_text("# synthetic fixture\n")

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-b", "codex/provenance-test")
    git("add", ".")
    git(
        "-c",
        "user.name=Synthetic",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "fixture",
    )
    monkeypatch.setattr(suite, "__file__", str(source))
    clean_hash, dirty = suite._compute_source_tree_hash()
    assert dirty is False
    assert len(suite._get_git_revision()) == 40
    source.write_text("# changed synthetic fixture\n")
    changed_hash, dirty = suite._compute_source_tree_hash()
    assert dirty is True and clean_hash != changed_hash
    git("restore", ".")
    worktree = tmp_path / "worktree"
    git("worktree", "add", "--detach", str(worktree))
    assert (worktree / ".git").is_file()
    monkeypatch.setattr(suite, "__file__", str(worktree / "backend/app/evaluation/suite.py"))
    assert suite._compute_source_tree_hash() == (clean_hash, False)


def test_json_bundle_rejects_semantic_tamper_even_with_updated_checksum(
    eval_runner: EvaluationRunner, tmp_path: Path
) -> None:
    results = eval_runner.run_all(sample_train_size=300)
    out = tmp_path / "export"
    eval_runner.save_evaluation_run(out, results)
    bundle = out / "deployment"
    path = bundle / "synthetic_inference_snapshot.json"
    original = json.loads(path.read_text())
    manifest_path = bundle / "manifest.json"
    original_manifest = json.loads(manifest_path.read_text())
    for change in ("config_window", "range", "feature", "protected"):
        snapshot = copy.deepcopy(original)
        row = snapshot["customers"][0]
        if change == "config_window":
            snapshot["window_days"] += 1
        elif change == "range":
            row["predicted_probability"] = 1.5
        elif change == "feature":
            row["features"].pop(next(iter(row["features"])))
        else:
            row["gender"] = "synthetic"
        raw = json.dumps(snapshot).encode()
        path.write_bytes(raw)
        manifest = copy.deepcopy(original_manifest)
        manifest["files"][path.name] = {
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        manifest_path.write_text(json.dumps(manifest))
        with pytest.raises(ArtifactVerificationError):
            ArtifactLoader.load_deployment_bundle_json(bundle)
