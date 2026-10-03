"""Comprehensive reproducible evaluation suite and experiment runner for Sathi.

Conforms strictly to docs/evaluation-plan.md, docs/design-repair-proposal.md, and tasks/T023b:
- Fail-closed manifest and shifted metadata validation BEFORE fitting.
- Models fitted on train only; calibrated on disjoint validation.
- Validation metrics explicitly disclosed as calibration-cohort diagnostics.
- Validation sanity ceiling check (PR-AUC <= max_pr_auc) before opening test cohorts.
- Score rule baselines and models across validation, held-out test, and shifted test.
- review_top_k clipped to cohort size with deterministic stable ties.
- Attainable recall where precision >= 0.80 computed explicitly.
- Skimming sweep via reviewed generator using subtle/moderate/obvious profiles.
- Signal ablations: assisted session signal and agent cash-gap ablation with train-only refit.
- Adoption sensitivity restricted to assisted simulated behavior users.
- Strict fairness evaluation with null handling for empty/one-class slices across cohorts.
- Serialization of results.json (finite JSON, no NaN), generated-report.md, joblib artifacts,
  manifest.json, and deployment bundle.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import math
import subprocess
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import auc, brier_score_loss, precision_recall_curve, roc_auc_score

from app.data.config import ConfigError, load_config, validate_config
from app.data.generator import build_canonical_agent_registry, generate_dataset
from app.evaluation.artifacts import (
    SanityCeilingExceededError,
    export_deployment_bundle,
    validate_manifest_and_metadata,
)
from app.features.guard import assert_feature_columns
from app.models.agent_model import AgentAnomalyDetector
from app.models.assisted_model import AssistedUserClassifier
from app.models.baselines import AgentAnomalyRuleBaseline, AssistedUserRuleBaseline
from app.models.features import extract_agent_features, extract_user_features


def _git_read(*args: str) -> str | None:
    repo = Path(__file__).resolve().parents[3]
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, check=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def _get_git_revision() -> str:
    return _git_read("rev-parse", "HEAD") or "unknown"


def _compute_source_tree_hash() -> tuple[str, bool | None]:
    """Hash relevant source and report actual Git status, including worktree checkouts."""
    repo = Path(__file__).resolve().parents[3]
    paths = sorted((repo / "backend/app").rglob("*.py"))
    paths += [
        repo / name
        for name in (
            "scripts/evaluate.py",
            "Makefile",
            "backend/pyproject.toml",
            "backend/requirements.txt",
            "backend/requirements-dev.lock",
        )
    ]
    entries = [
        (str(path.relative_to(repo)), hashlib.sha256(path.read_bytes()).hexdigest())
        for path in paths
        if path.is_file()
    ]
    tree_sha = hashlib.sha256(json.dumps(sorted(entries)).encode()).hexdigest()
    changed = _git_read(
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        "backend/app",
        "scripts/evaluate.py",
        "Makefile",
        "backend/pyproject.toml",
        "backend/requirements.txt",
        "backend/requirements-dev.lock",
    )
    return tree_sha, None if changed is None else bool(changed)


def _get_dependency_versions() -> dict[str, str]:
    """Capture runtime versions of core ML dependencies."""
    versions = {}
    for mod_name in ("numpy", "pandas", "sklearn", "lightgbm", "shap", "joblib", "scipy"):
        try:
            mod = __import__(mod_name)
            versions[mod_name] = getattr(mod, "__version__", "unknown")
        except ImportError:
            versions[mod_name] = "not-installed"
    return versions


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively replace NaN and infinite floats with None for valid JSON serialization."""
    if isinstance(obj, float):
        if not math.isfinite(obj):
            return None
        return obj
    if isinstance(obj, Decimal):
        val = float(obj)
        return val if math.isfinite(val) else None
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(item) for item in obj]
    if isinstance(obj, tuple):
        return [_sanitize_for_json(item) for item in obj]
    if isinstance(obj, (np.floating, np.float64, np.float32)):
        val = float(obj)
        return val if math.isfinite(val) else None
    if isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return _sanitize_for_json(obj.tolist())
    return obj


def _compute_max_attainable_recall_at_80p(y_true: np.ndarray, y_proba: np.ndarray) -> float:
    """Compute maximum attainable recall on PR curve where precision >= 0.80."""
    if len(np.unique(y_true)) < 2:
        return 0.0
    precision, recall, _ = precision_recall_curve(y_true, y_proba)
    idx_80 = np.where(precision >= 0.80)[0]
    if len(idx_80) > 0:
        return float(np.max(recall[idx_80]))
    return 0.0


class EvaluationRunner:
    """Orchestrates reproducible model evaluation, experiments, and artifact generation."""

    def __init__(
        self,
        splits_dir: str | Path | None = None,
        config: dict[str, Any] | None = None,
        config_path: str | Path | None = None,
        random_state: int = 42,
    ) -> None:
        self.random_state = random_state

        if config is not None:
            self.config = validate_config(config)
        else:
            self.config = load_config(config_path)

        if splits_dir is not None:
            self.splits_dir = Path(splits_dir)
            if not self.splits_dir.is_dir():
                raise FileNotFoundError(f"Splits directory not found: {self.splits_dir}")
        else:
            self.splits_dir = Path("data/generated/splits")
            if not self.splits_dir.is_dir():
                raise FileNotFoundError(
                    f"Default splits directory not found: {self.splits_dir}. "
                    "Run 'make split' or specify --splits-dir."
                )

        # Validate manifest and metadata BEFORE fitting models (Fail closed)
        self.split_artifacts = validate_manifest_and_metadata(
            splits_dir=self.splits_dir,
            config=self.config,
        )

        models_cfg = self.config.get("models", {})
        assisted_cfg = models_cfg.get("assisted_classifier", {})
        if "features_window_days" not in assisted_cfg:
            raise ConfigError("models.assisted_classifier.features_window_days is required.")
        self.features_window_days: int = int(assisted_cfg["features_window_days"])

        if "classification_threshold" not in assisted_cfg:
            raise ConfigError("models.assisted_classifier.classification_threshold is required.")
        self.classification_threshold: float = float(assisted_cfg["classification_threshold"])

        agent_cfg = models_cfg.get("agent_anomaly", {})
        if "review_top_k" not in agent_cfg:
            raise ConfigError("models.agent_anomaly.review_top_k is required.")
        self.agent_review_top_k: int = int(agent_cfg["review_top_k"])

        policy_cfg = self.config.get("policy", {})
        if "agent_risk_high" not in policy_cfg:
            raise ConfigError("policy.agent_risk_high is required.")
        self.agent_risk_high: float = float(policy_cfg["agent_risk_high"])

        if "agent_risk_medium" not in policy_cfg:
            raise ConfigError("policy.agent_risk_medium is required.")
        self.agent_risk_medium: float = float(policy_cfg["agent_risk_medium"])

        sanity_cfg = models_cfg.get("sanity", {})
        if "max_pr_auc" not in sanity_cfg:
            raise ConfigError("models.sanity.max_pr_auc is required.")
        self.max_pr_auc_sanity: float = float(sanity_cfg["max_pr_auc"])

        # Explicit common simulation snapshot derived from configured start+days
        sim_cfg = self.config["simulation"]
        start_ts = sim_cfg["start_timestamp"]
        start_dt = datetime.datetime.fromisoformat(str(start_ts).replace("Z", "+00:00"))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)
        duration_days = int(sim_cfg.get("days", 90))
        self.snapshot_as_of_dt = start_dt + datetime.timedelta(days=duration_days)
        self.as_of_iso = self.snapshot_as_of_dt.isoformat()
        self.cutoff_iso = (
            self.snapshot_as_of_dt - datetime.timedelta(days=self.features_window_days)
        ).isoformat()

        self.fitted_assisted_clf: AssistedUserClassifier | None = None
        self.fitted_agent_detector: AgentAnomalyDetector | None = None
        self.sampled_train_users: list[dict[str, Any]] | None = None

    def load_split(self, split_name: str) -> dict[str, Any]:
        """Load split dataset (train, validation, test, test_shifted) from split artifacts."""
        if split_name == "test_shifted":
            return self.split_artifacts["shifted_dataset"]
        if split_name in self.split_artifacts["datasets"]:
            return self.split_artifacts["datasets"][split_name]
        raise ValueError(f"Unknown split name: {split_name}")

    def load_observations(self, split_name: str) -> dict[str, Any]:
        """Load observations sidecar for given split name."""
        if split_name == "test_shifted":
            return self.split_artifacts["shifted_observations"]
        if split_name in self.split_artifacts["observations"]:
            return self.split_artifacts["observations"][split_name]
        raise ValueError(f"Unknown observations split: {split_name}")

    def fit_canonical_models(
        self,
        sample_train_size: int | None = 4000,
    ) -> tuple[AssistedUserClassifier, AgentAnomalyDetector]:
        """Fit models on train cohort only, validating sanity ceiling on validation diagnostic."""
        train_data = self.load_split("train")
        val_data = self.load_split("validation")
        train_obs = self.load_observations("train")

        train_users = train_data["users"]
        seed_train = self.config["simulation"]["seed_train"]
        if sample_train_size is not None and sample_train_size < len(train_users):
            rng = np.random.default_rng(seed_train)
            indices = np.sort(rng.choice(len(train_users), size=sample_train_size, replace=False))
            sampled_train_users = [train_users[i] for i in indices]
        else:
            sampled_train_users = train_users
        self.sampled_train_users = sampled_train_users

        # 1. User behavioral feature extraction with configured windowing and explicit as_of
        X_tr_user, y_tr_user, _, _ = extract_user_features(
            users_data=sampled_train_users,
            transactions_data=train_data["transactions"],
            sessions_data=train_data["sessions"],
            as_of=self.as_of_iso,
            window_days=self.features_window_days,
            config=self.config,
        )

        X_val_user, y_val_user, _, _ = extract_user_features(
            users_data=val_data["users"],
            transactions_data=val_data["transactions"],
            sessions_data=val_data["sessions"],
            as_of=self.as_of_iso,
            window_days=self.features_window_days,
            config=self.config,
        )

        assert_feature_columns(X_tr_user)
        assert_feature_columns(X_val_user)

        # 2. Fit AssistedUserClassifier on train only; calibrate on validation
        assisted_clf = AssistedUserClassifier(
            config=self.config,
            random_state=self.random_state,
        )
        assisted_clf.fit(X_tr_user, y_tr_user, X_val_user, y_val_user)

        # 3. Sanity check: Run ceiling on validation before opening test
        val_probs = assisted_clf.predict_proba(X_val_user)[:, 1]
        p_val, r_val, _ = precision_recall_curve(y_val_user, val_probs)
        val_pr_auc = float(auc(r_val, p_val))

        if val_pr_auc > self.max_pr_auc_sanity:
            raise SanityCeilingExceededError(
                f"Validation PR-AUC ({val_pr_auc:.4f}) exceeds configured sanity ceiling "
                f"({self.max_pr_auc_sanity:.4f}). Halting final scoring per T023b. "
                "Widen overlap under user instructions and document it; "
                "never tune to a target score."
            )

        # 4. Agent feature extraction with cash reports support
        X_tr_agent, y_tr_agent, _, _ = extract_agent_features(
            agents_data=train_data["agents"],
            transactions_data=train_data["transactions"],
            config=self.config,
            reports_data=train_obs,
            include_cash_reports=True,
        )
        assert_feature_columns(X_tr_agent)

        agent_detector = AgentAnomalyDetector(
            config=self.config,
            random_state=self.random_state,
        )
        agent_detector.fit(X_tr_agent)

        self.fitted_assisted_clf = assisted_clf
        self.fitted_agent_detector = agent_detector
        return assisted_clf, agent_detector

    def run_experiment_1_assisted_detection(
        self,
        assisted_clf: AssistedUserClassifier,
        train_data: dict[str, Any] | None = None,
        val_data: dict[str, Any] | None = None,
        test_data: dict[str, Any] | None = None,
        sample_train_size: int | None = 4000,
    ) -> dict[str, Any]:
        """Experiment 1: Rule baseline vs LightGBM on validation, test, and noise comparison."""
        if train_data is None:
            train_data = self.load_split("train")
        if val_data is None:
            val_data = self.load_split("validation")
        if test_data is None:
            test_data = self.load_split("test")

        X_val, y_val, _, _ = extract_user_features(
            users_data=val_data["users"],
            transactions_data=val_data["transactions"],
            sessions_data=val_data["sessions"],
            as_of=self.as_of_iso,
            window_days=self.features_window_days,
            config=self.config,
        )
        X_test, y_test, _, _ = extract_user_features(
            users_data=test_data["users"],
            transactions_data=test_data["transactions"],
            sessions_data=test_data["sessions"],
            as_of=self.as_of_iso,
            window_days=self.features_window_days,
            config=self.config,
        )

        baseline = AssistedUserRuleBaseline(config=self.config)

        def _evaluate_model_and_baseline(
            X_df: pd.DataFrame, y_ser: pd.Series, split_label: str, is_diagnostic: bool
        ) -> dict[str, Any]:
            y_arr = y_ser.to_numpy(dtype=int)
            positives = int(y_arr.sum())
            negatives = len(y_arr) - positives

            # Baseline evaluation
            b_preds = baseline.predict(X_df)
            b_proba = b_preds.astype(float)
            b_p, b_r, _ = precision_recall_curve(y_arr, b_proba)
            b_pr_auc = float(auc(b_r, b_p))
            b_roc_auc = float(roc_auc_score(y_arr, b_proba))
            b_brier = float(brier_score_loss(y_arr, b_proba))

            b_tp = int(((b_preds == 1) & (y_arr == 1)).sum())
            b_fp = int(((b_preds == 1) & (y_arr == 0)).sum())
            b_prec = b_tp / (b_tp + b_fp) if (b_tp + b_fp) > 0 else 0.0
            b_rec = b_tp / positives if positives > 0 else 0.0
            b_rec_at_80p = b_rec if b_prec >= 0.80 else 0.0

            # LightGBM model evaluation
            m_probs = assisted_clf.predict_proba(X_df)[:, 1]
            m_preds = (m_probs >= self.classification_threshold).astype(int)
            m_p, m_r, _ = precision_recall_curve(y_arr, m_probs)
            m_pr_auc = float(auc(m_r, m_p))
            m_roc_auc = float(roc_auc_score(y_arr, m_probs))
            m_brier = float(brier_score_loss(y_arr, m_probs))
            m_rec_at_80p = _compute_max_attainable_recall_at_80p(y_arr, m_probs)

            m_tp = int(((m_preds == 1) & (y_arr == 1)).sum())
            m_fp = int(((m_preds == 1) & (y_arr == 0)).sum())
            m_prec = m_tp / (m_tp + m_fp) if (m_tp + m_fp) > 0 else 0.0
            m_rec = m_tp / positives if positives > 0 else 0.0

            return {
                "split": split_label,
                "is_calibration_cohort_diagnostic": is_diagnostic,
                "disclosure": (
                    "Validation classifier metrics are calibration-cohort diagnostics, "
                    "not independent calibrated generalization; test cohort is final estimate."
                    if is_diagnostic
                    else "Held-out independent estimate."
                ),
                "denominators": {
                    "total_users": len(y_arr),
                    "positives_assisted": positives,
                    "negatives_independent": negatives,
                },
                "rule_baseline": {
                    "pr_auc": b_pr_auc,
                    "roc_auc": b_roc_auc,
                    "brier_score": b_brier,
                    "precision": b_prec,
                    "recall": b_rec,
                    "recall_at_80p_precision": b_rec_at_80p,
                },
                "assisted_classifier": {
                    "pr_auc": m_pr_auc,
                    "roc_auc": m_roc_auc,
                    "brier_score": m_brier,
                    "precision": m_prec,
                    "recall": m_rec,
                    "recall_at_80p_precision": m_rec_at_80p,
                    "classification_threshold": self.classification_threshold,
                },
            }

        val_res = _evaluate_model_and_baseline(X_val, y_val, "validation", is_diagnostic=True)
        test_res = _evaluate_model_and_baseline(
            X_test, y_test, "held_out_test_seed2026", is_diagnostic=False
        )

        train_users = train_data["users"]
        seed_train = self.config["simulation"]["seed_train"]
        if sample_train_size is not None and sample_train_size < len(train_users):
            rng_s = np.random.default_rng(seed_train)
            indices = np.sort(rng_s.choice(len(train_users), size=sample_train_size, replace=False))
            sampled_train_users = [train_users[i] for i in indices]
        else:
            sampled_train_users = train_users

        X_tr, y_tr, _, _ = extract_user_features(
            sampled_train_users,
            train_data["transactions"],
            train_data["sessions"],
            as_of=self.as_of_iso,
            window_days=self.features_window_days,
            config=self.config,
        )

        rng = np.random.default_rng(self.random_state)
        y_tr_noisy = y_tr.copy()
        flip_mask = rng.random(len(y_tr)) < 0.05
        y_tr_noisy[flip_mask] = 1 - y_tr_noisy[flip_mask]

        clf_noisy = AssistedUserClassifier(
            config=self.config,
            random_state=self.random_state,
        )
        clf_noisy.fit(X_tr, y_tr_noisy, X_val, y_val)
        probs_noisy = clf_noisy.predict_proba(X_test)[:, 1]
        p_n, r_n, _ = precision_recall_curve(y_test.to_numpy(), probs_noisy)
        pr_auc_noisy = float(auc(r_n, p_n))
        roc_auc_noisy = float(roc_auc_score(y_test.to_numpy(), probs_noisy))
        brier_noisy = float(brier_score_loss(y_test.to_numpy(), probs_noisy))
        rec_at_80p_noisy = _compute_max_attainable_recall_at_80p(y_test.to_numpy(), probs_noisy)

        noise_comparison = {
            "lightgbm_baseline_noise": {
                "noise_description": "Configured 10% baseline label noise (not claimed pristine)",
                "pr_auc": test_res["assisted_classifier"]["pr_auc"],
                "roc_auc": test_res["assisted_classifier"]["roc_auc"],
                "brier_score": test_res["assisted_classifier"]["brier_score"],
                "recall_at_80p_precision": (
                    test_res["assisted_classifier"]["recall_at_80p_precision"]
                ),
            },
            "lightgbm_extra_5pct_label_flips": {
                "noise_description": ("Extra 5% independent label flips beyond baseline 10% noise"),
                "pr_auc": pr_auc_noisy,
                "roc_auc": roc_auc_noisy,
                "brier_score": brier_noisy,
                "recall_at_80p_precision": rec_at_80p_noisy,
            },
        }

        return {
            "pr_auc_convention": "sklearn.metrics.auc(recall, precision)",
            "validation_diagnostic": val_res,
            "held_out_test": test_res,
            "noise_comparison": noise_comparison,
        }

    def run_experiment_2_agent_anomaly(
        self,
        agent_detector: AgentAnomalyDetector,
        val_data: dict[str, Any] | None = None,
        test_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Experiment 2: Rule baseline vs Peer Z vs Isolation Forest vs Combined for agents."""
        if val_data is None:
            val_data = self.load_split("validation")
        if test_data is None:
            test_data = self.load_split("test")

        val_obs = self.load_observations("validation")
        test_obs = self.load_observations("test")

        def _evaluate_agent_cohort(
            dataset: dict[str, Any],
            obs: dict[str, Any],
            cohort_name: str,
        ) -> dict[str, Any]:
            agents = dataset["agents"]
            txs = dataset["transactions"]
            X_ag, y_ag, meta_df, agent_ids = extract_agent_features(
                agents, txs, config=self.config, reports_data=obs, include_cash_reports=True
            )
            y_true = y_ag.to_numpy(dtype=int)
            total_agents = len(y_true)
            total_skimmers = int(y_true.sum())
            k_clipped = min(self.agent_review_top_k, total_agents)

            types_arr = meta_df["agent_type"].to_numpy()
            hv_honest_indices = np.where(types_arr == "high_volume_honest")[0]
            total_hv_honest = len(hv_honest_indices)

            # 1. Rule baseline
            rule_baseline = AgentAnomalyRuleBaseline(config=self.config)
            r_preds = rule_baseline.predict(X_ag)
            r_scores = rule_baseline.score(X_ag)

            r_sorted = sorted(
                range(total_agents),
                key=lambda i: (-r_scores[i], agent_ids[i]),
            )
            r_top_k_indices = r_sorted[:k_clipped]
            r_prec_k = (
                float(y_true[r_top_k_indices].sum()) / float(k_clipped) if k_clipped > 0 else 0.0
            )
            r_rec_skimmers = (
                float((r_preds & y_true).sum()) / float(total_skimmers)
                if total_skimmers > 0
                else 0.0
            )
            r_ff_honest = (
                float(r_preds[hv_honest_indices].sum()) / float(total_hv_honest)
                if total_hv_honest > 0
                else None
            )

            # 2. Detector methods (Peer Z, IF, Combined)
            z_risk, _ = agent_detector.score_peer_robust_zscore(X_ag)
            if_risk = agent_detector.score_isolation_forest(X_ag)
            comb_risk, _ = agent_detector.score_combined(X_ag)

            def _method_metrics(scores: np.ndarray, model_label: str) -> dict[str, Any]:
                sorted_idx = sorted(
                    range(total_agents),
                    key=lambda i: (-scores[i], agent_ids[i]),
                )
                top_k_idx = sorted_idx[:k_clipped]
                p_k = float(y_true[top_k_idx].sum()) / float(k_clipped) if k_clipped > 0 else 0.0

                flagged = (scores >= self.agent_risk_high).astype(int)
                rec = (
                    float((flagged & y_true).sum()) / float(total_skimmers)
                    if total_skimmers > 0
                    else 0.0
                )
                ff_honest = (
                    float(flagged[hv_honest_indices].sum()) / float(total_hv_honest)
                    if total_hv_honest > 0
                    else None
                )

                return {
                    "method": model_label,
                    "precision_at_k": p_k,
                    "recall_on_skimmers": rec,
                    "flagged_high_risk_count": int(flagged.sum()),
                    "false_flag_rate_honest_high_volume": ff_honest,
                }

            return {
                "cohort": cohort_name,
                "review_top_k_configured": self.agent_review_top_k,
                "review_top_k_clipped": k_clipped,
                "denominators": {
                    "total_agents": total_agents,
                    "total_skimmers": total_skimmers,
                    "total_honest_high_volume": total_hv_honest,
                },
                "baseline_rule": {
                    "precision_at_k": r_prec_k,
                    "recall_on_skimmers": r_rec_skimmers,
                    "flagged_count": int(r_preds.sum()),
                    "false_flag_rate_honest_high_volume": r_ff_honest,
                },
                "peer_robust_zscore": _method_metrics(z_risk, "peer_robust_zscore"),
                "isolation_forest": _method_metrics(if_risk, "isolation_forest"),
                "combined_ensemble": _method_metrics(comb_risk, "combined_ensemble"),
            }

        val_eval = _evaluate_agent_cohort(val_data, val_obs, "validation")
        test_eval = _evaluate_agent_cohort(test_data, test_obs, "held_out_test_seed2026")

        return {
            "validation": val_eval,
            "held_out_test": test_eval,
            "combined_ensemble": test_eval["combined_ensemble"],
            "baseline_rule": test_eval["baseline_rule"],
        }

    def run_experiment_3_skimming_sweep(
        self,
        agent_detector: AgentAnomalyDetector,
    ) -> dict[str, Any]:
        """Experiment 3: Skimming intensity sweep (subtle, moderate, obvious)."""
        val_agent_ids = self.split_artifacts["manifest"]["cohorts"]["validation"]["agent_ids"]
        val_seed = self.split_artifacts["manifest"]["cohorts"]["validation"]["seed"]
        val_cust_count = self.split_artifacts["manifest"]["cohorts"]["validation"]["customer_count"]
        canonical_agents = build_canonical_agent_registry(self.config)

        tiers = ("subtle", "moderate", "obvious")
        results: dict[str, Any] = {}

        for intensity in tiers:
            sweep_cfg = copy.deepcopy(self.config)
            sweep_cfg["simulation"]["skimming_intensity"] = intensity

            ds, obs = generate_dataset(
                config=sweep_cfg,
                seed=val_seed,
                agent_ids=val_agent_ids,
                customers=val_cust_count,
                return_observations=True,
                canonical_agents=canonical_agents,
            )

            X_ag, y_ag, _, _ = extract_agent_features(
                agents_data=ds["agents"],
                transactions_data=ds["transactions"],
                config=sweep_cfg,
                reports_data=obs,
                include_cash_reports=True,
            )

            scores, _ = agent_detector.score_combined(X_ag)
            y_arr = y_ag.to_numpy(dtype=int)

            skimmer_mask = y_arr == 1
            honest_mask = y_arr == 0

            skimmer_mean_risk = (
                float(np.mean(scores[skimmer_mask])) if skimmer_mask.sum() > 0 else 0.0
            )
            honest_mean_risk = float(np.mean(scores[honest_mask])) if honest_mask.sum() > 0 else 0.0

            flagged = (scores >= self.agent_risk_high).astype(int)
            skimmer_detection_rate = (
                float((flagged & y_arr).sum()) / float(skimmer_mask.sum())
                if skimmer_mask.sum() > 0
                else 0.0
            )
            honest_false_flag_rate = (
                float(flagged[honest_mask].sum()) / float(honest_mask.sum())
                if honest_mask.sum() > 0
                else 0.0
            )

            results[intensity] = {
                "intensity": intensity,
                "skimmer_count": int(skimmer_mask.sum()),
                "honest_agent_count": int(honest_mask.sum()),
                "skimmer_mean_risk_score": skimmer_mean_risk,
                "honest_mean_risk_score": honest_mean_risk,
                "skimmer_detection_rate": skimmer_detection_rate,
                "honest_false_flag_rate": honest_false_flag_rate,
            }

        return results

    def run_experiment_4_signal_ablations(
        self,
        assisted_clf: AssistedUserClassifier,
        agent_detector: AgentAnomalyDetector,
        train_data: dict[str, Any] | None = None,
        val_data: dict[str, Any] | None = None,
        sample_train_size: int | None = 4000,
    ) -> dict[str, Any]:
        """Experiment 4: Feature signal ablations with train-only refit."""
        if train_data is None:
            train_data = self.load_split("train")
        if val_data is None:
            val_data = self.load_split("validation")

        train_obs = self.load_observations("train")
        val_obs = self.load_observations("validation")

        # 1. Assisted user classifier: session signals ablation
        train_users = train_data["users"]
        seed_train = self.config["simulation"]["seed_train"]
        if sample_train_size is not None and sample_train_size < len(train_users):
            rng = np.random.default_rng(seed_train)
            idx = np.sort(rng.choice(len(train_users), size=sample_train_size, replace=False))
            sampled_users = [train_users[i] for i in idx]
        else:
            sampled_users = train_users

        X_tr_u, y_tr_u, _, _ = extract_user_features(
            sampled_users,
            train_data["transactions"],
            train_data["sessions"],
            as_of=self.as_of_iso,
            window_days=self.features_window_days,
            config=self.config,
        )
        X_val_u, y_val_u, _, _ = extract_user_features(
            val_data["users"],
            val_data["transactions"],
            val_data["sessions"],
            as_of=self.as_of_iso,
            window_days=self.features_window_days,
            config=self.config,
        )

        full_probs_u = assisted_clf.predict_proba(X_val_u)[:, 1]
        p_fu, r_fu, _ = precision_recall_curve(y_val_u.to_numpy(), full_probs_u)
        full_pr_auc_u = float(auc(r_fu, p_fu))

        session_cols = [
            c for c in X_tr_u.columns if c.startswith("pin_") or c.startswith("session_")
        ]
        sub_tr_u = X_tr_u.drop(columns=session_cols)
        sub_val_u = X_val_u.drop(columns=session_cols)
        assert_feature_columns(sub_tr_u)
        assert_feature_columns(sub_val_u)

        clf_no_sess = AssistedUserClassifier(config=self.config, random_state=self.random_state)
        clf_no_sess.fit(sub_tr_u, y_tr_u, sub_val_u, y_val_u)
        no_sess_probs = clf_no_sess.predict_proba(sub_val_u)[:, 1]
        p_ns, r_ns, _ = precision_recall_curve(y_val_u.to_numpy(), no_sess_probs)
        no_sess_pr_auc = float(auc(r_ns, p_ns))

        assisted_ablation = {
            "full_model": {
                "features_count": len(X_tr_u.columns),
                "pr_auc": full_pr_auc_u,
            },
            "no_session_signals": {
                "features_dropped_count": len(session_cols),
                "dropped_columns": session_cols,
                "pr_auc": no_sess_pr_auc,
                "delta_pr_auc": no_sess_pr_auc - full_pr_auc_u,
            },
        }

        # 2. Agent anomaly detector: ablate ALL report-derived columns
        X_tr_ag, y_tr_ag, _, _ = extract_agent_features(
            train_data["agents"],
            train_data["transactions"],
            config=self.config,
            reports_data=train_obs,
            include_cash_reports=True,
        )
        X_val_ag, y_val_ag, _, val_ag_ids = extract_agent_features(
            val_data["agents"],
            val_data["transactions"],
            config=self.config,
            reports_data=val_obs,
            include_cash_reports=True,
        )

        full_scores, _ = agent_detector.score_combined(X_val_ag)
        y_val_arr = y_val_ag.to_numpy(dtype=int)
        total_skimmers = int(y_val_arr.sum())
        k_val = min(self.agent_review_top_k, len(y_val_arr))

        full_sorted_idx = sorted(
            range(len(y_val_arr)),
            key=lambda i: (-full_scores[i], val_ag_ids[i]),
        )
        full_top_k = full_sorted_idx[:k_val]
        full_prec_k = float(y_val_arr[full_top_k].sum()) / float(k_val) if k_val > 0 else 0.0
        full_flagged = (full_scores >= self.agent_risk_high).astype(int)
        full_recall = (
            float((full_flagged & y_val_arr).sum()) / float(total_skimmers)
            if total_skimmers > 0
            else 0.0
        )

        report_cols = [c for c in X_tr_ag.columns if "cash_gap" in c or "cash_report" in c]
        sub_tr_ag = X_tr_ag.drop(columns=[c for c in report_cols if c in X_tr_ag.columns])
        sub_val_ag = X_val_ag.drop(columns=[c for c in report_cols if c in X_val_ag.columns])
        assert_feature_columns(sub_tr_ag)
        assert_feature_columns(sub_val_ag)

        ablated_detector = AgentAnomalyDetector(config=self.config, random_state=self.random_state)
        ablated_detector.fit(sub_tr_ag)

        ablated_scores, _ = ablated_detector.score_combined(sub_val_ag)
        ablated_sorted_idx = sorted(
            range(len(y_val_arr)),
            key=lambda i: (-ablated_scores[i], val_ag_ids[i]),
        )
        ablated_top_k = ablated_sorted_idx[:k_val]
        ablated_prec_k = float(y_val_arr[ablated_top_k].sum()) / float(k_val) if k_val > 0 else 0.0
        ablated_flagged = (ablated_scores >= self.agent_risk_high).astype(int)
        ablated_recall = (
            float((ablated_flagged & y_val_arr).sum()) / float(total_skimmers)
            if total_skimmers > 0
            else 0.0
        )

        agent_ablation = {
            "full_detector_with_cash_gap": {
                "features_count": len(X_tr_ag.columns),
                "precision_at_k": full_prec_k,
                "recall_on_skimmers": full_recall,
            },
            "no_cash_gap_signal": {
                "features_dropped_count": len(report_cols),
                "dropped_columns": report_cols,
                "precision_at_k": ablated_prec_k,
                "recall_on_skimmers": ablated_recall,
                "delta_precision_at_k": ablated_prec_k - full_prec_k,
                "delta_recall_on_skimmers": ablated_recall - full_recall,
            },
        }

        return {
            "assisted_classifier_ablation": assisted_ablation,
            "agent_detector_ablation": agent_ablation,
        }

    def run_experiment_5_adoption_sensitivity(
        self,
        test_obs_data: dict[str, Any] | None = None,
        test_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Experiment 5: Adoption sensitivity and loss prevented.

        Restricted strictly to assisted simulated behavior users under perfect compliance.
        Uses exact Decimal cents arithmetic.
        """
        if test_obs_data is None:
            test_obs_data = self.load_observations("test")
        if test_data is None:
            test_data = self.load_split("test")

        txn_obs = test_obs_data.get("transaction_observations", {})
        user_obs = test_obs_data.get("user_observations", {})

        # is_assisted_behavior is authoritative, never OR group_label
        assisted_uids: set[str] = {
            uid for uid, meta in user_obs.items() if bool(meta.get("is_assisted_behavior"))
        }

        total_skimming_loss = Decimal("0.00")
        total_fee_overcharge = Decimal("0.00")
        total_payout_reduction = Decimal("0.00")
        total_skimmer_actions = 0

        eligible_assisted_loss = Decimal("0.00")
        eligible_assisted_skimmer_actions = 0

        # Total cashouts by assisted behavior users
        total_eligible_assisted_cashouts = sum(
            1
            for t in test_data.get("transactions", [])
            if t.get("user_id") in assisted_uids and t.get("txn_type") == "cash_out"
        )

        for _, o in txn_obs.items():
            if not isinstance(o, dict) or "txn_id" not in o or "user_id" not in o:
                continue
            if o.get("is_skimmer_action"):
                fo = Decimal(str(o.get("fee_overcharge", 0.0))).quantize(Decimal("0.01"))
                pr = Decimal(str(o.get("payout_reduction", 0.0))).quantize(Decimal("0.01"))
                action_loss = fo + pr

                # Require positive injected cashout losses
                if action_loss > Decimal("0.00"):
                    total_skimmer_actions += 1
                    total_fee_overcharge += fo
                    total_payout_reduction += pr
                    total_skimming_loss += action_loss

                    if o.get("user_id") in assisted_uids:
                        eligible_assisted_skimmer_actions += 1
                        eligible_assisted_loss += action_loss

        scenarios: dict[str, Any] = {}
        for r_float in (0.30, 0.50, 0.70):
            r = Decimal(str(r_float))
            pct = int(round(r_float * 100))
            prevented = (eligible_assisted_loss * r).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            pct_total = (
                ((prevented / total_skimming_loss) * Decimal("100")).quantize(Decimal("0.01"))
                if total_skimming_loss > Decimal("0.00")
                else Decimal("0.00")
            )
            scenarios[f"adoption_{pct}pct"] = {
                "adoption_rate": r_float,
                "loss_prevented_bdt": float(prevented),
                "pct_eligible_assisted_loss_prevented": pct,
                "pct_total_injected_loss_prevented": float(pct_total),
            }

        return {
            "disclaimer": (
                "Idealized simulation assumption: counterfactual cashouts restricted to "
                "assisted simulated behavior users under hypothetical perfect mandate compliance. "
                "No claim of observed field impact."
            ),
            "total_test_skimmer_actions": total_skimmer_actions,
            "total_test_fee_overcharge_bdt": float(total_fee_overcharge),
            "total_test_payout_reduction_bdt": float(total_payout_reduction),
            "total_injected_skimming_loss_bdt": float(total_skimming_loss),
            "total_eligible_assisted_cashouts": total_eligible_assisted_cashouts,
            "eligible_assisted_skimmer_actions": eligible_assisted_skimmer_actions,
            "eligible_assisted_skimming_loss_bdt": float(eligible_assisted_loss),
            "scenarios": scenarios,
        }

    def run_experiment_6_distribution_shift(
        self,
        assisted_clf: AssistedUserClassifier,
        agent_detector: AgentAnomalyDetector,
        test_data: dict[str, Any] | None = None,
        test_shifted_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Experiment 6: Robustness under distribution shift (canonical vs shifted test)."""
        if test_data is None:
            test_data = self.load_split("test")
        if test_shifted_data is None:
            test_shifted_data = self.load_split("test_shifted")

        test_obs = self.load_observations("test")
        shifted_obs = self.load_observations("test_shifted")

        # 1. User models and rule baseline under shift
        X_test_u, y_test_u, _, _ = extract_user_features(
            test_data["users"],
            test_data["transactions"],
            test_data["sessions"],
            as_of=self.as_of_iso,
            window_days=self.features_window_days,
            config=self.config,
        )
        X_shift_u, y_shift_u, _, _ = extract_user_features(
            test_shifted_data["users"],
            test_shifted_data["transactions"],
            test_shifted_data["sessions"],
            as_of=self.as_of_iso,
            window_days=self.features_window_days,
            config=self.config,
        )

        user_rule_baseline = AssistedUserRuleBaseline(config=self.config)

        def _evaluate_user_cohort(X_df: pd.DataFrame, y_ser: pd.Series) -> dict[str, Any]:
            y_arr = y_ser.to_numpy(dtype=int)
            positives = int(y_arr.sum())
            total = len(y_arr)

            # Rule baseline evaluation
            r_preds = user_rule_baseline.predict(X_df)
            r_tp = int(((r_preds == 1) & (y_arr == 1)).sum())
            r_fp = int(((r_preds == 1) & (y_arr == 0)).sum())
            r_prec = (
                float(r_tp / (r_tp + r_fp)) if (r_tp + r_fp) > 0 else (None if total == 0 else 0.0)
            )
            r_rec = float(r_tp / positives) if positives > 0 else None
            # Baseline actual operating recall remains valid when precision >= 0.80
            r_op_valid = bool(r_prec is not None and r_prec >= 0.80)
            r_op_rec = r_rec if r_op_valid else None

            # Model evaluation with null handling for one-class/empty
            probs = assisted_clf.predict_proba(X_df)[:, 1]
            preds = (probs >= self.classification_threshold).astype(int)
            m_tp = int(((preds == 1) & (y_arr == 1)).sum())
            m_fp = int(((preds == 1) & (y_arr == 0)).sum())
            m_prec = (
                float(m_tp / (m_tp + m_fp)) if (m_tp + m_fp) > 0 else (None if total == 0 else 0.0)
            )
            m_rec = float(m_tp / positives) if positives > 0 else None

            if len(np.unique(y_arr)) < 2:
                pr_auc = None
                roc_auc = None
                brier = None
                rec_80 = None
            else:
                p, r, _ = precision_recall_curve(y_arr, probs)
                pr_auc = float(auc(r, p))
                roc_auc = float(roc_auc_score(y_arr, probs))
                brier = float(brier_score_loss(y_arr, probs))
                rec_80 = _compute_max_attainable_recall_at_80p(y_arr, probs)

            return {
                "rule_baseline": {
                    "precision": r_prec,
                    "recall": r_rec,
                    "operating_recall_valid": r_op_valid,
                    "operating_recall": r_op_rec,
                },
                "assisted_classifier": {
                    "pr_auc": pr_auc,
                    "roc_auc": roc_auc,
                    "brier_score": brier,
                    "recall_at_80p_precision": rec_80,
                    "precision_at_threshold": m_prec,
                    "recall_at_threshold": m_rec,
                    "classification_threshold": self.classification_threshold,
                },
            }

        canon_u = _evaluate_user_cohort(X_test_u, y_test_u)
        shift_u = _evaluate_user_cohort(X_shift_u, y_shift_u)

        clf_c = canon_u["assisted_classifier"]
        clf_s = shift_u["assisted_classifier"]
        delta_pr = (
            clf_s["pr_auc"] - clf_c["pr_auc"]
            if (clf_s["pr_auc"] is not None and clf_c["pr_auc"] is not None)
            else None
        )

        # 2. Agent models and rule baseline under shift
        X_test_ag, y_test_ag, meta_test_ag, test_ag_ids = extract_agent_features(
            test_data["agents"],
            test_data["transactions"],
            config=self.config,
            reports_data=test_obs,
            include_cash_reports=True,
        )
        X_shift_ag, y_shift_ag, meta_shift_ag, shift_ag_ids = extract_agent_features(
            test_shifted_data["agents"],
            test_shifted_data["transactions"],
            config=self.config,
            reports_data=shifted_obs,
            include_cash_reports=True,
        )

        agent_rule_baseline = AgentAnomalyRuleBaseline(config=self.config)

        def _evaluate_agent_shift_cohort(
            X_df: pd.DataFrame, y_ser: pd.Series, meta_df: pd.DataFrame, aids: list[str]
        ) -> dict[str, Any]:
            y_arr = y_ser.to_numpy(dtype=int)
            total = len(y_arr)
            total_skimmers = int(y_arr.sum())
            k = min(self.agent_review_top_k, total)

            types_arr = meta_df["agent_type"].to_numpy()
            hv_indices = np.where(types_arr == "high_volume_honest")[0]
            total_hv = len(hv_indices)

            # Rule baseline
            r_preds = agent_rule_baseline.predict(X_df)
            r_scores = agent_rule_baseline.score(X_df)
            r_sorted = sorted(range(total), key=lambda i: (-r_scores[i], aids[i]))
            r_top_k = r_sorted[:k]
            r_prec_k = float(y_arr[r_top_k].sum()) / float(k) if k > 0 else 0.0
            r_rec = (
                float((r_preds & y_arr).sum()) / float(total_skimmers)
                if total_skimmers > 0
                else None
            )
            r_ff_hv = float(r_preds[hv_indices].sum()) / float(total_hv) if total_hv > 0 else None

            # Detector methods
            z_risk, _ = agent_detector.score_peer_robust_zscore(X_df)
            if_risk = agent_detector.score_isolation_forest(X_df)
            comb_risk, _ = agent_detector.score_combined(X_df)

            def _method_calc(scores: np.ndarray, label: str) -> dict[str, Any]:
                sorted_idx = sorted(range(total), key=lambda i: (-scores[i], aids[i]))
                top_k = sorted_idx[:k]
                p_k = float(y_arr[top_k].sum()) / float(k) if k > 0 else 0.0
                flagged = (scores >= self.agent_risk_high).astype(int)
                rec = (
                    float((flagged & y_arr).sum()) / float(total_skimmers)
                    if total_skimmers > 0
                    else None
                )
                ff_hv = float(flagged[hv_indices].sum()) / float(total_hv) if total_hv > 0 else None
                return {
                    "method": label,
                    "precision_at_k": p_k,
                    "recall_on_skimmers": rec,
                    "flagged_count": int(flagged.sum()),
                    "false_flag_rate_honest_high_volume": ff_hv,
                }

            return {
                "denominators": {
                    "total_agents": total,
                    "total_skimmers": total_skimmers,
                    "total_honest_high_volume": total_hv,
                    "review_top_k_clipped": k,
                },
                "baseline_rule": {
                    "precision_at_k": r_prec_k,
                    "recall_on_skimmers": r_rec,
                    "flagged_count": int(r_preds.sum()),
                    "false_flag_rate_honest_high_volume": r_ff_hv,
                },
                "peer_robust_zscore": _method_calc(z_risk, "peer_robust_zscore"),
                "isolation_forest": _method_calc(if_risk, "isolation_forest"),
                "combined_ensemble": _method_calc(comb_risk, "combined_ensemble"),
            }

        canon_ag = _evaluate_agent_shift_cohort(X_test_ag, y_test_ag, meta_test_ag, test_ag_ids)
        shift_ag = _evaluate_agent_shift_cohort(X_shift_ag, y_shift_ag, meta_shift_ag, shift_ag_ids)

        comb_c = canon_ag["combined_ensemble"]
        comb_s = shift_ag["combined_ensemble"]
        delta_ag_rec = (
            comb_s["recall_on_skimmers"] - comb_c["recall_on_skimmers"]
            if (
                comb_s["recall_on_skimmers"] is not None
                and comb_c["recall_on_skimmers"] is not None
            )
            else None
        )

        return {
            "assisted_classifier": {
                "canonical_test": canon_u["assisted_classifier"],
                "shifted_test": shift_u["assisted_classifier"],
                "rule_baseline_canonical": canon_u["rule_baseline"],
                "rule_baseline_shifted": shift_u["rule_baseline"],
                "measured_delta_pr_auc": delta_pr,
            },
            "agent_detector": {
                "canonical_test": canon_ag,
                "shifted_test": shift_ag,
                "delta_combined_recall_on_skimmers": delta_ag_rec,
            },
        }

    def run_fairness_evaluation(
        self,
        assisted_clf: AssistedUserClassifier,
        val_data: dict[str, Any] | None = None,
        test_data: dict[str, Any] | None = None,
        test_shifted_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fairness audit across validation diagnostic, held-out, and shifted test cohorts."""
        if val_data is None:
            val_data = self.load_split("validation")
        if test_data is None:
            test_data = self.load_split("test")
        if test_shifted_data is None:
            test_shifted_data = self.load_split("test_shifted")

        fairness_cfg = self.config.get("fairness")
        if not isinstance(fairness_cfg, dict):
            raise ConfigError("Missing 'fairness' section in configuration.")

        if "slices" not in fairness_cfg:
            raise ConfigError("fairness.slices is required in config.")
        slice_cols = fairness_cfg["slices"]

        if "max_tpr_gap" not in fairness_cfg:
            raise ConfigError("fairness.max_tpr_gap is required in config.")
        target_max_gap = float(fairness_cfg["max_tpr_gap"])

        configured_categories = fairness_cfg.get("slice_categories", {})
        rule_baseline = AssistedUserRuleBaseline(config=self.config)

        def _audit_cohort_fairness(c_data: dict[str, Any], cohort_label: str) -> dict[str, Any]:
            X_df, y_ser, slices_df, _ = extract_user_features(
                c_data["users"],
                c_data["transactions"],
                c_data["sessions"],
                as_of=self.as_of_iso,
                window_days=self.features_window_days,
                config=self.config,
            )
            y_arr = y_ser.to_numpy(dtype=int)
            probs = assisted_clf.predict_proba(X_df)[:, 1]
            m_preds = (probs >= self.classification_threshold).astype(int)
            r_preds = rule_baseline.predict(X_df)

            slice_metrics: dict[str, Any] = {}
            max_tpr_gaps: dict[str, float | None] = {}
            unmet_targets: list[dict[str, Any]] = []

            for slice_col in slice_cols:
                slice_metrics[slice_col] = {}
                valid_m_tprs: list[float] = []
                valid_r_tprs: list[float] = []

                # Include all configured categories even if empty in cohort
                cat_list = list(configured_categories.get(slice_col, []))
                if slice_col in slices_df.columns:
                    for actual_val in slices_df[slice_col].unique():
                        if actual_val not in cat_list:
                            cat_list.append(actual_val)

                for cat_val in cat_list:
                    if slice_col in slices_df.columns:
                        mask = (slices_df[slice_col] == cat_val).to_numpy()
                    else:
                        mask = np.zeros(len(y_arr), dtype=bool)

                    sub_y = y_arr[mask]
                    sub_m = m_preds[mask]
                    sub_r = r_preds[mask]
                    n = len(sub_y)
                    positives = int(sub_y.sum())
                    negatives = n - positives

                    # Unavailable (null) if empty or single class (no positives or no negatives)
                    m_tpr = (
                        float((sub_m[sub_y == 1] == 1).sum()) / float(positives)
                        if positives > 0
                        else None
                    )
                    m_fpr = (
                        float((sub_m[sub_y == 0] == 1).sum()) / float(negatives)
                        if negatives > 0
                        else None
                    )
                    m_rev = float(sub_m.sum()) / float(n) if n > 0 else None

                    r_tpr = (
                        float((sub_r[sub_y == 1] == 1).sum()) / float(positives)
                        if positives > 0
                        else None
                    )
                    r_fpr = (
                        float((sub_r[sub_y == 0] == 1).sum()) / float(negatives)
                        if negatives > 0
                        else None
                    )

                    if m_tpr is not None:
                        valid_m_tprs.append(m_tpr)
                    if r_tpr is not None:
                        valid_r_tprs.append(r_tpr)

                    slice_metrics[slice_col][str(cat_val)] = {
                        "count": n,
                        "positives": positives,
                        "negatives": negatives,
                        "model": {
                            "tpr": m_tpr,
                            "fpr": m_fpr,
                            "review_rate": m_rev,
                        },
                        "rule_baseline": {
                            "tpr": r_tpr,
                            "fpr": r_fpr,
                        },
                        # Top-level keys for backwards compatibility
                        "tpr": m_tpr,
                        "fpr": m_fpr,
                        "review_rate": m_rev,
                    }

                # Do not turn insufficient coverage into pass
                if len(valid_m_tprs) >= 2:
                    gap = float(max(valid_m_tprs) - min(valid_m_tprs))
                    max_tpr_gaps[slice_col] = gap
                    if gap > target_max_gap:
                        unmet_targets.append(
                            {
                                "slice": slice_col,
                                "observed_gap": gap,
                                "target_max_gap": target_max_gap,
                                "proposed_mitigation": (
                                    f"Audit behavioral feature representation and training data "
                                    f"sampling balance for {slice_col}; preserve demographics "
                                    "as evaluation-only; no group-specific inference thresholds."
                                ),
                            }
                        )
                else:
                    max_tpr_gaps[slice_col] = None

            defined_gaps = list(max_tpr_gaps.values())
            global_max_gap = (
                max(defined_gaps)
                if (
                    len(defined_gaps) == len(slice_cols)
                    and all(g is not None for g in defined_gaps)
                )
                else None
            )

            return {
                "cohort": cohort_label,
                "slices": slice_metrics,
                "max_tpr_gaps": max_tpr_gaps,
                "global_max_tpr_gap": global_max_gap,
                "target_max_tpr_gap": target_max_gap,
                "satisfies_fairness_target": (
                    (global_max_gap <= target_max_gap) if global_max_gap is not None else None
                ),
                "unmet_targets": unmet_targets,
            }

        val_fairness = _audit_cohort_fairness(val_data, "validation_diagnostic")
        test_fairness = _audit_cohort_fairness(test_data, "held_out_canonical")
        shift_fairness = _audit_cohort_fairness(test_shifted_data, "held_out_shifted")

        return {
            "validation_diagnostic": val_fairness,
            "held_out_canonical": test_fairness,
            "held_out_shifted": shift_fairness,
            # Top-level convenience keys preserving backwards compatibility
            "slices": val_fairness["slices"],
            "max_tpr_gaps": val_fairness["max_tpr_gaps"],
            "global_max_tpr_gap": val_fairness["global_max_tpr_gap"],
            "target_max_tpr_gap": target_max_gap,
            "satisfies_fairness_target": val_fairness["satisfies_fairness_target"],
            "unmet_targets": val_fairness["unmet_targets"],
        }

    def run_all(self, sample_train_size: int | None = 4000) -> dict[str, Any]:
        """Execute full evaluation suite across all 6 experiments and demographic fairness."""
        assisted_clf, agent_detector = self.fit_canonical_models(
            sample_train_size=sample_train_size
        )

        train_data = self.load_split("train")
        val_data = self.load_split("validation")
        test_data = self.load_split("test")
        test_obs = self.load_observations("test")
        test_shifted = self.load_split("test_shifted")

        exp1 = self.run_experiment_1_assisted_detection(
            assisted_clf=assisted_clf,
            train_data=train_data,
            val_data=val_data,
            test_data=test_data,
            sample_train_size=sample_train_size,
        )
        exp2 = self.run_experiment_2_agent_anomaly(
            agent_detector=agent_detector,
            val_data=val_data,
            test_data=test_data,
        )
        exp3 = self.run_experiment_3_skimming_sweep(agent_detector=agent_detector)
        exp4 = self.run_experiment_4_signal_ablations(
            assisted_clf=assisted_clf,
            agent_detector=agent_detector,
            train_data=train_data,
            val_data=val_data,
            sample_train_size=sample_train_size,
        )
        exp5 = self.run_experiment_5_adoption_sensitivity(
            test_obs_data=test_obs,
            test_data=test_data,
        )
        exp6 = self.run_experiment_6_distribution_shift(
            assisted_clf=assisted_clf,
            agent_detector=agent_detector,
            test_data=test_data,
            test_shifted_data=test_shifted,
        )
        fairness = self.run_fairness_evaluation(
            assisted_clf=assisted_clf,
            val_data=val_data,
            test_data=test_data,
            test_shifted_data=test_shifted,
        )

        raw_results = {
            "schema_version": 1,
            "synthetic": True,
            "final_run_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "experiment_1_assisted_detection": exp1,
            "experiment_2_agent_anomaly": exp2,
            "experiment_3_skimming_sweep": exp3,
            "experiment_4_signal_ablations": exp4,
            "experiment_5_adoption_sensitivity": exp5,
            "experiment_6_distribution_shift": exp6,
            "fairness_evaluation": fairness,
        }

        return _sanitize_for_json(raw_results)

    def generate_markdown_report(self, results: dict[str, Any]) -> str:
        """Format full results into GitHub-flavored Markdown tables with rounded display."""
        exp1 = results["experiment_1_assisted_detection"]
        exp2 = results["experiment_2_agent_anomaly"]
        exp3 = results["experiment_3_skimming_sweep"]
        exp4 = results["experiment_4_signal_ablations"]
        exp5 = results["experiment_5_adoption_sensitivity"]
        exp6 = results["experiment_6_distribution_shift"]
        fairness = results["fairness_evaluation"]

        def _row(*cells: Any) -> str:
            return "| " + " | ".join(str(c) for c in cells) + " |"

        md = [
            "# Sathi Evaluation & Experimentation Results",
            "",
            "> [!NOTE]",
            "> All evaluations use synthetic MFS simulation data generated with disjoint cohorts",
            "> per `docs/evaluation-plan.md` (Train Seed 42, Val Seed 4242, Test Seed 2026).",
            "> Zero protected demographic features or ground truth labels were included in models.",
            "",
            "## 1. Assisted-User Classifier vs Rule Baseline",
            "",
            f"> PR-AUC metric convention: `{exp1.get('pr_auc_convention')}`.",
            "",
            _row(
                "Cohort / Split",
                "Model",
                "PR-AUC",
                "ROC-AUC",
                "Brier Calibration",
                "Recall @ 80% Prec",
            ),
            _row("---", "---", "---", "---", "---", "---"),
        ]

        v_diag = exp1["validation_diagnostic"]
        b_val = v_diag["rule_baseline"]
        m_val = v_diag["assisted_classifier"]
        md.append(
            _row(
                "Validation (Diagnostic)",
                "Rule Baseline",
                f"{b_val['pr_auc']:.4f}",
                f"{b_val['roc_auc']:.4f}",
                f"{b_val['brier_score']:.4f}",
                f"{b_val['recall_at_80p_precision']:.4f}",
            )
        )
        md.append(
            _row(
                "Validation (Diagnostic)*",
                "Sathi LightGBM",
                f"{m_val['pr_auc']:.4f}",
                f"{m_val['roc_auc']:.4f}",
                f"{m_val['brier_score']:.4f}",
                f"{m_val['recall_at_80p_precision']:.4f}",
            )
        )

        t_held = exp1["held_out_test"]
        b_test = t_held["rule_baseline"]
        m_test = t_held["assisted_classifier"]
        md.append(
            _row(
                "**Held-out Test (2026)**",
                "Rule Baseline",
                f"{b_test['pr_auc']:.4f}",
                f"{b_test['roc_auc']:.4f}",
                f"{b_test['brier_score']:.4f}",
                f"{b_test['recall_at_80p_precision']:.4f}",
            )
        )
        md.append(
            _row(
                "**Held-out Test (2026)**",
                "**Sathi LightGBM (Held-out)**",
                f"**{m_test['pr_auc']:.4f}**",
                f"**{m_test['roc_auc']:.4f}**",
                f"**{m_test['brier_score']:.4f}**",
                f"**{m_test['recall_at_80p_precision']:.4f}**",
            )
        )
        md.append("")
        md.append(
            "_*Validation metrics are calibration-cohort diagnostics and do not represent "
            "independent calibrated generalization; test cohort is held-out estimate._"
        )
        md.append("")

        md.append("### Noise Sensitivity Comparison:")
        md.append(_row("Configuration", "Label Noise Level", "PR-AUC", "Recall @ 80% Prec"))
        md.append(_row("---", "---", "---", "---"))
        nc = exp1["noise_comparison"]
        for _, n_info in nc.items():
            md.append(
                _row(
                    n_info["noise_description"],
                    "Baseline 10%" if "10%" in n_info["noise_description"] else "Perturbed",
                    f"{n_info['pr_auc']:.4f}",
                    f"{n_info['recall_at_80p_precision']:.4f}",
                )
            )
        md.append("")

        md.append("## 2. Agent Anomaly Detection: Ensemble & Baseline Comparison")
        md.append("")
        t_ag = exp2["held_out_test"]
        k_val = t_ag["review_top_k_clipped"]
        md.append(
            _row(
                "Method",
                f"Precision@{k_val}",
                "Recall on Skimmers",
                "Honest High-Volume False Flags",
            )
        )
        md.append(_row("---", "---", "---", "---"))
        b_ag = t_ag["baseline_rule"]
        z_ag = t_ag["peer_robust_zscore"]
        if_ag = t_ag["isolation_forest"]
        c_ag = t_ag["combined_ensemble"]
        md.append(
            _row(
                "Rule Baseline",
                f"{b_ag['precision_at_k']:.2f}",
                f"{b_ag['recall_on_skimmers']:.2f}",
                f"{b_ag['false_flag_rate_honest_high_volume']:.2f}"
                if b_ag["false_flag_rate_honest_high_volume"] is not None
                else "N/A",
            )
        )
        md.append(
            _row(
                "Peer Robust Z-Score",
                f"{z_ag['precision_at_k']:.2f}",
                f"{z_ag['recall_on_skimmers']:.2f}",
                f"{z_ag['false_flag_rate_honest_high_volume']:.2f}"
                if z_ag["false_flag_rate_honest_high_volume"] is not None
                else "N/A",
            )
        )
        md.append(
            _row(
                "Isolation Forest",
                f"{if_ag['precision_at_k']:.2f}",
                f"{if_ag['recall_on_skimmers']:.2f}",
                f"{if_ag['false_flag_rate_honest_high_volume']:.2f}"
                if if_ag["false_flag_rate_honest_high_volume"] is not None
                else "N/A",
            )
        )
        md.append(
            _row(
                "**Combined Ensemble (0.7 Z + 0.3 IF)**",
                f"**{c_ag['precision_at_k']:.2f}**",
                f"**{c_ag['recall_on_skimmers']:.2f}**",
                f"**{c_ag['false_flag_rate_honest_high_volume']:.2f}**"
                if c_ag["false_flag_rate_honest_high_volume"] is not None
                else "N/A",
            )
        )
        md.append("")

        md.append("## 3. Skimming Intensity Sweep")
        md.append("")
        md.append(
            _row(
                "Intensity",
                "Skimmer Mean Risk",
                "Honest Mean Risk",
                "Skimmer Detection Rate",
                "Honest False Flag Rate",
            )
        )
        md.append(_row("---", "---", "---", "---", "---"))
        for tier_name, t_val in exp3.items():
            md.append(
                _row(
                    tier_name.capitalize(),
                    f"{t_val['skimmer_mean_risk_score']:.3f}",
                    f"{t_val['honest_mean_risk_score']:.3f}",
                    f"{t_val['skimmer_detection_rate'] * 100:.1f}%",
                    f"{t_val['honest_false_flag_rate'] * 100:.1f}%",
                )
            )
        md.append("")

        md.append("## 4. Signal Ablations")
        md.append("")
        md.append("### Assisted Classifier Session Signals Ablation:")
        u_abl = exp4["assisted_classifier_ablation"]
        md.append(_row("Configuration", "Features Dropped", "PR-AUC", "Delta vs Full"))
        md.append(_row("---", "---", "---", "---"))
        full_u_auc = u_abl["full_model"]["pr_auc"]
        md.append(_row("Full Behavioral Model", "0", f"{full_u_auc:.4f}", "0.0000"))
        ns = u_abl["no_session_signals"]
        sign = "+" if ns["delta_pr_auc"] > 0 else ""
        md.append(
            _row(
                "No Session Signals",
                f"{ns['features_dropped_count']} dropped",
                f"{ns['pr_auc']:.4f}",
                f"{sign}{ns['delta_pr_auc']:.4f}",
            )
        )
        md.append("")

        md.append("### Agent Detector Cash-Report Ablation:")
        ag_abl = exp4["agent_detector_ablation"]
        md.append(_row("Configuration", "Precision@K", "Recall on Skimmers"))
        md.append(_row("---", "---", "---"))
        full_ag = ag_abl["full_detector_with_cash_gap"]
        no_gap = ag_abl["no_cash_gap_signal"]
        md.append(
            _row(
                "Full Detector (with Cash Gap)",
                f"{full_ag['precision_at_k']:.2f}",
                f"{full_ag['recall_on_skimmers']:.2f}",
            )
        )
        md.append(
            _row(
                "Ablated Detector (no Cash Gap)",
                f"{no_gap['precision_at_k']:.2f}",
                f"{no_gap['recall_on_skimmers']:.2f}",
            )
        )
        md.append("")

        tot_loss = exp5["total_injected_skimming_loss_bdt"]
        elig_loss = exp5["eligible_assisted_skimming_loss_bdt"]
        md.append("## 5. Adoption Sensitivity & Simulated Loss Prevented")
        md.append("")
        md.append(f"> {exp5.get('disclaimer')}")
        md.append("")
        md.append(f"- Total injected test skimming loss: **{tot_loss:,.2f} BDT**.")
        md.append(f"- Eligible assisted behavior customer loss: **{elig_loss:,.2f} BDT**.")
        md.append("")
        md.append(
            _row(
                "Adoption Assumption",
                "Loss Prevented (BDT)",
                "% Eligible Prevented",
                "% Total Injected Prevented",
            )
        )
        md.append(_row("---", "---", "---", "---"))
        for _, s_val in exp5["scenarios"].items():
            md.append(
                _row(
                    f"{s_val['adoption_rate'] * 100:.0f}% Adoption",
                    f"{s_val['loss_prevented_bdt']:,.2f} BDT",
                    f"{s_val['pct_eligible_assisted_loss_prevented']}%",
                    f"{s_val['pct_total_injected_loss_prevented']:.1f}%",
                )
            )
        md.append("")

        md.append("## 6. Distribution Shift Robustness")
        md.append("")

        def _format_metric(value: Any) -> str:
            return "null" if value is None else f"{value:.4f}"

        md.append(_row("Cohort", "Method", "Precision", "Recall", "PR-AUC", "Brier"))
        md.append(_row(*(["---"] * 6)))
        shifted_users = exp6["assisted_classifier"]
        for cohort, model_key, rule_key in (
            ("Canonical test (seed2026)", "canonical_test", "rule_baseline_canonical"),
            (
                "Shifted test (seed2026, separate distribution)",
                "shifted_test",
                "rule_baseline_shifted",
            ),
        ):
            rule = shifted_users[rule_key]
            model = shifted_users[model_key]
            md.append(
                _row(
                    cohort,
                    "Rule baseline",
                    _format_metric(rule["precision"]),
                    _format_metric(rule["recall"]),
                    "not defined",
                    "not defined",
                )
            )
            md.append(
                _row(
                    cohort,
                    "LightGBM",
                    _format_metric(model["precision_at_threshold"]),
                    _format_metric(model["recall_at_threshold"]),
                    _format_metric(model["pr_auc"]),
                    _format_metric(model["brier_score"]),
                )
            )
        md.append("")
        md.append(
            _row(
                "Agent cohort",
                "Method",
                "n",
                "Skimmers",
                "Honest high volume",
                "Top-K",
                "Precision@K",
                "Recall",
                "Honest HV false flags",
            )
        )
        md.append(_row(*(["---"] * 9)))
        for cohort in ("canonical_test", "shifted_test"):
            cohort_results = exp6["agent_detector"][cohort]
            denoms = cohort_results["denominators"]
            for method in (
                "baseline_rule",
                "peer_robust_zscore",
                "isolation_forest",
                "combined_ensemble",
            ):
                metrics = cohort_results[method]
                md.append(
                    _row(
                        cohort,
                        method,
                        denoms["total_agents"],
                        denoms["total_skimmers"],
                        denoms["total_honest_high_volume"],
                        denoms["review_top_k_clipped"],
                        _format_metric(metrics["precision_at_k"]),
                        _format_metric(metrics["recall_on_skimmers"]),
                        _format_metric(metrics["false_flag_rate_honest_high_volume"]),
                    )
                )
        md.append("")

        md.append("## 7. Demographic Fairness Audit")
        md.append("")
        for cohort in ("validation_diagnostic", "held_out_canonical", "held_out_shifted"):
            audit = fairness[cohort]
            md.extend([f"### {cohort}", ""])
            md.append(
                "Validation is a calibration diagnostic; test cohorts are held-out estimates."
            )
            md.append(f"Configured TPR gap target: {audit['target_max_tpr_gap']:.4f}.")
            md.append(
                f"Maximum gap: {audit['global_max_tpr_gap']}; "
                f"target status: {audit['satisfies_fairness_target']}."
            )
            md.append("")
            md.append(
                _row("Slice", "Category", "n", "Positive", "Negative", "Method", "TPR", "FPR")
            )
            md.append(_row(*(["---"] * 8)))
            for column, categories in audit["slices"].items():
                for category, metrics in categories.items():
                    for method in ("rule_baseline", "model"):
                        rates = metrics[method]

                        def fmt(value):
                            return "null" if value is None else f"{value:.4f}"

                        md.append(
                            _row(
                                column,
                                category,
                                metrics["count"],
                                metrics["positives"],
                                metrics["negatives"],
                                method,
                                fmt(rates["tpr"]),
                                fmt(rates["fpr"]),
                            )
                        )
            for miss in audit["unmet_targets"]:
                md.append(
                    f"Unmet {miss['slice']}: {miss['observed_gap']:.4f}; "
                    f"{miss['proposed_mitigation']}"
                )
            md.append("")

        return "\n".join(md)

    def save_evaluation_run(
        self,
        output_dir: str | Path,
        results: dict[str, Any],
    ) -> Path:
        """Serialize full evaluation artifacts, manifest, and bundle to output directory."""
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        if self.fitted_assisted_clf is None or self.fitted_agent_detector is None:
            raise RuntimeError("Models must be fitted before saving evaluation run.")

        # 1. results.json
        results_clean = _sanitize_for_json(results)
        results_bytes = json.dumps(results_clean, indent=2, sort_keys=True).encode("utf-8")
        (out_path / "results.json").write_bytes(results_bytes)

        # 2. generated-report.md
        report_md = self.generate_markdown_report(results_clean)
        (out_path / "generated-report.md").write_text(report_md, encoding="utf-8")

        # 3. Model joblib artifacts
        assisted_joblib_path = out_path / "assisted.joblib"
        agent_joblib_path = out_path / "agent.joblib"
        self.fitted_assisted_clf.save(assisted_joblib_path)
        self.fitted_agent_detector.save(agent_joblib_path)

        # 4. Manifest.json
        assisted_sha = hashlib.sha256(assisted_joblib_path.read_bytes()).hexdigest()
        agent_sha = hashlib.sha256(agent_joblib_path.read_bytes()).hexdigest()

        cfg_bytes = json.dumps(self.config, sort_keys=True, separators=(",", ":")).encode("utf-8")
        config_sha = hashlib.sha256(cfg_bytes).hexdigest()

        split_manifest = self.split_artifacts["manifest"]
        sim_cfg = self.config["simulation"]

        train_users_sampled = (
            self.sampled_train_users
            if self.sampled_train_users is not None
            else self.load_split("train")["users"]
        )
        sampled_uids = sorted(u["user_id"] for u in train_users_sampled)
        uids_sha = hashlib.sha256(",".join(sampled_uids).encode("utf-8")).hexdigest()

        tree_sha, is_dirty = _compute_source_tree_hash()

        # Gather hashes of ALL data and observation files
        data_hashes: dict[str, Any] = {}
        for c_k in ("train", "validation", "test"):
            if c_k in split_manifest.get("cohorts", {}):
                data_hashes[c_k] = {
                    "file": split_manifest["cohorts"][c_k]["file"],
                    "content_sha256": split_manifest["cohorts"][c_k]["content_sha256"],
                    "observations_file": split_manifest["cohorts"][c_k]["observations_file"],
                    "observations_sha256": split_manifest["cohorts"][c_k]["observations_sha256"],
                }
        shifted_m = self.split_artifacts["shifted_meta"]
        shifted_obs_f = shifted_m.get("observations_file", "test_shifted.observations.json")
        data_hashes["test_shifted"] = {
            "file": shifted_m.get("file", "test_shifted.json"),
            "content_sha256": shifted_m.get("content_sha256"),
            "observations_file": shifted_obs_f,
            "observations_sha256": shifted_m.get("observations_sha256"),
        }

        # Files manifest
        files_map = {
            "results.json": {
                "size_bytes": len(results_bytes),
                "sha256": hashlib.sha256(results_bytes).hexdigest(),
            },
            "generated-report.md": {
                "size_bytes": len(report_md.encode("utf-8")),
                "sha256": hashlib.sha256(report_md.encode("utf-8")).hexdigest(),
            },
            "assisted.joblib": {
                "size_bytes": assisted_joblib_path.stat().st_size,
                "sha256": assisted_sha,
            },
            "agent.joblib": {
                "size_bytes": agent_joblib_path.stat().st_size,
                "sha256": agent_sha,
            },
        }

        run_manifest = {
            "schema_version": 1,
            "synthetic": True,
            "artifact_type": "sathi_evaluation_run",
            "final_run_timestamp": results.get("final_run_timestamp"),
            "git_revision": _get_git_revision(),
            "source_tree_sha256": tree_sha,
            "dirty_source_status": is_dirty,
            "config_sha256": config_sha,
            "training_sample": {
                "count": len(sampled_uids),
                "user_ids_sha256": uids_sha,
                "seed": sim_cfg["seed_train"],
            },
            "seeds": {
                "train": sim_cfg["seed_train"],
                "validation": sim_cfg["seed_validation"],
                "test": sim_cfg["seed_test"],
            },
            "cohorts": split_manifest["cohorts"],
            "data_hashes": data_hashes,
            "features": {
                "assisted_classifier": self.fitted_assisted_clf.feature_names_,
                "agent_anomaly": self.fitted_agent_detector.feature_names_,
            },
            "feature_provenance": {
                "window_days": self.features_window_days,
                "as_of": self.as_of_iso,
                "cutoff": self.cutoff_iso,
                "description": "Synthetic 90-day simulation snapshot; offline windowed extraction.",
            },
            "dependency_versions": _get_dependency_versions(),
            "model_artifacts": {
                "assisted_sha256": assisted_sha,
                "agent_sha256": agent_sha,
            },
            "files": files_map,
        }
        manifest_bytes = json.dumps(run_manifest, indent=2, sort_keys=True).encode("utf-8")
        (out_path / "manifest.json").write_bytes(manifest_bytes)

        # 5. Deployment-sized curated inference snapshot
        test_data = self.load_split("test")
        sample_users = test_data["users"]
        X_sample_u, _, _, u_ids = extract_user_features(
            sample_users,
            test_data["transactions"],
            test_data["sessions"],
            as_of=self.as_of_iso,
            window_days=self.features_window_days,
            config=self.config,
        )
        sample_user_rows: list[dict[str, Any]] = []
        sample_probs = self.fitted_assisted_clf.predict_proba(X_sample_u)[:, 1]
        sample_preds = (sample_probs >= self.classification_threshold).astype(int)

        selected_users = sorted(range(len(u_ids)), key=lambda i: (-sample_probs[i], u_ids[i]))[:20]
        for i in selected_users:
            uid = u_ids[i]
            row_df = X_sample_u.iloc[[i]]
            explanations = self.fitted_assisted_clf.explain(row_df, top_k=4)
            sample_user_rows.append(
                {
                    "user_id": uid,
                    "features": {c: float(row_df[c].iloc[0]) for c in row_df.columns},
                    "predicted_probability": float(sample_probs[i]),
                    "predicted_class": int(sample_preds[i]),
                    "explanations": explanations,
                }
            )

        test_obs = self.load_observations("test")
        sample_agents_raw = test_data["agents"]
        X_sample_ag, _, _, ag_ids = extract_agent_features(
            sample_agents_raw,
            test_data["transactions"],
            config=self.config,
            reports_data=test_obs,
            include_cash_reports=True,
        )
        sample_agent_rows: list[dict[str, Any]] = []
        ag_scores, _ = self.fitted_agent_detector.score_combined(X_sample_ag)

        selected_agents = sorted(range(len(ag_ids)), key=lambda i: (-ag_scores[i], ag_ids[i]))[:10]
        for i in selected_agents:
            aid = ag_ids[i]
            row_df = X_sample_ag.iloc[[i]]
            exp_ag = self.fitted_agent_detector.explain(aid, row_df)
            sample_agent_rows.append(
                {
                    "agent_id": aid,
                    "features": {c: float(row_df[c].iloc[0]) for c in row_df.columns},
                    "risk_score": float(ag_scores[i]),
                    "risk_level": exp_ag["level"],
                    "reasons": exp_ag["reasons"],
                }
            )

        export_deployment_bundle(
            output_dir=out_path,
            assisted_clf=self.fitted_assisted_clf,
            agent_detector=self.fitted_agent_detector,
            results=results_clean,
            manifest=run_manifest,
            sample_customers=sample_user_rows,
            sample_agents=sample_agent_rows,
            as_of=self.as_of_iso,
            window_days=self.features_window_days,
            cutoff=self.cutoff_iso,
        )

        return out_path
