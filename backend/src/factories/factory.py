from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.config import Settings, get_settings
from core.lifespan import lifespan
from infrastructure.dres_client import DresClient
from infrastructure.hf_signed_url import HuggingFaceUrlSigner
from router.config_router import router as config_router
from router.dres_router import router as dres_router
from router.health_router import router as health_router
from router.search_router import router as search_router
from services.dres_service import DresSubmissionService


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        description="API for inspecting AIC 2026 retrieval results.",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.private_url_signer = (
        HuggingFaceUrlSigner(
            resolved_settings.hf_token.get_secret_value(),
            resolved_settings.hf_private_repo,
            ttl_seconds=resolved_settings.hf_signed_url_ttl_seconds,
        )
        if resolved_settings.hf_token
        else None
    )
    app.state.dres_service = DresSubmissionService(
        DresClient(
            resolved_settings.dres_base_url,
            resolved_settings.dres_username,
            resolved_settings.dres_password,
        ),
        resolved_settings.data_root / resolved_settings.dres_log_filename,
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
    app.include_router(dres_router, prefix="/api")
    
    # Serve media files directly from DATA_ROOT via StaticFiles
    app.mount("/media", StaticFiles(directory=str(resolved_settings.data_root)), name="media")
    
    return app
