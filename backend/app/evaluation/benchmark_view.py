"""Read-only, hash-verified view of the extended agent benchmark (v2) for the console.

Nothing is recomputed. The archive's hashes are re-checked on every read; a changed or missing
archive returns an "unavailable" reason instead of numbers. The held-out denominator is the
final cohorts only (3,600 agents), not the 9,000 agents generated in total.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.evaluation.agent_benchmark import REVIEW_BUDGETS, sha256_file, verify_archive

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "data" / "benchmarks" / "agent_v2"
METHOD_LABEL = {
    "rule_baseline": "Rule baseline (fee ratio >= 1.2)",
    "peer_robust_zscore": "Peer robust z-score",
    "isolation_forest": "Isolation forest",
    "ensemble_v1": "Deployed ensemble",
    "ensemble_v2_shortfall": "Candidate (dev-selected, NOT deployed)",
}


class BenchmarkUnavailable(Exception):
    pass


def benchmark_dir() -> Path:
    return Path(os.environ.get("SATHI_BENCHMARK_V2_DIR", str(DEFAULT_DIR)))


def load_summary(directory: Path | None = None) -> dict[str, Any]:
    directory = directory or benchmark_dir()
    try:
        problems = verify_archive(directory)
        final = json.loads((directory / "final_results.json").read_text())
        dev = json.loads((directory / "dev_results.json").read_text())
        protocol = json.loads((directory / "protocol.json").read_text())
    except (OSError, ValueError, KeyError) as exc:
        raise BenchmarkUnavailable(
            f"benchmark archive missing or unreadable ({type(exc).__name__})") from None
    if problems:
        raise BenchmarkUnavailable("archive hash check failed: " + "; ".join(problems))
    pooled = final["pooled"]
    moderate = pooled["moderate"]["ensemble_v1"]["denominators"]
    rows = []
    for scenario, entry in pooled.items():
        row: dict[str, Any] = {"scenario": scenario,
                               "skimmers": entry["ensemble_v1"]["denominators"]["skimmers"],
                               "methods": {}}
        for method, label in METHOD_LABEL.items():
            policy = entry[method]["threshold_policy"]
            budget = entry[method]["review_budget_policy"]["pct_5"]
            row["methods"][method] = {
                "label": label,
                "recall": policy["recall_on_skimmers"],
                "honest_high_volume_false_flags": policy["false_flags_honest_high_volume"],
                "precision_at_5pct": budget["precision_at_budget"],
                "average_precision": entry[method]["average_precision_mean"],
            }
        rows.append(row)
    return {
        "version": final["benchmark_version"],
        "status": "synthetic evidence, not field validation",
        "protocol_sha256": protocol["protocol_sha256"],
        "dev_results_sha256": final["dev_results_sha256"],
        "final_results_sha256": sha256_file(directory / "final_results.json"),
        "completed_at": final["completed_at"],
        "replications": len(final["replications"]),
        "agents_generated_total": sum(sum(r["cohort_agent_counts"].values())
                                      for r in final["replications"]),
        "final_held_out": moderate,
        "review_budgets": REVIEW_BUDGETS,
        "candidate_decision": {k: dev["decision"][k] for k in
                               ("candidate", "candidate_selected", "checks", "note")},
        "scenarios": rows,
        "limits": final["limits"] + [
            "Honest agents have zero fee noise in the simulator, so moderate skimming is an "
            "easy task here.",
            "The candidate is benchmark-side only. It is not in the deployed model bundle."],
        "canonical_comparison": "The canonical held-out cohort (Experiment 2 tabs) has 60 "
                                "agents, 2 skimmers and 4 honest high-volume agents.",
    }
