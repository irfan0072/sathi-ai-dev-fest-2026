"""Extended agent benchmark (v2): protocol discipline, independence and counting checks.

A small run (150 agents per replication) exercises the same code as the real 3,000-agent run.
These tests check the guarantees that make the evidence credible, not the scores.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from app.data.config import load_config
from app.evaluation import agent_benchmark as bench

SMALL = 150


@pytest.fixture(scope="module")
def out_dir(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("bench")
    bench.run_dev(path, agents=SMALL, workers=1)
    return path


def test_wilson_interval_basics():
    assert bench.wilson_interval(0, 0) is None
    low, high = bench.wilson_interval(2, 2)
    assert 0.3 < low < 0.4 and high == 1.0                 # 2/2 is not "100% certain"
    low, high = bench.wilson_interval(40, 80)
    assert low < 0.5 < high and high - low < 0.25


def test_derived_config_preserves_prevalence_and_uses_new_seeds():
    base = load_config()
    cfg = bench.derive_config(base, bench.REPLICATION_SEEDS[0], agents=3000)
    mix, sim = cfg["simulation"]["agent_mix"], cfg["simulation"]
    assert sum(mix.values()) == sim["agents"] == 3000
    assert mix["skimmers"] / 3000 == pytest.approx(10 / 300)
    assert mix["high_volume_honest"] / 3000 == pytest.approx(20 / 300)
    assert sim["customers"] / sim["agents"] == pytest.approx(base["simulation"]["customers"] / 300)
    canonical = {base["simulation"][k] for k in ("seed_train", "seed_validation", "seed_test")}
    for replication in bench.REPLICATION_SEEDS:
        seeds = {replication[k] for k in ("seed_train", "seed_validation", "seed_test")}
        assert not seeds & canonical and len(seeds) == 3
    all_seeds = [r[k] for r in bench.REPLICATION_SEEDS
                 for k in ("seed_train", "seed_validation", "seed_test")]
    assert len(set(all_seeds)) == len(all_seeds)           # replications never share a seed
    # The canonical config object is untouched.
    assert base["simulation"]["agents"] == 300 and base["simulation"]["skimming_intensity"] == \
        "moderate"


def test_scenarios_change_only_the_evaluated_cohort_generator_settings():
    cfg = bench.derive_config(load_config(), bench.REPLICATION_SEEDS[0], agents=SMALL)
    shortfall = bench.scenario_config(cfg, "unchanged_fee_shortfall_moderate")
    profile = shortfall["simulation"]["agent_behavior"]["skimmers"]["intensity_profiles"]
    assert profile["moderate"]["fee_multiplier_probability"] == 0.0
    assert profile["moderate"]["payout_reduction_probability"] == 0.20
    assert cfg["simulation"]["agent_behavior"]["skimmers"]["intensity_profiles"]["moderate"][
        "fee_multiplier_probability"] == 0.30             # the source config was not mutated
    assert bench.scenario_config(cfg, "sparse_reports")["simulation"]["customer_report_rate"] == 0.2
    with pytest.raises(ValueError):
        bench.scenario_config(cfg, "made_up")


def test_protocol_is_predeclared_and_immutable(out_dir):
    protocol = json.loads((out_dir / "protocol.json").read_text())
    dev = json.loads((out_dir / "dev_results.json").read_text())
    assert protocol["protocol_sha256"] == dev["protocol_sha256"]
    assert protocol["threshold_tuning"].startswith("none")
    assert "final_results.json" not in {p.name for p in out_dir.iterdir()}   # not generated yet
    # Changing the predeclared protocol in place is refused.
    with pytest.raises(RuntimeError, match="protocol.json already exists"):
        bench.write_protocol(out_dir, SMALL + 30, None)


def test_dev_phase_scores_validation_only_and_cohorts_are_disjoint(out_dir):
    dev = json.loads((out_dir / "dev_results.json").read_text())
    assert dev["phase"] == "development" and "final cohorts not generated" in dev["cohort"]
    for rep in dev["replications"]:
        counts = rep["cohort_agent_counts"]
        assert sum(counts.values()) == SMALL and all(v > 0 for v in counts.values())
    # Independent populations: each replication reports its own denominators.
    skimmers = [r["scenarios"]["moderate"]["ensemble_v1"]["skimmers"] for r in dev["replications"]]
    assert dev["pooled"]["moderate"]["ensemble_v1"]["denominators"]["skimmers"] == sum(skimmers)


def test_candidate_selection_uses_dev_only_and_is_recorded(out_dir):
    decision = json.loads((out_dir / "dev_results.json").read_text())["decision"]
    assert set(decision["checks"]) >= {"recall_gain_ok", "false_flag_ok", "precision_ok"}
    assert decision["selected_method"] in ("ensemble_v1", bench.CANDIDATE["name"])
    assert "validation cohorts only" in decision["note"]


def test_final_phase_needs_dev_scores_once_and_archives_hashes(out_dir, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(RuntimeError, match="Run the development phase first"):
        bench.run_final(empty, agents=SMALL, workers=1)
    final = bench.run_final(out_dir, agents=SMALL, workers=1)
    assert final["phase"] == "final" and set(final["pooled"]) == set(bench.SCENARIOS)
    assert final["dev_results_sha256"] == bench.sha256_file(out_dir / "dev_results.json")
    assert bench.verify_archive(out_dir) == []
    with pytest.raises(RuntimeError, match="scored once"):
        bench.run_final(out_dir, agents=SMALL, workers=1)
    # Tampering is detected.
    (out_dir / "dev_results.json").write_text((out_dir / "dev_results.json").read_text() + " ")
    assert any("dev_results.json" in p for p in bench.verify_archive(out_dir))


def test_denominators_and_policies_are_reported_separately(out_dir):
    final = json.loads((out_dir / "final_results.json").read_text())
    entry = final["pooled"]["moderate"]["ensemble_v1"]
    assert {"threshold_policy", "review_budget_policy", "denominators"} <= set(entry)
    policy = entry["threshold_policy"]
    assert policy["recall_on_skimmers"]["denominator"] == entry["denominators"]["skimmers"]
    assert policy["false_flags_honest_high_volume"]["denominator"] == \
        entry["denominators"]["honest_high_volume"]
    assert set(entry["review_budget_policy"]) == set(bench.REVIEW_BUDGETS)
    assert any("different policies" in line for line in final["limits"])
    assert final["provenance"]["git_revision"] and final["provenance"]["dependencies"]


def test_output_never_goes_to_canonical_or_frozen_directories():
    for forbidden in ("data/generated/evaluation", "data/artifacts/deployment"):
        with pytest.raises(ValueError, match="never writes"):
            bench._check_out_dir(Path(forbidden))


def test_shortfall_scorer_is_support_aware_and_label_free():
    train = pd.DataFrame({"n_reports": [100] * 20, "gap_reports": [1] * 20,
                          "distinct_reporting_customers": [90] * 20,
                          "distinct_gap_customers": [1] * 20})
    scorer = bench.ShortfallScorer().fit(train)
    assert scorer.baseline_rate_ == pytest.approx(0.01)
    test = pd.DataFrame({
        "n_reports": [3, 200, 200, 200, 4],
        "gap_reports": [3, 40, 40, 2, 4],
        "distinct_reporting_customers": [3, 150, 150, 150, 4],
        "distinct_gap_customers": [3, 38, 1, 2, 1],
    })
    risk = scorer.score(test)
    assert risk[0] == 0.0          # 3/3 reports is too little support to accuse anyone
    assert risk[1] > 0.5           # repeated shortfalls from many customers with real support
    assert risk[2] == 0.0          # one customer repeating: not independent evidence
    assert risk[3] < 0.05          # 2/200 is ordinary report noise
    assert risk[4] == 0.0          # tiny sample, single customer
    assert np.all((risk >= 0) & (risk <= 1))


def test_evaluate_scores_counts_exactly():
    y = np.array([1, 1, 0, 0, 0, 0])
    types = np.array(["skimmer", "skimmer", "high_volume_honest", "normal", "normal", "normal"])
    ids = [f"A{i}" for i in range(6)]
    scores = np.array([0.9, 0.5, 0.85, 0.1, 0.1, 0.1])
    result = bench.evaluate_scores(y, scores, types, ids, threshold=0.8)
    assert (result["skimmers"], result["honest_agents"], result["honest_high_volume"]) == (2, 4, 1)
    assert (result["flagged"], result["flagged_skimmers"], result["flagged_honest"],
            result["flagged_honest_high_volume"]) == (2, 1, 1, 1)
    top = result["budgets"]["absolute_15"]
    assert top["k"] == 6 and top["true_skimmers_in_top_k"] == 2     # K is clipped to the cohort
