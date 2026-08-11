import logging
from collections import defaultdict
from pathlib import Path

import faiss
import numpy as np

logger = logging.getLogger(__name__)

import uuid
from repositories.keyframe_metadata_repository import KeyframeMetadataRepository
from schemas.retrieval import ScoredCandidate


class KeyframeVectorRepository:
    def __init__(self, index_path: Path, index_dim: int, keyframe_repository: KeyframeMetadataRepository):
        self.index_path = index_path
        self._keyframe_repository = keyframe_repository
        self.index_dim = index_dim
        self._index = None
        self._load_index()

    def _load_index(self):
        # Fallback to empty indexes if file doesn't exist to prevent crash during development
        if self.index_path.exists():
            self._index = faiss.read_index(str(self.index_path))
            logger.info("Loaded index from %s", self.index_path)
        else:
            logger.warning("Index not found at %s. Creating empty index.", self.index_path)
            self._index = faiss.IndexFlatIP(self.index_dim)

    def search(self, query_vector: np.ndarray, top_k: int) -> list[ScoredCandidate]:
        if self._index.ntotal == 0:
            return []

        distances, indices = self._index.search(query_vector, top_k)
        faiss_scores = self._format_single_search_result(distances, indices)
        return self._hydrate_candidates(faiss_scores)

    def _format_single_search_result(self, distances: np.ndarray, indices: np.ndarray) -> list[tuple[int, float]]:
        if indices.size == 0 or distances.size == 0:
            return []
        dist_list = distances[0].tolist()
        idx_list = indices[0].tolist()
        return [(idx, dist) for idx, dist in zip(idx_list, dist_list) if idx != -1]

    def _hydrate_candidates(self, faiss_scores: list[tuple[int, float]]) -> list[ScoredCandidate]:
        collection = self._keyframe_repository.load()
        candidates = []
        for faiss_id, score in faiss_scores:
            try:
                # Assuming faiss_id corresponds to the index in the keyframes list
                keyframe = collection.keyframes[faiss_id]
                candidate = ScoredCandidate(
                    result_id=str(uuid.uuid4()),
                    keyframe=keyframe,
                    similarity_score=score,
                    image_path=keyframe.image_path,
                )
                candidates.append(candidate)
            except IndexError:
                logger.warning("FAISS returned id %d which is out of bounds for keyframes", faiss_id)
        return candidates
