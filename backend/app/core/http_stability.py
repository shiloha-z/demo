"""HTTP reliability and diagnostics shared by the FastAPI application."""

from __future__ import annotations

import logging
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
PROCESS_TIME_HEADER = "X-Process-Time-Ms"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _request_id_from(request: Request) -> str:
    """Accept a safe upstream ID or generate a compact correlation ID."""
    candidate = request.headers.get(REQUEST_ID_HEADER, "")
    if _VALID_REQUEST_ID.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex


def install_http_stability(app: FastAPI) -> None:
    """Install correlation, latency diagnostics, and safe 500 responses."""

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = _request_id_from(request)
        request.state.request_id = request_id
        started = time.perf_counter()
        request.state.request_started = started

        response = await call_next(request)

        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[PROCESS_TIME_HEADER] = f"{elapsed_ms:.1f}"
        if elapsed_ms >= max(0.0, settings.SLOW_REQUEST_THRESHOLD_SECONDS) * 1000:
            logger.warning(
                "Slow request method=%s path=%s status=%s duration_ms=%.1f request_id=%s",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
                request_id,
            )
        return response

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
        started = getattr(request.state, "request_started", time.perf_counter())
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.exception(
            "Unhandled request failure method=%s path=%s request_id=%s",
            request.method,
            request.url.path,
            request_id,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "服务暂时不可用，请稍后重试",
                "request_id": request_id,
            },
            headers={
                REQUEST_ID_HEADER: request_id,
                PROCESS_TIME_HEADER: f"{elapsed_ms:.1f}",
            },
        )
