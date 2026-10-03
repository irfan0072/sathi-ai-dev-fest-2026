"""Artifact-backed HTTP responses fail closed and never load ML objects."""

from pathlib import Path

import pytest
from app.analytics.router import set_analytics_service
from app.analytics.service import AnalyticsService
from app.data.config import load_config
from app.main import app
from fastapi.testclient import TestClient
from tests.artifact_fixture import write_test_bundle
from tests.conftest import create_test_token


@pytest.fixture
def bundle_client(tmp_path: Path):
    directory = write_test_bundle(tmp_path / "bundle")
    set_analytics_service(AnalyticsService(artifact_dir=directory))
    yield TestClient(app), directory
    set_analytics_service(None)


def analyst_headers():
    return {"Authorization": "Bearer " + create_test_token("reviewer", "analyst")}


@pytest.mark.parametrize(
    "route",
    ["outreach", "metrics/summary", "users/U_fixture_1/assisted-score", "agents/A_fixture_1/risk"],
)
def test_snapshot_routes_require_analyst(bundle_client, route):
    client, _ = bundle_client
    assert client.get("/api/v1/" + route).status_code == 401
    headers = {"Authorization": "Bearer " + create_test_token("U_fixture_1", "customer_channel")}
    assert client.get("/api/v1/" + route, headers=headers).status_code == 403
    assert client.get("/api/v1/" + route, headers=analyst_headers()).status_code == 200


def test_unknown_snapshot_subject_not_invented(bundle_client):
    client, _ = bundle_client
    assert (
        client.get(
            "/api/v1/users/U_777_000001/assisted-score", headers=analyst_headers()
        ).status_code
        == 404
    )


def test_tamper_after_good_request_is_unavailable(bundle_client):
    client, directory = bundle_client
    assert client.get("/api/v1/outreach", headers=analyst_headers()).status_code == 200
    (directory / "agent.joblib").write_bytes(b"changed")
    response = client.get("/api/v1/outreach", headers=analyst_headers())
    assert response.status_code == 503
    assert str(directory) not in response.text


def test_missing_artifacts_no_sample_fallback(tmp_path):
    set_analytics_service(AnalyticsService(artifact_dir=tmp_path / "missing"))
    try:
        response = TestClient(app).get("/api/v1/outreach", headers=analyst_headers())
        assert response.status_code == 503
        assert "items" not in response.json()
    finally:
        set_analytics_service(None)


def test_runtime_config_mismatch_is_unavailable(bundle_client):
    client, directory = bundle_client
    config = load_config()
    config["policy"]["official_fee_rate"] = 0.02
    set_analytics_service(AnalyticsService(artifact_dir=directory, config=config))
    assert client.get("/api/v1/metrics/summary", headers=analyst_headers()).status_code == 503
