"""Shared HTTP problem contract for the local API.

Routers retain ownership of their domain-specific error codes.  This module
keeps the response envelope and HTTP meaning of those codes consistent.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError


def api_problem(status_code: int, code: str, message: str, **details: Any) -> HTTPException:
    """Create the one API error envelope consumed by UI-001."""
    return HTTPException(status_code, {"code": code, "message": message, **details})


def domain_problem(
    error: Exception, *, status_code: int, code: str | None = None, **details: Any,
) -> HTTPException:
    """Adapt a domain exception without making the API parse its prose."""
    return api_problem(status_code, code or getattr(error, "code", "domain_error"), str(error), **details)


def workspace_unavailable(message: str) -> HTTPException:
    return api_problem(status.HTTP_503_SERVICE_UNAVAILABLE, "workspace_unavailable", message)


def register_api_error_handlers(app: FastAPI) -> None:
    """Map schema bounds to 413 and all other request schema failures to 422."""
    @app.exception_handler(RequestValidationError)
    async def request_validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        problem = validation_problem(error)
        return JSONResponse(status_code=problem.status_code, content={"detail": problem.detail})


def validation_problem(error: RequestValidationError | ValidationError) -> HTTPException:
    """Return 413 for bounded content and 422 for malformed typed input."""
    if any(_is_size_limit_violation(item) for item in error.errors()):
        return api_problem(413, "request_payload_too_large", "Request content exceeds an allowed limit.")
    return api_problem(422, "request_validation", "Request validation failed.")


def _is_size_limit_violation(error: Mapping[str, Any]) -> bool:
    # Pydantic v2 reports bounded strings as string_too_long and bounded
    # containers as too_long. Values below a lower bound remain malformed
    # request data and therefore retain 422.
    return error.get("type") in {"string_too_long", "too_long"}
