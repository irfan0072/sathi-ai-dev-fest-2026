#!/usr/bin/env python3
"""Run the repeatable synthetic workflow scenario in a disposable PostgreSQL schema.

    SATHI_TEST_DATABASE_URL=postgresql://user@localhost:5432/dbname \
        python scripts/demo_scenario.py [--out docs/evidence] [--keep-schema]

Creates a throw-away schema, migrates and seeds it, runs cash-out -> call -> mismatch / help
signal / silence / uncertain speech / provider failure -> supervisor queue -> follow-up ->
human decision -> audit through the real backend, prints a readable transcript and writes
workflow-evidence.json. Nothing is called, texted or published. Synthetic, not field evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import uuid
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "backend"))
os.environ.setdefault("JWT_SECRET", secrets.token_hex(32))
os.environ["SATHI_WORKER_ENABLED"] = "false"
os.environ.setdefault("SATHI_PBKDF2_ITERATIONS", "1000")
os.environ["SATHI_DEPLOYMENT_MODE"] = "local"
os.environ["SATHI_VOICE_PROVIDER"] = "simulated"
os.environ["SATHI_SMS_PROVIDER"] = "simulated"
os.environ["SATHI_SETTINGS_EDITABLE"] = "false"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("SATHI_TEST_DATABASE_URL"))
    parser.add_argument("--out", default=str(repo_root / "docs" / "evidence"))
    parser.add_argument("--keep-schema", action="store_true")
    args = parser.parse_args(argv)
    if not args.database_url:
        print("Set SATHI_TEST_DATABASE_URL (a disposable local database) or pass --database-url.",
              file=sys.stderr)
        return 2

    from app.bootstrap import prepare_runtime
    from app.data.database import get_connection
    from app.mandates.service import MandateService
    from app.ops.demo_scenario import run_scenario

    schema = f"sathi_demo_{uuid.uuid4().hex[:10]}"
    with get_connection(args.database_url) as conn:
        conn.execute(f"CREATE SCHEMA {schema};")
        conn.commit()
    try:
        prepare_runtime(args.database_url, schema)
        mandates = MandateService(db_url=args.database_url, schema=schema)
        result = run_scenario(mandates)
        with get_connection(args.database_url) as conn, conn.cursor() as cur:
            cur.execute("SHOW server_version;")
            result["environment"] = {"postgresql": cur.fetchone()[0],
                                     "schema": "disposable (dropped after the run)"}
    finally:
        if not args.keep_schema:
            with get_connection(args.database_url) as conn:
                conn.execute(f"DROP SCHEMA {schema} CASCADE;")
                conn.commit()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "workflow-evidence.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str), encoding="utf-8")
    scenario = None
    for step in result["steps"]:
        if step["scenario"] != scenario:
            scenario = step["scenario"]
            print(f"\n== {scenario}")
        status = f"[{step['http']}]" if "http" in step else "[ - ]"
        print(f"  {status:6s} {step['as']:<22s} {step['step']}")
    ev = result["workflow_evidence"]
    print("\nObserved in this synthetic run (not field impact):")
    print(f"  calls attempted {ev['calls']['attempted']}, answered "
          f"{ev['calls']['answered']['numerator']}/{ev['calls']['answered']['denominator']}, "
          f"clear outcome {ev['calls']['completed_with_a_clear_outcome']['numerator']}, "
          f"unclear {ev['calls']['unclear']['numerator']}, "
          f"failed to place {ev['calls']['failed_to_place']['numerator']}")
    print(f"  cases {ev['cases']['total']} (confirmed {ev['cases']['confirmed_problem']}, "
          f"escalated {ev['cases']['escalated']}, "
          f"cleared {ev['cases']['cleared_no_wrongdoing_found']})")
    print(f"\nEvidence written to {out / 'workflow-evidence.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
