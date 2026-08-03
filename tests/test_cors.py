"""CORS for local Next.js dashboard (WHI-808)."""

from fastapi.testclient import TestClient

from spread_compare.api.app import create_app


def test_cors_allows_localhost_3000_preflight() -> None:
    with TestClient(create_app()) as client:
        response = client.options(
            "/quotes",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code in (200, 204)
        assert (
            response.headers.get("access-control-allow-origin")
            == "http://localhost:3000"
        )


def test_cors_allows_localhost_3000_get() -> None:
    with TestClient(create_app()) as client:
        response = client.get(
            "/health",
            headers={"Origin": "http://localhost:3000"},
        )
        assert response.status_code == 200
        assert (
            response.headers.get("access-control-allow-origin")
            == "http://localhost:3000"
        )


def test_cors_allows_localhost_3000_post_preflight() -> None:
    """WHI-814 POST /simulate needs CORS POST for the dashboard."""
    with TestClient(create_app()) as client:
        response = client.options(
            "/simulate",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code in (200, 204)
        assert (
            response.headers.get("access-control-allow-origin")
            == "http://localhost:3000"
        )
        allow = response.headers.get("access-control-allow-methods", "")
        assert "POST" in allow.upper()
