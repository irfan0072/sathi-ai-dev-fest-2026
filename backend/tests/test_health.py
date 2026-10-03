"""Tests for infrastructure health check endpoint."""

from __future__ import annotations

import pytest
from app.main import app
from fastapi.testclient import TestClient


def test_health_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that GET /health returns ok when database and signing are configured."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://sathi:secret@localhost:5432/sathi")
    monkeypatch.setenv("JWT_SECRET", "a" * 64)
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "configured",
        "auth_signing": "configured",
    }


def test_health_degraded_when_secret_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that GET /health returns degraded when signing secret is unconfigured."""
    monkeypatch.delenv("JWT_SECRET", raising=False)
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["auth_signing"] == "unconfigured"
