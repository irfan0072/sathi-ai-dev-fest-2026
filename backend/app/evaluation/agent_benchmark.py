"""Extended independent agent benchmark, version agent-benchmark-v2.0 (synthetic).

Purpose: the canonical held-out agent cohort has 60 agents with only 2 skimmers and 4 honest
high-volume agents. This benchmark re-runs the SAME generator, features and detectors on a much
larger, independently seeded population so the agent-detection claims have usable denominators.
It does not touch, rewrite or re-tune the canonical experiment, its config or its frozen
artifacts (data/config.yaml, data/generated/*, data/artifacts/*).

Design (all of it is written to protocol.json BEFORE any data is generated):
- Independence: every replication has its own registry seed, so its agents are new simulated
  agents. The three replications are disjoint populations (pooled counts are independent
  agents). Within a replication, train / validation / final cohorts are disjoint agents and
  customers. Re-scoring the same agents under another scenario is a robustness check on the
  same agents, not new agents; per-scenario denominators say so.
- Prevalence preserved: 90% normal, 6.67% honest high-volume, 3.33% skimmers, customers per
  agent unchanged. The skimming profile is the documented one ("moderate"). Nothing in the
  simulator is tuned.
- Development versus final: phase `dev` generates train + validation only, fits the detector on
  train and evaluates on validation. It decides, by criteria fixed in the protocol, whether the
  one development-only candidate (support-aware repeated-shortfall evidence) is selected. Phase
  `final` refuses to run without a verified dev record, then generates the final cohorts (new
  seeds that dev never touched) and scores them ONCE with the frozen detector, the fixed 0.8
  high-risk threshold from data/config.yaml and the predeclared review budgets.
- No ground-truth leakage: features come from the existing allow-listed extractor; the
  candidate only uses ledger payouts and customer-reported cash. Reference rates are learned on
  train agents without labels.
- Honest limits: this is synthetic. Customer reports follow the simulator's own noise model.
  It says nothing about real skimming prevalence, real reporting behaviour or deployment loss.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import math
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from app.data.config import load_config, validate_config
from app.data.generator import build_canonical_agent_registry, generate_dataset
from app.data.splits import allocate_cohorts
from app.models.agent_model import AgentAnomalyDetector
from app.models.baselines import AgentAnomalyRuleBaseline
from app.models.features import extract_agent_features

BENCHMARK_VERSION = "agent-benchmark-v2.0"

# Predeclared. The canonical benchmark uses seeds 42 / 4242 / 2026; these never overlap them.
REPLICATION_SEEDS = (
    {"replication": 1, "seed_train": 1101, "seed_validation": 1102, "seed_test": 1103},
    {"replication": 2, "seed_train": 2201, "seed_validation": 2202, "seed_test": 2203},
    {"replication": 3, "seed_train": 3301, "seed_validation": 3302, "seed_test": 3303},
)
AGENTS_PER_REPLICATION = 3000
AGENT_SPLIT = {"train": 0.40, "validation": 0.20, "test": 0.40}
REVIEW_BUDGETS = {"absolute_15": 15, "pct_5": 0.05, "pct_10": 0.10, "pct_25": 0.25}

# Scenario name -> description. Each one is a change of the generator config for the evaluated
# cohort only (the detector is always trained on the documented "moderate" behaviour).
SCENARIOS = {
    "moderate": "Documented default: fee overcharge plus payout reduction, moderate intensity",
    "subtle": "Subtle intensity: rare small overcharges and rare 1-3% payout reductions",
    "obvious": "Obvious intensity: frequent large overcharges and payout reductions",
    "unchanged_fee_shortfall_moderate": "Ledger fee is exactly correct; only the cash paid out "
                                        "is short (moderate payout reduction)",
    "unchanged_fee_shortfall_subtle": "Ledger fee is exactly correct; only rare small cash "
                                      "shortfalls (subtle payout reduction)",
    "sparse_reports": "Moderate intensity, only 20% of customers report cash received",
    "noisy_reports": "Moderate intensity, customer reports 70% accurate (default 90%)",
}
DEV_SCENARIOS = ("moderate", "subtle", "obvious", "unchanged_fee_shortfall_moderate",
                 "unchanged_fee_shortfall_subtle")

# The one development-only candidate and the rule that selects it (fixed before any run).
CANDIDATE = {
    "name": "ensemble_v2_shortfall",
    "description": "max(ensemble risk, support-aware repeated-shortfall risk). The shortfall "
                   "risk uses the Wilson lower bound of an agent's cash-shortfall report rate "
                   "against the train-population median rate, and needs shortfall reports from "
                   "at least 2 distinct customers.",
    "min_distinct_gap_customers": 2,
    "min_reports": 5,
    "scale": 0.05,
}
SELECTION_RULE = {
    "recall_gain_min_pp_on": "unchanged_fee_shortfall_moderate",
    "recall_gain_min_pp": 5.0,
    "honest_hv_false_flag_increase_max_pp_on": "moderate",
    "honest_hv_false_flag_increase_max_pp": 1.0,
    "precision_at_5pct_not_lower_on": "moderate",
    "evaluated_on": "validation cohorts, pooled over replications; never on final cohorts",
}
METHODS = ("rule_baseline", "peer_robust_zscore", "isolation_forest", "ensemble_v1",
           "ensemble_v2_shortfall")


# --------------------------------------------------------------------------- small helpers
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


def wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    """95% Wilson score interval for a binomial proportion; None when total == 0."""
    if total <= 0:
        return None
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def _rate(successes: int, total: int) -> dict[str, Any]:
    return {"numerator": int(successes), "denominator": int(total),
            "rate": round(successes / total, 4) if total else None,
            "ci95": wilson_interval(int(successes), int(total))}


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# --------------------------------------------------------------------------- configuration
def derive_config(base: dict[str, Any], replication: dict[str, int],
                  agents: int = AGENTS_PER_REPLICATION) -> dict[str, Any]:
    """Scale the canonical config: same mix proportions and customers per agent, new seeds."""
    cfg = copy.deepcopy(base)
    sim = cfg["simulation"]
    base_agents = int(sim["agents"])
    mix = sim["agent_mix"]
    skimmers = max(1, round(agents * mix["skimmers"] / base_agents))
    honest_hv = max(1, round(agents * mix["high_volume_honest"] / base_agents))
    sim["agents"] = agents
    sim["agent_mix"] = {"normal": agents - skimmers - honest_hv,
                        "high_volume_honest": honest_hv, "skimmers": skimmers}
    sim["customers"] = round(agents * int(base["simulation"]["customers"]) / base_agents)
    sim["agent_split"] = dict(AGENT_SPLIT)
    for key in ("seed_train", "seed_validation", "seed_test"):
        sim[key] = replication[key]
    return validate_config(cfg)


def scenario_config(cfg: dict[str, Any], scenario: str) -> dict[str, Any]:
    out = copy.deepcopy(cfg)
    sim = out["simulation"]
    profiles = sim["agent_behavior"]["skimmers"]["intensity_profiles"]
    if scenario in ("moderate", "subtle", "obvious"):
        sim["skimming_intensity"] = scenario
    elif scenario == "unchanged_fee_shortfall_moderate":
        sim["skimming_intensity"] = "moderate"
        profiles["moderate"] = {**profiles["moderate"], "fee_multiplier": 1.0,
                                "fee_multiplier_probability": 0.0}
    elif scenario == "unchanged_fee_shortfall_subtle":
        sim["skimming_intensity"] = "subtle"
        profiles["subtle"] = {**profiles["subtle"], "fee_multiplier": 1.0,
                              "fee_multiplier_probability": 0.0}
    elif scenario == "sparse_reports":
        sim["skimming_intensity"] = "moderate"
        sim["customer_report_rate"] = 0.2
    elif scenario == "noisy_reports":
        sim["skimming_intensity"] = "moderate"
        sim["customer_report_accuracy"] = 0.7
    else:
        raise ValueError(f"Unknown scenario {scenario!r}")
    return validate_config(out)


# --------------------------------------------------------------------------- candidate scorer
def shortfall_evidence(dataset: dict[str, Any], obs: dict[str, Any], cfg: dict[str, Any],
                       agent_ids: list[str]) -> pd.DataFrame:
    """Per agent: customer-reported shortfall evidence with its support (report counts).

    Uses only ledger payouts and customer-reported cash, with the same tolerance as the
    production feature `agent_cash_gap_rate`. Ground-truth columns of the observations
    (actual cash, skimmer flags) are never read.
    """
    policy = cfg.get("policy", {}).get("cash_gap", {})
    gap_min, gap_rate = float(policy.get("min_bdt", 50.0)), float(policy.get("rate", 0.02))
    reports = obs.get("transaction_observations", {})
    reported: dict[int, float] = {}
    for key, entry in reports.items():
        value = entry.get("cash_received_reported")
        if value is not None:
            reported[int(entry.get("txn_id", key))] = float(value)
    n_reports: dict[str, int] = defaultdict(int)
    gap_reports: dict[str, int] = defaultdict(int)
    reporters: dict[str, set[str]] = defaultdict(set)
    gap_customers: dict[str, set[str]] = defaultdict(set)
    for tx in dataset["transactions"]:
        if tx.get("txn_type") != "cash_out" or not tx.get("agent_id"):
            continue
        tid = int(tx["txn_id"])
        if tid not in reported:
            continue
        agent, user, amount = tx["agent_id"], tx["user_id"], float(tx["amount"])
        n_reports[agent] += 1
        reporters[agent].add(user)
        if amount - reported[tid] > max(gap_min, gap_rate * amount):
            gap_reports[agent] += 1
            gap_customers[agent].add(user)
    return pd.DataFrame({
        "n_reports": [n_reports[a] for a in agent_ids],
        "gap_reports": [gap_reports[a] for a in agent_ids],
        "distinct_reporting_customers": [len(reporters[a]) for a in agent_ids],
        "distinct_gap_customers": [len(gap_customers[a]) for a in agent_ids],
    })


def wilson_lower(successes: np.ndarray, totals: np.ndarray, z: float = 1.96) -> np.ndarray:
    n = np.maximum(totals, 1).astype(float)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return np.where(totals > 0, centre - half, 0.0)


class ShortfallScorer:
    """Support-aware repeated-shortfall risk. Fit without labels on train agents only."""

    def __init__(self, scale: float = CANDIDATE["scale"],
                 min_distinct: int = CANDIDATE["min_distinct_gap_customers"],
                 min_reports: int = CANDIDATE["min_reports"]) -> None:
        self.scale, self.min_distinct, self.min_reports = scale, min_distinct, min_reports
        self.baseline_rate_: float | None = None

    def fit(self, evidence: pd.DataFrame) -> ShortfallScorer:
        usable = evidence[evidence["n_reports"] >= self.min_reports]
        rates = usable["gap_reports"] / usable["n_reports"] if len(usable) else pd.Series([0.0])
        self.baseline_rate_ = float(np.median(rates))
        return self

    def score(self, evidence: pd.DataFrame) -> np.ndarray:
        if self.baseline_rate_ is None:
            raise RuntimeError("fit the scorer on train agents first")
        lower = wilson_lower(evidence["gap_reports"].to_numpy(float),
                             evidence["n_reports"].to_numpy(float))
        excess = np.maximum(0.0, lower - self.baseline_rate_)
        risk = 1.0 - np.exp(-excess / self.scale)
        supported = ((evidence["n_reports"].to_numpy() >= self.min_reports)
                     & (evidence["distinct_gap_customers"].to_numpy() >= self.min_distinct))
        return np.where(supported, risk, 0.0)


# --------------------------------------------------------------------------- evaluation
def _budget_sizes(n_agents: int) -> dict[str, int]:
    sizes = {}
    for label, value in REVIEW_BUDGETS.items():
        k = value if isinstance(value, int) else math.ceil(value * n_agents)
        sizes[label] = int(min(k, n_agents))
    return sizes


def evaluate_scores(y: np.ndarray, scores: np.ndarray, types: np.ndarray, ids: list[str],
                    threshold: float, flagged_override: np.ndarray | None = None
                    ) -> dict[str, Any]:
    """Counts only (no rates), so replications can be pooled exactly."""
    n = len(y)
    flagged = (scores >= threshold) if flagged_override is None else flagged_override.astype(bool)
    skim = y == 1
    hv = types == "high_volume_honest"
    honest = ~skim
    order = sorted(range(n), key=lambda i: (-scores[i], ids[i]))
    budgets = {}
    for label, k in _budget_sizes(n).items():
        top = np.array(order[:k], dtype=int)
        budgets[label] = {"k": k, "true_skimmers_in_top_k": int(y[top].sum()),
                          "honest_high_volume_in_top_k": int(hv[top].sum())}
    ap = float(average_precision_score(y, scores)) if 0 < skim.sum() < n else None
    return {
        "agents": int(n), "skimmers": int(skim.sum()), "honest_agents": int(honest.sum()),
        "honest_high_volume": int(hv.sum()),
        "flagged": int(flagged.sum()), "flagged_skimmers": int((flagged & skim).sum()),
        "flagged_honest": int((flagged & honest).sum()),
        "flagged_honest_high_volume": int((flagged & hv).sum()),
        "budgets": budgets, "average_precision": ap,
    }


def score_methods(detector: AgentAnomalyDetector, scorer: ShortfallScorer,
                  cfg: dict[str, Any], X: pd.DataFrame, evidence: pd.DataFrame,
                  ) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Scores per method for one cohort. The rule baseline is a hard flag (1.0 / 0.0)."""
    rule = AgentAnomalyRuleBaseline(config=cfg)
    rule_flags = np.asarray(rule.predict(X), dtype=int)
    rule_score = np.asarray(rule.score(X), dtype=float)
    z_risk, _ = detector.score_peer_robust_zscore(X)
    if_risk = detector.score_isolation_forest(X)
    combined, _ = detector.score_combined(X)
    shortfall = scorer.score(evidence)
    return {
        "rule_baseline": rule_score,
        "peer_robust_zscore": z_risk,
        "isolation_forest": if_risk,
        "ensemble_v1": combined,
        "ensemble_v2_shortfall": np.maximum(combined, shortfall),
    }, rule_flags


def cohort_metrics(detector: AgentAnomalyDetector, scorer: ShortfallScorer,
                   cfg: dict[str, Any], dataset: dict[str, Any], obs: dict[str, Any]
                   ) -> dict[str, Any]:
    X, y_ser, meta, ids = extract_agent_features(
        dataset["agents"], dataset["transactions"], config=cfg, reports_data=obs,
        include_cash_reports=True)
    evidence = shortfall_evidence(dataset, obs, cfg, ids)
    y = y_ser.to_numpy(dtype=int)
    types = meta["agent_type"].to_numpy()
    threshold = float(cfg["policy"]["agent_risk_high"])
    scores, rule_flags = score_methods(detector, scorer, cfg, X, evidence)
    out = {}
    for method in METHODS:
        override = rule_flags if method == "rule_baseline" else None
        out[method] = evaluate_scores(y, scores[method], types, ids, threshold, override)
    return out


# --------------------------------------------------------------------------- generation
def _generate(cfg: dict[str, Any], canonical: list[dict[str, Any]], cohort_ids: list[str],
              seed: int, customers: int) -> tuple[dict[str, Any], dict[str, Any]]:
    return generate_dataset(config=cfg, seed=seed, agent_ids=cohort_ids, customers=customers,
                            return_observations=True, canonical_agents=canonical)


def _customer_counts(cfg: dict[str, Any]) -> dict[str, int]:
    from app.data.splits import allocate_largest_remainder

    return allocate_largest_remainder(int(cfg["simulation"]["customers"]),
                                      cfg["simulation"]["agent_split"])


def run_dev_replication(task: dict[str, Any]) -> dict[str, Any]:
    """Train + validation only. Never generates a final cohort."""
    base, replication, agents, out_dir = (task["base"], task["replication"], task["agents"],
                                          Path(task["out_dir"]))
    started = time.time()
    cfg = derive_config(base, replication, agents)
    canonical = build_canonical_agent_registry(cfg)
    cohorts = allocate_cohorts(cfg, canonical_agents=canonical)
    counts = _customer_counts(cfg)
    sim = cfg["simulation"]
    train_ds, train_obs = _generate(cfg, canonical, cohorts["train"], sim["seed_train"],
                                    counts["train"])
    X_tr, _y, _m, ids_tr = extract_agent_features(
        train_ds["agents"], train_ds["transactions"], config=cfg, reports_data=train_obs,
        include_cash_reports=True)
    detector = AgentAnomalyDetector(config=cfg, random_state=42).fit(X_tr)
    scorer = ShortfallScorer().fit(shortfall_evidence(train_ds, train_obs, cfg, ids_tr))
    del train_ds, train_obs
    model_path = out_dir / "models" / f"replication_{replication['replication']}_detector.joblib"
    detector.save(model_path)
    scenarios = {}
    for name in DEV_SCENARIOS:
        s_cfg = scenario_config(cfg, name)
        val_ds, val_obs = _generate(s_cfg, canonical, cohorts["validation"],
                                    sim["seed_validation"], counts["validation"])
        scenarios[name] = cohort_metrics(detector, scorer, s_cfg, val_ds, val_obs)
    return {
        "replication": replication["replication"], "seeds": replication,
        "cohort_agent_counts": {k: len(v) for k, v in cohorts.items()},
        "customer_counts": counts,
        "shortfall_baseline_rate": scorer.baseline_rate_,
        "detector_sha256": sha256_file(model_path),
        "scenarios": scenarios, "seconds": round(time.time() - started, 1),
    }


def run_final_replication(task: dict[str, Any]) -> dict[str, Any]:
    """Final cohort: generated here for the first time, scored once with the frozen detector."""
    base, replication, agents, out_dir = (task["base"], task["replication"], task["agents"],
                                          Path(task["out_dir"]))
    started = time.time()
    cfg = derive_config(base, replication, agents)
    canonical = build_canonical_agent_registry(cfg)
    cohorts = allocate_cohorts(cfg, canonical_agents=canonical)
    counts = _customer_counts(cfg)
    sim = cfg["simulation"]
    model_path = out_dir / "models" / f"replication_{replication['replication']}_detector.joblib"
    if sha256_file(model_path) != task["expected_detector_sha256"]:
        raise RuntimeError("Detector file changed since the dev phase; refusing to score final.")
    detector = AgentAnomalyDetector.load(model_path)
    train_ds, train_obs = _generate(cfg, canonical, cohorts["train"], sim["seed_train"],
                                    counts["train"])
    _X, _y, _m, ids_tr = extract_agent_features(
        train_ds["agents"], train_ds["transactions"], config=cfg, reports_data=train_obs,
        include_cash_reports=True)
    scorer = ShortfallScorer().fit(shortfall_evidence(train_ds, train_obs, cfg, ids_tr))
    del train_ds, train_obs
    scenarios = {}
    for name in task["scenarios"]:
        s_cfg = scenario_config(cfg, name)
        final_ds, final_obs = _generate(s_cfg, canonical, cohorts["test"], sim["seed_test"],
                                        counts["test"])
        scenarios[name] = cohort_metrics(detector, scorer, s_cfg, final_ds, final_obs)
    return {
        "replication": replication["replication"], "seeds": replication,
        "cohort_agent_counts": {k: len(v) for k, v in cohorts.items()},
        "customer_counts": counts, "scenarios": scenarios,
        "seconds": round(time.time() - started, 1),
    }


# --------------------------------------------------------------------------- pooling
def pool(replications: list[dict[str, Any]]) -> dict[str, Any]:
    """Pool counts over replications (independent agents) into rates with Wilson intervals."""
    pooled: dict[str, Any] = {}
    scenario_names = list(replications[0]["scenarios"])
    for scenario in scenario_names:
        entry: dict[str, Any] = {}
        for method in METHODS:
            parts = [r["scenarios"][scenario][method] for r in replications]
            skim = sum(p["skimmers"] for p in parts)
            honest = sum(p["honest_agents"] for p in parts)
            hv = sum(p["honest_high_volume"] for p in parts)
            agents = sum(p["agents"] for p in parts)
            flagged = sum(p["flagged"] for p in parts)
            tp = sum(p["flagged_skimmers"] for p in parts)
            budgets = {}
            for label in REVIEW_BUDGETS:
                k_total = sum(p["budgets"][label]["k"] for p in parts)
                hits = sum(p["budgets"][label]["true_skimmers_in_top_k"] for p in parts)
                busy = sum(p["budgets"][label]["honest_high_volume_in_top_k"] for p in parts)
                per_rep = [p["budgets"][label]["true_skimmers_in_top_k"]
                           / p["budgets"][label]["k"] for p in parts]
                budgets[label] = {
                    "review_slots": k_total, "skimmers_found": hits,
                    "precision_at_budget": _rate(hits, k_total),
                    "recall_at_budget": _rate(hits, skim),
                    "honest_high_volume_in_budget": busy,
                    "precision_per_replication": [round(v, 4) for v in per_rep],
                    "interval_note": "approximate: selections within a cohort are not "
                                     "independent; use per-replication spread as well",
                }
            aps = [p["average_precision"] for p in parts if p["average_precision"] is not None]
            entry[method] = {
                "denominators": {"agents": agents, "skimmers": skim, "honest_agents": honest,
                                 "honest_high_volume": hv},
                "threshold_policy": {
                    "flagged_total": flagged,
                    "precision": _rate(tp, flagged),
                    "recall_on_skimmers": _rate(tp, skim),
                    "recall_per_replication": [
                        round(p["flagged_skimmers"] / p["skimmers"], 4) if p["skimmers"] else None
                        for p in parts],
                    "false_flags_total_honest": _rate(
                        sum(p["flagged_honest"] for p in parts), honest),
                    "false_flags_honest_high_volume": _rate(
                        sum(p["flagged_honest_high_volume"] for p in parts), hv),
                },
                "review_budget_policy": budgets,
                "average_precision_mean": round(float(np.mean(aps)), 4) if aps else None,
                "average_precision_per_replication": [round(a, 4) for a in aps],
            }
        pooled[scenario] = entry
    return pooled


def decide_candidate(dev_pooled: dict[str, Any]) -> dict[str, Any]:
    """Apply the predeclared selection rule to VALIDATION results only."""
    rule = SELECTION_RULE
    v1 = dev_pooled[rule["recall_gain_min_pp_on"]]["ensemble_v1"]["threshold_policy"]
    v2 = dev_pooled[rule["recall_gain_min_pp_on"]]["ensemble_v2_shortfall"]["threshold_policy"]
    gain = round(100 * ((v2["recall_on_skimmers"]["rate"] or 0)
                        - (v1["recall_on_skimmers"]["rate"] or 0)), 2)
    mod1 = dev_pooled["moderate"]["ensemble_v1"]
    mod2 = dev_pooled["moderate"]["ensemble_v2_shortfall"]
    ff1 = mod1["threshold_policy"]["false_flags_honest_high_volume"]["rate"] or 0
    ff2 = mod2["threshold_policy"]["false_flags_honest_high_volume"]["rate"] or 0
    ff_increase = round(100 * (ff2 - ff1), 2)
    p1 = mod1["review_budget_policy"]["pct_5"]["precision_at_budget"]["rate"] or 0
    p2 = mod2["review_budget_policy"]["pct_5"]["precision_at_budget"]["rate"] or 0
    checks = {
        "recall_gain_pp": gain, "recall_gain_ok": gain >= rule["recall_gain_min_pp"],
        "honest_hv_false_flag_increase_pp": ff_increase,
        "false_flag_ok": ff_increase <= rule["honest_hv_false_flag_increase_max_pp"],
        "precision_at_5pct_v1": p1, "precision_at_5pct_v2": p2, "precision_ok": p2 >= p1,
    }
    selected = checks["recall_gain_ok"] and checks["false_flag_ok"] and checks["precision_ok"]
    return {"candidate": CANDIDATE["name"], "selection_rule": rule, "checks": checks,
            "candidate_selected": bool(selected),
            "selected_method": CANDIDATE["name"] if selected else "ensemble_v1",
            "note": "Decided on validation cohorts only. The candidate is a benchmark-side "
                    "scorer: it is not part of the deployed model bundle."}


# --------------------------------------------------------------------------- orchestration
FORBIDDEN_OUTPUT_PARTS = ("data/generated", "data/artifacts")


def _check_out_dir(out_dir: Path) -> Path:
    resolved = out_dir.resolve()
    text = str(resolved)
    if any(part in text for part in FORBIDDEN_OUTPUT_PARTS):
        raise ValueError("The extended benchmark never writes into the canonical evaluation "
                         "or frozen artifact directories.")
    return resolved


def write_protocol(out_dir: Path, agents: int, base_config_path: str | None) -> dict[str, Any]:
    base = load_config(base_config_path)
    protocol = {
        "benchmark_version": BENCHMARK_VERSION,
        "declared_at": now_iso(),
        "canonical_config_sha256": sha256_bytes(canonical_json(base)),
        "agents_per_replication": agents,
        "agent_split": AGENT_SPLIT,
        "replications": list(REPLICATION_SEEDS),
        "canonical_seeds_not_reused": [base["simulation"]["seed_train"],
                                       base["simulation"]["seed_validation"],
                                       base["simulation"]["seed_test"]],
        "prevalence": "agent_mix and customers-per-agent proportions copied from the "
                      "canonical config; documented 'moderate' skimming profile",
        "development_scenarios": list(DEV_SCENARIOS),
        "final_scenarios": list(SCENARIOS),
        "scenario_definitions": SCENARIOS,
        "review_budgets": REVIEW_BUDGETS,
        "high_risk_threshold": base["policy"]["agent_risk_high"],
        "threshold_tuning": "none: 0.8 from data/config.yaml, fixed",
        "methods": list(METHODS),
        "candidate": CANDIDATE, "selection_rule": SELECTION_RULE,
        "final_cohort_rule": "generated and scored once, only after dev_results.json exists "
                             "and its hash is recorded; never used for any choice",
        "interval_method": "95% Wilson score interval on pooled independent-agent counts; "
                           "per-replication values shown for seed variation",
    }
    protocol["protocol_sha256"] = sha256_bytes(canonical_json(
        {k: v for k, v in protocol.items() if k != "declared_at"}))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "protocol.json"
    if path.exists():
        existing = json.loads(path.read_text())
        if existing["protocol_sha256"] != protocol["protocol_sha256"]:
            raise RuntimeError("protocol.json already exists with different content; use a "
                               "new output directory instead of editing a predeclared protocol.")
        return existing
    path.write_text(json.dumps(protocol, indent=2, sort_keys=True))
    return protocol


def _run_parallel(func, tasks: list[dict[str, Any]], workers: int) -> list[dict[str, Any]]:
    if workers <= 1 or len(tasks) == 1:
        return [func(t) for t in tasks]
    with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as pool_:
        return list(pool_.map(func, tasks))


def run_dev(out_dir: Path, agents: int = AGENTS_PER_REPLICATION, workers: int = 3,
            base_config_path: str | None = None) -> dict[str, Any]:
    out_dir = _check_out_dir(Path(out_dir))
    protocol = write_protocol(out_dir, agents, base_config_path)
    base = load_config(base_config_path)
    tasks = [{"base": base, "replication": r, "agents": agents, "out_dir": str(out_dir)}
             for r in REPLICATION_SEEDS]
    reps = _run_parallel(run_dev_replication, tasks, workers)
    pooled = pool(reps)
    decision = decide_candidate(pooled)
    result = {
        "benchmark_version": BENCHMARK_VERSION, "phase": "development",
        "protocol_sha256": protocol["protocol_sha256"], "completed_at": now_iso(),
        "cohort": "validation (train fits the detector; final cohorts not generated)",
        "replications": reps, "pooled": pooled, "decision": decision,
    }
    (out_dir / "dev_results.json").write_text(json.dumps(result, indent=2, sort_keys=True))
    return result


def run_final(out_dir: Path, agents: int = AGENTS_PER_REPLICATION, workers: int = 3,
              base_config_path: str | None = None) -> dict[str, Any]:
    from app.evaluation.suite import (
        _compute_source_tree_hash,
        _get_dependency_versions,
        _get_git_revision,
    )

    out_dir = _check_out_dir(Path(out_dir))
    dev_path, protocol_path = out_dir / "dev_results.json", out_dir / "protocol.json"
    final_path = out_dir / "final_results.json"
    if not dev_path.exists() or not protocol_path.exists():
        raise RuntimeError("Run the development phase first: the final cohort needs a verified "
                           "dev record.")
    if final_path.exists():
        raise RuntimeError("final_results.json already exists: the final cohort is scored once.")
    protocol = json.loads(protocol_path.read_text())
    dev = json.loads(dev_path.read_text())
    if dev["protocol_sha256"] != protocol["protocol_sha256"]:
        raise RuntimeError("dev_results.json does not match protocol.json.")
    base = load_config(base_config_path)
    tasks = []
    for r in REPLICATION_SEEDS:
        expected = next(x for x in dev["replications"]
                        if x["replication"] == r["replication"])["detector_sha256"]
        tasks.append({"base": base, "replication": r, "agents": agents, "out_dir": str(out_dir),
                      "scenarios": list(SCENARIOS), "expected_detector_sha256": expected})
    reps = _run_parallel(run_final_replication, tasks, workers)
    pooled = pool(reps)
    selected = dev["decision"]["selected_method"]
    tree_sha, dirty = _compute_source_tree_hash()
    result = {
        "benchmark_version": BENCHMARK_VERSION, "phase": "final",
        "protocol_sha256": protocol["protocol_sha256"],
        "dev_results_sha256": sha256_file(dev_path),
        "selected_method_from_dev": selected,
        "completed_at": now_iso(),
        "provenance": {"git_revision": _get_git_revision(), "source_tree_sha256": tree_sha,
                       "worktree_has_uncommitted_changes": dirty,
                       "dependencies": _get_dependency_versions()},
        "replications": reps, "pooled": pooled,
        "limits": [
            "Synthetic data from the project's own simulator; customer reports follow its "
            "noise model. No real prevalence, reporting behaviour or loss is implied.",
            "Scenario rows on the same agents are robustness checks, not additional independent "
            "agents; the independent-agent counts are per replication cohort.",
            "Precision at a review budget and threshold precision/recall are different "
            "policies with different denominators and must not be mixed.",
        ],
    }
    final_path.write_text(json.dumps(result, indent=2, sort_keys=True))
    manifest = {
        "benchmark_version": BENCHMARK_VERSION,
        "files": {name: sha256_file(out_dir / name)
                  for name in ("protocol.json", "dev_results.json", "final_results.json")},
        "detectors": {p.name: sha256_file(p) for p in sorted((out_dir / "models").glob("*"))},
        "generated_at": now_iso(),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return result


def verify_archive(out_dir: Path) -> list[str]:
    """Recompute the archived hashes. Returns a list of problems (empty means intact)."""
    out_dir = Path(out_dir)
    problems = []
    manifest = json.loads((out_dir / "manifest.json").read_text())
    for name, digest in manifest["files"].items():
        if sha256_file(out_dir / name) != digest:
            problems.append(f"{name} changed")
    for name, digest in manifest["detectors"].items():
        if sha256_file(out_dir / "models" / name) != digest:
            problems.append(f"models/{name} changed")
    final = json.loads((out_dir / "final_results.json").read_text())
    if final["dev_results_sha256"] != manifest["files"]["dev_results.json"]:
        problems.append("final results do not reference the archived dev results")
    return problems
