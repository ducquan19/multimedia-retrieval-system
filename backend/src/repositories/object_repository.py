import json
import logging
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from core.intro_exclusion import IntroExclusionPolicy
from repositories.keyframe_metadata_repository import KeyframeMetadataRepository
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
        self._lock = threading.Lock()
        self._labels: tuple[str, ...] = ()
        self._label_lookup: dict[str, int] = {}
        self._detections: dict[str, tuple[Detection, ...]] = {}
        # label -> (faiss ids, scores, counts), sorted by score descending
        self._postings: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        self._loaded = False

    @property
    def available(self) -> bool:
        self.load()
        return bool(self._detections)

    def load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            if self._index_path.exists():
                self._read_index()
            else:
                logger.warning(
                    "Object index not found at %s. Run scripts/build_object_index.py.",
                    self._index_path,
                )
            self._loaded = True

    def _read_index(self) -> None:
        raw = json.loads(self._index_path.read_bytes())
        labels = tuple(raw["labels"])
        detections: dict[str, tuple[Detection, ...]] = {}
        postings: dict[int, list[tuple[int, float, int]]] = {}
        unknown = 0
        for keyframe_id, entries in raw["keyframes"].items():
            keyframe_detections = tuple(
                (int(label), float(score), int(count)) for label, score, count in entries
            )
            detections[keyframe_id] = keyframe_detections
            faiss_id = self._keyframe_repository.find_index(keyframe_id)
            if faiss_id is None:
                unknown += 1
                continue
            for label, score, count in keyframe_detections:
                postings.setdefault(label, []).append((faiss_id, score, count))
        if unknown:
            logger.warning("%d keyframes of the object index are not in keyframes.json", unknown)

        self._postings = {
            label: (
                np.array([entry[0] for entry in entries], dtype=np.int64),
                np.array([entry[1] for entry in entries], dtype=np.float32),
                np.array([entry[2] for entry in entries], dtype=np.int32),
            )
            for label, entries in (
                (label, sorted(entries, key=lambda entry: entry[1], reverse=True))
                for label, entries in postings.items()
            )
        }
        self._labels = labels
        self._label_lookup = {label.casefold(): index for index, label in enumerate(labels)}
        self._detections = detections
        logger.info("Loaded object index: %d keyframes, %d labels", len(detections), len(labels))

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
        """Mean per-term match in [0, 1] over the known terms; a term scores its detection
        confidence, scaled down when fewer instances than requested were detected."""
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
        return total / len(resolved)

    def search(
        self,
        terms: Sequence[ObjectQueryTerm],
        top_k: int,
        allowed: np.ndarray | None = None,
    ) -> list[ScoredCandidate]:
        """Top-k keyframes by object match; ``allowed`` is a boolean mask over FAISS ids."""
        resolved = self._resolve(terms)
        if not resolved or top_k <= 0:
            return []

        totals: dict[int, float] = {}
        for label, min_count in resolved:
            posting = self._postings.get(label)
            if posting is None:
                continue
            faiss_ids, scores, counts = posting
            if allowed is not None:
                keep = allowed[faiss_ids]
                faiss_ids, scores, counts = faiss_ids[keep], scores[keep], counts[keep]
            term_scores = scores * np.minimum(1.0, counts / min_count)
            for faiss_id, term_score in zip(faiss_ids.tolist(), term_scores.tolist(), strict=True):
                totals[faiss_id] = totals.get(faiss_id, 0.0) + term_score

        keyframes = self._keyframe_repository.load().keyframes
        candidates = []
        for faiss_id in sorted(totals, key=totals.__getitem__, reverse=True):
            keyframe = keyframes[faiss_id]
            if self._intro_exclusion_policy.is_intro(keyframe):
                continue
            candidates.append(
                ScoredCandidate(
                    faiss_id=faiss_id,
                    keyframe=keyframe,
                    similarity_score=totals[faiss_id] / len(resolved),
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
