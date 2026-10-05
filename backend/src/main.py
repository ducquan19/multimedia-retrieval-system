"""ASGI entry point: ``uvicorn main:app --app-dir backend/src``."""

from factories.factory import create_app

app = create_app()
