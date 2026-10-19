"""Lightweight stand-ins for the heavy services, so API tests never load real models.

``build_test_services`` wires the real RetrievalService / SearchService to a small data root:
an in-memory FAISS index with deterministic vectors, a fake text encoder and a fake
Elasticsearch client. Only model inference and network access are faked.
"""

import json
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from core.config import Settings
from core.container import AppServices
from core.intro_exclusion import IntroExclusionPolicy
from repositories.keyframe_metadata_repository import KeyframeMetadataRepository
from repositories.object_repository import KeyframeObjectRepository
from repositories.text_repository import KeyframeTextRepository
from repositories.traffic_repository import TrafficMetadataRepository
from repositories.vector_repository import KeyframeVectorRepository
from schemas.search import KISQueryPlan, QueryVariants, SearchSources
from services.retrieval_service import RetrievalService
from services.search_service import SearchService
from services.video_source_service import VideoSourceService

TEST_DIM = 8
VIDEOS = ("L01_V001", "L01_V002", "L02_V001", "L02_V002", "L03_V001", "L03_V002")
FRAMES_PER_VIDEO = 100
FRAME_STEP = 25  # one keyframe per second at 25 fps


def write_test_data_root(root: Path) -> list[dict[str, Any]]:
    """keyframes.json (600 keyframes), video_sources.json and one media file."""
    keyframes = [
        {
            "keyframe_id": f"{video_id}/{n:06d}",
            "video_id": video_id,
            "frame_id": n * FRAME_STEP,
            "image_path": f"keyframes/{video_id}/{n:06d}.jpg",
            "segment_id": f"{video_id}_S{n // 10:05d}",
        }
        for video_id in VIDEOS
        for n in range(FRAMES_PER_VIDEO)
    ]
    (root / "keyframes.json").write_text(
        json.dumps({"version": 1, "keyframes": keyframes}), encoding="utf-8"
    )
    (root / "video_sources.json").write_text(
        json.dumps(
            {
                "version": 1,
                "videos": {
                    video_id: {"remote_url": f"https://example.com/{video_id}.mp4", "fps": 25.0}
                    for video_id in VIDEOS
                },
            }
        ),
        encoding="utf-8",
    )
    media = root / "keyframes" / "mock-frame.svg"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    (root / "dres_submissions.jsonl").write_text("", encoding="utf-8")
    return keyframes


def keyframe_vectors(count: int) -> np.ndarray:
    rng = np.random.default_rng(seed=7)
    vectors = rng.normal(size=(count, TEST_DIM)).astype(np.float32)
    faiss.normalize_L2(vectors)
    return vectors


class FakeEmbeddingService:
    """Deterministic text vectors: the same text always maps to the same unit vector."""

    siglip_model = object()
    siglip_error = None
    beit3_model = object()
    beit3_error = None

    def _vector(self, text: str) -> np.ndarray:
        seed = sum(ord(char) for char in text)
        vector = np.random.default_rng(seed).normal(size=(1, TEST_DIM)).astype(np.float32)
        faiss.normalize_L2(vector)
        return vector

    def get_siglip_embedding(self, text: str) -> np.ndarray:
        return self._vector(text)

    def get_beit3_embedding(self, text: str) -> np.ndarray:
        return self._vector(text[::-1])


class FakeElasticsearch:
    """Answers every BM25 query with the first keyframes inside the requested ranges."""

    def __init__(self, available: bool = True, meta: dict[str, Any] | None = None) -> None:
        self.available = available
        self.queries: list[dict[str, Any]] = []
        self.indices = _FakeIndices(self, meta)

    def ping(self) -> bool:
        return self.available

    def close(self) -> None:
        pass

    def search(self, *, index: str, query: dict, size: int, source: list[str]) -> dict:
        if not self.available:
            raise ConnectionError("Elasticsearch is offline")
        self.queries.append(query)
        ranges = [
            (clause["range"]["faiss_id"]["gte"], clause["range"]["faiss_id"]["lte"])
            for clause in query["bool"].get("filter", {}).get("bool", {}).get("should", [])
        ] or [(0, 10**9)]
        hits = []
        for start, end in ranges:
            for faiss_id in range(start, min(end, start + size) + 1):
                hits.append({"_source": {"faiss_id": faiss_id}, "_score": 10.0 / (1 + len(hits))})
                if len(hits) >= size:
                    break
        return {"hits": {"hits": hits[:size]}}


class _FakeIndices:
    """The mapping of the one index: ``meta`` is what build_es_index.py records in _meta."""

    def __init__(self, es: FakeElasticsearch, meta: dict[str, Any] | None) -> None:
        self._es = es
        self.meta = meta

    def get_mapping(self, *, index: str) -> dict:
        if not self._es.available:
            raise ConnectionError("Elasticsearch is offline")
        mappings: dict[str, Any] = {"properties": {}}
        if self.meta is not None:
            mappings["_meta"] = self.meta
        return {index: {"mappings": mappings}}


class FakeQueryEnhancer:
    available = True

    def enhance(
        self, query: str, query_type: str, sources: SearchSources | None = None
    ) -> QueryVariants:
        return QueryVariants(variants=[f"[Mock enhanced {query_type}] {query}"], w_vis=1.0)

    def enhance_batch(
        self, queries: dict[int, str], sources: SearchSources | None = None
    ) -> dict[int, QueryVariants]:
        return {
            index: QueryVariants(variants=[f"[Mock enhanced TRAKE] {query}"])
            for index, query in queries.items()
        }

    def plan_kis(self, query: str) -> KISQueryPlan | None:
        return None


def build_test_services(
    settings: Settings,
    video_sources: VideoSourceService,
    es: FakeElasticsearch | None = None,
) -> AppServices:
    keyframe_repository = KeyframeMetadataRepository(settings.data_root)
    count = len(keyframe_repository)
    intro_policy = IntroExclusionPolicy({})
    index = faiss.IndexFlatIP(TEST_DIM)
    index.add(keyframe_vectors(count))
    siglip = KeyframeVectorRepository(
        "SigLIP", Path("memory"), TEST_DIM, keyframe_repository, intro_policy, index=index
    )
    beit3 = KeyframeVectorRepository(
        "BEiT-3", Path("memory"), TEST_DIM, keyframe_repository, intro_policy, index=index
    )
    text_repository = KeyframeTextRepository(
        "http://es.invalid",
        keyframe_repository,
        intro_policy,
        es_client=es
        or FakeElasticsearch(
            meta={"keyframe_order": keyframe_repository.order_hash(), "keyframe_count": count}
        ),
    )
    object_repository = KeyframeObjectRepository(
        settings.object_index_path, keyframe_repository, intro_policy
    )
    traffic_repository = TrafficMetadataRepository(settings.data_root, keyframe_repository)
    retrieval = RetrievalService(
        keyframe_repository=keyframe_repository,
        siglip_vector_repo=siglip,
        beit3_vector_repo=beit3,
        text_repository=text_repository,
        embedding_service=FakeEmbeddingService(),  # type: ignore[arg-type]
        intro_exclusion_policy=intro_policy,
        object_repository=object_repository,
        traffic_repository=traffic_repository,
        fps_lookup=video_sources.fps,
    )
    search_service = SearchService(
        retrieval_engine=retrieval,
        query_enhancer=FakeQueryEnhancer(),
        max_trake_events=settings.max_trake_events,
        max_query_length=settings.max_query_length,
        object_repository=object_repository,
    )
    return AppServices(
        search_service=search_service,
        keyframe_repository=keyframe_repository,
        object_repository=object_repository,
        traffic_repository=traffic_repository,
        readiness_checks={"siglip": lambda: (True, "ok")},
    )
