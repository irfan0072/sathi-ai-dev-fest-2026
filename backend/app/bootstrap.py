"""Fail-closed service startup; reuse migrations and the idempotent demo seed only."""

from __future__ import annotations

import os
import sys
from typing import Any

from psycopg.conninfo import make_conninfo

from app.analytics.service import AnalyticsService
from app.auth.jwt import get_jwt_secret, is_jwt_secret_configured
from app.data.config import load_config
from app.data.database import get_connection, run_migrations
from app.data.demo_seed import seed_demo_fixtures


class BootstrapError(RuntimeError):
    """Safe startup diagnostic, without underlying credentials or file contents."""


def verify_artifacts() -> None:
    """Validate trusted local JSON, hashes and current configuration; never load models."""
    AnalyticsService().get_metrics_summary()


def database_ready(
    config: dict[str, Any], db_url: str | None = None, schema: str | None = None
) -> bool:
    """Probe connectivity, migrated tables and the configured small demo namespace."""
    url = db_url or os.getenv("DATABASE_URL")
    if not url:
        return False
    principals = config["auth"]["principals"]
    try:
        with get_connection(make_conninfo(url, connect_timeout=3), schema=schema) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT (SELECT count(*) FROM schema_migrations) >= 2, "
                    "EXISTS(SELECT 1 FROM users WHERE user_id = %s), "
                    "EXISTS(SELECT 1 FROM agents WHERE agent_id = %s), "
                    "EXISTS(SELECT 1 FROM transactions WHERE user_id = %s)",
                    (principals["demo_customer"]["subject"],
                     principals["demo_agent"]["subject"],
                     principals["demo_customer"]["subject"]),
                )
                return all(cur.fetchone())
    except Exception:
        return False


def readiness() -> dict[str, str]:
    """Actual readiness for the existing health endpoint, with safe failure states."""
    signing = is_jwt_secret_configured()
    try:
        config = load_config()
        verify_artifacts()
        artifacts = True
    except Exception:
        config = None
        artifacts = False
    database = bool(config is not None and database_ready(config))
    return {
        "status": "ok" if signing and artifacts and database else "degraded",
        "database": "ready" if database else "unavailable",
        "auth_signing": "configured" if signing else "unconfigured",
        "artifacts": "verified" if artifacts else "unavailable",
    }


def _seed_staff(url: str, schema: str | None, config: dict[str, Any]) -> None:
    """Mirror config staff and demo supervisors into the staff table (idempotent)."""
    from app.staff.service import StaffService

    StaffService(lambda: get_connection(url, schema=schema)).seed(
        config["auth"].get("principals", {}))


def prepare_runtime(db_url: str | None = None, schema: str | None = None) -> None:
    """Validate before writes, then preserve existing migrations, balances and cases."""
    url = db_url or os.getenv("DATABASE_URL")
    try:
        get_jwt_secret()
        config = load_config()
        verify_artifacts()
        if not url:
            raise ValueError("Database not configured")
    except Exception as exc:
        raise BootstrapError(
            "Startup preflight failed; check signing/config/artifacts/database."
        ) from exc
    try:
        run_migrations(url, schema=schema)
        seed_demo_fixtures(url, schema=schema)
        _seed_staff(url, schema, config)
        from app.live.rebase import rebase_ledger

        rebase_ledger(lambda: get_connection(url, schema=schema))
        try:
            from app.scam.seed import seed_scam_demo

            seed_scam_demo(lambda: get_connection(url, schema=schema))
        except Exception:
            pass  # demo scenario is optional; never block startup
        if not database_ready(config, db_url=url, schema=schema):
            raise ValueError("Database not ready")
    except Exception as exc:
        raise BootstrapError(
            "Startup database preparation failed; existing data preserved."
        ) from exc


def main() -> int:
    try:
        port = int(os.getenv("PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError("Invalid port")
    except ValueError:
        print("Startup failed: PORT must be an integer between 1 and 65535.", file=sys.stderr)
        return 1
    try:
        prepare_runtime()
    except BootstrapError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
