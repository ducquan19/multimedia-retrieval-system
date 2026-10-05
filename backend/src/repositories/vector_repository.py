import json
import logging
import threading
from pathlib import Path

import faiss
import numpy as np

from core.intro_exclusion import IntroExclusionPolicy
from infrastructure.retrieval import RetrievalDataError
from repositories import id_filter
from repositories.keyframe_metadata_repository import KeyframeMetadataRepository
from schemas.retrieval import ScoredCandidate

logger = logging.getLogger(__name__)


class KeyframeVectorRepository:
    """Exhaustive inner-product search over one FAISS index aligned with keyframes.json.

    Row i of the index must be the embedding of keyframes[i]. The alignment is checked when
    the index is loaded: dimension, row count and, when the builder wrote
    ``<index>.meta.json``, the hash of the keyframe order the index was built from.
    """

    def __init__(
        self,
        name: str,
        index_path: Path,
        index_dim: int,
        keyframe_repository: KeyframeMetadataRepository,
        intro_exclusion_policy: IntroExclusionPolicy | None = None,
        index: faiss.Index | None = None,
    ) -> None:
        self.name = name
        self.index_path = index_path
        self.index_dim = index_dim
        self._keyframe_repository = keyframe_repository
        self._intro_exclusion_policy = intro_exclusion_policy or IntroExclusionPolicy()
        self._lock = threading.Lock()
        self._intro_mask: np.ndarray | None = None
        self._index = index if index is not None else self._read_index()
        if self._index is not None:
            self._validate_alignment()

    @property
    def available(self) -> bool:
        return self._index is not None

    @property
    def keyframe_repository(self) -> KeyframeMetadataRepository:
        return self._keyframe_repository

    def _read_index(self) -> faiss.Index | None:
        if not self.index_path.exists():
            logger.warning("%s index not found at %s; it is disabled.", self.name, self.index_path)
            return None
        index = faiss.read_index(str(self.index_path))
        logger.info(
            "Loaded %s index (%d vectors) from %s", self.name, index.ntotal, self.index_path
        )
        return index

    def _validate_alignment(self) -> None:
        index = self._index
        keyframe_count = len(self._keyframe_repository)
        if index.d != self.index_dim:
            raise RetrievalDataError(
                f"{self.name} index has dimension {index.d}, expected {self.index_dim}"
            )
        if index.ntotal != keyframe_count:
            raise RetrievalDataError(
                f"{self.name} index has {index.ntotal} vectors but keyframes.json has "
                f"{keyframe_count} keyframes; rebuild the index "
                "(scripts/build_faiss_index.py)"
            )
        meta_path = self.index_path.with_name(self.index_path.name + ".meta.json")
        if not meta_path.exists():
            return
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        expected_hash = meta.get("keyframe_order")
        if expected_hash and expected_hash != self._keyframe_repository.order_hash():
            raise RetrievalDataError(
                f"{self.name} index was built from a different keyframes.json order; "
                "rebuild the index (scripts/build_faiss_index.py)"
            )

    def search(
        self, query_vector: np.ndarray, top_k: int, allowed: np.ndarray | None = None
    ) -> list[ScoredCandidate]:
        """Top-k keyframes; ``allowed`` is a boolean mask over FAISS ids restricting the search."""
        if self._index is None:
            raise RetrievalDataError(f"The {self.name} index is not available")
        if self._index.ntotal == 0 or top_k <= 0:
            return []

        mask = self._restriction(allowed)
        if mask is None:
            params = None
        else:
            allowed_count = int(mask.sum())
            if allowed_count == 0:
                return []
            top_k = min(top_k, allowed_count)
            bitmap = np.packbits(mask, bitorder="little")
            # The bitmap must outlive the search call, so keep it in a local.
            params = faiss.SearchParameters(sel=faiss.IDSelectorBitmap(bitmap))
        distances, indices = self._index.search(
            np.ascontiguousarray(query_vector, dtype=np.float32), top_k, params=params
        )
        return self._hydrate_candidates(indices[0].tolist(), distances[0].tolist())

    def _restriction(self, allowed: np.ndarray | None) -> np.ndarray | None:
        intro_mask = self._get_intro_mask()
        if allowed is None:
            return intro_mask
        return allowed if intro_mask is None else allowed & intro_mask

    def _get_intro_mask(self) -> np.ndarray | None:
        """Mask of every non-intro keyframe, or None when no keyframe is an intro."""
        if self._intro_mask is None:
            with self._lock:
                if self._intro_mask is None:
                    collection = self._keyframe_repository.load()
                    excluded = self._intro_exclusion_policy.excluded_faiss_ids(collection)
                    mask = id_filter.combine(len(collection.keyframes), None, excluded)
                    self._intro_mask = mask if mask is not None else np.ones(0, dtype=bool)
                    logger.info("Excluding %d intro keyframes from %s", excluded.size, self.name)
        return self._intro_mask if self._intro_mask.size else None

    def _hydrate_candidates(
        self, faiss_ids: list[int], scores: list[float]
    ) -> list[ScoredCandidate]:
        keyframes = self._keyframe_repository.load().keyframes
        return [
            ScoredCandidate(faiss_id=faiss_id, keyframe=keyframes[faiss_id], similarity_score=score)
            for faiss_id, score in zip(faiss_ids, scores, strict=True)
            if faiss_id != -1 and not self._intro_exclusion_policy.is_intro(keyframes[faiss_id])
        ]
