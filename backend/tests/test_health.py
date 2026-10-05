from fastapi.testclient import TestClient

from core.config import Settings
from factories.factory import create_app
from fakes import build_test_services


def test_health_endpoint(app_settings: Settings) -> None:
    client = TestClient(create_app(app_settings, build_test_services))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_components_after_startup(client: TestClient) -> None:
    response = client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "ready": True,
        "components": {"siglip": {"ok": True, "detail": "ok"}},
    }


def test_readiness_is_503_before_startup(app_settings: Settings) -> None:
    # Without the context manager the lifespan (service loading) never runs.
    client = TestClient(create_app(app_settings, build_test_services))

    response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["ready"] is False


def test_cors_allows_configured_local_frontend(app_settings: Settings) -> None:
    settings = app_settings.model_copy(update={"frontend_origin": "http://localhost:4173"})
    client = TestClient(create_app(settings, build_test_services))

    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:4173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:4173"
