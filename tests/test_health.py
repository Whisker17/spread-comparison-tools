"""FastAPI /health + lifespan (WHI-823 / WHI-840)."""

from fastapi.testclient import TestClient

from spread_compare.api.app import create_app


def test_health_returns_200_with_adapter_count() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {
            "status",
            "adapters_initialized",
            "adapters_expected",
            "degraded",
            "unavailable_venues",
        }
        assert body["status"] == "ok"
        assert isinstance(body["adapters_initialized"], int)
        assert body["adapters_initialized"] >= 1
        assert body["adapters_expected"] >= body["adapters_initialized"]
        assert isinstance(body["degraded"], bool)
        assert isinstance(body["unavailable_venues"], list)
        if body["degraded"]:
            assert body["unavailable_venues"]
        else:
            assert body["unavailable_venues"] == []
            assert body["adapters_initialized"] == body["adapters_expected"]


def test_lifespan_closes_adapters() -> None:
    from spread_compare.adapters import initialized_count

    with TestClient(create_app()) as client:
        assert client.get("/health").json()["adapters_initialized"] >= 1
    # After context exit, aclose_all cleared the initialized set.
    assert initialized_count() == 0
