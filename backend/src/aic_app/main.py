from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aic_app.adapters.query_enhancer import MockQueryEnhancer
from aic_app.adapters.retrieval import FixtureRetrievalEngine
from aic_app.adapters.submission_csv import CsvSubmissionFormatter
from aic_app.api.routes_config import router as config_router
from aic_app.api.routes_health import router as health_router
from aic_app.api.routes_media import router as media_router
from aic_app.api.routes_search import router as search_router
from aic_app.api.routes_submissions import router as submissions_router
from aic_app.config import Settings, get_settings
from aic_app.repositories.manifest_repository import ManifestRepository
from aic_app.services.media_resolver import SafeMediaResolver
from aic_app.services.search_service import SearchService
from aic_app.services.submission_service import SubmissionService


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        description="Mock-only API for inspecting AIC 2026 retrieval results.",
    )
    app.state.settings = resolved_settings
    manifest_repository = ManifestRepository(
        resolved_settings.data_root,
        resolved_settings.manifest_filename,
    )
    retrieval_engine = FixtureRetrievalEngine(
        manifest_repository,
        resolved_settings.data_root / resolved_settings.fixture_filename,
    )
    app.state.search_service = SearchService(
        retrieval_engine,
        MockQueryEnhancer(),
        resolved_settings.max_trake_events,
        resolved_settings.max_query_length,
    )
    app.state.media_resolver = SafeMediaResolver(resolved_settings.data_root)
    app.state.submission_service = SubmissionService(
        CsvSubmissionFormatter(), resolved_settings.max_answer_length
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(resolved_settings.frontend_origin).rstrip("/")],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.include_router(health_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(search_router, prefix="/api")
    app.include_router(submissions_router, prefix="/api")
    app.include_router(media_router)
    return app


app = create_app()
