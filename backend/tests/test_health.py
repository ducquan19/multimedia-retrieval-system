from fastapi.testclient import TestClient

from aic_app.config import Settings
from aic_app.main import create_app


def test_health_endpoint() -> None:
    client = TestClient(create_app(Settings()))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_configured_local_frontend() -> None:
    settings = Settings(frontend_origin="http://localhost:4173")
    client = TestClient(create_app(settings))

    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:4173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:4173"
