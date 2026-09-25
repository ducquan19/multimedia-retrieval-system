import logging
import uuid
from pathlib import Path

import faiss
import numpy as np

from core.intro_exclusion import IntroExclusionPolicy
from repositories.keyframe_metadata_repository import KeyframeMetadataRepository
from schemas.retrieval import ScoredCandidate

logger = logging.getLogger(__name__)


class KeyframeVectorRepository:
    def __init__(
        self,
        index_path: Path,
        index_dim: int,
        keyframe_repository: KeyframeMetadataRepository,
        intro_exclusion_policy: IntroExclusionPolicy | None = None,
    ):
        self.index_path = index_path
        self._keyframe_repository = keyframe_repository
        self._intro_exclusion_policy = intro_exclusion_policy or IntroExclusionPolicy()
        self.index_dim = index_dim
        self._index = None
        self._search_parameters = None
        self._excluded_id_array = None
        self._excluded_selector = None
        self._allowed_selector = None
        self._load_index()

    def _load_index(self):
        # Fallback to empty indexes if file doesn't exist to prevent crash during development
        if self.index_path.exists():
            self._index = faiss.read_index(str(self.index_path))
            logger.info("Loaded index from %s", self.index_path)
        else:
            logger.warning("Index not found at %s. Creating empty index.", self.index_path)
            self._index = faiss.IndexFlatIP(self.index_dim)

    @property
    def keyframe_repository(self) -> KeyframeMetadataRepository:
        return self._keyframe_repository

    def search(
        self, query_vector: np.ndarray, top_k: int, allowed_ids: np.ndarray | None = None
    ) -> list[ScoredCandidate]:
        """Top-k keyframes; ``allowed_ids`` restricts the search to those FAISS ids."""
        if self._index.ntotal == 0:
            return []

        if allowed_ids is None:
            search_parameters = self._get_search_parameters()
        else:
            self._get_search_parameters()
            if self._excluded_id_array is not None:
                allowed_ids = np.setdiff1d(allowed_ids, self._excluded_id_array)
            if allowed_ids.size == 0:
                return []
            allowed_ids = np.ascontiguousarray(allowed_ids, dtype=np.int64)
            # The selector must outlive the search call, so keep it in a local.
            selector = faiss.IDSelectorBatch(allowed_ids)
            search_parameters = faiss.SearchParameters(sel=selector)
            top_k = min(top_k, int(allowed_ids.size))
        distances, indices = self._index.search(query_vector, top_k, params=search_parameters)
        faiss_scores = self._format_single_search_result(distances, indices)
        return self._hydrate_candidates(faiss_scores)

    def _get_search_parameters(self):
        if self._search_parameters is not None:
            return self._search_parameters

        collection = self._keyframe_repository.load()
        excluded_ids = self._intro_exclusion_policy.excluded_faiss_ids(collection)
        if not excluded_ids:
            return None

        # Keep every SWIG-backed object alive for as long as the search parameters.
        self._excluded_id_array = np.asarray(excluded_ids, dtype=np.int64)
        self._excluded_selector = faiss.IDSelectorBatch(self._excluded_id_array)
        self._allowed_selector = faiss.IDSelectorNot(self._excluded_selector)
        self._search_parameters = faiss.SearchParameters(sel=self._allowed_selector)
        logger.info("Excluding %d intro keyframes from %s", len(excluded_ids), self.index_path)
        return self._search_parameters

    def _format_single_search_result(
        self, distances: np.ndarray, indices: np.ndarray
    ) -> list[tuple[int, float]]:
        if indices.size == 0 or distances.size == 0:
            return []
        dist_list = distances[0].tolist()
        idx_list = indices[0].tolist()
        return [
            (idx, dist)
            for idx, dist in zip(idx_list, dist_list, strict=True)
            if idx != -1
        ]

    def _hydrate_candidates(self, faiss_scores: list[tuple[int, float]]) -> list[ScoredCandidate]:
        collection = self._keyframe_repository.load()
        candidates = []
        for faiss_id, score in faiss_scores:
            try:
                # Assuming faiss_id corresponds to the index in the keyframes list
                keyframe = collection.keyframes[faiss_id]
                if self._intro_exclusion_policy.is_intro(keyframe):
                    continue
                candidate = ScoredCandidate(
                    result_id=str(uuid.uuid4()),
                    keyframe=keyframe,
                    similarity_score=score,
                    image_path=keyframe.image_path,
                )
                candidates.append(candidate)
            except IndexError:
                logger.warning(
                    "FAISS returned id %d which is out of bounds for keyframes", faiss_id
                )
        return candidates
