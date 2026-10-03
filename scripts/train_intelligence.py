#!/usr/bin/env python3
"""Train and evaluate the liquidity forecast (Track 05) and uplift model (Track 04).

Reads the synthetic ledger only, writes hash-manifested JSON artifacts that the API serves.
Usage: PYTHONPATH=backend .venv/bin/python scripts/train_intelligence.py
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.intelligence import liquidity, uplift  # noqa: E402
from app.intelligence.artifacts import write_artifacts  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(ROOT / "data/generated/train.json"))
    parser.add_argument("--external", default=str(ROOT / "data/generated/splits/test.json"))
    parser.add_argument("--out", default=str(ROOT / "data/artifacts/intelligence"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    dataset, external_path = Path(args.dataset), Path(args.external)
    data = json.loads(dataset.read_text())
    external = json.loads(external_path.read_text()) if external_path.exists() else None

    liquidity_result = liquidity.train_and_evaluate(data, seed=args.seed, external=external)
    uplift_result = uplift.train_and_evaluate(data, seed=args.seed)
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                           text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "unknown"
    write_artifacts(Path(args.out), {"liquidity": liquidity_result, "uplift": uplift_result}, {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "git_revision": revision,
        "seed": args.seed,
        "dataset_sha256": _sha256(dataset),
        "external_sha256": _sha256(external_path) if external else None,
        "synthetic": True,
    })
    holdout = liquidity_result["evaluation"]["time_holdout"]
    print(json.dumps({
        "liquidity_time_holdout": {k: holdout[k] for k in
                                   ("lightgbm", "seasonal_naive", "moving_average_7",
                                    "p90_coverage")},
        "liquidity_unseen": liquidity_result["evaluation"].get("unseen_agent_population", {}).get(
            "lightgbm"),
        "uplift": {k: {m: v[m] for m in ("qini_coefficient", "true_incremental_top20")}
                   for k, v in uplift_result["policies"].items()},
        "uplift_truth_correlation": uplift_result["uplift_truth_correlation"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
