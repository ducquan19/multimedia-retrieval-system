from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aic_app.api.routes_health import router as health_router
from aic_app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        description="Mock-only API for inspecting AIC 2026 retrieval results.",
    )
    app.state.settings = resolved_settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(resolved_settings.frontend_origin).rstrip("/")],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.include_router(health_router, prefix="/api")
    return app


app = create_app()
