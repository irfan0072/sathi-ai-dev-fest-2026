"""Health must distinguish real readiness from merely configured environment."""

import pytest
from app import bootstrap
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def ready_checks(monkeypatch):
    monkeypatch.delenv("SATHI_DEPLOYMENT_MODE", raising=False)
    monkeypatch.setattr(bootstrap, "verify_artifacts", lambda: None)
    monkeypatch.setattr(bootstrap, "database_ready", lambda config: True)
    monkeypatch.setenv("JWT_SECRET", "a" * 64)


def test_health_ready(ready_checks):
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok", "database": "ready", "auth_signing": "configured",
        "artifacts": "verified", "integrations": "not_verified_by_health",
        "deployment_mode": "local",
    }


@pytest.mark.parametrize("failure", ["database", "artifacts", "signing"])
def test_health_failures_are_safe_503(ready_checks, monkeypatch, failure):
    if failure == "database":
        monkeypatch.setattr(bootstrap, "database_ready", lambda config: False)
    elif failure == "artifacts":
        def unavailable():
            raise ValueError("SECRET=do-not-leak")
        monkeypatch.setattr(bootstrap, "verify_artifacts", unavailable)
    else:
        monkeypatch.delenv("JWT_SECRET")
    response = TestClient(app).get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert "do-not-leak" not in response.text
