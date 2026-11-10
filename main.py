"""Convenience entrypoint so `uvicorn main:app` works from the repo root."""
from app.main import app  # noqa: F401
