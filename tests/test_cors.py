from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware

from app_base.main import app


def test_cors_middleware_is_configured() -> None:
    cors = next(middleware for middleware in app.user_middleware if middleware.cls is CORSMiddleware)

    assert cors.kwargs["allow_credentials"] is True
    assert "OPTIONS" in cors.kwargs["allow_methods"]
    assert "X-Request-ID" in cors.kwargs["expose_headers"]
