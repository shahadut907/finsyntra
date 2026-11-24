"""Public-demo usage endpoints: the visitor's indicator and Super Admin controls.

Every ``/admin/demo-usage`` route requires ``get_super_admin_user``: an
authenticated private admin account on the SUPER_ADMIN_EMAILS allowlist. The
public-demo "Admin" persona can never pass it.
"""
import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.backend.api.auth_deps import (
    get_current_user,
    get_super_admin_user,
    require_visitor_session_for_demo,
)
from src.backend.services import demo_usage
from src.config.settings import settings

router = APIRouter()


@router.get("/demo/usage")
async def my_demo_usage(request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    """Today's allowance for the calling visitor (public-demo identities only)."""
    if demo_usage.is_super_admin(user):
        return {"enabled": False, "super_admin": True}
    if not (user.get("is_public_demo") and settings.public_demo_enabled):
        return {"enabled": False}
    vsid = require_visitor_session_for_demo(user, request)
    return await asyncio.to_thread(
        demo_usage.usage_snapshot,
        demo_usage.visitor_key(vsid),
        demo_usage.ip_key(demo_usage.resolve_client_ip(request)),
    )


@router.get("/admin/demo-usage")
async def admin_demo_usage(user: Dict[str, Any] = Depends(get_super_admin_user)):
    """Overall daily usage, remaining quota, active requests and effective limits.
    Aggregates only: no visitor or IP identifiers."""
    return await asyncio.to_thread(demo_usage.admin_overview)


class LimitsUpdate(BaseModel):
    """Omitted fields are untouched; null restores the environment default."""
    model_config = ConfigDict(extra="forbid")

    visitor_daily_limit: Optional[int] = None
    ip_daily_limit: Optional[int] = None
    global_daily_limit: Optional[int] = None
    daily_token_budget: Optional[int] = None
    super_admin_token_reserve: Optional[int] = None


@router.put("/admin/demo-usage/limits")
async def update_limits(body: LimitsUpdate, user: Dict[str, Any] = Depends(get_super_admin_user)):
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    if not changes:
        raise HTTPException(status_code=400, detail="No limits supplied")
    try:
        return await asyncio.to_thread(demo_usage.update_runtime_settings, changes, user["email"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class AccessUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    # Optional automatic re-enable: pause for this many minutes (max 7 days).
    pause_minutes: Optional[int] = Field(default=None, ge=1, le=10080)
    message: Optional[str] = Field(default=None, max_length=300)


@router.put("/admin/demo-usage/access")
async def update_access(body: AccessUpdate, user: Dict[str, Any] = Depends(get_super_admin_user)):
    """Temporarily disable (or re-enable) public demo chat. Super Admin chat
    keeps working while paused."""
    from datetime import datetime, timedelta, timezone
    if body.enabled:
        changes = {"paused": None, "paused_until": None, "pause_message": None}
    else:
        until = None
        if body.pause_minutes:
            until = (datetime.now(timezone.utc) + timedelta(minutes=body.pause_minutes)).isoformat()
        changes = {"paused": True, "paused_until": until,
                   "pause_message": (body.message or "").strip() or None}
    await asyncio.to_thread(demo_usage.update_runtime_settings, changes, user["email"])
    return {"public_access": demo_usage.pause_state()}


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str = Field(..., description="visitors | global_messages | all_messages")


@router.post("/admin/demo-usage/reset")
async def reset_counters(body: ResetRequest, user: Dict[str, Any] = Depends(get_super_admin_user)):
    """Reset today's message counters. Token usage is deliberately not reset."""
    try:
        return await asyncio.to_thread(demo_usage.reset_counters, body.scope, user["email"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
