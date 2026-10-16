"""Map domain errors to RFC 9457 problem+json responses."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from nexscout.domain import errors as e
from nexscout.observability import get_logger

log = get_logger(__name__)

_STATUS: dict[type[e.DomainError], int] = {
    e.NotFound: 404,
    e.ConcurrencyConflict: 409,
    e.Conflict: 409,
    e.ValidationFailed: 422,
    e.AuthenticationFailed: 401,
    e.PermissionDenied: 403,
    e.RateLimited: 429,
    e.InvalidTransition: 409,
}


def status_for(exc: e.DomainError) -> int:
    for cls in type(exc).__mro__:
        status = _STATUS.get(cls)
        if status is not None:
            return status
    return 400


def problem(status: int, code: str, detail: str, request: Request, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"https://nexscout.local/problems/{code}",
            "title": code.replace("_", " ").capitalize(),
            "status": status,
            "detail": detail,
            "code": code,
            "request_id": getattr(request.state, "request_id", None),
            **extra,
        },
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(e.DomainError)
    async def _domain(request: Request, exc: e.DomainError) -> JSONResponse:
        return problem(status_for(exc), exc.code, exc.message, request)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"loc": [str(p) for p in err.get("loc", ())], "msg": str(err.get("msg", ""))}
            for err in exc.errors()
        ]
        return problem(422, "validation_failed", "Some fields are invalid.", request, errors=fields)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path)
        return problem(500, "internal_error", "Something went wrong on our side.", request)
