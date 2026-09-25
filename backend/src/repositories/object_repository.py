import json
import logging
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from core.intro_exclusion import IntroExclusionPolicy
from repositories.keyframe_metadata_repository import (
    KeyframeMetadataError,
    KeyframeMetadataRepository,
)
from schemas.retrieval import ScoredCandidate
from schemas.search import ObjectQueryTerm

logger = logging.getLogger(__name__)

# (label index, max detection score, max instance count in one frame)
Detection = tuple[int, float, int]


class KeyframeObjectRepository:
    """In-memory object index built by scripts/build_object_index.py."""

    def __init__(
        self,
        index_path: Path,
        keyframe_repository: KeyframeMetadataRepository,
        intro_exclusion_policy: IntroExclusionPolicy | None = None,
    ) -> None:
        self._index_path = index_path
        self._keyframe_repository = keyframe_repository
        self._intro_exclusion_policy = intro_exclusion_policy or IntroExclusionPolicy()
        self._labels: tuple[str, ...] = ()
        self._label_lookup: dict[str, int] = {}
        self._detections: dict[str, tuple[Detection, ...]] = {}
        self._postings: dict[int, list[tuple[str, float, int]]] = {}
        self._loaded = False

    @property
    def available(self) -> bool:
        self.load()
        return bool(self._detections)

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._index_path.exists():
            logger.warning(
                "Object index not found at %s. Run scripts/build_object_index.py.",
                self._index_path,
            )
            return

        with open(self._index_path, encoding="utf-8") as f:
            raw = json.load(f)

        self._labels = tuple(raw["labels"])
        self._label_lookup = {label.casefold(): index for index, label in enumerate(self._labels)}
        postings: dict[int, list[tuple[str, float, int]]] = {}
        for keyframe_id, entries in raw["keyframes"].items():
            detections = tuple(
                (int(label), float(score), int(count)) for label, score, count in entries
            )
            self._detections[keyframe_id] = detections
            for label, score, count in detections:
                postings.setdefault(label, []).append((keyframe_id, score, count))
        for entries in postings.values():
            entries.sort(key=lambda entry: entry[1], reverse=True)
        self._postings = postings
        logger.info(
            "Loaded object index: %d keyframes, %d labels",
            len(self._detections),
            len(self._labels),
        )

    def labels(self) -> tuple[str, ...]:
        self.load()
        return self._labels

    def unknown_labels(self, terms: Sequence[ObjectQueryTerm]) -> list[str]:
        self.load()
        return [term.label for term in terms if term.label.casefold() not in self._label_lookup]

    def objects_for(self, keyframe_id: str) -> list[dict[str, Any]]:
        self.load()
        return [
            {"label": self._labels[label], "score": score, "count": count}
            for label, score, count in self._detections.get(keyframe_id, ())
        ]

    def score(self, keyframe_id: str, terms: Sequence[ObjectQueryTerm]) -> float:
        """Mean per-term match in [0, 1]; a term scores its detection confidence,
        scaled down when fewer instances than requested were detected."""
        resolved = self._resolve(terms)
        if not resolved:
            return 0.0
        detections = {
            label: (score, count) for label, score, count in self._detections.get(keyframe_id, ())
        }
        total = 0.0
        for label, min_count in resolved:
            match = detections.get(label)
            if match:
                total += self._term_score(match[0], match[1], min_count)
        return total / len(terms)

    def search(
        self,
        terms: Sequence[ObjectQueryTerm],
        top_k: int,
        allowed: Callable[[str], bool] | None = None,
    ) -> list[ScoredCandidate]:
        """Top-k keyframes by object match; ``allowed`` keeps only matching keyframe ids."""
        resolved = self._resolve(terms)
        if not resolved:
            return []

        totals: dict[str, float] = {}
        for label, min_count in resolved:
            for keyframe_id, score, count in self._postings.get(label, ()):
                if allowed is not None and not allowed(keyframe_id):
                    continue
                totals[keyframe_id] = totals.get(keyframe_id, 0.0) + self._term_score(
                    score, count, min_count
                )

        candidates = []
        for keyframe_id in sorted(totals, key=totals.__getitem__, reverse=True):
            try:
                keyframe = self._keyframe_repository.get_keyframe(keyframe_id)
            except KeyframeMetadataError:
                continue
            if self._intro_exclusion_policy.is_intro(keyframe):
                continue
            candidates.append(
                ScoredCandidate(
                    result_id=str(uuid.uuid4()),
                    keyframe=keyframe,
                    similarity_score=totals[keyframe_id] / len(terms),
                    image_path=keyframe.image_path,
                )
            )
            if len(candidates) >= top_k:
                break
        return candidates

    def _resolve(self, terms: Sequence[ObjectQueryTerm]) -> list[tuple[int, int]]:
        self.load()
        return [
            (self._label_lookup[term.label.casefold()], term.min_count)
            for term in terms
            if term.label.casefold() in self._label_lookup
        ]

    @staticmethod
    def _term_score(score: float, count: int, min_count: int) -> float:
        return score * min(1.0, count / min_count)
