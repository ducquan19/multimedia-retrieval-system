import logging
import time
from typing import Any

import numpy as np
from elasticsearch import Elasticsearch

from core.intro_exclusion import IntroExclusionPolicy
from repositories import id_filter
from repositories.keyframe_metadata_repository import KeyframeMetadataRepository
from schemas.retrieval import ScoredCandidate

logger = logging.getLogger(__name__)


class TextSearchUnavailable(RuntimeError):
    """Raised when Elasticsearch cannot answer a query (offline, missing index, ...)."""


class KeyframeTextRepository:
    """BM25 search over the ASR transcripts indexed by scripts/build_es_index.py.

    Documents carry the FAISS id of their keyframe, so restrictions (intro frames, traffic
    filters) are sent to Elasticsearch as faiss_id ranges instead of being applied afterwards.
    """

    # A restriction with more runs than this is applied after the search instead.
    _MAX_RANGE_CLAUSES = 1_000
    _POST_FILTER_OVERFETCH = 3
    # After a failure, skip Elasticsearch for a while instead of paying connection retries on
    # every query (ES offline used to add ~17 s per search).
    _RETRY_AFTER_SECONDS = 30.0

    def __init__(
        self,
        es_url: str,
        keyframe_repository: KeyframeMetadataRepository,
        intro_exclusion_policy: IntroExclusionPolicy | None = None,
        index_name: str = "keyframes_metadata",
        es_client: Any | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        self.es = (
            es_client
            if es_client is not None
            else Elasticsearch(es_url, request_timeout=5, max_retries=1, retry_on_timeout=False)
        )
        self._clock = clock
        self._unavailable_until = 0.0
        self.index_name = index_name
        self._keyframe_repository = keyframe_repository
        self._intro_exclusion_policy = intro_exclusion_policy or IntroExclusionPolicy()

    def ping(self) -> bool:
        try:
            return bool(self.es.ping())
        except Exception:  # noqa: BLE001 - any transport failure means "not reachable"
            return False

    def close(self) -> None:
        close = getattr(self.es, "close", None)
        if close is not None:
            close()

    def search_text(
        self,
        text_query: str,
        fields: list[str],
        top_k: int,
        allowed: np.ndarray | None = None,
    ) -> list[ScoredCandidate]:
        """Top-k keyframes by BM25; ``allowed`` is a boolean mask over FAISS ids."""
        collection = self._keyframe_repository.load()
        keyframes = collection.keyframes
        mask = id_filter.combine(
            len(keyframes), allowed, self._intro_exclusion_policy.excluded_faiss_ids(collection)
        )

        query: dict[str, Any] = {
            "bool": {
                "must": (
                    {"multi_match": {"query": text_query, "fields": fields, "type": "best_fields"}}
                    if text_query and fields
                    else {"match_all": {}}
                )
            }
        }
        size = top_k
        post_filter = False
        if mask is not None:
            ranges = id_filter.mask_to_ranges(mask)
            if not ranges:
                return []
            if len(ranges) <= self._MAX_RANGE_CLAUSES:
                query["bool"]["filter"] = {
                    "bool": {
                        "should": [
                            {"range": {"faiss_id": {"gte": start, "lte": end}}}
                            for start, end in ranges
                        ],
                        "minimum_should_match": 1,
                    }
                }
            else:
                post_filter = True
                size = min(top_k * self._POST_FILTER_OVERFETCH, 10_000)

        if self._clock() < self._unavailable_until:
            raise TextSearchUnavailable("ASR search is unavailable (Elasticsearch is down)")
        try:
            response = self.es.search(
                index=self.index_name, query=query, size=size, source=["faiss_id"]
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user as a warning
            self._unavailable_until = self._clock() + self._RETRY_AFTER_SECONDS
            logger.error(
                "Elasticsearch search failed, skipping it for %.0f s: %s",
                self._RETRY_AFTER_SECONDS,
                exc,
            )
            raise TextSearchUnavailable(f"ASR search is unavailable: {exc}") from exc

        candidates = []
        for hit in response["hits"]["hits"]:
            faiss_id = hit["_source"]["faiss_id"]
            if not 0 <= faiss_id < len(keyframes):
                logger.warning("ES returned faiss_id %d which is out of bounds", faiss_id)
                continue
            if mask is not None and not mask[faiss_id]:
                if not post_filter:
                    logger.warning("ES returned faiss_id %d outside the filter", faiss_id)
                continue
            candidates.append(
                ScoredCandidate(
                    faiss_id=faiss_id,
                    keyframe=keyframes[faiss_id],
                    similarity_score=float(hit["_score"] or 0.0),
                )
            )
            if len(candidates) >= top_k:
                break
        return candidates
