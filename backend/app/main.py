from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import get_settings
from .db import init_db
from .errors import (
    AppError,
    app_error_handler,
    http_handler,
    unexpected_handler,
    validation_handler,
)
from .middleware import SecurityHeadersMiddleware
from .rate_limit import limiter
from .routers import auth, chat, groups, org, profile, verify
from .services.face import preload_model

log = logging.getLogger("secureconnect")

# Project root: backend/  → suraj/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_FRONTEND_DIR = _PROJECT_ROOT / "frontend"

_settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=_settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log.info("startup app_env=%s", _settings.app_env)
    init_db()
    preload_model()
    yield
    log.info("shutdown")


app = FastAPI(
    title="SecureConnect-AI",
    version="1.0.0",
    description="Hyperlocal trust-network demo with face + org verification.",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

# Rate limiter wiring
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Security headers (runs on every response)
app.add_middleware(SecurityHeadersMiddleware)

# CORS — exact origin allowlist (not "*").
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_settings.allowed_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining"],
)

# Exception handlers — sanitized output.
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_handler)
app.add_exception_handler(StarletteHTTPException, http_handler)
app.add_exception_handler(Exception, unexpected_handler)

# API routers
app.include_router(auth.router)
app.include_router(verify.router)
app.include_router(org.router)
app.include_router(groups.router)
app.include_router(chat.router)
app.include_router(profile.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "secureconnect-ai", "version": app.version}


# Frontend static files.
if _FRONTEND_DIR.exists():
    app.mount("/css", StaticFiles(directory=_FRONTEND_DIR / "css"), name="css")
    app.mount("/js", StaticFiles(directory=_FRONTEND_DIR / "js"), name="js")
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIR / "assets"), name="assets")

    _PAGE_FILES = {
        "/": "index.html",
        "/login": "login.html",
        "/register": "register.html",
        "/verify": "verify.html",
        "/discover": "discover.html",
        "/profile": "profile.html",
        "/chat": "chat.html",
    }

    def _make_page_route(filename: str):
        async def _serve():
            return FileResponse(_FRONTEND_DIR / filename)
        return _serve

    for route, filename in _PAGE_FILES.items():
        app.add_api_route(
            route,
            _make_page_route(filename),
            methods=["GET", "HEAD"],
            include_in_schema=False,
        )


@app.exception_handler(404)
async def _not_found(request: Request, exc: StarletteHTTPException) -> JSONResponse | FileResponse:
    # Frontend pages handle their own 404 messaging; API consumers get JSON.
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=404, content={"detail": "Not found."})
    if _FRONTEND_DIR.exists():
        return FileResponse(_FRONTEND_DIR / "index.html", status_code=404)
    return JSONResponse(status_code=404, content={"detail": "Not found."})
