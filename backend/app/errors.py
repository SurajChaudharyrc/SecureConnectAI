from __future__ import annotations

import logging

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("secureconnect.errors")


class AppError(Exception):
    status_code: int = 400
    public_message: str = "Request could not be processed."

    def __init__(self, public_message: str | None = None, status_code: int | None = None):
        super().__init__(public_message or self.public_message)
        if public_message:
            self.public_message = public_message
        if status_code:
            self.status_code = status_code


class AuthRequired(AppError):
    status_code = 401
    public_message = "Authentication required."


class Forbidden(AppError):
    status_code = 403
    public_message = "You do not have permission to perform this action."


class NotFound(AppError):
    status_code = 404
    public_message = "Not found."


class Conflict(AppError):
    status_code = 409
    public_message = "Conflict with existing resource."


class UploadInvalid(AppError):
    status_code = 400
    public_message = "Uploaded file is not a valid image."


class TooLarge(AppError):
    status_code = 413
    public_message = "File too large."


class CsrfInvalid(AppError):
    status_code = 403
    public_message = "Invalid CSRF token."


def _json(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": message})


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    log.info("app_error", extra={"status": exc.status_code, "path": request.url.path})
    return _json(exc.status_code, exc.public_message)


async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Surface field-level issues but not internal trace.
    fields = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", []) if x not in ("body",))
        fields.append({"field": loc or "?", "issue": err.get("msg", "invalid")})
    log.info("validation_error", extra={"path": request.url.path, "errors": len(fields)})
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Invalid request.", "errors": fields},
    )


async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return _json(exc.status_code, detail)


async def unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error", extra={"path": request.url.path})
    return _json(500, "Internal server error.")
