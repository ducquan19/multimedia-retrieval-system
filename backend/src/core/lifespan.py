import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the heavy services (models, FAISS indexes) with the app's own settings."""
    settings = app.state.settings
    factory = app.state.services_factory
    logger.info("Starting up: loading models and indexes from %s", settings.data_root)
    started = time.perf_counter()
    try:
        # Loading takes a while; run it off the event loop.
        services = await run_in_threadpool(factory, settings, app.state.video_sources)
    except Exception:
        logger.exception("Failed to start the application")
        raise

    app.state.services = services
    app.state.search_service = services.search_service
    app.state.keyframe_repository = services.keyframe_repository
    app.state.object_repository = services.object_repository
    app.state.traffic_repository = services.traffic_repository
    logger.info("Application startup completed in %.1fs.", time.perf_counter() - started)
    try:
        yield
    finally:
        logger.info("Shutting down...")
        services.close()
        app.state.dres_service.close()
