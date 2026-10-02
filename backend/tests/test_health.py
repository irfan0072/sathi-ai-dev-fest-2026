"""Tests for infrastructure health check endpoint."""

from app.main import app
from fastapi.testclient import TestClient


def test_health() -> None:
    """Test that GET /health returns 200 and {'status': 'ok'}."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
