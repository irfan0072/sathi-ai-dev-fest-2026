"""Tests for Sathi database migrations, schema verification, and seed loader."""

import json
import os
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from app.data.database import (
    MigrationError,
    SeedCollisionError,
    ValidationError,
    compute_dataset_checksum,
    get_connection,
    load_seed,
    run_migrations,
    sanitize_database_url,
    validate_dataset,
)


def sample_valid_dataset() -> dict[str, Any]:
    """Return a minimal valid synthetic dataset fixture."""
    return {
        "schema_version": 1,
        "synthetic": True,
        "seed": 42,
        "users": [
            {
                "user_id": "U_000001",
                "group_label": "independent_urban",
                "gender": "female",
                "age_band": "26-40",
                "region": "dhaka",
                "urban_rural": "urban",
                "created_at": "2026-10-01T00:00:00Z",
            },
            {
                "user_id": "U_000002",
                "group_label": "assisted_allowance",
                "gender": "male",
                "age_band": "60+",
                "region": "rajshahi",
                "urban_rural": "rural",
                "created_at": "2026-10-01T00:00:00Z",
            },
        ],
        "agents": [
            {
                "agent_id": "A_000001",
                "region": "dhaka",
                "volume_band": "high",
                "agent_type": "high_volume_honest",
                "created_at": "2026-10-01T00:00:00Z",
            }
        ],
        "transactions": [
            {
                "txn_id": 101,
                "user_id": "U_000001",
                "agent_id": None,
                "txn_type": "credit",
                "credit_source": "salary",
                "amount": 5000.0,
                "fee": 0.0,
                "balance_after": 5000.0,
                "channel": "app",
                "ts": "2026-10-01T08:00:00Z",
            },
            {
                "txn_id": 102,
                "user_id": "U_000001",
                "agent_id": "A_000001",
                "txn_type": "cash_out",
                "credit_source": None,
                "amount": 1000.0,
                "fee": 15.0,
                "balance_after": 3985.0,
                "channel": "agent_initiated",
                "ts": "2026-10-01T10:00:00Z",
            },
        ],
        "sessions": [
            {
                "session_id": 201,
                "user_id": "U_000001",
                "txn_id": 101,
                "pin_retries": 0,
                "pin_entry_ms": 4200,
                "steps": 4,
                "ts": "2026-10-01T08:00:00Z",
            },
            {
                "session_id": 202,
                "user_id": "U_000001",
                "txn_id": 102,
                "pin_retries": 1,
                "pin_entry_ms": 7800,
                "steps": 5,
                "ts": "2026-10-01T10:00:00Z",
            },
        ],
    }


# =============================================================================
# Unit Tests: Schema Source Comparison & Credential Sanitization
# =============================================================================


def test_migration_exact_copy_of_docs_schema_sql():
    """Verify backend/migrations/001_initial.sql matches docs/schema.sql exactly."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    docs_schema = repo_root / "docs" / "schema.sql"
    migration_schema = repo_root / "backend" / "migrations" / "001_initial.sql"

    assert docs_schema.is_file(), f"docs/schema.sql not found at {docs_schema}"
    assert migration_schema.is_file(), f"001_initial.sql not found at {migration_schema}"

    docs_content = docs_schema.read_text(encoding="utf-8")
    mig_content = migration_schema.read_text(encoding="utf-8")

    assert mig_content == docs_content, "001_initial.sql must match docs/schema.sql exactly"


def test_sanitize_database_url_redacts_credentials():
    """Verify database URLs with credentials have passwords redacted."""
    url1 = "postgresql://sathi_user:super_secret@localhost:5432/sathidb"
    sanitized1 = sanitize_database_url(url1)
    assert "super_secret" not in sanitized1
    assert "sathi_user:***@localhost:5432/sathidb" in sanitized1

    url2 = "host=localhost dbname=sathi user=admin password=topsecret port=5432"
    sanitized2 = sanitize_database_url(url2)
    assert "topsecret" not in sanitized2
    assert "password=***" in sanitized2

    assert sanitize_database_url("") == ""
    assert sanitize_database_url(None) == ""


# =============================================================================
# Unit Tests: Pure Dataset Payload Validation
# =============================================================================


def test_validate_dataset_valid():
    """Verify a conforming synthetic dataset passes validation."""
    data = sample_valid_dataset()
    validate_dataset(data)


def test_validate_dataset_rejects_missing_top_level_field():
    """Reject dataset missing any required top-level key."""
    keys = (
        "schema_version",
        "synthetic",
        "seed",
        "users",
        "agents",
        "transactions",
        "sessions",
    )
    for key in keys:
        data = sample_valid_dataset()
        del data[key]
        with pytest.raises(ValidationError, match="missing keys"):
            validate_dataset(data)


def test_validate_dataset_rejects_unknown_top_level_field():
    """Reject dataset containing unknown top-level key."""
    data = sample_valid_dataset()
    data["extra_field"] = "unexpected"
    with pytest.raises(ValidationError, match="unknown keys"):
        validate_dataset(data)


def test_validate_dataset_rejects_invalid_schema_version_or_synthetic():
    """Reject dataset with non-1 schema_version or non-True synthetic flag."""
    data = sample_valid_dataset()
    data["schema_version"] = 2
    with pytest.raises(ValidationError, match="schema_version"):
        validate_dataset(data)

    data = sample_valid_dataset()
    data["synthetic"] = False
    with pytest.raises(ValidationError, match="synthetic"):
        validate_dataset(data)


def test_validate_dataset_rejects_unknown_field_in_records():
    """Reject real-looking free-text fields or unknown columns in records."""
    # Unknown field in user
    data = sample_valid_dataset()
    data["users"][0]["real_name"] = "Rahim Mia"
    with pytest.raises(ValidationError, match="unknown fields"):
        validate_dataset(data)

    # Unknown field in agent
    data = sample_valid_dataset()
    data["agents"][0]["phone_number"] = "+8801700000000"
    with pytest.raises(ValidationError, match="unknown fields"):
        validate_dataset(data)

    # Unknown field in transaction
    data = sample_valid_dataset()
    data["transactions"][0]["note"] = "Payment for goods"
    with pytest.raises(ValidationError, match="unknown fields"):
        validate_dataset(data)

    # Unknown field in session
    data = sample_valid_dataset()
    data["sessions"][0]["ip_address"] = "192.168.1.1"
    with pytest.raises(ValidationError, match="unknown fields"):
        validate_dataset(data)


def test_validate_dataset_rejects_invalid_id_prefix():
    """Reject non-synthetic IDs missing required U_ or A_ prefix."""
    data = sample_valid_dataset()
    data["users"][0]["user_id"] = "USER_123"
    with pytest.raises(ValidationError, match="user_id"):
        validate_dataset(data)

    data = sample_valid_dataset()
    data["agents"][0]["agent_id"] = "AGENT_999"
    with pytest.raises(ValidationError, match="agent_id"):
        validate_dataset(data)


def test_validate_dataset_rejects_invalid_enums_or_slices():
    """Reject unknown categories for domain enums and evaluation slices."""
    data = sample_valid_dataset()
    data["users"][0]["group_label"] = "malicious_user"
    with pytest.raises(ValidationError, match="group_label"):
        validate_dataset(data)

    data = sample_valid_dataset()
    data["users"][0]["region"] = "atlantis"
    with pytest.raises(ValidationError, match="region"):
        validate_dataset(data)

    data = sample_valid_dataset()
    data["agents"][0]["agent_type"] = "rogue_bot"
    with pytest.raises(ValidationError, match="agent_type"):
        validate_dataset(data)

    data = sample_valid_dataset()
    data["transactions"][0]["txn_type"] = "bitcoin_buy"
    with pytest.raises(ValidationError, match="txn_type"):
        validate_dataset(data)


def test_validate_dataset_rejects_missing_foreign_keys():
    """Reject records referencing non-existent foreign keys."""
    # Transaction references missing user
    data = sample_valid_dataset()
    data["transactions"][0]["user_id"] = "U_999999"
    with pytest.raises(ValidationError, match="missing foreign key"):
        validate_dataset(data)

    # Transaction references missing agent
    data = sample_valid_dataset()
    data["transactions"][1]["agent_id"] = "A_999999"
    with pytest.raises(ValidationError, match="missing foreign key"):
        validate_dataset(data)

    # Session references missing user
    data = sample_valid_dataset()
    data["sessions"][0]["user_id"] = "U_999999"
    with pytest.raises(ValidationError, match="missing foreign key"):
        validate_dataset(data)

    # Session references missing transaction
    data = sample_valid_dataset()
    data["sessions"][0]["txn_id"] = 999999
    with pytest.raises(ValidationError, match="missing foreign key"):
        validate_dataset(data)


def test_validate_dataset_rejects_inconsistent_relations():
    """Reject sessions referencing transactions belonging to a different user."""
    data = sample_valid_dataset()
    # session belongs to U_000002, but txn 101 belongs to U_000001
    data["sessions"][0]["user_id"] = "U_000002"
    with pytest.raises(ValidationError, match="inconsistent relations"):
        validate_dataset(data)


def test_validate_dataset_rejects_duplicate_ids():
    """Reject duplicate primary keys within dataset."""
    data = sample_valid_dataset()
    data["users"].append(deepcopy(data["users"][0]))
    with pytest.raises(ValidationError, match="Duplicate user_id"):
        validate_dataset(data)

    data = sample_valid_dataset()
    data["transactions"].append(deepcopy(data["transactions"][0]))
    with pytest.raises(ValidationError, match="Duplicate txn_id"):
        validate_dataset(data)


def test_validate_dataset_rejects_invalid_monetary_values():
    """Reject negative or zero amounts and negative fees."""
    data = sample_valid_dataset()
    data["transactions"][0]["amount"] = -100
    with pytest.raises(ValidationError, match="amount"):
        validate_dataset(data)

    data = sample_valid_dataset()
    data["transactions"][0]["fee"] = -5
    with pytest.raises(ValidationError, match="fee"):
        validate_dataset(data)


def test_compute_dataset_checksum_deterministic():
    """Verify checksum is deterministic regardless of key order."""
    data1 = sample_valid_dataset()
    data2 = json.loads(json.dumps(data1))
    # Reverse top-level order
    data2_reordered = {k: data2[k] for k in reversed(list(data2.keys()))}

    cs1 = compute_dataset_checksum(data1)
    cs2 = compute_dataset_checksum(data2_reordered)
    assert cs1 == cs2, "Checksum must be invariant to dictionary key order"


# =============================================================================
# Integration Tests: PostgreSQL Dedicated Test Database
# =============================================================================


@pytest.fixture
def test_db_schema():
    """Fixture providing dedicated test DB URL and disposable isolated schema."""
    test_db_url = os.environ.get("SATHI_TEST_DATABASE_URL")
    if not test_db_url:
        pytest.skip(
            "SATHI_TEST_DATABASE_URL not set; skipping integration tests"
        )

    # Generate isolated temporary schema
    schema_name = f"sathi_test_{uuid.uuid4().hex[:10]}"
    try:
        conn = get_connection(test_db_url)
    except Exception as e:
        pytest.skip(
            f"Could not connect to {sanitize_database_url(test_db_url)}: {e}"
        )

    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA {schema_name};")
        conn.commit()
    finally:
        conn.close()

    try:
        yield test_db_url, schema_name
    finally:
        # Disposable test schema cleanup inside test DB only
        conn = get_connection(test_db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE;")
            conn.commit()
        finally:
            conn.close()


def test_integration_migrate_twice(test_db_schema):
    """Verify migrations apply once and subsequent run is an idempotent no-op."""
    test_db_url, schema_name = test_db_schema

    # First migration run
    applied1 = run_migrations(test_db_url, schema=schema_name)
    assert "001_initial.sql" in applied1

    # Second migration run: should no-op
    applied2 = run_migrations(test_db_url, schema=schema_name)
    assert applied2 == [], "Second migration run should apply 0 migrations"

    # Verify schema_migrations table records migration
    conn = get_connection(test_db_url, schema=schema_name)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version, checksum FROM schema_migrations;")
            rows = cur.fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "001_initial.sql"
    finally:
        conn.close()


def test_integration_bad_checksum_refuse(test_db_schema):
    """Verify migration runner refuses execution if recorded checksum does not match file."""
    test_db_url, schema_name = test_db_schema

    # Apply initial migration
    run_migrations(test_db_url, schema=schema_name)

    # Manually tamper with checksum in schema_migrations
    conn = get_connection(test_db_url, schema=schema_name)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE schema_migrations SET checksum = 'tampered_bad_val' "
                "WHERE version = '001_initial.sql';"
            )
        conn.commit()
    finally:
        conn.close()

    # Subsequent migration must fail with MigrationError
    with pytest.raises(MigrationError, match="checksum mismatch"):
        run_migrations(test_db_url, schema=schema_name)


def test_integration_seed_and_repeat_count(test_db_schema):
    """Verify seeding dataset populates tables and exact repeat no-ops with unchanged count."""
    test_db_url, schema_name = test_db_schema

    # Run migrations first
    run_migrations(test_db_url, schema=schema_name)

    dataset = sample_valid_dataset()

    # First seed
    res1 = load_seed(test_db_url, dataset, schema=schema_name)
    assert res1["status"] == "loaded"

    # Verify counts in DB
    conn = get_connection(test_db_url, schema=schema_name)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM users;")
            user_count1 = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM agents;")
            agent_count1 = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM transactions;")
            txn_count1 = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM sessions;")
            sess_count1 = cur.fetchone()[0]

            assert user_count1 == len(dataset["users"])
            assert agent_count1 == len(dataset["agents"])
            assert txn_count1 == len(dataset["transactions"])
            assert sess_count1 == len(dataset["sessions"])

            # Verify no mandate rows seeded
            cur.execute("SELECT count(*) FROM mandates;")
            assert cur.fetchone()[0] == 0

        # Repeat exact seed: must return noop and preserve counts
        res2 = load_seed(test_db_url, dataset, schema=schema_name)
        assert res2["status"] == "noop"

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM users;")
            assert cur.fetchone()[0] == user_count1
            cur.execute("SELECT count(*) FROM agents;")
            assert cur.fetchone()[0] == agent_count1
            cur.execute("SELECT count(*) FROM transactions;")
            assert cur.fetchone()[0] == txn_count1
            cur.execute("SELECT count(*) FROM sessions;")
            assert cur.fetchone()[0] == sess_count1
    finally:
        conn.close()


def test_integration_malformed_seed_leaves_state_intact(test_db_schema):
    """Verify malformed seed fails validation and leaves prior database state intact."""
    test_db_url, schema_name = test_db_schema
    run_migrations(test_db_url, schema=schema_name)

    # Initial valid seed
    valid_data = sample_valid_dataset()
    load_seed(test_db_url, valid_data, schema=schema_name)

    # Check baseline row count
    conn = get_connection(test_db_url, schema=schema_name)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM users;")
            initial_count = cur.fetchone()[0]

        # Malformed seed (unknown field)
        bad_data = deepcopy(valid_data)
        bad_data["seed"] = 99
        bad_data["users"][0]["unauthorized_field"] = "bad"

        with pytest.raises(ValidationError):
            load_seed(test_db_url, bad_data, schema=schema_name)

        # Verify state is completely intact
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM users;")
            assert cur.fetchone()[0] == initial_count
    finally:
        conn.close()


def test_integration_conflicting_reseed_leaves_state_intact(test_db_schema):
    """Verify altered reseed with same seed or colliding IDs rejects and leaves state intact."""
    test_db_url, schema_name = test_db_schema
    run_migrations(test_db_url, schema=schema_name)

    data1 = sample_valid_dataset()
    load_seed(test_db_url, data1, schema=schema_name)

    # Modified data with the SAME seed (changed user region)
    data2 = deepcopy(data1)
    data2["users"][0]["region"] = "khulna"

    with pytest.raises(
        SeedCollisionError, match="Overwriting or reseeding modified data is rejected"
    ):
        load_seed(test_db_url, data2, schema=schema_name)

    # Verify original state preserved
    conn = get_connection(test_db_url, schema=schema_name)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT region FROM users WHERE user_id = 'U_000001';")
            assert cur.fetchone()[0] == "dhaka"
    finally:
        conn.close()


def test_integration_sequence_setval_preserves_max_id(test_db_schema):
    """Verify sequence setval preserves max explicit IDs so future serial inserts don't collide."""
    test_db_url, schema_name = test_db_schema
    run_migrations(test_db_url, schema=schema_name)

    data = sample_valid_dataset()
    # Explicit txn_id 101 and 102 in dataset
    load_seed(test_db_url, data, schema=schema_name)

    conn = get_connection(test_db_url, schema=schema_name)
    try:
        with conn.cursor() as cur:
            # Query nextval from transactions sequence
            cur.execute("SELECT nextval(pg_get_serial_sequence('transactions', 'txn_id'));")
            next_txn = cur.fetchone()[0]
            # Since max explicit txn_id is 102, nextval must be >= 103
            assert next_txn >= 103, f"Expected nextval >= 103, got {next_txn}"
    finally:
        conn.close()


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "1.001", "10000000000"])
def test_invalid_db_numeric_rejected(amount):
    data = sample_valid_dataset()
    data["transactions"][0]["amount"] = amount
    with pytest.raises(ValidationError):
        validate_dataset(data)


def test_naive_timestamp_and_named_id_rejected():
    data = sample_valid_dataset()
    data["transactions"][0]["ts"] = "2026-10-01T08:00:00"
    with pytest.raises(ValidationError):
        validate_dataset(data)
    data = sample_valid_dataset()
    data["users"][0]["user_id"] = "U_actual_person_name"
    with pytest.raises(ValidationError):
        validate_dataset(data)


def test_integration_migration_failure_rolls_back(test_db_schema, tmp_path):
    url, schema = test_db_schema
    (tmp_path / "001_bad.sql").write_text(
        "CREATE TABLE rollback_probe (id integer); SELECT 1/0;"
    )
    with pytest.raises(Exception):
        run_migrations(url, migrations_dir=tmp_path, schema=schema)
    with get_connection(url, schema=schema) as conn:
        assert conn.execute("SELECT to_regclass('rollback_probe')").fetchone()[0] is None
        assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 0


def test_integration_insert_failure_rolls_back_all_rows(test_db_schema):
    url, schema = test_db_schema
    run_migrations(url, schema=schema)
    with get_connection(url, schema=schema) as conn:
        conn.execute("ALTER TABLE transactions ADD CHECK (amount < 2000)")
    with pytest.raises(Exception):
        load_seed(url, sample_valid_dataset(), schema=schema)
    with get_connection(url, schema=schema) as conn:
        for table in ["users", "agents", "transactions", "sessions", "dataset_metadata"]:
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
