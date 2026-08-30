import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.config import Settings
from core.constants import DEFAULT_TOP_K, MAX_TOP_K
from infrastructure.embedding_service import (
    EmbeddingService,
    _remap_beit3_sentencepiece_ids,
)
from main import create_app
from router.config_router import public_config
from schemas.search import KISSearchRequest


def sources(**overrides: bool) -> dict[str, bool]:
    values = {"image": True, "asr": False, "object": False}
    values.update(overrides)
    return values


@pytest.mark.parametrize(("top_k", "expected_count"), [(1, 1), (100, 100), (500, 500)])
def test_scoring_top_k_bounds_are_accepted(
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


def test_manually_entered_top_k_is_accepted(client: TestClient) -> None:
    response = client.post(
        "/api/search",
        json={
            "query_type": "KIS",
            "query": "top-k contract",
            "top_k": 10,
            "search_sources": sources(),
        },
    )

    assert response.status_code == 200
    assert len(response.json()["results"]) <= 10


def test_top_k_above_maximum_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/search",
        json={
            "query_type": "KIS",
            "query": "top-k contract",
            "top_k": 501,
            "search_sources": sources(),
        },
    )

    assert response.status_code == 422


def test_code_managed_top_k_ignores_legacy_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIC_DEFAULT_TOP_K", "50")

    config = asyncio.run(public_config(Settings(_env_file=None)))
    request = KISSearchRequest(query_type="KIS", query="visual query")

    assert config.default_top_k == DEFAULT_TOP_K == 100
    assert config.max_top_k == MAX_TOP_K == 500
    assert request.top_k == DEFAULT_TOP_K
    assert request.model_choices == ["siglip"]


def test_request_schema_accepts_500_and_rejects_501() -> None:
    assert KISSearchRequest(query_type="KIS", query="visual query", top_k=500).top_k == 500

    with pytest.raises(ValidationError):
        KISSearchRequest(query_type="KIS", query="visual query", top_k=501)


def test_beit3_text_ids_follow_xlm_roberta_vocabulary_mapping() -> None:
    assert _remap_beit3_sentencepiece_ids([0, 9, 402], sentencepiece_unk_id=0) == [
        3,
        10,
        403,
    ]

    class StubSentencePiece:
        @staticmethod
        def encode(text: str, out_type: type[int]) -> list[int]:
            assert text == "a person"
            assert out_type is int
            return [9, 402]

        @staticmethod
        def unk_id() -> int:
            return 0

    service = EmbeddingService.__new__(EmbeddingService)
    service.device = "cpu"
    service.beit3_tokenizer = StubSentencePiece()

    tokens, padding_mask = service._get_beit3_text_segment("a person", max_len=6)

    assert tokens.tolist() == [[0, 10, 403, 2, 1, 1]]
    assert padding_mask.tolist() == [[False, False, False, False, True, True]]


def test_text_limits_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIC_MAX_QUERY_LENGTH", "123")
    monkeypatch.setenv("AIC_MAX_ANSWER_LENGTH", "456")

    settings = Settings(_env_file=None)

    assert settings.max_query_length == 123
    assert settings.max_answer_length == 456


@pytest.mark.parametrize("field_name", ["max_query_length", "max_answer_length"])
def test_text_limits_must_be_positive(field_name: str) -> None:
    with pytest.raises(ValueError):
        Settings(**{field_name: 0})


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
    assert body["model_choices"] == ["siglip"]
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
    assert disabled.json()["applied_weights"] is None
    assert enabled.json()["original_query"] == "người đang mở laptop"
    assert enabled.json()["enhanced_query"] == "[Mock enhanced KIS] người đang mở laptop"
    assert enabled.json()["applied_weights"] is not None


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


def test_removed_ocr_source_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/search",
        json={
            "query_type": "KIS",
            "query": "anything",
            "top_k": 5,
            "search_sources": {"image": True, "asr": False, "object": False, "ocr": True},
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


def test_runtime_max_trake_events_is_enforced(app_settings: Settings) -> None:
    settings = app_settings.model_copy(update={"max_trake_events": 1})
    client = TestClient(create_app(settings))

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


@pytest.mark.parametrize(
    "payload",
    [
        {
            "query_type": "KIS",
            "query": "four",
            "top_k": 1,
            "search_sources": sources(),
        },
        {
            "query_type": "TRAKE",
            "main_query": "one",
            "events": [{"event_index": 1, "query": "four"}],
            "top_k": 1,
            "search_sources": sources(),
        },
    ],
)
def test_runtime_query_length_is_enforced(app_settings: Settings, payload: dict[str, Any]) -> None:
    settings = app_settings.model_copy(update={"max_query_length": 3})

    with TestClient(create_app(settings)) as limited_client:
        response = limited_client.post("/api/search", json=payload)

    assert response.status_code == 422
    assert "at most 3 characters" in response.json()["detail"]


def test_runtime_query_length_can_exceed_default(app_settings: Settings) -> None:
    settings = app_settings.model_copy(update={"max_query_length": 4_001})

    with TestClient(create_app(settings)) as expanded_client:
        response = expanded_client.post(
            "/api/search",
            json={
                "query_type": "KIS",
                "query": "q" * 4_001,
                "top_k": 1,
                "search_sources": sources(),
            },
        )

    assert response.status_code == 200


def test_media_endpoint_serves_only_existing_data_file(client: TestClient) -> None:
    response = client.get("/media/keyframes/mock-frame.svg")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
