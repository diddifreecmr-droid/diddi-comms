from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from app_base.core.metrics import increment

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers or {}


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    if exc.status_code in {401, 403}:
        increment("diddicomms_auth_denials_total", {"code": exc.code, "status_code": exc.status_code})
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "request_id": request.state.request_id}},
        headers=exc.headers,
    )


async def infrastructure_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("infrastructure_error", extra={"request_id": getattr(request.state, "request_id", None)})
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "INFRASTRUCTURE_UNAVAILABLE",
                "message": "A required dependency is temporarily unavailable.",
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error", extra={"request_id": getattr(request.state, "request_id", None)})
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred.",
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )
