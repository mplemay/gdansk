from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.responses import RedirectResponse, Response

from gdansk.inertia.utils import _ERRORS_SESSION_KEY

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from starlette.requests import Request

_REQUEST_SCOPES = {"body", "cookie", "form", "header", "path", "query"}


async def inertia_request_validation_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, RequestValidationError):
        msg = "The inertia validation handler only accepts RequestValidationError instances"
        raise TypeError(msg)

    if "X-Inertia" not in request.headers:
        return await request_validation_exception_handler(request, exc)

    try:
        session = request.session
    except AssertionError:
        return await request_validation_exception_handler(request, exc)

    errors = _collect_errors(cast("Sequence[Mapping[str, Any]]", exc.errors()))
    if bag := request.headers.get("X-Inertia-Error-Bag", "").strip():
        session[_ERRORS_SESSION_KEY] = {bag: errors}
    else:
        session[_ERRORS_SESSION_KEY] = errors

    return RedirectResponse(
        url=request.headers.get("referer", "/"),
        status_code=307 if request.method == "GET" else 303,
        headers={"Vary": "X-Inertia"},
    )


def _collect_errors(error_details: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    errors: dict[str, str] = {}

    for detail in error_details:
        message = detail.get("msg")
        if not isinstance(message, str):
            continue

        field = _resolve_error_field(detail.get("loc"))
        errors[field] = message

    return errors


def _resolve_error_field(location: object) -> str:
    if not isinstance(location, tuple) or not location:
        return "form"

    parts = [str(part) for part in location]
    if parts[0] in _REQUEST_SCOPES:
        parts = parts[1:]

    return ".".join(parts) if parts else "form"


__all__ = ["inertia_request_validation_exception_handler"]
