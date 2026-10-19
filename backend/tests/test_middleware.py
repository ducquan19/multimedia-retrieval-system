import logging

import pytest
from fastapi.testclient import TestClient

from core.config import Settings
from factories.factory import create_app
from fakes import build_test_services


@pytest.mark.parametrize(
    ("host", "status"),
    [("127.0.0.1", 200), ("::1", 200), ("192.168.1.20", 403), ("testclient", 403)],
)
def test_only_local_requests_are_answered_by_default(
    app_settings: Settings, host: str, status: int
) -> None:
    settings = app_settings.model_copy(update={"allow_remote_clients": False})
    client = TestClient(create_app(settings, build_test_services), client=(host, 50000))

    assert client.get("/api/health").status_code == status


def test_remote_requests_can_be_allowed(app_settings: Settings) -> None:
    client = TestClient(
        create_app(app_settings, build_test_services), client=("192.168.1.20", 50000)
    )

    assert client.get("/api/health").status_code == 200


def test_search_logs_its_stage_timings(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    payload = {
        "query_type": "KIS",
        "query": "a street",
        "search_sources": {"image": True, "asr": True, "object": False},
    }

    with caplog.at_level(logging.INFO, logger="factories.middleware"):
        response = client.post("/api/search", json=payload)

    assert response.status_code == 200
    request_id = response.headers["X-Request-ID"]
    [line] = [r.getMessage() for r in caplog.records if r.name == "factories.middleware"]
    assert line.startswith("POST /api/search 200 in ")
    for stage in ("embed=", "faiss=", "asr=", "fusion="):
        assert stage in line
    assert line.endswith(f"id={request_id}")


def test_other_requests_are_not_timed(client: TestClient) -> None:
    assert "X-Request-ID" not in client.get("/api/health").headers
