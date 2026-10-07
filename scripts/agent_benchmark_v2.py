#!/usr/bin/env python3
"""Run the extended agent benchmark (agent-benchmark-v2.0). Synthetic data only.

    python scripts/agent_benchmark_v2.py --phase dev   [--out-dir data/benchmarks/agent_v2]
    python scripts/agent_benchmark_v2.py --phase final [--out-dir data/benchmarks/agent_v2]
    python scripts/agent_benchmark_v2.py --phase verify

The canonical evaluation (data/config.yaml, data/generated/*, data/artifacts/*) is never
modified. The final phase refuses to run before a dev record exists and scores once.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "backend"))

from app.evaluation import agent_benchmark as bench  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("dev", "final", "verify"), required=True)
    parser.add_argument("--out-dir", default="data/benchmarks/agent_v2")
    parser.add_argument("--agents", type=int, default=bench.AGENTS_PER_REPLICATION,
                        help="agents per replication (default 3000; smaller only for smoke runs)")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    if args.phase == "dev":
        result = bench.run_dev(out_dir, args.agents, args.workers, args.config)
        print(json.dumps(result["decision"], indent=2))
    elif args.phase == "final":
        result = bench.run_final(out_dir, args.agents, args.workers, args.config)
        print(f"final cohort scored once; selected method from dev: "
              f"{result['selected_method_from_dev']}")
    else:
        problems = bench.verify_archive(out_dir)
        print("archive intact" if not problems else "PROBLEMS: " + "; ".join(problems))
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
