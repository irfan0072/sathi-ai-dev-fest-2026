"""Shared test configuration, PostgreSQL disposable schema fixtures, and auth helpers."""

from __future__ import annotations

import os
import uuid
from typing import Generator

import pytest
from app.auth.jwt import create_access_token
from app.data.database import get_connection, run_migrations, sanitize_database_url
from app.mandates.router import set_mandate_service
from app.mandates.service import MandateService

TEST_JWT_SECRET = "test_synthetic_signing_secret_for_jwt_2026_0123456789"
os.environ["JWT_SECRET"] = TEST_JWT_SECRET


def create_test_token(
    subject: str,
    role: str,
    allowed_users: list[str] | None = None,
    expires_in_seconds: int = 1800,
    secret: str = TEST_JWT_SECRET,
) -> str:
    """Helper to generate signed test Bearer JWT tokens."""
    payload = {
        "sub": subject,
        "role": role,
        "principal": f"test_{role}_{subject}",
        "allowed_users": allowed_users or [],
        "scope": "synthetic_demo",
    }
    return create_access_token(payload, expires_in_seconds=expires_in_seconds, secret=secret)


@pytest.fixture(scope="session")
def test_db_url() -> str:
    """Return test database URL from environment or skip if unconfigured."""
    url = os.environ.get("SATHI_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SATHI_TEST_DATABASE_URL not set; skipping PostgreSQL tests")
    try:
        conn = get_connection(url)
        conn.close()
    except Exception as exc:
        pytest.skip(
            f"Could not connect to test database at {sanitize_database_url(url)}: {exc}"
        )
    return url


@pytest.fixture
def test_schema(test_db_url: str) -> Generator[str, None, None]:
    """Create an isolated, disposable schema for a test, run migrations, and clean up."""
    schema_name = f"sathi_test_{uuid.uuid4().hex[:12]}"
    conn = get_connection(test_db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA {schema_name};")
        conn.commit()
    finally:
        conn.close()

    try:
        # Run migrations 001 and 002 into the isolated test schema
        run_migrations(test_db_url, schema=schema_name)

        # Seed common test users and agents with ample credit (disjoint from demo 777 fixtures)
        seed_conn = get_connection(test_db_url, schema=schema_name)
        try:
            with seed_conn.transaction():
                with seed_conn.cursor() as cur:
                    test_users = [
                        ("U_001", "independent_urban"),
                        ("U_002", "independent_urban"),
                        ("U_DAILY", "independent_urban"),
                        ("U_EXP", "independent_urban"),
                        ("U_LOCK", "independent_urban"),
                        ("U_ONCE", "independent_urban"),
                        ("U_MIS", "independent_urban"),
                        ("U_ATT", "independent_urban"),
                        ("U_GAP", "independent_urban"),
                        ("U_REV", "independent_urban"),
                        ("U_REV2", "independent_urban"),
                        ("U_API_001", "independent_urban"),
                        ("U_API_002", "independent_urban"),
                        ("U_API_CONC", "independent_urban"),
                        ("U_API_LOCK", "independent_urban"),
                        ("U_API_GAP", "independent_urban"),
                        ("U_API_REV", "independent_urban"),
                        ("U_RCPT_01", "independent_urban"),
                        ("U_42_000008", "assisted_allowance"),
                    ]
                    for uid, grp in test_users:
                        cur.execute(
                            """
                            INSERT INTO users (
                                user_id, group_label, gender, age_band, region, urban_rural
                            )
                            VALUES (%s, %s, 'female', '26-40', 'dhaka', 'urban')
                            ON CONFLICT (user_id) DO NOTHING;
                            """,
                            (uid, grp),
                        )

                    test_agents = ["A_001", "A_002", "A_000042", "A_000015"]
                    for aid in test_agents:
                        cur.execute(
                            """
                            INSERT INTO agents (agent_id, region, volume_band, agent_type)
                            VALUES (%s, 'dhaka', 'high', 'high_volume_honest')
                            ON CONFLICT (agent_id) DO NOTHING;
                            """,
                            (aid,),
                        )

                    for uid, _ in test_users:
                        cur.execute(
                            """
                            INSERT INTO transactions (
                                user_id, agent_id, txn_type, credit_source,
                                amount, fee, balance_after, channel, ts
                            ) VALUES (
                                %s, NULL, 'credit', 'salary', 50000.00, 0.00, 50000.00, 'app',
                                '2026-09-30T00:00:00Z'::timestamptz
                            );
                            """,
                            (uid,),
                        )
        finally:
            seed_conn.close()

        yield schema_name
    finally:
        # Disposable test schema cleanup guaranteed even if setup or migrations fail
        cleanup_conn = get_connection(test_db_url)
        try:
            with cleanup_conn.cursor() as cur:
                cur.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE;")
            cleanup_conn.commit()
        finally:
            cleanup_conn.close()


@pytest.fixture
def durable_service(
    test_db_url: str,
    test_schema: str,
) -> Generator[MandateService, None, None]:
    """Fixture providing a MandateService instance bound to the isolated PostgreSQL test schema."""
    service = MandateService(db_url=test_db_url, schema=test_schema)
    set_mandate_service(service)
    try:
        yield service
    finally:
        set_mandate_service(None)


# ---------------------------------------------------------------------------
# Live (real-network) provider tests
# ---------------------------------------------------------------------------
# Tests in test_live_providers.py hit the real Twilio / Alpha SMS / Gemini /
# OpenAI / BD-IVR endpoints. They are NEVER run by default. Opt in explicitly:
#
#   SATHI_LIVE_TESTS=1 pytest tests/test_live_providers.py
#
# Each live test further checks for its own provider's env vars and skips
# individually if they are missing — so you can opt into one provider at a
# time without having to set every credential.

LIVE_TESTS_FLAG = "SATHI_LIVE_TESTS"


def _live_tests_enabled() -> bool:
    return os.environ.get(LIVE_TESTS_FLAG, "").strip() in ("1", "true", "yes")


@pytest.fixture
def live_tests_enabled() -> Generator[None, None, None]:
    """Skip unless SATHI_LIVE_TESTS=1 is set in the environment."""
    if not _live_tests_enabled():
        pytest.skip(f"{LIVE_TESTS_FLAG}=1 not set; skipping live provider test")
    yield


def require_live_env(*names: str) -> None:
    """Skip the current test if any required env var is missing.

    Used by live tests to opt into one provider at a time without forcing
    the caller to set every credential. Has no effect when live tests are
    disabled.
    """
    if not _live_tests_enabled():
        pytest.skip(f"{LIVE_TESTS_FLAG}=1 not set; skipping live provider test")
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        pytest.skip(f"Live test requires env: {', '.join(missing)}")


# Provider credentials, admin token and runtime toggles from a developer's .env must not
# leak into hermetic tests. Live provider tests keep them on purpose.
_HERMETIC_ENV = (
    "SATHI_SECRETS_KEY", "SATHI_SETTINGS_EDITABLE",
    "SATHI_VOICE_PROVIDER", "SATHI_SMS_PROVIDER", "SATHI_STEP_UP_ENFORCED",
    "SATHI_PUBLIC_API_URL", "SATHI_VOICE_PHONE_BOOK",
    "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER",
    "SATHI_BD_IVR_BASE_URL", "SATHI_BD_IVR_API_KEY", "SATHI_BD_IVR_WEBHOOK_SECRET",
    "ALPHA_SMS_API_KEY", "ALPHA_SMS_SENDER_ID", "GEMINI_API_KEY", "OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def _hermetic_provider_env(request, monkeypatch):
    if request.node.module.__name__.endswith("test_live_providers"):
        return
    for name in _HERMETIC_ENV:
        monkeypatch.delenv(name, raising=False)
