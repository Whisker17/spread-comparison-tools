"""FastAPI /health smoke."""

from fastapi.testclient import TestClient

from spread_compare.api.app import create_app


def test_health_returns_200() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
