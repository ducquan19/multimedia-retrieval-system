import asyncio
from pathlib import Path
from typing import Any

import faiss
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.config import Settings
from core.constants import DEFAULT_TOP_K, MAX_TOP_K
from core.intro_exclusion import IntroExclusionPolicy
from factories.factory import create_app
from fakes import FakeElasticsearch, build_test_services
from infrastructure.embedding_service import EmbeddingService, _remap_beit3_sentencepiece_ids
from models.errors import RetrievalDataError
from models.keyframe import Keyframe, KeyframeCollection
from repositories.text_repository import KeyframeTextRepository, TextSearchUnavailable
from repositories.vector_repository import KeyframeVectorRepository
from router.config_router import public_config
from schemas.search import KISSearchRequest


def sources(**overrides: bool) -> dict[str, bool]:
    values = {"image": True, "asr": False, "object": False}
    values.update(overrides)
    return values


def kis(query: str = "top-k contract", **overrides: Any) -> dict[str, Any]:
    return {
        "query_type": "KIS",
        "query": query,
        "top_k": 5,
        "search_sources": sources(),
        **overrides,
    }


@pytest.mark.parametrize("top_k", [1, 100, 500])
def test_top_k_bounds_are_accepted(client: TestClient, top_k: int) -> None:
    response = client.post("/api/search", json=kis(top_k=top_k))

    assert response.status_code == 200, response.text
    assert len(response.json()["results"]) == top_k


def test_top_k_above_maximum_is_rejected(client: TestClient) -> None:
    assert client.post("/api/search", json=kis(top_k=501)).status_code == 422


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
    assert _remap_beit3_sentencepiece_ids([0, 9, 402], sentencepiece_unk_id=0) == [3, 10, 403]

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


def test_unloaded_models_raise_instead_of_returning_zero_vectors() -> None:
    service = EmbeddingService.__new__(EmbeddingService)
    service.siglip_model = None
    service.siglip_error = "download failed"
    service.beit3_model = None
    service.beit3_error = "missing checkpoint"

    with pytest.raises(RetrievalDataError, match="download failed"):
        service.get_siglip_embedding("query")
    with pytest.raises(RetrievalDataError, match="missing checkpoint"):
        service.get_beit3_embedding("query")


def test_text_limits_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIC_MAX_QUERY_LENGTH", "123")
    monkeypatch.setenv("AIC_MAX_ANSWER_LENGTH", "456")

    settings = Settings(_env_file=None)

    assert settings.max_query_length == 123
    assert settings.max_answer_length == 456


@pytest.mark.parametrize("field_name", ["max_query_length", "max_answer_length"])
def test_text_limits_must_be_positive(field_name: str) -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field_name: 0})


@pytest.mark.parametrize(
    ("payload", "query_type"),
    [
        (kis("người đang mở laptop"), "KIS"),
        (
            {
                "query_type": "VQA",
                "query": "người phụ nữ đang cầm ly màu gì?",
                "top_k": 5,
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


def test_kis_results_are_ranked_with_stable_ids_and_cacheable_urls(client: TestClient) -> None:
    first = client.post("/api/search", json=kis("laptop")).json()["results"]
    second = client.post("/api/search", json=kis("laptop")).json()["results"]

    assert [result["rank"] for result in first] == list(range(1, 6))
    assert [result["result_id"] for result in first] == [r["result_id"] for r in second]
    for result in first:
        assert result["result_id"] == f"{result['video_id']}/{result['frame_id'] // 25:06d}"
        # No cache-busting query string: thumbnails stay cached across searches.
        assert result["keyframe_url"] == f"/media/{result['image_path']}"
        assert result["asr_text"] == ""
        assert result["objects"] == []


def test_hybrid_search_fuses_both_visual_models(client: TestClient) -> None:
    response = client.post("/api/search", json=kis(model_choices=["siglip", "beit3"]))

    assert response.status_code == 200
    scores = [result["similarity_score"] for result in response.json()["results"]]
    assert scores == sorted(scores, reverse=True)


def test_enhance_query_is_deterministic_and_optional(client: TestClient) -> None:
    base_payload = kis("  người đang mở laptop  ")

    disabled = client.post("/api/search", json={**base_payload, "enhance_query": False}).json()
    enabled = client.post("/api/search", json={**base_payload, "enhance_query": True}).json()

    assert disabled["original_query"] == "người đang mở laptop"
    assert disabled["enhanced_query"] is None
    assert disabled["applied_weights"] is None
    assert enabled["original_query"] == "người đang mở laptop"
    assert enabled["enhanced_query"] == "- [Mock enhanced KIS] người đang mở laptop"
    assert enabled["applied_weights"] == {"w_vis": 1.0, "w_asr": 0.0, "w_obj": 0.0}


def test_trake_response_preserves_event_invariants(client: TestClient) -> None:
    payload = {
        "query_type": "TRAKE",
        "main_query": "nhảy cao",
        "events": [
            {"event_index": 1, "query": "giậm nhảy"},
            {"event_index": 2, "query": "bay qua xà"},
            {"event_index": 3, "query": "tiếp đất"},
        ],
        "top_k": 5,
        "search_sources": sources(),
    }
    response = client.post("/api/search", json=payload)

    assert response.status_code == 200
    rows = response.json()["results"]
    assert rows
    assert len({row["result_id"] for row in rows}) == len(rows)
    for row in rows:
        frames = [event["frame_id"] for event in row["events"]]
        assert [event["event_index"] for event in row["events"]] == [1, 2, 3]
        assert frames == sorted(frames) and len(set(frames)) == 3
        # Every event belongs to the row's video (its keyframe URL carries the video id).
        assert all(f"/{row['video_id']}/" in event["keyframe_url"] for event in row["events"])
        # Gap limit: 120 s at 25 fps.
        assert all(b - a <= 120 * 25 for a, b in zip(frames, frames[1:], strict=False))
    assert client.post("/api/search", json=payload).json()["results"] == rows


def test_asr_source_uses_elasticsearch(client: TestClient) -> None:
    response = client.post("/api/search", json=kis(search_sources=sources(image=False, asr=True)))

    assert response.status_code == 200
    assert response.json()["warnings"] == []
    assert len(response.json()["results"]) == 5


def test_offline_elasticsearch_is_reported_as_a_warning(app_settings: Settings) -> None:
    def services_with_offline_es(settings, video_sources):
        return build_test_services(settings, video_sources, es=FakeElasticsearch(available=False))

    with TestClient(create_app(app_settings, services_with_offline_es)) as offline_client:
        response = offline_client.post(
            "/api/search", json=kis(search_sources=sources(image=True, asr=True))
        )

    assert response.status_code == 200
    body = response.json()
    assert body["results"]
    assert body["warnings"] == [
        "ASR search (Elasticsearch) is unavailable, so the ASR source was ignored."
    ]


def test_all_search_sources_disabled_is_rejected(client: TestClient) -> None:
    response = client.post("/api/search", json=kis(search_sources=sources(image=False)))

    assert response.status_code == 422


def test_removed_ocr_source_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/search",
        json=kis(search_sources={"image": True, "asr": False, "object": False, "ocr": True}),
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"query_type": "KIS", "top_k": 5, "search_sources": sources()},
        {"query_type": "VQA", "query": "", "top_k": 5, "search_sources": sources()},
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

    with TestClient(create_app(settings, build_test_services)) as limited_client:
        response = limited_client.post(
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
        kis("four", top_k=1),
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

    with TestClient(create_app(settings, build_test_services)) as limited_client:
        response = limited_client.post("/api/search", json=payload)

    assert response.status_code == 422
    assert "at most 3 characters" in response.json()["detail"]


def test_runtime_query_length_can_exceed_default(app_settings: Settings) -> None:
    settings = app_settings.model_copy(update={"max_query_length": 4_001})

    with TestClient(create_app(settings, build_test_services)) as expanded_client:
        response = expanded_client.post("/api/search", json=kis("q" * 4_001, top_k=1))

    assert response.status_code == 200


def intro_test_keyframe(video_id: str, frame_id: int) -> Keyframe:
    return Keyframe(
        keyframe_id=f"{video_id}/{frame_id}",
        video_id=video_id,
        frame_id=frame_id,
        image_path=f"keyframes/{video_id}/F{frame_id:06d}.jpg",
    )


def test_intro_exclusion_uses_exclusive_frame_count_boundaries() -> None:
    policy = IntroExclusionPolicy()

    for group_id, frame_count in policy.intro_frame_counts.items():
        assert policy.is_intro(intro_test_keyframe(f"{group_id}_V001", frame_count - 1))
        assert not policy.is_intro(intro_test_keyframe(f"{group_id}_V001", frame_count))


def test_intro_group_matching_does_not_use_an_ambiguous_prefix() -> None:
    policy = IntroExclusionPolicy()

    assert policy.is_intro(intro_test_keyframe("L21_V999", 49))
    assert not policy.is_intro(intro_test_keyframe("L210_V001", 49))
    assert not policy.is_intro(intro_test_keyframe("OTHER_L21_V001", 49))


class StubKeyframeMetadataRepository:
    def __init__(self, collection: KeyframeCollection) -> None:
        self._collection = collection

    def load(self) -> KeyframeCollection:
        return self._collection

    def __len__(self) -> int:
        return len(self._collection.keyframes)


def _index(vectors: list[list[float]]) -> faiss.Index:
    index = faiss.IndexFlatIP(2)
    index.add(np.asarray(vectors, dtype=np.float32))
    return index


def test_faiss_search_skips_intro_without_reducing_top_k() -> None:
    collection = KeyframeCollection(
        version=1,
        keyframes=(
            intro_test_keyframe("L26_V001", 10),
            intro_test_keyframe("L26_V002", 20),
            intro_test_keyframe("L26_V001", 300),
            intro_test_keyframe("L20_V001", 5),
        ),
    )
    repository = KeyframeVectorRepository(
        "test",
        Path("memory"),
        2,
        StubKeyframeMetadataRepository(collection),  # type: ignore[arg-type]
        index=_index([[1.0, 0.0], [0.9, 0.1], [0.8, 0.2], [0.7, 0.3]]),
    )

    candidates = repository.search(np.asarray([[1.0, 0.0]], dtype=np.float32), top_k=2)

    assert [(c.keyframe.video_id, c.keyframe.frame_id, c.faiss_id) for c in candidates] == [
        ("L26_V001", 300, 2),
        ("L20_V001", 5, 3),
    ]

    allowed = np.array([False, False, False, True])
    restricted = repository.search(np.asarray([[1.0, 0.0]], dtype=np.float32), 5, allowed)
    assert [c.faiss_id for c in restricted] == [3]


def test_faiss_index_misaligned_with_keyframes_is_rejected() -> None:
    collection = KeyframeCollection(version=1, keyframes=(intro_test_keyframe("L20_V001", 5),))
    metadata = StubKeyframeMetadataRepository(collection)

    with pytest.raises(RetrievalDataError, match="1 keyframes"):
        KeyframeVectorRepository(
            "test",
            Path("memory"),
            2,
            metadata,
            index=_index([[1, 0], [0, 1]]),  # type: ignore[arg-type]
        )
    with pytest.raises(RetrievalDataError, match="dimension"):
        KeyframeVectorRepository(
            "test",
            Path("memory"),
            3,
            metadata,
            index=_index([[1, 0]]),  # type: ignore[arg-type]
        )


def test_missing_index_is_disabled_and_fails_loudly_when_used(tmp_path: Path) -> None:
    collection = KeyframeCollection(version=1, keyframes=(intro_test_keyframe("L20_V001", 5),))
    repository = KeyframeVectorRepository(
        "BEiT-3",
        tmp_path / "missing.index",
        2,
        StubKeyframeMetadataRepository(collection),  # type: ignore[arg-type]
    )

    assert not repository.available
    with pytest.raises(RetrievalDataError, match="BEiT-3 index is not available"):
        repository.search(np.asarray([[1.0, 0.0]], dtype=np.float32), 1)


def test_asr_search_sends_intro_and_filters_as_faiss_id_ranges() -> None:
    collection = KeyframeCollection(
        version=1,
        keyframes=(
            intro_test_keyframe("L25_V001", 74),
            intro_test_keyframe("L25_V001", 75),
            intro_test_keyframe("L25_V001", 76),
            intro_test_keyframe("N01_V001", 0),
        ),
    )
    fake_es = FakeElasticsearch()
    repository = KeyframeTextRepository(
        "http://es.invalid",
        StubKeyframeMetadataRepository(collection),  # type: ignore[arg-type]
        es_client=fake_es,
    )

    candidates = repository.search_text(
        "query", ["asr_text"], top_k=5, allowed=np.array([True, True, True, False])
    )

    should = fake_es.queries[0]["bool"]["filter"]["bool"]["should"]
    assert should == [{"range": {"faiss_id": {"gte": 1, "lte": 2}}}]
    assert [c.faiss_id for c in candidates] == [1, 2]


def test_offline_elasticsearch_is_skipped_for_a_while_after_a_failure() -> None:
    collection = KeyframeCollection(version=1, keyframes=(intro_test_keyframe("L20_V001", 5),))
    now = [100.0]
    fake_es = FakeElasticsearch(available=False)
    repository = KeyframeTextRepository(
        "http://es.invalid",
        StubKeyframeMetadataRepository(collection),  # type: ignore[arg-type]
        es_client=fake_es,
        clock=lambda: now[0],
    )

    with pytest.raises(TextSearchUnavailable):
        repository.search_text("query", ["asr_text"], top_k=5)
    fake_es.available = True
    with pytest.raises(TextSearchUnavailable, match="down"):
        repository.search_text("query", ["asr_text"], top_k=5)  # still in the back-off window
    assert fake_es.queries == []

    now[0] += 31
    assert [c.faiss_id for c in repository.search_text("query", ["asr_text"], top_k=5)] == [0]
