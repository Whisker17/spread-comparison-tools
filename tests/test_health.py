"""FastAPI /health + lifespan (WHI-823)."""

from fastapi.testclient import TestClient

from spread_compare.api.app import create_app


def test_health_returns_200_with_adapter_count() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body == {
            "status": "ok",
            "adapters_initialized": body["adapters_initialized"],
        }
        assert isinstance(body["adapters_initialized"], int)
        assert body["adapters_initialized"] >= 1


def test_lifespan_closes_adapters() -> None:
    from spread_compare.adapters import initialized_count

    with TestClient(create_app()) as client:
        assert client.get("/health").json()["adapters_initialized"] >= 1
    # After context exit, aclose_all cleared the initialized set.
    assert initialized_count() == 0
