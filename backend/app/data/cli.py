"""CLI for Sathi migrations, synthetic generation, and dataset seeding."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from app.data.config import load_config
from app.data.database import (
    MigrationError,
    SeedCollisionError,
    ValidationError,
    load_seed,
    run_migrations,
)
from app.data.generator import generate_dataset
from app.data.splits import generate_shifted_test_split, generate_splits


def build_parser() -> argparse.ArgumentParser:
    """Build command-line parser for database migrations, generation, and seeding."""
    parser = argparse.ArgumentParser(
        prog="python -m app.data.cli",
        description="Sathi database migration, generator, and seed CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # generate subcommand
    generate_parser = subparsers.add_parser(
        "generate", help="Generate synthetic dataset and sidecar"
    )
    generate_parser.add_argument(
        "--config",
        default=None,
        help="Path to YAML configuration file (defaults to data/config.yaml)",
    )
    generate_parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed (defaults to seed_train in config)",
    )
    generate_parser.add_argument(
        "--output",
        default="data/generated/train.json",
        help="Path to output main dataset JSON (defaults to data/generated/train.json)",
    )
    generate_parser.add_argument(
        "--customers",
        type=int,
        default=None,
        help="Optional customer count override (e.g. for smoke testing)",
    )

    # split subcommand
    split_parser = subparsers.add_parser(
        "split", help="Generate disjoint train/validation/test splits and manifest"
    )
    split_parser.add_argument(
        "--config",
        default=None,
        help="Path to YAML configuration file (defaults to data/config.yaml)",
    )
    split_parser.add_argument(
        "--output-dir",
        default="data/generated/splits",
        help="Directory to write split datasets and manifest (defaults to data/generated/splits)",
    )

    # migrate subcommand
    migrate_parser = subparsers.add_parser("migrate", help="Apply schema migrations")
    migrate_parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL connection URL (defaults to DATABASE_URL environment variable)",
    )
    migrate_parser.add_argument(
        "--schema",
        default=os.environ.get("DATABASE_SCHEMA"),
        help="Optional database schema (search_path)",
    )

    # seed subcommand
    seed_parser = subparsers.add_parser("seed", help="Load synthetic seed dataset")
    seed_parser.add_argument(
        "--dataset",
        required=True,
        help="Path to JSON dataset file",
    )
    seed_parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL connection URL (defaults to DATABASE_URL environment variable)",
    )
    seed_parser.add_argument(
        "--schema",
        default=os.environ.get("DATABASE_SCHEMA"),
        help="Optional database schema (search_path)",
    )

    # demo-seed subcommand
    demo_seed_parser = subparsers.add_parser(
        "demo-seed", help="Load deterministic demo seed fixtures (namespace 777)"
    )
    demo_seed_parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL connection URL (defaults to DATABASE_URL environment variable)",
    )
    demo_seed_parser.add_argument(
        "--schema",
        default=os.environ.get("DATABASE_SCHEMA"),
        help="Optional database schema (search_path)",
    )
    demo_seed_parser.add_argument(
        "--config",
        default=None,
        help="Path to YAML configuration file (defaults to data/config.yaml)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute CLI command with error handling and credential sanitization."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "generate":
        try:
            cfg = load_config(args.config)
            seed = args.seed if args.seed is not None else cfg["simulation"]["seed_train"]
            output_file = Path(args.output)
            output_file.parent.mkdir(parents=True, exist_ok=True)

            main_data, sidecar_data = generate_dataset(
                config=cfg,
                seed=seed,
                customers=args.customers,
                return_observations=True,
            )

            main_bytes = json.dumps(main_data, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
            sidecar_bytes = json.dumps(sidecar_data, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )

            output_file.write_bytes(main_bytes)

            if output_file.name.endswith(".json"):
                obs_file = output_file.with_name(output_file.stem + ".observations.json")
            else:
                obs_file = output_file.with_suffix(".observations.json")
            obs_file.write_bytes(sidecar_bytes)

            main_hash = hashlib.sha256(main_bytes).hexdigest()
            u_count = len(main_data["users"])
            a_count = len(main_data["agents"])
            t_count = len(main_data["transactions"])
            s_count = len(main_data["sessions"])
            print(
                f"Generated dataset (seed={seed}): {u_count} users, {a_count} agents, "
                f"{t_count} transactions, {s_count} sessions."
            )
            print(f"Checksum (SHA-256): {main_hash}")
            return 0
        except Exception as exc:
            print(f"Generation error ({type(exc).__name__}): {exc}", file=sys.stderr)
            return 1

    if args.command == "split":
        try:
            cfg = load_config(args.config)
            out_dir = Path(args.output_dir)
            print(f"Generating disjoint dataset splits into {out_dir}...")
            result = generate_splits(config=cfg, output_dir=out_dir)
            manifest = result["manifest"]
            print("Successfully generated disjoint dataset splits:")
            for c_name in ("train", "validation", "test"):
                c_info = manifest["cohorts"][c_name]
                print(
                    f"  - {c_name} (seed={c_info['seed']}): {c_info['customer_count']} customers, "
                    f"{c_info['agent_count']} agents ({c_info['counts']['transactions']} txns, "
                    f"{c_info['counts']['sessions']} sessions) "
                    f"[SHA-256: {c_info['content_sha256'][:16]}...]"
                )

            shifted_res = generate_shifted_test_split(config=cfg, output_dir=out_dir)
            s_meta = shifted_res["metadata"]
            print(
                f"  - test_shifted (seed={s_meta['seed']}): {s_meta['customer_count']} customers, "
                f"{s_meta['agent_count']} agents ({s_meta['counts']['transactions']} txns, "
                f"{s_meta['counts']['sessions']} sessions) "
                f"[SHA-256: {s_meta['content_sha256'][:16]}...]"
            )
            print(
                f"Split manifest (config SHA-256: {manifest['config_sha256'][:16]}...) "
                f"written to {out_dir / 'manifest.json'}"
            )
            print(f"Shifted test metadata written to {out_dir / 'test_shifted.meta.json'}")
            return 0
        except Exception as exc:
            print(f"Split generation error ({type(exc).__name__}): {exc}", file=sys.stderr)
            return 1

    # Database commands (migrate, seed) require DATABASE_URL
    db_url = args.database_url
    if not db_url:
        print(
            "Error: DATABASE_URL must be provided via --database-url "
            "or DATABASE_URL environment variable.",
            file=sys.stderr,
        )
        return 1

    if args.command == "migrate":
        print("Applying migrations...")
        try:
            applied = run_migrations(db_url=db_url, schema=args.schema)
            if applied:
                print(f"Applied {len(applied)} migration(s): {', '.join(applied)}")
            else:
                print("Migrations are up to date. (0 applied)")
            return 0
        except MigrationError as exc:
            print(f"Migration error: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"Failed to apply migrations ({type(exc).__name__})", file=sys.stderr)
            return 1

    elif args.command == "seed":
        dataset_path = Path(args.dataset)
        if not dataset_path.is_file():
            print(f"Error: Dataset file not found: {dataset_path}", file=sys.stderr)
            return 1

        print(f"Loading synthetic dataset from {dataset_path}...")
        try:
            result = load_seed(db_url=db_url, dataset=dataset_path, schema=args.schema)
            status = result.get("status")
            if status == "noop":
                print(result.get("message", "Dataset already seeded; no-op."))
            else:
                counts = result.get("counts", {})
                print(
                    f"Dataset seeded successfully: {counts.get('users', 0)} users, "
                    f"{counts.get('agents', 0)} agents, "
                    f"{counts.get('transactions', 0)} transactions, "
                    f"{counts.get('sessions', 0)} sessions."
                )
            return 0
        except ValidationError as exc:
            print(f"Validation error in dataset: {exc}", file=sys.stderr)
            return 1
        except SeedCollisionError as exc:
            print(f"Seed collision error: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"Failed to seed dataset ({type(exc).__name__})", file=sys.stderr)
            return 1

    elif args.command == "demo-seed":
        print("Seeding deterministic demo fixtures (namespace 777)...")
        try:
            from app.data.demo_seed import seed_demo_fixtures

            res = seed_demo_fixtures(
                db_url=db_url,
                schema=args.schema,
                config_path=args.config,
            )
            print(res.get("message", "Demo fixtures processed."))
            return 0
        except Exception as exc:
            print(f"Failed to seed demo fixtures ({type(exc).__name__}): {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
