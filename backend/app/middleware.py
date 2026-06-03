from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .config import get_settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds standard security headers to every response.

    CSP is intentionally strict but compatible with the bundled
    vanilla HTML/CSS/JS frontend (no external scripts, no inline JS).
    """

    def __init__(self, app):
        super().__init__(app)
        self._settings = get_settings()

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)

        csp = (
            "default-src 'self'; "
            "img-src 'self' data: blob:; "
            "media-src 'self' blob:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; "
            "connect-src 'self'; "
            "font-src 'self' data:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        response.headers.setdefault("Content-Security-Policy", csp)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(self), microphone=(), geolocation=(self), payment=()",
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")

        if self._settings.is_prod:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

        # Don't allow caching auth-sensitive responses by default.
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        else:
            # Frontend assets/pages: cache but force revalidation, so updated
            # JS/CSS/HTML is always picked up instead of a stale cached copy.
            response.headers.setdefault("Cache-Control", "no-cache")

        return response
