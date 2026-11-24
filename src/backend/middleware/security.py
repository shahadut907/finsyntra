"""Registered HTTP security controls for FinSyntra."""
import hashlib
import logging
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config.settings import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self):
        self.requests = defaultdict(deque)
        self._lock = threading.Lock()

    def is_allowed(self, identifier: str, max_requests: int, window: int = 60) -> bool:
        now = time.monotonic()
        with self._lock:
            entries = self.requests[identifier]
            while entries and entries[0] <= now - window:
                entries.popleft()
            if len(entries) >= max_requests:
                return False
            entries.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self.requests.clear()


rate_limiter = RateLimiter()


class SecurityValidator:
    @staticmethod
    def validate_query_input(query: str) -> tuple[bool, Optional[str]]:
        if not query or not query.strip():
            return False, "Query cannot be empty"
        if len(query) > 10000:
            return False, "Query too long (max 10,000 characters)"
        for pattern in (r"<script[^>]*>.*?</script>", r"javascript:", r"vbscript:",
                        r"on\w+\s*=", r"eval\s*\(", r"exec\s*\("):
            if re.search(pattern, query, re.IGNORECASE):
                return False, "Invalid characters detected in query"
        return True, None

    @staticmethod
    def validate_session_id(session_id: str) -> tuple[bool, Optional[str]]:
        if not session_id:
            return True, None
        if len(session_id) > 100 or not re.match(r"^[a-zA-Z0-9_-]+$", session_id):
            return False, "Invalid session ID format"
        return True, None


def _client_key(request: Request, bucket: str) -> str:
    from src.backend.services.demo_usage import resolve_client_ip
    address = resolve_client_ip(request)
    return hashlib.sha256(f"{bucket}:{address}".encode()).hexdigest()


def _routed_path(request: Request) -> str:
    """The path the router actually dispatches on.

    request.url is rebuilt from the Host header, which Starlette < 1.0.1 does
    not validate (CVE-2026-48710): a crafted Host can make request.url.path
    differ from the routed path. Security decisions use the scope path.
    """
    return request.scope.get("path", "")


def _cookie_authenticated_mutation(request: Request) -> bool:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False
    if _routed_path(request) in {"/auth/login", "/auth/demo-login"}:
        return False
    if request.headers.get("Authorization", "").lower().startswith("bearer "):
        return False
    return bool(request.cookies.get("session_token") or request.cookies.get("refresh_token"))


async def security_middleware(request: Request, call_next):
    path = _routed_path(request)

    # No endpoint accepts urlencoded forms (the UI sends JSON or multipart),
    # and Starlette < 1.3.1 parses them without field/size limits
    # (CVE-2026-54283). Refuse them before any handler parses a body.
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type == "application/x-www-form-urlencoded":
        return JSONResponse(status_code=415, content={"detail": "Unsupported media type"})
    if path in {"/auth/login", "/auth/demo-login"}:
        if path == "/auth/demo-login" and settings.public_demo_enabled:
            limit = settings.public_demo_login_rate_limit_per_minute
            bucket = "public-demo-login"
        else:
            limit = settings.login_rate_limit_per_minute
            bucket = "login"
    elif path == "/auth/refresh":
        limit = settings.refresh_rate_limit_per_minute
        bucket = "refresh"
    elif path == "/api/speech/transcribe":
        # Each dictation spends provider quota; keep it tighter than general.
        limit = settings.speech_rate_limit_per_minute
        bucket = "speech"
    elif settings.public_demo_enabled and path in {"/api/chat", "/api/chat/stream"}:
        limit = settings.public_demo_chat_rate_limit_per_minute
        bucket = "public-demo-chat"
    else:
        limit = settings.rate_limit_per_minute
        bucket = "general"
    if not rate_limiter.is_allowed(_client_key(request, bucket), limit):
        # Structured detail: AuthContext unwraps detail.message for display.
        return JSONResponse(
            status_code=429,
            content={"detail": {
                "code": "RATE_LIMITED",
                "message": "Too many requests. Please wait a minute and try again.",
            }},
            headers={"Retry-After": "60"})

    if _cookie_authenticated_mutation(request):
        origin = request.headers.get("Origin")
        if origin and origin not in settings.cors_origins:
            return JSONResponse(status_code=403, content={"detail": "Origin not allowed"})
        cookie_token = request.cookies.get("csrf_token")
        header_token = request.headers.get("X-CSRF-Token")
        if not cookie_token or not header_token or not secrets.compare_digest(
            cookie_token, header_token
        ):
            return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    if settings.is_production and (
        request.url.scheme == "https"
        or request.headers.get("X-Forwarded-Proto", "").lower() == "https"
    ):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def setup_security_middleware(app) -> None:
    app.middleware("http")(security_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Authorization", "Content-Type", "X-CSRF-Token"],
        expose_headers=["Retry-After"],
    )


def validate_input(func):
    async def wrapper(*args, **kwargs):
        for arg in args:
            if hasattr(arg, "message"):
                valid, error = SecurityValidator.validate_query_input(arg.message)
                if not valid:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)
                valid, error = SecurityValidator.validate_session_id(
                    getattr(arg, "session_id", None)
                )
                if not valid:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)
                break
        return await func(*args, **kwargs)
    return wrapper
