"""Query by example: keyframes that look like a given keyframe."""

from collections.abc import Callable, Sequence
from typing import Protocol

import numpy as np

from core.intro_exclusion import IntroExclusionPolicy
from core.timing import stage
from models.candidate import ScoredCandidate
from models.errors import RetrievalDataError
from repositories.keyframe_metadata_repository import KeyframeMetadataRepository
from services.retrieval.fusion import VectorIndex, fuse_visual_lists


class ExampleNotFound(LookupError):
    """The video has no keyframe at the requested frame."""


class IndexedVectors(VectorIndex, Protocol):
    def vector(self, faiss_id: int) -> np.ndarray: ...


class SimilarSearch:
    """Searches every chosen index with the example's own indexed embedding.

    The example's embedding was computed from the image itself, so this finds frames that look
    alike rather than frames that match a text description. With several models the lists are
    fused like the visual lists of a text search.
    """

    def __init__(
        self,
        keyframe_repository: KeyframeMetadataRepository,
        indexes: dict[str, IndexedVectors],
        intro_exclusion_policy: IntroExclusionPolicy,
    ) -> None:
        self._keyframe_repository = keyframe_repository
        self._indexes = indexes
        self._intro_exclusion_policy = intro_exclusion_policy

    def search(
        self,
        video_id: str,
        frame_id: int,
        model_choices: Sequence[str],
        top_k: int,
        allowed_for: Callable[[str], np.ndarray | None],
    ) -> list[ScoredCandidate]:
        """``allowed_for(video_id)`` restricts the search given the example's video."""
        faiss_id = self._keyframe_repository.find_frame(video_id, frame_id)
        if faiss_id is None:
            raise ExampleNotFound(f"No keyframe at frame {frame_id} of {video_id}.")
        models = [model for model in self._indexes if model in model_choices]
        if not models:
            raise RetrievalDataError("No image model was chosen")
        allowed = allowed_for(video_id)

        lists = []
        for model in models:
            index = self._indexes[model]
            with stage("faiss"):
                # One extra, as the example itself is usually the best match.
                candidates = index.search(index.vector(faiss_id), top_k + 1, allowed)
            lists.append(
                self._intro_exclusion_policy.filter_candidates(
                    [c for c in candidates if c.faiss_id != faiss_id]
                )
            )
        with stage("fusion"):
            return fuse_visual_lists(lists)[:top_k]
