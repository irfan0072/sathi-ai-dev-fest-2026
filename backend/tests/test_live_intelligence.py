"""Live AI on the current database: agent risk, outreach, liquidity, uplift, ledger rebase."""

from __future__ import annotations

import datetime

import pytest
from app.live import intelligence
from app.live.rebase import rebase_ledger
from app.main import app
from app.mandates.service import MandateService
from fastapi.testclient import TestClient
from tests.conftest import create_test_token

client = TestClient(app)
ANALYST = {"Authorization": f"Bearer {create_test_token('analyst_1', 'analyst')}"}
ADMIN = {"Authorization": f"Bearer {create_test_token('admin_777', 'super_admin')}"}
CUSTOMER = {"Authorization": f"Bearer {create_test_token('U_001', 'customer_channel')}"}


def _seed_ledger(service: MandateService) -> None:
    """60 days of live history: 8 agents (A_LV_8 overcharges), 300 customers with sessions."""
    with service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO agents (agent_id, region, volume_band, agent_type)
            SELECT 'A_LV_' || g, 'dhaka', 'medium', 'normal' FROM generate_series(1, 8) g;
            INSERT INTO users (user_id, group_label, gender, age_band, region, urban_rural)
            SELECT 'U_LV_' || g,
                   CASE WHEN g % 3 = 0 THEN 'assisted_allowance' ELSE 'independent_urban' END,
                   'female', '26-40', 'dhaka', 'urban'
            FROM generate_series(1, 300) g;
            INSERT INTO transactions (user_id, agent_id, txn_type, credit_source, amount, fee,
                                      balance_after, channel, ts)
            SELECT 'U_LV_' || g, NULL, 'credit', 'salary', 20000, 0, 20000, 'app',
                   now() - make_interval(days => 45 + g % 10)
            FROM generate_series(1, 300) g;
            INSERT INTO transactions (user_id, agent_id, txn_type, credit_source, amount, fee,
                                      balance_after, channel, ts)
            SELECT 'U_LV_' || (1 + (d * 7 + k) % 300), 'A_LV_' || (1 + k % 8), 'cash_out', NULL,
                   1000 + (k % 5) * 500,
                   round((1000 + (k % 5) * 500) * 0.015
                         * CASE WHEN k % 8 = 7 THEN 1.8 ELSE 1 END, 2),
                   10000, 'agent_initiated',
                   now() - make_interval(days => d, hours => k % 20)
            FROM generate_series(0, 59) d, generate_series(0, 23) k;
            INSERT INTO sessions (user_id, txn_id, pin_retries, pin_entry_ms, steps, ts)
            SELECT t.user_id, t.txn_id, (t.txn_id % 3)::int, 4000 + (t.txn_id % 9) * 1500,
                   3 + (t.txn_id % 4)::int, t.ts
            FROM transactions t WHERE t.user_id LIKE 'U_LV_%';
        """)
        conn.commit()


@pytest.fixture(autouse=True)
def live_db(durable_service: MandateService):
    intelligence.CACHE.clear()
    _seed_ledger(durable_service)
    yield durable_service
    intelligence.CACHE.clear()


def test_agent_risk_board_ranks_overcharging_agent_first():
    res = client.get("/api/v1/agents/risk-board", headers=ANALYST)
    assert res.status_code == 200, res.text
    board = res.json()
    ids = [a["agent_id"] for a in board["agents"]]
    assert ids[0] == "A_LV_8"
    assert all(0 <= a["risk"] <= 1 for a in board["agents"])
    assert board["window_days"] == 30 and board["computed_at"]
    one = client.get("/api/v1/agents/A_LV_8/risk", headers=ADMIN).json()
    assert one["reasons"][0]["feature"] == "fee_ratio_vs_official"
    assert one["reasons"][0]["value"] > 1.5
    assert one["provenance"] == "live database, last 30 days"
    assert client.get("/api/v1/agents/A_NOBODY/risk", headers=ANALYST).status_code == 404


def test_confirmations_feed_cash_gap_feature(live_db):
    with live_db.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT txn_id, user_id, amount FROM transactions WHERE agent_id = 'A_LV_2' "
                    "AND txn_type = 'cash_out' ORDER BY ts DESC LIMIT 3;")
        for txn_id, user_id, amount in cur.fetchall():
            cur.execute("INSERT INTO txn_checks (txn_id, user_id, agent_id, amount, status, "
                        "outcome, stated_amount) VALUES (%s, %s, 'A_LV_2', %s, 'suspicious', "
                        "'mismatch', %s);", (txn_id, user_id, amount, float(amount) - 500))
        conn.commit()
    agent = client.get("/api/v1/agents/A_LV_2/risk", headers=ANALYST).json()
    assert agent["features"]["agent_cash_gap_rate"] == 1.0
    assert agent["suspicious_30d"] == 3


def test_outreach_scores_active_customers():
    res = client.get("/api/v1/outreach", headers=ANALYST)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["scored_customers"] >= 200 and data["is_sample"] is False
    scores = [i["assisted_score"] for i in data["items"]]
    assert scores == sorted(scores, reverse=True) and 0 <= scores[-1] <= scores[0] <= 1
    one = client.get("/api/v1/users/U_LV_3/assisted-score", headers=ANALYST).json()
    assert 0 <= one["score"] <= 1 and one["provenance"] == "live database, last 30 days"
    assert client.get("/api/v1/outreach", headers=CUSTOMER).status_code == 403


def test_liquidity_forecasts_from_today():
    res = client.get("/api/v1/liquidity/overview", headers=ADMIN)
    assert res.status_code == 200, res.text
    data = res.json()
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=6))).date()
    assert data["forecast_origin"] == today.isoformat()
    assert data["provenance"]["source"] == "live database"
    own = {"Authorization": f"Bearer {create_test_token('A_LV_1', 'agent', [])}"}
    mine = client.get("/api/v1/liquidity/agents/A_LV_1", headers=own).json()
    assert len(mine["days"]) == 7 and mine["basis"].startswith("own live")
    assert mine["days"][0]["date"] == (today + datetime.timedelta(days=1)).isoformat()


def test_uplift_trains_on_live_customers():
    res = client.get("/api/v1/campaigns/uplift", headers=ANALYST)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["provenance"]["customers"] >= 200
    plan = client.post("/api/v1/campaigns/optimize", headers=ANALYST, json={"budget_bdt": 500})
    assert plan.status_code == 200 and plan.json()["spent_bdt"] <= 500


def test_rebase_moves_future_cohort_rows_to_the_past(live_db):
    with live_db.get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO users (user_id, group_label) VALUES ('U_42_123456', "
                    "'independent_urban');")
        cur.execute("INSERT INTO transactions (user_id, txn_type, amount, ts) VALUES "
                    "('U_42_123456', 'credit', 100, now() + interval '20 days 3 hours');")
        conn.commit()
    first = rebase_ledger(live_db.get_connection)
    assert first["shift_days"] == 21 and first["transactions"] >= 1
    assert rebase_ledger(live_db.get_connection)["shift_days"] == 0
    with live_db.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT ts <= now() FROM transactions WHERE user_id = 'U_42_123456';")
        assert cur.fetchone()[0] is True
        cur.execute("SELECT ts < now() - interval '1 day' FROM transactions "
                    "WHERE user_id = 'U_LV_1' AND txn_type = 'credit';")
        assert cur.fetchone()[0] is True  # live rows untouched


def test_snapshot_survives_restart(durable_service: MandateService):
    """A restart serves the last saved result at once, marked stale so it is retrained."""
    import numpy as np

    intelligence.CACHE.clear()
    value = {"agents": [{"agent_id": "A_001", "score": np.float64(0.42)}], "computed_at": "t"}
    intelligence._save_snapshot(durable_service, "agent_risk", value)
    intelligence._load_snapshots(durable_service)
    loaded = intelligence.CACHE.peek("agent_risk")
    assert loaded["agents"][0]["score"] == 0.42
    stamp = intelligence.CACHE._values["agent_risk"][0]
    assert intelligence.time.monotonic() - stamp > intelligence.TTL["agent_risk"]
    intelligence.CACHE.clear()


def test_failed_model_answers_at_once_instead_of_waiting(monkeypatch):
    """Too little live data must not make the page wait 20 seconds."""
    import time

    class _Alive:
        def is_alive(self):
            return True

    intelligence.CACHE.clear()
    monkeypatch.setattr(intelligence, "_thread", _Alive())
    monkeypatch.setitem(intelligence.FAILURES, "uplift",
                        (time.monotonic(), "Not enough active customers"))
    started = time.monotonic()
    with pytest.raises(intelligence.WarmingUp, match="Not enough active customers"):
        intelligence.CACHE.get("uplift", 60, lambda: {}, stale_ok=True)
    assert time.monotonic() - started < 1
