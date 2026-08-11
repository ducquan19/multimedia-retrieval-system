from adapters.query_enhancer import MockQueryEnhancer
from domain.search import KISSearchRequest, SearchRequest, SearchSources
from services.search_service import SearchService


class RecordingRetrievalEngine:
    def __init__(self) -> None:
        self.last_request: SearchRequest | None = None

    def retrieve(self, request: SearchRequest) -> tuple[()]:
        self.last_request = request
        return ()


def test_hybrid_source_flags_pass_through_to_retrieval_engine() -> None:
    engine = RecordingRetrievalEngine()
    service = SearchService(
        engine,
        MockQueryEnhancer(),
        max_trake_events=10,
        max_query_length=4_000,
    )
    request = KISSearchRequest(
        query_type="KIS",
        query="query",
        top_k=5,
        search_sources=SearchSources(image=False, asr=True, object=True, ocr=True),
    )

    service.search(request)

    assert engine.last_request is request
    assert engine.last_request.search_sources.model_dump() == {
        "image": False,
        "asr": True,
        "object": True,
        "ocr": True,
    }
