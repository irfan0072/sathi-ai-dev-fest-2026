"""Startup preflight, safe failure and real idempotent spent-balance preservation."""

from decimal import Decimal

import pytest
from app import bootstrap
from app.data.config import load_config
from app.data.database import get_connection
from app.mandates.service import MandateService
from artifact_fixture import write_test_bundle


@pytest.fixture
def valid_bundle(tmp_path, monkeypatch):
    directory = write_test_bundle(tmp_path / "bundle")
    monkeypatch.setenv("SATHI_ARTIFACTS_DIR", str(directory))
    bootstrap.verify_artifacts()
    return directory


@pytest.mark.parametrize("failure", ["signing", "artifacts", "database"])
def test_preflight_failure_precedes_any_database_writes(valid_bundle, monkeypatch, failure):
    writes = []
    monkeypatch.setattr(bootstrap, "run_migrations", lambda *a, **k: writes.append("migrate"))
    monkeypatch.setattr(bootstrap, "seed_demo_fixtures", lambda *a, **k: writes.append("seed"))
    if failure == "signing":
        monkeypatch.setenv("JWT_SECRET", "CHANGE_ME")
    elif failure == "artifacts":
        (valid_bundle / "results.json").write_text("tampered")
    else:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.prepare_runtime(db_url=None if failure == "database" else "fake")
    assert writes == []


def test_database_failure_does_not_serve_or_leak(valid_bundle, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://private:SECRET@invalid/db")
    attempts = []
    def fail(*a, **k):
        attempts.append("migration")
        raise ValueError("postgresql://private:SECRET@invalid/db")
    monkeypatch.setattr(bootstrap, "run_migrations", fail)
    assert bootstrap.main() == 1
    assert "SECRET" not in capsys.readouterr().err
    assert attempts == ["migration"]


def test_invalid_port_precedes_preparation(monkeypatch, capsys):
    monkeypatch.setenv("PORT", "99999")
    def unexpected():
        pytest.fail("Preparation must not run")
    monkeypatch.setattr(bootstrap, "prepare_runtime", unexpected)
    assert bootstrap.main() == 1
    assert "PORT" in capsys.readouterr().err


def test_ready_rejects_missing_tables_and_seed(test_db_url, monkeypatch):
    import uuid
    schema = "bootstrap_empty_" + uuid.uuid4().hex[:10]
    with get_connection(test_db_url) as conn:
        conn.execute(f"CREATE SCHEMA {schema}")
    try:
        assert bootstrap.database_ready(load_config(), test_db_url, schema) is False
    finally:
        with get_connection(test_db_url) as conn:
            conn.execute(f"DROP SCHEMA {schema} CASCADE")


def test_bootstrap_twice_after_spend_preserves_ledger(valid_bundle, test_db_url, test_schema):
    bootstrap.prepare_runtime(test_db_url, test_schema)
    service = MandateService(db_url=test_db_url, schema=test_schema)
    req = service.request_mandate("U_777_000001", "A_777_000001", 3000.0)
    mid = req["mandate_id"]
    service.verify_mandate(mid, "keypad", 3000.0)
    code = service.issue_code(mid, actor="A_777_000001")["code"]
    redemption = service.redeem_mandate(mid, code, actor="A_777_000001")
    bootstrap.prepare_runtime(test_db_url, test_schema)
    bootstrap.prepare_runtime(test_db_url, test_schema)
    with get_connection(test_db_url, schema=test_schema) as conn:
        balance = conn.execute(
            "SELECT balance_after FROM transactions WHERE txn_id=%s", (redemption["txn_id"],)
        ).fetchone()[0]
        assert balance == Decimal("46955.00")
        assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 2
    assert bootstrap.database_ready(load_config(), test_db_url, test_schema)
