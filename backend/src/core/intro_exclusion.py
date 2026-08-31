from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Protocol, TypeVar

from models.keyframe import Keyframe, KeyframeCollection

DEFAULT_INTRO_FRAME_COUNTS: Mapping[str, int] = MappingProxyType(
    {
        "L21": 50,
        "L22": 50,
        "L25": 75,
        "L26": 300,
        "L27": 540,
        "L28": 890,
        "L29": 570,
        "L30": 289,
    }
)


class CandidateWithKeyframe(Protocol):
    keyframe: Keyframe


CandidateT = TypeVar("CandidateT", bound=CandidateWithKeyframe)


class IntroExclusionPolicy:
    """Identify keyframes that belong to a programme's opening intro."""

    def __init__(self, intro_frame_counts: Mapping[str, int] | None = None) -> None:
        counts = dict(
            DEFAULT_INTRO_FRAME_COUNTS
            if intro_frame_counts is None
            else intro_frame_counts
        )
        if any(not group_id or frame_count < 0 for group_id, frame_count in counts.items()):
            raise ValueError("Intro group IDs must be non-empty and frame counts non-negative")
        self._intro_frame_counts = MappingProxyType(counts)
        self._cached_collection: KeyframeCollection | None = None
        self._cached_excluded_ids: tuple[int, ...] = ()

    @property
    def intro_frame_counts(self) -> Mapping[str, int]:
        return self._intro_frame_counts

    def is_intro(self, keyframe: Keyframe) -> bool:
        group_id = keyframe.video_id.partition("_")[0]
        intro_frame_count = self._intro_frame_counts.get(group_id)
        return intro_frame_count is not None and keyframe.frame_id < intro_frame_count

    def excluded_faiss_ids(self, collection: KeyframeCollection) -> tuple[int, ...]:
        if collection is not self._cached_collection:
            self._cached_excluded_ids = tuple(
                faiss_id
                for faiss_id, keyframe in enumerate(collection.keyframes)
                if self.is_intro(keyframe)
            )
            self._cached_collection = collection
        return self._cached_excluded_ids

    def filter_candidates(self, candidates: Sequence[CandidateT]) -> list[CandidateT]:
        return [
            candidate for candidate in candidates if not self.is_intro(candidate.keyframe)
        ]
