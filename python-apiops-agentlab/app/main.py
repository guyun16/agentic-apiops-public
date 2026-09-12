"""Minimal FastAPI application boundary for local Python validation."""

from __future__ import annotations

import logging
from asyncio import to_thread
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.api.routes import router
from app.core.errors import register_exception_handlers
from app.core.http_tls import client_tls_context
from app.core.logging import bind_correlation, configure_logging, correlation_log_extra

configure_logging()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Pay certificate loading once before accepting traffic, off the event loop.
    await to_thread(client_tls_context)
    yield


app = FastAPI(
    title="Python APIOps AgentLab",
    version="0.1.0",
    lifespan=lifespan,
)
http_logger = logging.getLogger("app.http")


@app.middleware("http")
async def correlation_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Bind request-local IDs and log the HTTP boundary without request headers."""

    with bind_correlation(request.headers.get("x-trace-id")) as ids:
        extra = correlation_log_extra()
        http_logger.info(
            "request started method=%s path=%s trace_id=%s request_id=%s",
            request.method,
            request.url.path,
            ids.trace_id,
            ids.request_id,
            extra=extra,
        )
        try:
            response = await call_next(request)
        except Exception:
            http_logger.error(
                "request failed method=%s path=%s trace_id=%s request_id=%s",
                request.method,
                request.url.path,
                ids.trace_id,
                ids.request_id,
                extra=extra,
            )
            raise
        http_logger.info(
            "request completed method=%s path=%s status_code=%s trace_id=%s request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            ids.trace_id,
            ids.request_id,
            extra=extra,
        )
        return response


register_exception_handlers(app)
app.include_router(router)


async def main() -> None:
    """Preserve the existing async module boundary for the AgentLab."""
    pass
