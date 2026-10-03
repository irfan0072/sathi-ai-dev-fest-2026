#!/usr/bin/env python3
"""Sathi go-live preflight: probe every 3rd-party integration and print a
readiness table.

Every probe is read-only and free: account, balance and model lookups. No call is
placed, no SMS is sent and no tokens are generated.

Probe code lives in `backend/app/ops/readiness.py` so the Settings page runs the exact
same probes via `/api/v1/settings/probe`.

Usage:
    scripts/preflight.py [--env .env]
    scripts/preflight.py --only twilio

Exit codes:
    0 — every checked provider is ready (or deliberately skipped)
    1 — at least one checked provider reports a problem
    2 — operator error (e.g. cannot read .env)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app.ops.readiness import PROBES, ProbeResult, run_one


def load_env_file(path: Path) -> dict[str, str]:
    """Minimal .env parser. Quoting and `export` are accepted but ignored;
    lines starting with '#' are comments."""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if value.startswith(("'", '"')) and value.endswith(value[0]):
            value = value[1:-1]
        env[key] = value
    return env


def _render(r: ProbeResult) -> str:
    env_mark = "yes" if r.env_ok else "no "
    if not r.env_ok:
        probe = "skipped"
    elif r.probe_ok is None:
        probe = "vendor pending"
    elif r.probe_ok:
        probe = "ok"
    else:
        probe = "FAIL"
    ready = "yes" if r.ready else "no"
    return f"{r.name:<13} {env_mark:<13} {probe:<18} {ready:<6} {r.detail}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env",
                        help="Path to the .env file (default: .env in cwd)")
    parser.add_argument("--timeout", type=float, default=8.0,
                        help="Per-probe network timeout in seconds")
    parser.add_argument("--only", default=None,
                        help="Run only one probe (twilio|alpha_sms|gemini|openai|bd_http_ivr)")
    args = parser.parse_args(argv)

    env_path = Path(args.env)
    env = load_env_file(env_path)
    # Existing process env wins over .env so a real shell override sticks.
    merged = {**env, **os.environ}

    if env_path.exists():
        print(f"Loaded .env from {env_path.resolve()}")
    else:
        print(f"No .env file at {env_path.resolve()} — using process env only")
    print()

    print(f"{'Integration':<13} {'Env present':<13} {'Sandbox probe':<18} "
          f"{'Ready':<6} Detail")
    print("-" * 90)

    if args.only:
        if args.only not in PROBES:
            parser.error(
                f"unknown --only value {args.only!r}; "
                f"choose one of {', '.join(PROBES)}"
            )
        names_to_run = (args.only,)
    else:
        names_to_run = tuple(PROBES)
    results = [run_one(name, merged, args.timeout) for name in names_to_run]

    for r in results:
        print(_render(r))

    ready_count = sum(1 for r in results if r.ready)
    pending_count = sum(1 for r in results if r.probe_ok is None)
    fail_count = sum(1 for r in results if r.probe_ok is False)

    print()
    print(f"Ready: {ready_count}    Pending: {pending_count}    Failed: {fail_count}")
    if fail_count:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())