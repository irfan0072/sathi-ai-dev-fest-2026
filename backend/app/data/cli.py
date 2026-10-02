"""Command-line interface for Sathi database migrations and dataset seeding."""

import argparse
import os
import sys
from pathlib import Path

from app.data.database import (
    MigrationError,
    SeedCollisionError,
    ValidationError,
    load_seed,
    run_migrations,
)


def build_parser() -> argparse.ArgumentParser:
    """Build command-line parser for database migrations and seeding."""
    parser = argparse.ArgumentParser(
        prog="python -m app.data.cli",
        description="Sathi database migration and seed CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

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

    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute CLI command with error handling and credential sanitization."""
    parser = build_parser()
    args = parser.parse_args(argv)

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

    return 0


if __name__ == "__main__":
    sys.exit(main())
