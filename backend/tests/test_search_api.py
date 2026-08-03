from typing import Any

import pytest
from fastapi.testclient import TestClient

from aic_app.config import Settings
from aic_app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Settings()))


def sources(**overrides: bool) -> dict[str, bool]:
    values = {"image": True, "asr": False, "object": False, "ocr": False}
    values.update(overrides)
    return values


def test_public_config_reports_mock_modes(client: TestClient) -> None:
    response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json() == {
        "top_k_options": [1, 5, 20, 50, 100],
        "default_top_k": 20,
        "max_trake_events": 10,
        "retrieval_mode": "mock",
        "gemini_mode": "mock",
    }


@pytest.mark.parametrize(("top_k", "expected_count"), [(1, 1), (5, 5)])
def test_scoring_top_k_options_are_accepted(
    client: TestClient, top_k: int, expected_count: int
) -> None:
    response = client.post(
        "/api/search",
        json={
            "query_type": "KIS",
            "query": "top-k contract",
            "top_k": top_k,
            "search_sources": sources(),
        },
    )

    assert response.status_code == 200
    assert len(response.json()["results"]) == expected_count


def test_non_scoring_top_k_option_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/search",
        json={
            "query_type": "KIS",
            "query": "top-k contract",
            "top_k": 10,
            "search_sources": sources(),
        },
    )

    assert response.status_code == 422


def test_default_top_k_must_use_a_scoring_option() -> None:
    with pytest.raises(ValueError, match="default_top_k must be one of"):
        Settings(default_top_k=10)


@pytest.mark.parametrize(
    ("payload", "query_type"),
    [
        (
            {
                "query_type": "KIS",
                "query": "người đang mở laptop",
                "top_k": 5,
                "enhance_query": False,
                "search_sources": sources(),
            },
            "KIS",
        ),
        (
            {
                "query_type": "VQA",
                "query": "người phụ nữ đang cầm ly màu gì?",
                "top_k": 5,
                "enhance_query": False,
                "search_sources": sources(asr=True),
            },
            "VQA",
        ),
        (
            {
                "query_type": "TRAKE",
                "main_query": "chuỗi động tác nhảy cao",
                "events": [
                    {"event_index": 1, "query": "giậm nhảy"},
                    {"event_index": 2, "query": "bay qua xà"},
                ],
                "top_k": 5,
                "enhance_query": False,
                "search_sources": sources(),
            },
            "TRAKE",
        ),
    ],
)
def test_search_accepts_all_query_types(
    client: TestClient, payload: dict[str, Any], query_type: str
) -> None:
    response = client.post("/api/search", json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["query_type"] == query_type
    assert body["retrieval_mode"] == "mock"
    assert body["results"]


def test_kis_search_truncates_to_top_k_and_uses_manifest_frame_id(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/search",
        json={
            "query_type": "KIS",
            "query": "laptop",
            "top_k": 5,
            "enhance_query": False,
            "search_sources": sources(),
        },
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 5
    assert [result["rank"] for result in results] == list(range(1, 6))
    assert results[0]["frame_id"] == 505
    assert results[0]["keyframe_url"] == "/media/keyframes/mock-frame.svg"


def test_enhance_query_is_deterministic_and_optional(client: TestClient) -> None:
    base_payload = {
        "query_type": "KIS",
        "query": "  người đang mở laptop  ",
        "top_k": 5,
        "search_sources": sources(),
    }

    disabled = client.post("/api/search", json={**base_payload, "enhance_query": False})
    enabled = client.post("/api/search", json={**base_payload, "enhance_query": True})

    assert disabled.json()["original_query"] == "người đang mở laptop"
    assert disabled.json()["enhanced_query"] is None
    assert enabled.json()["original_query"] == "người đang mở laptop"
    assert enabled.json()["enhanced_query"] == "[Mock enhanced KIS] người đang mở laptop"


def test_missing_optional_manifest_fields_are_normalized(client: TestClient) -> None:
    response = client.post(
        "/api/search",
        json={
            "query_type": "KIS",
            "query": "fixture with missing fields",
            "top_k": 5,
            "enhance_query": False,
            "search_sources": sources(),
        },
    )

    fourth_result = response.json()["results"][3]
    assert fourth_result["video_id"] == "L04_V004"
    assert fourth_result["asr_text"] == ""
    assert fourth_result["ocr_text"] == ""
    assert fourth_result["objects"] == []


def test_trake_response_preserves_event_invariants(client: TestClient) -> None:
    response = client.post(
        "/api/search",
        json={
            "query_type": "TRAKE",
            "main_query": "nhảy cao",
            "events": [
                {"event_index": 1, "query": "giậm nhảy"},
                {"event_index": 2, "query": "bay qua xà"},
                {"event_index": 3, "query": "tiếp đất"},
            ],
            "top_k": 5,
            "enhance_query": False,
            "search_sources": sources(),
        },
    )

    assert response.status_code == 200
    for row in response.json()["results"]:
        assert row["video_id"] == "L10_V010"
        assert [event["event_index"] for event in row["events"]] == [1, 2, 3]
        assert [event["frame_id"] for event in row["events"]] == [101, 151, 203]


def test_all_search_sources_disabled_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/search",
        json={
            "query_type": "KIS",
            "query": "anything",
            "top_k": 5,
            "enhance_query": False,
            "search_sources": sources(image=False),
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {
            "query_type": "KIS",
            "top_k": 5,
            "search_sources": sources(),
        },
        {
            "query_type": "VQA",
            "query": "",
            "top_k": 5,
            "search_sources": sources(),
        },
        {
            "query_type": "TRAKE",
            "main_query": "sequence",
            "events": [{"event_index": 2, "query": "wrong index"}],
            "top_k": 5,
            "search_sources": sources(),
        },
    ],
)
def test_invalid_request_for_each_query_type_is_rejected(
    client: TestClient, payload: dict[str, Any]
) -> None:
    assert client.post("/api/search", json=payload).status_code == 422


def test_runtime_max_trake_events_is_enforced() -> None:
    client = TestClient(create_app(Settings(max_trake_events=1)))

    response = client.post(
        "/api/search",
        json={
            "query_type": "TRAKE",
            "main_query": "sequence",
            "events": [
                {"event_index": 1, "query": "one"},
                {"event_index": 2, "query": "two"},
            ],
            "top_k": 5,
            "search_sources": sources(),
        },
    )

    assert response.status_code == 422
    assert "at most 1 events" in response.json()["detail"]


def test_media_endpoint_serves_only_existing_data_file(client: TestClient) -> None:
    response = client.get("/media/keyframes/mock-frame.svg")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
