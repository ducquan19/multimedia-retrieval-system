"""TRAKE must not fill its results with copies of one sequence that differ by adjacent frames."""

import pytest

from models.candidate import ScoredCandidate
from models.keyframe import Keyframe
from schemas.search import SearchSources, TRAKEEventQuery, TRAKESearchRequest
from services.ports import RetrievalOutcome
from services.retrieval.presenter import ResultPresenter
from services.retrieval.trake import TrakeConfig, TrakeSearch

FPS = 25.0


def candidate(frame: int, score: float, video: str = "L01_V001", shot: str | None = None):
    keyframe = Keyframe(
        keyframe_id=f"{video}/{frame:06d}",
        video_id=video,
        frame_id=frame,
        image_path=f"keyframes/{video}/{frame:06d}.jpg",
        segment_id=shot,
    )
    return ScoredCandidate(faiss_id=frame, keyframe=keyframe, similarity_score=score)


class _FixedCandidates:
    """Only the beam search is under test: each event query returns fixed candidates."""

    def __init__(self, candidates_by_query: dict[str, list[ScoredCandidate]]) -> None:
        self._candidates_by_query = candidates_by_query

    def search(self, query: str, *args, **kwargs) -> list[ScoredCandidate]:
        return list(self._candidates_by_query[query])


class _TrakeOnly:
    def __init__(self, search: TrakeSearch) -> None:
        self._search = search

    def retrieve(self, request: TRAKESearchRequest) -> RetrievalOutcome:
        sequences = self._search.search(request, None, None, [])
        return RetrievalOutcome(results=ResultPresenter().trake(sequences))


def service(candidates_by_query: dict[str, list[ScoredCandidate]], dedup_seconds: float):
    return _TrakeOnly(
        TrakeSearch(
            _FixedCandidates(candidates_by_query),  # type: ignore[arg-type]
            TrakeConfig(dedup_seconds=dedup_seconds),
            fps_lookup=lambda _: FPS,
        )
    )


def trake(*queries: str) -> TRAKESearchRequest:
    return TRAKESearchRequest(
        query_type="TRAKE",
        events=tuple(TRAKEEventQuery(event_index=i, query=q) for i, q in enumerate(queries, 1)),
        top_k=10,
        search_sources=SearchSources(),
    )


def frames(outcome: RetrievalOutcome) -> list[list[int]]:
    return [[event.frame_id for event in row.events] for row in outcome.results]


CANDIDATES = {
    "e1": [candidate(1000, 0.90)],
    # 1100 and 1120 are 0.8 s apart: the same moment.
    "e2": [candidate(1100, 0.80), candidate(1120, 0.79), candidate(1600, 0.50)],
    "e3": [candidate(1200, 0.70), candidate(1700, 0.60)],
}


def test_sequences_differing_by_adjacent_frames_are_merged() -> None:
    outcome = service(CANDIDATES, dedup_seconds=2.0).retrieve(trake("e1", "e2", "e3"))

    rows = frames(outcome)
    # The best copy of (1000, 11xx, 1200) stays; the 1120 variant is gone.
    assert rows[0] == [1000, 1100, 1200]
    assert [1000, 1120, 1200] not in rows
    # Genuinely different sequences are still offered.
    assert [1000, 1600, 1700] in rows
    assert len({tuple(row) for row in rows}) == len(rows)


def test_merge_can_be_disabled() -> None:
    outcome = service(CANDIDATES, dedup_seconds=0).retrieve(trake("e1", "e2", "e3"))

    assert [1000, 1120, 1200] in frames(outcome)


def test_frames_in_the_same_shot_count_as_the_same_moment() -> None:
    candidates = {
        "e1": [candidate(100, 0.9, shot="S1")],
        # 10 s apart but in one shot: one moment of the video.
        "e2": [candidate(400, 0.8, shot="S2"), candidate(650, 0.7, shot="S2")],
    }

    outcome = service(candidates, dedup_seconds=2.0).retrieve(trake("e1", "e2"))

    assert frames(outcome) == [[100, 400]]


def test_a_shared_event_alone_does_not_make_sequences_duplicates() -> None:
    # Same first and last frame, but the middle events are 20 s apart: different answers.
    candidates = {
        "e1": [candidate(1000, 0.9)],
        "e2": [candidate(1100, 0.8), candidate(1600, 0.7)],
        "e3": [candidate(1700, 0.6)],
    }

    outcome = service(candidates, dedup_seconds=2.0).retrieve(trake("e1", "e2", "e3"))

    assert frames(outcome) == [[1000, 1100, 1700], [1000, 1600, 1700]]


def test_other_videos_are_never_merged() -> None:
    candidates = {
        "e1": [candidate(1000, 0.9, "L01_V001"), candidate(1000, 0.85, "L01_V002")],
        "e2": [candidate(1100, 0.8, "L01_V001"), candidate(1100, 0.75, "L01_V002")],
    }

    outcome = service(candidates, dedup_seconds=2.0).retrieve(trake("e1", "e2"))

    assert [row.video_id for row in outcome.results] == ["L01_V001", "L01_V002"]


@pytest.mark.parametrize("dedup_seconds", [0.5, 2.0, 10.0])
def test_merged_results_keep_the_temporal_invariants(dedup_seconds: float) -> None:
    outcome = service(CANDIDATES, dedup_seconds).retrieve(trake("e1", "e2", "e3"))

    for row in frames(outcome):
        assert row == sorted(row) and len(set(row)) == len(row)


def test_merging_partial_sequences_never_loses_the_only_complete_one() -> None:
    # (100, 330) outscores (100, 300) and they are 1.2 s apart, but only E3 = 310 exists, which
    # (100, 330) cannot reach. Merging must keep (100, 300) alive for the last event.
    candidates = {
        "e1": [candidate(100, 0.9)],
        "e2": [candidate(330, 0.8), candidate(300, 0.7)],
        "e3": [candidate(310, 0.6)],
    }

    outcome = service(candidates, dedup_seconds=2.0).retrieve(trake("e1", "e2", "e3"))

    assert frames(outcome) == [[100, 300, 310]]
