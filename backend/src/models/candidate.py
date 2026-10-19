from dataclasses import dataclass, replace

from models.keyframe import Keyframe


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    """One keyframe hit of a retrieval modality; faiss_id is its position in keyframes.json."""

    faiss_id: int
    keyframe: Keyframe
    similarity_score: float

    @property
    def image_path(self) -> str:
        return self.keyframe.image_path

    def with_score(self, score: float) -> "ScoredCandidate":
        return replace(self, similarity_score=score)
