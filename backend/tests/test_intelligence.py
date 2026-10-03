"""Liquidity forecasting and uplift targeting: models, artifacts and APIs."""

from __future__ import annotations

import datetime
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from app.intelligence import liquidity, uplift
from app.intelligence.artifacts import IntelligenceArtifactError, load_artifact, write_artifacts
from app.main import app
from fastapi.testclient import TestClient
from tests.conftest import create_test_token

ROOT = Path(__file__).resolve().parents[2]
client = TestClient(app)
ANALYST = {"Authorization": f"Bearer {create_test_token('analyst_1', 'analyst')}"}


def _tiny_dataset(days: int = 70, agents: int = 6, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    start = datetime.datetime(2026, 10, 1, 4, tzinfo=datetime.timezone.utc)
    agent_rows = [{"agent_id": f"A{i}", "volume_band": ["low", "medium", "high"][i % 3]}
                  for i in range(agents)]
    users = [{"user_id": f"U{i}", "group_label": "assisted_allowance" if i % 2 else
              "independent_urban"} for i in range(60)]
    tx, sessions = [], []
    for d in range(days):
        for a in range(agents):
            for _ in range(int(rng.poisson(3 + a + (5 if d % 30 == 5 else 0)))):
                user = f"U{int(rng.integers(0, 60))}"
                ts = (start + datetime.timedelta(days=d, hours=int(rng.integers(0, 10))))
                tx.append({"agent_id": f"A{a}", "user_id": user, "txn_type": "cash_out",
                           "amount": float(rng.integers(5, 40) * 100), "ts": ts.isoformat(),
                           "channel": "agent_initiated"})
    for i in range(60):
        tx.append({"agent_id": None, "user_id": f"U{i}", "txn_type": "credit",
                   "amount": 5000.0, "ts": start.isoformat(), "channel": "app"})
        sessions.append({"user_id": f"U{i}", "pin_retries": i % 3, "pin_entry_ms": 6000 + i})
    return {"agents": agent_rows, "users": users, "transactions": tx, "sessions": sessions}


def test_liquidity_examples_never_use_target_window():
    data = _tiny_dataset()
    daily = liquidity.daily_cashout(data)
    origin = pd.Timestamp(sorted(daily["day"].unique())[30])
    examples = liquidity.build_examples(daily, data["agents"], [origin])
    assert set(examples["h"]) == set(range(1, 8))
    assert (examples["target_day"] > examples["origin"]).all()
    # Rolling features equal statistics computed from history up to the origin only.
    hist = daily[(daily["agent_id"] == "A0") & (daily["day"] <= origin)].tail(7)
    assert examples.loc[examples["agent_id"] == "A0", "mean_7"].iloc[0] == pytest.approx(
        hist["demand"].mean())


def test_liquidity_train_and_forecast_shape():
    result = liquidity.train_and_evaluate(_tiny_dataset())
    holdout = result["evaluation"]["time_holdout"]
    assert {"lightgbm", "seasonal_naive", "moving_average_7", "p90_coverage"} <= set(holdout)
    assert len(result["agents"]) == 6
    first = result["agents"][0]
    assert len(first["days"]) == 7
    assert all(day["p90_bdt"] >= day["forecast_bdt"] for day in first["days"])
    assert first["recommended_opening_float_bdt"] % 500 == 0


def test_uplift_policies_and_budget_optimizer():
    frame = uplift.simulate_experiment(uplift.user_features(_tiny_dataset()), seed=1)
    assert set(frame["treated"]) == {True, False}
    candidates = [
        {"user_id": "a", "predicted_uplift": 0.30, "p_if_contacted": 0.4, "p_if_not": 0.1},
        {"user_id": "b", "predicted_uplift": 0.05, "p_if_contacted": 0.9, "p_if_not": 0.85},
        {"user_id": "c", "predicted_uplift": -0.02, "p_if_contacted": 0.2, "p_if_not": 0.22},
    ]
    plan = uplift.optimize_budget(candidates, budget_bdt=4.0)
    assert plan["spent_bdt"] <= 4.0
    assert plan["skipped_non_positive_uplift"] == 1
    assert all(c["user_id"] != "c" for c in plan["first_contacts"])
    curve = uplift.qini_curve(np.array([0.9, 0.1, 0.5, 0.2]), np.array([True, False, True, False]),
                              np.array([True, False, False, False]), points=4)
    assert curve[0]["incremental"] == 0.0 and len(curve) == 5


def test_artifacts_hash_verified(tmp_path: Path):
    write_artifacts(tmp_path, {"liquidity": {"x": 1}, "uplift": {"y": 2}}, {"seed": 1})
    assert load_artifact("liquidity", tmp_path)["provenance"]["seed"] == 1
    (tmp_path / "uplift.json").write_text(json.dumps({"y": 3}))
    with pytest.raises(IntelligenceArtifactError):
        load_artifact("uplift", tmp_path)
    with pytest.raises(IntelligenceArtifactError):
        load_artifact("secrets", tmp_path)


def test_committed_artifacts_verify_and_api_roles(monkeypatch):
    directory = ROOT / "data/artifacts/intelligence"
    monkeypatch.setenv("SATHI_INTELLIGENCE_DIR", str(directory))
    overview = client.get("/api/v1/liquidity/overview", headers=ANALYST)
    assert overview.status_code == 200, overview.text
    data = overview.json()
    holdout = data["evaluation"]["time_holdout"]
    assert holdout["lightgbm"]["wape"] < holdout["moving_average_7"]["wape"]
    agent_id = data["agents"][0]["agent_id"]

    own = {"Authorization": f"Bearer {create_test_token(agent_id, 'agent', [])}"}
    assert client.get(f"/api/v1/liquidity/agents/{agent_id}", headers=own).status_code == 200
    assert client.get("/api/v1/liquidity/agents/A_other", headers=own).status_code == 403
    demo = {"Authorization": f"Bearer {create_test_token('A_777_000001', 'agent', [])}"}
    cohort = client.get("/api/v1/liquidity/agents/A_777_000001", headers=demo).json()
    assert cohort["basis"].startswith("peer cohort") and len(cohort["days"]) == 7
    assert client.get("/api/v1/liquidity/overview", headers=own).status_code == 403

    summary = client.get("/api/v1/campaigns/uplift", headers=ANALYST).json()
    assert summary["policies"]["uplift_t_learner"]["qini_coefficient"] > \
        summary["policies"]["random"]["qini_coefficient"]
    plan = client.post("/api/v1/campaigns/optimize", headers=ANALYST,
                       json={"budget_bdt": 5000}).json()
    assert plan["spent_bdt"] <= 5000 and plan["expected_incremental_enrollments"] > 0
    assert client.post("/api/v1/campaigns/optimize", headers=ANALYST,
                       json={"budget_bdt": 1}).status_code == 422


def test_tampered_artifact_returns_503(tmp_path: Path, monkeypatch):
    shutil.copytree(ROOT / "data/artifacts/intelligence", tmp_path / "intel")
    path = tmp_path / "intel" / "liquidity.json"
    path.write_text(path.read_text().replace("lightgbm", "lightgbx", 1))
    monkeypatch.setenv("SATHI_INTELLIGENCE_DIR", str(tmp_path / "intel"))
    res = client.get("/api/v1/liquidity/overview", headers=ANALYST)
    assert res.status_code == 503 and res.json()["error"]["code"] == "ARTIFACT_UNAVAILABLE"
