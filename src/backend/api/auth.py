"""Authentication API backed by the authoritative SQLAlchemy user store."""
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from src.backend.api.auth_deps import get_current_user, resolve_active_user
from src.backend.auth.authentication import (
    create_access_token, get_password_hash, verify_password, verify_token,
)
from src.backend.database.database import RefreshToken, SessionLocal, User
from src.config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Auth"])
REFRESH_LIFETIME = timedelta(days=7)


class LoginRequest(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    password: str


class BootstrapSuperAdminRequest(BaseModel):
    email: str
    password: str
    name: Optional[str] = None


class DemoLoginRequest(BaseModel):
    # "employee" is kept only as a backward-compatible alias for "general" —
    # new callers should use "general" so the selected department is never
    # ambiguous. Each of finance/hr/engineering maps to exactly one dedicated
    # public-demo identity, never to an internal credentialed account.
    role: Literal["admin", "employee", "general", "finance", "hr", "engineering", "ceo"]


# identifier -> {authoritative demo email, the DB role that email MUST carry}.
# The expected_role is validated below rather than assumed equal to the
# identifier key, precisely so "general" and "employee" can both resolve to
# the same employee-role identity without an identifier/DB-role mismatch.
PUBLIC_DEMO_IDENTITIES: dict[str, dict[str, str]] = {
    "admin": {"email": "portfolio.admin@finsolve.demo", "expected_role": "admin"},
    "general": {"email": "portfolio.employee@finsolve.demo", "expected_role": "employee"},
    "employee": {"email": "portfolio.employee@finsolve.demo", "expected_role": "employee"},
    "finance": {"email": "portfolio.finance@finsolve.demo", "expected_role": "finance"},
    "hr": {"email": "portfolio.hr@finsolve.demo", "expected_role": "hr"},
    "engineering": {"email": "portfolio.engineering@finsolve.demo", "expected_role": "engineering"},
    "ceo": {"email": "portfolio.ceo@finsolve.demo", "expected_role": "c_level"},
}


def _extract_access_token(request: Request) -> Optional[str]:
    """Compatibility helper; never reads the refresh cookie."""
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1]
    return request.cookies.get("session_token")


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _cookie_options() -> dict:
    # Production is intentionally same-site. Cross-site cookies are not enabled
    # until a deployment has an explicit CSRF/origin design for that topology.
    return {
        "httponly": True,
        "secure": settings.is_production,
        "samesite": "lax",
    }


VSID_COOKIE_NAME = "vsid"


def _issue_visitor_session_cookie(response: Response) -> str:
    """Issue a fresh, opaque, high-entropy visitor-session id for a public-
    demo login.

    Server-issued only: never accepted from the client, never a JWT claim,
    never returned in a JSON response body. httpOnly (unreadable by frontend
    JS), and reuses the exact same Secure/SameSite policy as the other auth
    cookies (_cookie_options()) plus the refresh-cookie lifetime, so it is
    never weaker than the existing cookie policy.
    """
    vsid = secrets.token_urlsafe(32)
    options = _cookie_options()
    response.set_cookie(
        VSID_COOKIE_NAME, vsid,
        max_age=int(REFRESH_LIFETIME.total_seconds()),
        path="/", **options,
    )
    return vsid


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str,
                      csrf_token: str) -> None:
    options = _cookie_options()
    response.set_cookie("session_token", access_token,
                        max_age=settings.access_token_expire_minutes * 60,
                        path="/", **options)
    response.set_cookie("refresh_token", refresh_token,
                        max_age=int(REFRESH_LIFETIME.total_seconds()),
                        path="/auth", **options)
    response.set_cookie(
        "csrf_token", csrf_token, httponly=False, secure=settings.is_production,
        samesite="lax", path="/", max_age=int(REFRESH_LIFETIME.total_seconds()),
    )


def _issue_tokens(user: dict) -> tuple[str, str, str, datetime]:
    identity = {"sub": user["email"], "type": "access"}
    access_token = create_access_token(identity)
    refresh_token = create_access_token(
        {"sub": user["email"], "type": "refresh"},
        expires_delta=REFRESH_LIFETIME,
    )
    refresh_payload = verify_token(refresh_token)
    return access_token, refresh_token, refresh_payload["jti"], datetime.fromtimestamp(
        refresh_payload["exp"], timezone.utc
    )


@router.post("/bootstrap-super-admin")
async def bootstrap_super_admin(payload: BootstrapSuperAdminRequest, request: Request):
    """One-time creation of the private Super Admin account.

    Disabled (404) unless SUPER_ADMIN_BOOTSTRAP_TOKEN is set; requires that
    token in X-Bootstrap-Token, an email already listed in SUPER_ADMIN_EMAILS,
    and refuses if the account exists. The password is hashed with the normal
    scheme and never logged. Remove the token afterwards to disable the route.
    """
    token = settings.super_admin_bootstrap_token or ""
    if len(token) < 32:
        raise HTTPException(status_code=404, detail="Not found")
    presented = request.headers.get("X-Bootstrap-Token", "")
    if not hmac.compare_digest(presented.encode(), token.encode()):
        raise HTTPException(status_code=403, detail="Forbidden")
    email = _normalize_email(payload.email)
    allowed = {e.strip().lower() for e in (settings.super_admin_emails or [])}
    if "@" not in email or email not in allowed:
        raise HTTPException(status_code=403, detail="Forbidden")
    if len(payload.password) < 12 or len(payload.password) > 128:
        raise HTTPException(status_code=422, detail="Password must be 12-128 characters")
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == email).first():
            raise HTTPException(status_code=409, detail="Account already exists")
        db.add(User(
            id=email, username=email, email=email,
            hashed_password=get_password_hash(payload.password),
            full_name=(payload.name or "Super Admin").strip()[:80] or "Super Admin",
            role="admin", tenant_id=settings.demo_tenant_id, department="General",
            is_active=True, is_public_demo=False,
        ))
        db.commit()
    finally:
        db.close()
    logger.warning("SUPER_ADMIN_BOOTSTRAPPED")
    return {"created": True}


@router.post("/login")
async def login(payload: LoginRequest, response: Response):
    identifier = payload.email or payload.username
    if not identifier:
        raise HTTPException(status_code=422, detail="Email or username is required")
    email = _normalize_email(identifier)
    db = SessionLocal()
    try:
        record = db.query(User).filter(User.email == email).first()
        # Public-demo identities have publicly documented passwords; they may
        # only be entered through /auth/demo-login, which PUBLIC_DEMO_ENABLED
        # gates. Rejected with the same response as a wrong password.
        valid = bool(
            record and record.is_active and record.hashed_password
            and not record.is_public_demo
            and verify_password(payload.password, record.hashed_password)
        )
        if not valid:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        db.close()
        user = resolve_active_user(email)
        access, refresh, jti, expires_at = _issue_tokens(user)
        db = SessionLocal()
        db.add(RefreshToken(jti=jti, user_id=user["id"], expires_at=expires_at))
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Login token issuance failed")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    finally:
        db.close()

    csrf_token = secrets.token_urlsafe(32)
    _set_auth_cookies(response, access, refresh, csrf_token)
    return {"access_token": access, "token_type": "bearer", "csrf_token": csrf_token,
            "user": user}


@router.post("/demo-login")
async def demo_login(payload: DemoLoginRequest, response: Response):
    """Issue a normal session for one predefined public-demo identity.

    This is not an authentication bypass: the role maps to a server allowlist,
    the SQLAlchemy User row remains authoritative, and normal JWT/JTI/cookie
    issuance is reused.
    """
    if not settings.public_demo_enabled:
        raise HTTPException(status_code=404, detail="Public demo login is unavailable")
    identity = PUBLIC_DEMO_IDENTITIES[payload.role]
    email = identity["email"]
    user = resolve_active_user(email)
    if (
        not user.get("is_public_demo")
        or user.get("tenant_id") != settings.demo_tenant_id
        or user.get("role") != identity["expected_role"]
    ):
        logger.error("Public demo identity has invalid authoritative state: %s", email)
        raise HTTPException(status_code=503, detail="Public demo login is unavailable")

    access, refresh_token, jti, expires_at = _issue_tokens(user)
    db = SessionLocal()
    try:
        db.add(RefreshToken(jti=jti, user_id=user["id"], expires_at=expires_at))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Public demo token issuance failed")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    finally:
        db.close()

    csrf_token = secrets.token_urlsafe(32)
    _set_auth_cookies(response, access, refresh_token, csrf_token)
    # Every successful public-demo login gets a FRESH visitor-session id, so
    # re-choosing a demo identity always starts an isolated conversation
    # partition rather than reusing whatever the browser happened to hold.
    _issue_visitor_session_cookie(response)
    return {"access_token": access, "token_type": "bearer", "csrf_token": csrf_token,
            "user": user}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return user


@router.post("/refresh")
async def refresh(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing refresh token")
    try:
        payload = verify_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if payload.get("type") != "refresh" or not payload.get("jti"):
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = resolve_active_user(payload.get("sub"))
    access, new_refresh, new_jti, expires_at = _issue_tokens(user)
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        consumed = (
            db.query(RefreshToken)
            .filter(
                RefreshToken.jti == payload["jti"],
                RefreshToken.user_id == user["id"],
                RefreshToken.revoked_at.is_(None),
            )
            .update({"revoked_at": now, "replaced_by": new_jti}, synchronize_session=False)
        )
        if consumed != 1:
            db.rollback()
            raise HTTPException(status_code=401, detail="Refresh token has been revoked")
        db.add(RefreshToken(jti=new_jti, user_id=user["id"], expires_at=expires_at))
        db.commit()
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Refresh rotation failed")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    finally:
        db.close()

    csrf_token = secrets.token_urlsafe(32)
    _set_auth_cookies(response, access, new_refresh, csrf_token)
    return {"access_token": access, "token_type": "bearer", "csrf_token": csrf_token}


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if token:
        try:
            payload = verify_token(token)
            if payload.get("type") == "refresh" and payload.get("jti"):
                db = SessionLocal()
                try:
                    db.query(RefreshToken).filter(
                        RefreshToken.jti == payload["jti"],
                        RefreshToken.revoked_at.is_(None),
                    ).update({"revoked_at": datetime.now(timezone.utc)}, synchronize_session=False)
                    db.commit()
                finally:
                    db.close()
        except Exception:
            logger.info("Logout received an invalid or already-expired refresh credential")
    response.delete_cookie("session_token", path="/", secure=settings.is_production,
                           samesite="lax")
    response.delete_cookie("refresh_token", path="/auth", secure=settings.is_production,
                           samesite="lax")
    response.delete_cookie("csrf_token", path="/", secure=settings.is_production,
                           samesite="lax")
    # Always attempt to clear the visitor-session cookie too. A no-op for a
    # non-demo session (the cookie was never set); for a demo session this
    # ends that browser's visitor-scoped conversation partition.
    response.delete_cookie(VSID_COOKIE_NAME, path="/", secure=settings.is_production,
                           samesite="lax")
    return {"success": True}
