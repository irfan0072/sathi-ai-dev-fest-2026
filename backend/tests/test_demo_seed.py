"""Tests for deterministic demo seed namespace 777 and local init helper."""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from app.data.database import get_connection, run_migrations
from app.data.demo_seed import seed_demo_fixtures
from app.mandates.service import MandateService

from scripts.init_env import init_env


def test_seed_demo_fixtures_idempotent_and_spent_balance_preservation(
    test_db_url: str,
    test_schema: str,
) -> None:
    """Verify demo fixtures seed into namespace 777, repeat is noop,
    and spent balance is preserved."""
    # 1. First seed into fresh migrated schema
    res1 = seed_demo_fixtures(db_url=test_db_url, schema=test_schema)
    assert res1["status"] == "loaded"
    assert res1["seed"] == 777

    # 2. Verify seeded records in PostgreSQL
    with get_connection(test_db_url, schema=test_schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, group_label, region FROM users WHERE user_id = 'U_777_000001';"
            )
            u_row = cur.fetchone()
            assert u_row is not None
            assert u_row[0] == "U_777_000001"

            cur.execute(
                "SELECT agent_id, agent_type FROM agents WHERE agent_id = 'A_777_000001';"
            )
            a_row = cur.fetchone()
            assert a_row is not None
            assert a_row[0] == "A_777_000001"

            cur.execute(
                """
                SELECT amount, balance_after, txn_type, credit_source, ts
                FROM transactions WHERE user_id = 'U_777_000001';
                """
            )
            t_row = cur.fetchone()
            assert t_row is not None
            assert Decimal(str(t_row[0])) == Decimal("50000.00")
            assert Decimal(str(t_row[1])) == Decimal("50000.00")
            assert t_row[2] == "credit"
            # Verify timestamp is before simulation anchor (2026-10-01)
            ts_iso = t_row[4].isoformat()
            assert "2026-09-30" in ts_iso

            # Invariant: No PIN session for initial incoming credit transaction
            cur.execute("SELECT count(*) FROM sessions WHERE user_id = 'U_777_000001';")
            assert cur.fetchone()[0] == 0

    # 3. Repeating seed immediately is an idempotent no-op
    res2 = seed_demo_fixtures(db_url=test_db_url, schema=test_schema)
    assert res2["status"] == "noop"
    assert "spent balances are strictly preserved" in res2["message"]

    # 4. Perform cash-out spending balance
    service = MandateService(db_url=test_db_url, schema=test_schema)
    req = service.request_mandate(
        user_id="U_777_000001",
        agent_id="A_777_000001",
        amount=5000.0,
    )
    service.verify_mandate(mandate_id=req["mandate_id"], mode="keypad", stated_amount=5000.0)
    iss = service.issue_code(mandate_id=req["mandate_id"], actor="A_777_000001")
    service.redeem_mandate(mandate_id=req["mandate_id"], code=iss["code"], actor="A_777_000001")

    # 5. Check new balance in ledger: 50000 - 5000 - 75 = 44925
    with get_connection(test_db_url, schema=test_schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT balance_after FROM transactions
                WHERE user_id = 'U_777_000001'
                ORDER BY ts DESC, txn_id DESC LIMIT 1;
                """
            )
            bal = Decimal(str(cur.fetchone()[0]))
            assert bal == Decimal("44925.00")

    # 6. Re-running demo seed must NOT restore or overwrite the spent balance!
    res3 = seed_demo_fixtures(db_url=test_db_url, schema=test_schema)
    assert res3["status"] == "noop"

    with get_connection(test_db_url, schema=test_schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT balance_after FROM transactions
                WHERE user_id = 'U_777_000001'
                ORDER BY ts DESC, txn_id DESC LIMIT 1;
                """
            )
            bal_after_reseed = Decimal(str(cur.fetchone()[0]))
            assert bal_after_reseed == Decimal("44925.00")


def test_init_env_creates_fresh_and_preserves_valid(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Verify init_env generates secure secret when missing/placeholder and preserves valid."""
    env_file = tmp_path / ".env"
    example_file = tmp_path / ".env.example"
    example_file.write_text(
        "DATABASE_URL=postgresql://sathi:CHANGE_ME@localhost:5432/sathi\n"
        "JWT_SECRET=CHANGE_ME\n"
    )

    # 1. Missing .env: created with fresh random secret
    created = init_env(env_path=env_file, example_path=example_file)
    assert created is True
    assert env_file.is_file()
    content1 = env_file.read_text()
    match1 = re.search(r"^JWT_SECRET=([a-f0-9]{64})$", content1, re.MULTILINE)
    assert match1 is not None
    secret1 = match1.group(1)

    captured = capsys.readouterr()
    assert secret1 not in captured.out  # Secret never printed!

    # 2. Existing valid .env: preserved without change
    preserved = init_env(env_path=env_file, example_path=example_file)
    assert preserved is False
    content2 = env_file.read_text()
    match2 = re.search(r"^JWT_SECRET=([a-f0-9]{64})$", content2, re.MULTILINE)
    assert match2.group(1) == secret1

    # 3. Placeholder secret: replaced with fresh random secret
    env_file.write_text(
        "DATABASE_URL=postgresql://sathi:CHANGE_ME@localhost:5432/sathi\n"
        "JWT_SECRET=CHANGE_ME\n"
    )
    updated = init_env(env_path=env_file, example_path=example_file)
    assert updated is True
    content3 = env_file.read_text()
    match3 = re.search(r"^JWT_SECRET=([a-f0-9]{64})$", content3, re.MULTILINE)
    assert match3 is not None
    assert match3.group(1) != "CHANGE_ME"
    assert match3.group(1) != secret1


def test_seed_demo_fixtures_into_empty_migrated_schema(test_db_url: str) -> None:
    """Verify demo fixtures seed into empty migrated schema with no credit PIN session."""
    schema_name = f"sathi_seed_empty_{uuid.uuid4().hex[:10]}"
    conn = get_connection(test_db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA {schema_name};")
        conn.commit()
    finally:
        conn.close()

    try:
        # Run migrations into the isolated empty schema (zero users/agents)
        run_migrations(test_db_url, schema=schema_name)

        # Seed demo fixtures: must perform real first seed (not fixture noop)
        res = seed_demo_fixtures(db_url=test_db_url, schema=schema_name)
        assert res["status"] == "loaded"
        assert res["seed"] == 777

        # Verify real records were inserted into empty schema
        with get_connection(test_db_url, schema=schema_name) as c:
            with c.cursor() as cur:
                cur.execute("SELECT count(*) FROM users WHERE user_id = 'U_777_000001';")
                assert cur.fetchone()[0] == 1

                cur.execute("SELECT count(*) FROM agents WHERE agent_id = 'A_777_000001';")
                assert cur.fetchone()[0] == 1

                cur.execute(
                    "SELECT amount, txn_type, credit_source FROM transactions "
                    "WHERE user_id = 'U_777_000001';"
                )
                txn = cur.fetchone()
                assert txn is not None
                assert Decimal(str(txn[0])) == Decimal("50000.00")
                assert txn[1] == "credit"
                assert txn[2] == "salary"

                # Invariant: No PIN session for initial incoming credit
                cur.execute(
                    "SELECT count(*) FROM sessions WHERE user_id = 'U_777_000001';"
                )
                assert cur.fetchone()[0] == 0
    finally:
        cleanup_conn = get_connection(test_db_url)
        try:
            with cleanup_conn.cursor() as cur:
                cur.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE;")
            cleanup_conn.commit()
        finally:
            cleanup_conn.close()
