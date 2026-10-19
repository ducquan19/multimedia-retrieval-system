import importlib.util
import json
import sys
from pathlib import Path

import pytest

from core.intro_exclusion import IntroExclusionPolicy
from models.candidate import ScoredCandidate
from repositories.keyframe_metadata_repository import KeyframeMetadataRepository
from repositories.object_repository import KeyframeObjectRepository
from schemas.search import KISSearchRequest, ObjectQueryTerm, QueryVariants, SearchSources
from services.ports import RetrievalOutcome
from services.retrieval.fusion import (
    AsrModality,
    CandidateSearch,
    ObjectModality,
    VisualModality,
)
from services.search_service import SearchService, SearchValidationError

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_object_index.py"


def _load_build_script():
    # The scripts import their shared helpers as `_common`, like `python scripts/<x>.py` does.
    if str(_SCRIPT.parent) not in sys.path:
        sys.path.insert(0, str(_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("build_object_index", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _keyframe(video_id: str, shot: int, frame: int) -> dict:
    return {
        "keyframe_id": f"{video_id}/S{shot:05d}/{frame:06d}",
        "video_id": video_id,
        "frame_id": frame,
        "image_path": f"keyframes/{video_id}/S{shot:05d}/F{frame:06d}.jpg",
        "segment_id": f"{video_id}_S{shot:05d}",
    }


def _write_provided(root: Path, video_id: str, frames: list[int], detections: list[list]) -> None:
    rows = ["n,pts_time,fps,frame_idx"] + [
        f"{n},{frame / 25},25.0,{frame}" for n, frame in enumerate(frames, start=1)
    ]
    (root / "map-keyframes").mkdir(exist_ok=True)
    (root / "map-keyframes" / f"{video_id}.csv").write_text("\n".join(rows), encoding="utf-8")
    objects_dir = root / "objects" / video_id
    objects_dir.mkdir(parents=True)
    for n, frame_detections in enumerate(detections, start=1):
        (objects_dir / f"{n:03d}.json").write_text(
            json.dumps(
                {
                    "detection_class_entities": [label for label, _ in frame_detections],
                    "detection_scores": [str(score) for _, score in frame_detections],
                }
            ),
            encoding="utf-8",
        )


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    keyframes = [
        _keyframe("L99_V001", 0, 400),
        _keyframe("L99_V001", 0, 480),
        _keyframe("L99_V001", 1, 600),
        _keyframe("L99_V001", 2, 900),
        _keyframe("M01_V001", 0, 500),
        _keyframe("M01_V001", 0, 510),
    ]
    (tmp_path / "keyframes.json").write_text(
        json.dumps({"version": 1, "keyframes": keyframes}), encoding="utf-8"
    )
    (tmp_path / "scenes").mkdir()
    (tmp_path / "scenes" / "L99_V001.scenes.csv").write_text(
        "video_id,scene_id,start_frame,end_frame\n"
        "L99_V001,0,0,499\nL99_V001,1,502,799\nL99_V001,2,800,999\n",
        encoding="utf-8",
    )
    _write_provided(
        tmp_path,
        "L99_V001",
        [100, 450, 501, 820],
        [
            [("Person", 0.9), ("Person", 0.8), ("Car", 0.1)],
            [("Dog", 0.7)],
            [("Cat", 0.6)],  # in the 499..502 gap, nearest shot is 1
            [("Bicycle", 0.95)],
        ],
    )
    _write_provided(tmp_path, "M01_V001", [0, 500], [[("Tree", 0.5)], [("Boat", 0.8)]])
    _load_build_script().build_object_index(
        tmp_path, tmp_path / "objects_index.json", 0.3, ("L",), workers=2
    )
    return tmp_path


def _index(data_root: Path) -> dict:
    raw = json.loads((data_root / "objects_index.json").read_text(encoding="utf-8"))
    return {
        keyframe_id: {raw["labels"][label]: (score, count) for label, score, count in entries}
        for keyframe_id, entries in raw["keyframes"].items()
    }


def test_l_videos_share_objects_across_the_whole_shot(data_root: Path) -> None:
    index = _index(data_root)

    shot_0 = {"Person": (0.9, 2), "Dog": (0.7, 1)}
    assert index["L99_V001/S00000/000400"] == shot_0
    assert index["L99_V001/S00000/000480"] == shot_0
    assert index["L99_V001/S00001/000600"] == {"Cat": (0.6, 1)}
    assert index["L99_V001/S00002/000900"] == {"Bicycle": (0.95, 1)}


def test_other_sets_match_the_exact_provided_frame(data_root: Path) -> None:
    index = _index(data_root)

    assert index["M01_V001/S00000/000500"] == {"Boat": (0.8, 1)}
    assert "M01_V001/S00000/000510" not in index


def _repository(data_root: Path) -> KeyframeObjectRepository:
    keyframes = KeyframeMetadataRepository(data_root)
    return KeyframeObjectRepository(
        data_root / "objects_index.json", keyframes, IntroExclusionPolicy({})
    )


def test_search_ranks_keyframes_matching_more_terms_and_counts_first(data_root: Path) -> None:
    repository = _repository(data_root)
    terms = (ObjectQueryTerm(label="person", min_count=2), ObjectQueryTerm(label="Dog"))

    results = repository.search(terms, top_k=10)

    assert [c.keyframe.keyframe_id for c in results] == [
        "L99_V001/S00000/000400",
        "L99_V001/S00000/000480",
    ]
    assert results[0].similarity_score == pytest.approx((0.9 + 0.7) / 2)
    assert repository.score(
        "L99_V001/S00000/000400", (ObjectQueryTerm(label="Person", min_count=4),)
    ) == pytest.approx(0.9 * 2 / 4)
    assert repository.score("L99_V001/S00002/000900", terms) == 0.0


def test_objects_for_returns_labels_for_result_details(data_root: Path) -> None:
    repository = _repository(data_root)

    assert repository.objects_for("L99_V001/S00000/000400") == [
        {"label": "Person", "score": 0.9, "count": 2},
        {"label": "Dog", "score": 0.7, "count": 1},
    ]
    assert repository.unknown_labels((ObjectQueryTerm(label="Unicorn"),)) == ["Unicorn"]


class _EmptyRetrievalEngine:
    def retrieve(self, request, enhanced_queries=None):
        return RetrievalOutcome(results=())


def _service(repository: KeyframeObjectRepository) -> SearchService:
    return SearchService(
        _EmptyRetrievalEngine(),
        query_enhancer=None,
        max_trake_events=10,
        max_query_length=2_000,
        object_repository=repository,
    )


def test_object_source_requires_an_object_query(data_root: Path) -> None:
    request = KISSearchRequest(
        query_type="KIS",
        query="a dog",
        search_sources=SearchSources(image=True, object=True),
    )

    with pytest.raises(SearchValidationError):
        _service(_repository(data_root)).search(request)


def test_unknown_object_labels_are_reported_as_warnings(data_root: Path) -> None:
    request = KISSearchRequest(
        query_type="KIS",
        query="a dog",
        search_sources=SearchSources(image=False, object=True),
        object_query=(ObjectQueryTerm(label="Dog"), ObjectQueryTerm(label="Unicorn")),
    )

    response = _service(_repository(data_root)).search(request)

    assert response.warnings == ["Unknown object labels were ignored: Unicorn"]


class _FakeEnhancer:
    def __init__(self, enhanced: QueryVariants | None) -> None:
        self.enhanced = enhanced
        self.sources = None

    def enhance(self, query, query_type, sources=None):
        self.sources = sources
        return self.enhanced


def test_enhanced_search_reports_auto_objects_and_gated_weights(data_root: Path) -> None:
    enhanced = QueryVariants(
        variants=["a dog next to a person"],
        w_vis=0.8,
        w_asr=0.6,
        w_obj=0.9,
        objects=(ObjectQueryTerm(label="Dog"),),
    )
    enhancer = _FakeEnhancer(enhanced)
    service = SearchService(
        _EmptyRetrievalEngine(),
        query_enhancer=enhancer,
        max_trake_events=10,
        max_query_length=2_000,
        object_repository=_repository(data_root),
    )
    request = KISSearchRequest(
        query_type="KIS",
        query="con chó",
        enhance_query=True,
        search_sources=SearchSources(image=True, asr=False, object=True),
    )

    response = service.search(request)

    assert enhancer.sources == request.search_sources
    assert response.auto_object_query == (ObjectQueryTerm(label="Dog"),)
    assert response.applied_weights.model_dump() == {"w_vis": 0.8, "w_asr": 0.0, "w_obj": 0.9}
    assert response.warnings == []
    assert "Objects: Dog ≥1" in response.enhanced_query


def test_gemini_output_is_restricted_to_detector_labels() -> None:
    from infrastructure.query_enhancer import (
        GeminiQueryEnhancer,
        _GeminiObjectTerm,
        _GeminiQueryVariants,
    )

    enhancer = GeminiQueryEnhancer(api_key="test", object_labels=["Bicycle", "Helmet"])
    parsed = _GeminiQueryVariants(
        variants=["two cyclists wearing helmets"],
        asr_query_vi="  ",
        objects=[
            _GeminiObjectTerm(label="bicycle", min_count=2),
            _GeminiObjectTerm(label="Unicorn"),
            _GeminiObjectTerm(label="BICYCLE", min_count=0),
            _GeminiObjectTerm(label="Helmet", min_count=0),
        ],
        w_vis=1.4,
        w_asr=-1,
        w_obj=0.7,
    )

    result = enhancer._to_query_variants(parsed)

    assert result.objects == (
        ObjectQueryTerm(label="Bicycle", min_count=2),
        ObjectQueryTerm(label="Helmet", min_count=1),
    )
    assert (result.w_vis, result.w_asr, result.w_obj) == (1.0, 0.0, 0.7)
    assert result.asr_query_vi is None

    no_objects = enhancer._to_query_variants(
        _GeminiQueryVariants(variants=["a street"], w_vis=0, w_asr=0, w_obj=0.9)
    )
    assert (no_objects.w_vis, no_objects.w_obj) == (1.0, 0.0)


class _FakeVectorRepository:
    def __init__(self, candidates):
        self.candidates = candidates

    def search(self, vector, top_k, allowed=None):
        return self.candidates[:top_k]


class _FakeTextRepository:
    def __init__(self, candidates):
        self.candidates = candidates
        self.queries = []

    def search_text(self, query, fields, top_k, allowed=None):
        self.queries.append(query)
        return self.candidates


def _candidate(repository: KeyframeMetadataRepository, keyframe_id: str, score: float):
    return ScoredCandidate(
        faiss_id=repository.index_of(keyframe_id),
        keyframe=repository.get_keyframe(keyframe_id),
        similarity_score=score,
    )


def _fusion(data_root: Path, visual, text) -> CandidateSearch:
    intro = IntroExclusionPolicy({})
    return CandidateSearch(
        visual=VisualModality(
            {"siglip": lambda _: None, "beit3": lambda _: None},
            {"siglip": _FakeVectorRepository(visual), "beit3": _FakeVectorRepository([])},
            intro,
        ),
        asr=AsrModality(text, intro),
        objects=ObjectModality(_repository(data_root)),
        intro_exclusion_policy=intro,
    )


def test_fusion_merges_auto_objects_and_shares_asr_scores_within_a_shot(
    data_root: Path,
) -> None:
    keyframes = KeyframeMetadataRepository(data_root)
    visual = [
        _candidate(keyframes, "L99_V001/S00002/000900", 0.9),
        _candidate(keyframes, "L99_V001/S00000/000480", 0.5),
        _candidate(keyframes, "L99_V001/S00001/000600", 0.1),
    ]
    # ASR only hit the other keyframe of shot 0; its score must reach 000480 too.
    text = _FakeTextRepository([_candidate(keyframes, "L99_V001/S00000/000400", 12.0)])
    service = _fusion(data_root, visual, text)
    enhanced = QueryVariants(
        variants=["a dog"],
        w_vis=0.5,
        w_asr=0.5,
        w_obj=1.0,
        asr_query_vi="con chó",
        objects=(ObjectQueryTerm(label="Dog"), ObjectQueryTerm(label="Person")),
    )

    candidates = service.search(
        "chó",
        ["siglip"],
        fetch_k=10,
        sources=SearchSources(image=True, asr=True, object=True),
        enhanced=enhanced,
        warnings=[],
        object_query=(ObjectQueryTerm(label="person", min_count=2),),
    )

    by_id = {c.keyframe.keyframe_id: c.similarity_score for c in candidates}
    assert text.queries == ["con chó chó"]
    assert candidates[0].keyframe.keyframe_id in {
        "L99_V001/S00000/000400",
        "L99_V001/S00000/000480",
    }
    assert by_id["L99_V001/S00000/000480"] > by_id["L99_V001/S00002/000900"]
    # vis(480)=min-max of rank 2, asr=1.0 via the shot, obj=(0.9+0.7)/2; weights sum to 2.0
    assert max(by_id.values()) <= 1.0


def test_fusion_renormalizes_weights_when_a_modality_returns_nothing(data_root: Path) -> None:
    keyframes = KeyframeMetadataRepository(data_root)
    visual = [
        _candidate(keyframes, "L99_V001/S00002/000900", 0.9),
        _candidate(keyframes, "L99_V001/S00001/000600", 0.1),
    ]
    service = _fusion(data_root, visual, _FakeTextRepository([]))

    candidates = service.search(
        "q",
        ["siglip"],
        fetch_k=10,
        sources=SearchSources(image=True, asr=True),
        enhanced=QueryVariants(variants=["q"], w_vis=0.4, w_asr=0.9),
        warnings=[],
    )

    assert candidates[0].keyframe.keyframe_id == "L99_V001/S00002/000900"
    assert candidates[0].similarity_score == pytest.approx(1.0, abs=1e-4)
