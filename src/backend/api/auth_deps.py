"""Authoritative FastAPI authentication dependencies.

JWT claims identify a credential. Current role, tenant and active state always
come from the SQLAlchemy User row and are never accepted from token claims.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, status

from src.backend.auth.authentication import verify_token
from src.backend.database.database import SessionLocal, User
from src.config.settings import settings

logger = logging.getLogger(__name__)


def _unauthorized(message: str = "Invalid or expired access token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "INVALID_ACCESS_TOKEN", "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _extract_access_credential(request: Request) -> Optional[str]:
    header = request.headers.get("Authorization", "")
    if header:
        scheme, separator, token = header.partition(" ")
        if scheme.lower() != "bearer" or not separator or not token.strip():
            raise _unauthorized("A Bearer access token is required")
        return token.strip()
    return request.cookies.get("session_token")


def resolve_active_user(subject: str) -> Dict[str, Any]:
    """Resolve server-authoritative identity, tenancy, role, and active state."""
    if not isinstance(subject, str) or "@" not in subject or len(subject) > 320:
        raise _unauthorized("Token subject is invalid")
    subject = subject.strip().lower()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == subject).first()
        if user is None or not user.is_active:
            raise _unauthorized("User account is unavailable")
        if not user.tenant_id or not user.role:
            logger.error("User %s has incomplete authorization state", subject)
            raise _unauthorized("User account is unavailable")
        role = user.role.lower()
        return {
            "id": user.id,
            "email": user.email,
            "name": user.full_name or "User",
            "role": role,
            "department": user.department or "General",
            "tenant_id": user.tenant_id,
            "organization_id": user.tenant_id,
            "is_active": bool(user.is_active),
            "is_public_demo": bool(user.is_public_demo),
            # Display hint only: this tenant's content is served to the
            # public demo personas. Never used for authorization.
            "tenant_serves_public_demo": user.tenant_id == settings.demo_tenant_id,
            "is_admin": role in {"admin", "c_level"},
            "admin_level": "c_level" if role == "c_level" else (
                "admin" if role == "admin" else "none"
            ),
        }
    finally:
        db.close()


async def get_current_user(request: Request) -> Dict[str, Any]:
    token = _extract_access_credential(request)
    if not token:
        raise _unauthorized("Authentication required")
    try:
        payload = verify_token(token)
    except Exception:
        raise _unauthorized()
    if payload.get("type") != "access":
        raise _unauthorized("An access token is required")
    return resolve_active_user(payload.get("sub"))


async def get_current_user_optional(request: Request) -> Optional[Dict[str, Any]]:
    try:
        return await get_current_user(request)
    except HTTPException:
        return None


async def get_current_admin_user(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    if user["role"] not in {"admin", "c_level"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "ADMIN_REQUIRED", "message": "Administrator access required"},
        )
    return user


async def get_super_admin_user(request: Request) -> Dict[str, Any]:
    """Backend-only gate for the public-demo controls: an authenticated private
    admin account on the configured allowlist. No IP allowlist, no bypass."""
    user = await get_current_admin_user(request)
    from src.backend.services.demo_usage import is_super_admin
    if not is_super_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "SUPER_ADMIN_REQUIRED", "message": "Super Administrator access required"},
        )
    return user


def require_non_demo_mutation(user: Dict[str, Any]) -> None:
    """Block shared-state mutations for authoritative public-demo identities."""
    if user.get("is_public_demo"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PUBLIC_DEMO_READ_ONLY", "message": "Disabled in public demo"},
        )


def get_visitor_session_id(request: Request) -> Optional[str]:
    """Read the server-issued, httpOnly visitor-session cookie ("vsid").

    Cookie only — never accepted from a query parameter, request JSON body,
    or JWT claim. Returns None when absent; the cookie is never a claim on
    the JWT itself, so its presence/absence is independent of token refresh.
    """
    return request.cookies.get("vsid") or None


def require_visitor_session_for_demo(user: Dict[str, Any], request: Request) -> Optional[str]:
    """Resolve the extra Phase 3 conversation-ownership partition key.

    Non-demo accounts: always returns None. Callers must treat None as "do
    not apply any visitor_session_id filter" so existing user_id+tenant_id
    ownership semantics are completely unchanged for every non-demo account.

    Public-demo accounts: the visitor cookie is REQUIRED. Its absence fails
    closed with DEMO_VISITOR_SESSION_REQUIRED rather than silently falling
    back to legacy visitor_session_id IS NULL conversations, which could
    otherwise expose old shared demo history to a brand-new visitor.

    This is the single place that decides "is a vsid required, and do we
    have one" — every conversation-touching route calls this instead of
    duplicating the cookie read and the fail-closed check.
    """
    if not user.get("is_public_demo"):
        return None
    vsid = get_visitor_session_id(request)
    if not vsid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "DEMO_VISITOR_SESSION_REQUIRED",
                "message": "A visitor session is required for the public demo.",
            },
        )
    return vsid
