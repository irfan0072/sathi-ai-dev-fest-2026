"""Deterministic demo seed loader for namespace 777.

Provides isolated synthetic fixtures (U_777_000001, A_777_000001) with fixed
initial balance before the simulation anchor, disjoint from train/val/test cohorts.
Repeating this seed is strictly an idempotent no-op that never restores spent balances.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from typing import Any

from app.data.config import load_config
from app.data.database import SEED_LOCK_NAMESPACE, get_connection


class SeedCollisionError(RuntimeError):
    """Raised when synthetic demo seed encounters partial or colliding fixtures."""


def seed_demo_fixtures(
    db_url: str,
    schema: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Load isolated synthetic demo fixtures for namespace 777 into PostgreSQL.

    - Idempotent: If U_777_000001 already exists, performs zero writes and returns noop.
    - Never restores or overwrites spent balances.
    - Never touches training or validation ledger.
    - Safe concurrency via PostgreSQL advisory lock.
    """
    cfg = load_config(config_path)
    auth_cfg = cfg.get("auth", {})

    demo_seed = int(auth_cfg.get("demo_seed", 777))
    if demo_seed <= 0:
        raise ValueError(f"demo_seed must be positive integer, got {demo_seed}")

    initial_balance_val = auth_cfg.get("demo_initial_balance", 50000)
    try:
        initial_balance = Decimal(str(initial_balance_val))
    except Exception as exc:
        raise ValueError(f"Invalid demo_initial_balance: {initial_balance_val}") from exc
    if not initial_balance.is_finite() or initial_balance <= 0:
        raise ValueError(f"demo_initial_balance must be positive and finite, got {initial_balance}")
    if initial_balance != initial_balance.quantize(Decimal("0.01")):
        raise ValueError("demo_initial_balance must have at most 2 decimal places")

    credit_ts_str = auth_cfg.get("demo_credit_timestamp", "2026-09-30T00:00:00Z")
    try:
        parsed_ts = datetime.datetime.fromisoformat(credit_ts_str)
        if parsed_ts.tzinfo is None:
            raise ValueError("demo_credit_timestamp must include timezone offset")
    except Exception as exc:
        raise ValueError(f"Invalid demo_credit_timestamp: {credit_ts_str}") from exc

    principals = auth_cfg.get("principals", {})
    demo_agent_cfg = principals.get("demo_agent", {})
    demo_customer_cfg = principals.get("demo_customer", {})

    demo_user_id = str(demo_customer_cfg.get("subject", f"U_{demo_seed}_000001"))
    demo_agent_id = str(demo_agent_cfg.get("subject", f"A_{demo_seed}_000001"))

    if not demo_user_id.startswith(f"U_{demo_seed}_"):
        raise ValueError(
            f"demo_customer subject '{demo_user_id}' does not match namespace {demo_seed}"
        )
    if not demo_agent_id.startswith(f"A_{demo_seed}_"):
        raise ValueError(
            f"demo_agent subject '{demo_agent_id}' does not match namespace {demo_seed}"
        )

    demo_txn_id = int(f"{demo_seed}000001")

    conn = get_connection(db_url, schema=schema)
    try:
        # Acquire advisory lock for demo seed
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s, %s);", (SEED_LOCK_NAMESPACE, demo_seed))
        conn.commit()

        try:
            # Check existing fixtures for collision or idempotency
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM users WHERE user_id = %s;", (demo_user_id,))
                user_exists = cur.fetchone()[0] > 0

                cur.execute("SELECT count(*) FROM agents WHERE agent_id = %s;", (demo_agent_id,))
                agent_exists = cur.fetchone()[0] > 0

                cur.execute(
                    "SELECT count(*), COALESCE(max(user_id), '') FROM transactions "
                    "WHERE txn_id = %s;",
                    (demo_txn_id,),
                )
                txn_row = cur.fetchone()
                txn_exists = txn_row[0] > 0
                txn_user = txn_row[1]

            if user_exists and agent_exists and txn_exists:
                if txn_user != demo_user_id:
                    raise SeedCollisionError(
                        f"Transaction {demo_txn_id} belongs to '{txn_user}', "
                        f"not '{demo_user_id}'."
                    )
                return {
                    "status": "noop",
                    "seed": demo_seed,
                    "message": (
                        f"Demo fixtures for seed {demo_seed} ({demo_user_id}) already exist. "
                        "No-op; spent balances are strictly preserved."
                    ),
                }

            if user_exists or agent_exists or txn_exists:
                raise SeedCollisionError(
                    f"Partial demo fixture or collision detected for namespace {demo_seed}: "
                    f"user_exists={user_exists}, agent_exists={agent_exists}, "
                    f"txn_exists={txn_exists}."
                )

            # Transactionally seed demo fixtures
            with conn.transaction():
                with conn.cursor() as cur:
                    # 1. Insert demo user
                    cur.execute(
                        """
                        INSERT INTO users (
                            user_id, group_label, gender, age_band, region, urban_rural, created_at
                        ) VALUES (
                            %s, 'independent_urban', 'female', '26-40', 'dhaka', 'urban',
                            %s::timestamptz
                        );
                        """,
                        (demo_user_id, credit_ts_str),
                    )

                    # 2. Insert demo agent
                    cur.execute(
                        """
                        INSERT INTO agents (
                            agent_id, region, volume_band, agent_type, created_at
                        ) VALUES (%s, 'dhaka', 'high', 'high_volume_honest', %s::timestamptz);
                        """,
                        (demo_agent_id, credit_ts_str),
                    )

                    # 3. Insert initial credit transaction before simulation anchor (no session)
                    cur.execute(
                        """
                        INSERT INTO transactions (
                            txn_id, user_id, agent_id, txn_type, credit_source,
                            amount, fee, balance_after, channel, ts
                        ) VALUES (
                            %s, %s, NULL, 'credit', 'salary', %s, 0.00, %s, 'app', %s::timestamptz
                        );
                        """,
                        (
                            demo_txn_id,
                            demo_user_id,
                            initial_balance,
                            initial_balance,
                            credit_ts_str,
                        ),
                    )

                    # 4. Record metadata
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS dataset_metadata (
                            seed BIGINT PRIMARY KEY,
                            checksum TEXT NOT NULL,
                            record_counts JSONB NOT NULL,
                            loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
                        );
                        """
                    )
                    cur.execute(
                        """
                        INSERT INTO dataset_metadata (seed, checksum, record_counts, loaded_at)
                        VALUES (%s, %s, %s::jsonb, now())
                        ON CONFLICT (seed) DO NOTHING;
                        """,
                        (
                            demo_seed,
                            f"synthetic_demo_seed_{demo_seed}",
                            json.dumps(
                                {"users": 1, "agents": 1, "transactions": 1}
                            ),
                        ),
                    )

            # Update serial sequence to avoid ID collision with explicit demo_txn_id
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DO $$
                    DECLARE
                        txn_seq TEXT;
                        max_txn BIGINT;
                    BEGIN
                        txn_seq := pg_get_serial_sequence('transactions', 'txn_id');
                        IF txn_seq IS NOT NULL THEN
                            SELECT MAX(txn_id) INTO max_txn FROM transactions;
                            IF max_txn IS NOT NULL THEN
                                PERFORM setval(txn_seq, max_txn, true);
                            END IF;
                        END IF;
                    END $$;
                    """
                )
            conn.commit()

            return {
                "status": "loaded",
                "seed": demo_seed,
                "message": (
                    f"Successfully seeded demo fixtures for namespace {demo_seed}: "
                    f"user '{demo_user_id}', agent '{demo_agent_id}', "
                    f"balance {initial_balance} BDT."
                ),
            }

        finally:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT pg_advisory_unlock(%s, %s);",
                        (SEED_LOCK_NAMESPACE, demo_seed),
                    )
                conn.commit()
            except Exception:
                pass
    finally:
        conn.close()
