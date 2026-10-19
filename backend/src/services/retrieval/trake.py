"""TRAKE: ranked sequences of one video, one keyframe per event, in temporal order."""

import math
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from core.timing import stage
from models.candidate import ScoredCandidate
from models.keyframe import Keyframe
from models.query import QueryVariants
from schemas.search import TRAKESearchRequest
from services.retrieval.fusion import CandidateSearch

# One element of a beam: the candidate of an event and its temporal decay factor.
_BeamStep = tuple[ScoredCandidate, float]
_Beam = tuple[float, tuple[_BeamStep, ...]]
# A finished sequence: its total score and one rescored candidate per event.
TrakeSequence = tuple[float, list[ScoredCandidate]]


@dataclass(frozen=True)
class TrakeConfig:
    """Temporal constraints of TRAKE sequences, in seconds of video time."""

    max_gap_seconds: float = 120.0
    decay_per_second: float = 0.010
    default_fps: float = 25.0
    # Two sequences are the same answer when every event shows the same moment: same shot, or
    # at most this many seconds apart. Only the best of such a group is kept. 0 disables it.
    dedup_seconds: float = 2.0


class MatchScorer(Protocol):
    @property
    def ready(self) -> bool: ...

    def match_probabilities(self, query: str, image_paths: list[str]) -> list[float]: ...


class TrakeSearch:
    def __init__(
        self,
        candidate_search: CandidateSearch,
        config: TrakeConfig,
        fps_lookup: Callable[[str], float | None] | None = None,
        reranker: MatchScorer | None = None,
    ) -> None:
        self._candidate_search = candidate_search
        self._config = config
        self._fps_lookup = fps_lookup
        self._reranker = reranker

    def search(
        self,
        request: TRAKESearchRequest,
        enhanced_queries: dict[int, QueryVariants] | None,
        allowed: np.ndarray | None,
        warnings: list[str],
    ) -> list[TrakeSequence]:
        beam_width = max(150, request.top_k * 5)
        fetch_k = request.top_k * 10

        candidates_by_event = [
            self._candidate_search.search(
                event.query,
                request.model_choices,
                fetch_k,
                request.search_sources,
                enhanced_queries.get(event.event_index) if enhanced_queries else None,
                warnings,
                object_query=request.object_query,
                allowed=allowed,
            )
            for event in request.events
        ]
        if not candidates_by_event[0]:
            return []

        # Near-identical sequences are merged at every step, so beam slots go to sequences that
        # are actually different instead of to adjacent frames of the same moment.
        last_step = len(candidates_by_event) - 1
        with stage("trake_beams"):
            beams = self._distinct_beams(
                [(c.similarity_score, ((c, 1.0),)) for c in candidates_by_event[0]],
                beam_width,
                complete=last_step == 0,
            )
            for step, candidates in enumerate(candidates_by_event[1:], start=1):
                beams = self._distinct_beams(
                    self._extend_beams(beams, candidates), beam_width, complete=step == last_step
                )
                if not beams:
                    return []

        gates = self._rerank_gates(request, beams)
        final_beams: list[TrakeSequence] = []
        for _, sequence in beams:
            gated = [
                c.with_score(c.similarity_score * decay * gates[position].get(c.faiss_id, 1.0))
                for position, (c, decay) in enumerate(sequence)
            ]
            final_beams.append((sum(c.similarity_score for c in gated), gated))
        final_beams.sort(key=lambda item: item[0], reverse=True)
        return final_beams[: request.top_k]

    def _extend_beams(self, beams: list[_Beam], candidates: list[ScoredCandidate]) -> list[_Beam]:
        """Append every same-video candidate that comes later within the gap limit."""
        by_video: dict[str, list[ScoredCandidate]] = {}
        for candidate in candidates:
            by_video.setdefault(candidate.keyframe.video_id, []).append(candidate)
        frames_by_video: dict[str, list[int]] = {}
        for video_id, video_candidates in by_video.items():
            video_candidates.sort(key=lambda c: c.keyframe.frame_id)
            frames_by_video[video_id] = [c.keyframe.frame_id for c in video_candidates]

        next_beams = []
        for total_score, sequence in beams:
            last = sequence[-1][0].keyframe
            video_candidates = by_video.get(last.video_id)
            if not video_candidates:
                continue
            last_seconds = self._seconds(last)
            # Strictly later frames only.
            start = bisect_right(frames_by_video[last.video_id], last.frame_id)
            for candidate in video_candidates[start:]:
                delta = max(self._seconds(candidate.keyframe) - last_seconds, 0.0)
                if delta > self._config.max_gap_seconds:
                    break
                decay = math.exp(-self._config.decay_per_second * delta)
                next_beams.append(
                    (
                        total_score + candidate.similarity_score * decay,
                        (*sequence, (candidate, decay)),
                    )
                )
        next_beams.sort(key=lambda item: item[0], reverse=True)
        return next_beams

    def _distinct_beams(self, beams: list[_Beam], limit: int, *, complete: bool) -> list[_Beam]:
        """Best-first, keep a sequence only if no kept one shows the same moment at every event.

        A partial sequence (``complete=False``) is only dropped for a kept duplicate that ends at
        the same frame or earlier: every later event it could still reach is then reachable from
        the kept one too, so merging never loses the eventual best sequence.

        ``beams`` must be sorted by score, best first. Kept sequences are indexed by the shot and
        the time bucket of their first event, so each new sequence is compared only with the few
        kept ones that can be duplicates (a duplicate's first event is in the same shot or at most
        one bucket away).
        """
        window = self._config.dedup_seconds
        if window <= 0:
            return beams[:limit]

        kept: list[_Beam] = []
        index: dict[tuple, list[tuple[_BeamStep, ...]]] = {}
        for beam in beams:
            sequence = beam[1]
            first = sequence[0][0].keyframe
            bucket = int(self._seconds(first) // window)
            shot_key = (first.video_id, "shot", first.segment_id) if first.segment_id else None
            time_keys = [(first.video_id, "t", bucket + offset) for offset in (-1, 0, 1)]
            nearby = [
                other
                for key in ([shot_key] if shot_key else []) + time_keys
                for other in index.get(key, ())
            ]
            last_frame = sequence[-1][0].keyframe.frame_id
            if any(
                self._same_sequence(sequence, other)
                and (complete or other[-1][0].keyframe.frame_id <= last_frame)
                for other in nearby
            ):
                continue
            kept.append(beam)
            if len(kept) >= limit:
                break
            if shot_key:
                index.setdefault(shot_key, []).append(sequence)
            index.setdefault((first.video_id, "t", bucket), []).append(sequence)
        return kept

    def _same_sequence(self, left: tuple[_BeamStep, ...], right: tuple[_BeamStep, ...]) -> bool:
        return all(
            self._same_moment(a.keyframe, b.keyframe)
            for (a, _), (b, _) in zip(left, right, strict=True)
        )

    def _same_moment(self, left: Keyframe, right: Keyframe) -> bool:
        if left.video_id != right.video_id:
            return False
        if left.segment_id and left.segment_id == right.segment_id:
            return True
        return abs(self._seconds(left) - self._seconds(right)) <= self._config.dedup_seconds

    def _rerank_gates(
        self, request: TRAKESearchRequest, beams: list[_Beam]
    ) -> list[dict[int, float]]:
        """BLIP-2 match probability per event and FAISS id (multiplicative gating)."""
        gates: list[dict[int, float]] = [{} for _ in request.events]
        if not (request.use_reranking and self._reranker is not None and self._reranker.ready):
            return gates
        for position, event in enumerate(request.events):
            unique = {
                sequence[position][0].faiss_id: sequence[position][0] for _, sequence in beams
            }
            with stage("rerank"):
                probabilities = self._reranker.match_probabilities(
                    event.query, [c.image_path for c in unique.values()]
                )
            gates[position] = dict(zip(unique, probabilities, strict=True))
        return gates

    def _seconds(self, keyframe: Keyframe) -> float:
        """Presentation time of a keyframe: time_ms when known (VFR), else frame_id / fps."""
        if keyframe.time_ms is not None:
            return keyframe.time_ms / 1000
        fps = self._fps_lookup(keyframe.video_id) if self._fps_lookup else None
        return keyframe.frame_id / (fps or self._config.default_fps)
