"""Stable application error responses for the FastAPI boundary."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictStr

from app.core.logging import correlation_log_extra

logger = logging.getLogger("app.errors")


class ApplicationError(Exception):
    """Expected application failure with a stable public error code."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    code: StrictStr
    message: StrictStr


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    error: ErrorDetail


async def application_error_handler(request: Request, exc: ApplicationError) -> JSONResponse:
    del request
    extra = correlation_log_extra()
    logger.warning(
        "application error mapped code=%s status_code=%s trace_id=%s request_id=%s",
        exc.code,
        exc.status_code,
        extra["trace_id"],
        extra["request_id"],
        extra=extra,
    )
    response = ErrorResponse(
        error=ErrorDetail(code=exc.code, message=exc.message),
    )
    return JSONResponse(status_code=exc.status_code, content=response.model_dump())


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    del request, exc
    extra = correlation_log_extra()
    logger.error(
        "unexpected application error mapped to stable internal response trace_id=%s request_id=%s",
        extra["trace_id"],
        extra["request_id"],
        extra=extra,
    )
    response = ErrorResponse(
        error=ErrorDetail(
            code="INTERNAL_ERROR",
            message="Internal server error",
        ),
    )
    return JSONResponse(status_code=500, content=response.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApplicationError, application_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
