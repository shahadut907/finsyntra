"""Daily usage and abuse protection for the public demo.

Persistent limits (Neon/SQLite, UTC day):
  * per visitor   (demo_visitor_daily_limit)
  * per client IP (demo_ip_daily_limit)
  * global        (demo_global_daily_limit) + a Groq token budget

Concurrency limits (process-local; the service runs one uvicorn worker):
  * one active chat per visitor
  * demo_global_concurrency AI requests globally

Counters use conditional upserts, so a limit can never be exceeded under
concurrent requests, and the three scopes are charged in one transaction: a
request is either admitted against all of them or charged against none.
Identifiers are stored only as HMACs.

Super Admin (an authenticated private account, see ``is_super_admin``) is
exempt from the visitor/IP/global message limits and from the pause switch, but
never from infrastructure limits: the per-minute rate limit, the concurrency
slots and the token budget. Admin generations draw on a reserved token pool
(``demo_super_admin_token_reserve``) that public visitors can never spend.
The limits can be tuned at runtime by the Super Admin; overrides persist in the
database and are clamped to hard bounds.
"""
from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Request
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError

from src.config.settings import settings

logger = logging.getLogger(__name__)

_ACTIVE_TTL_SECONDS = 180.0  # a leaked lease can never block a visitor longer
_PRUNE_AFTER_DAYS = 14
_CONFIG_TTL_SECONDS = 5.0
_chain_logged = 0

# Who the current generation is charged to ("public" unless a Super Admin).
ACTOR: contextvars.ContextVar[str] = contextvars.ContextVar("demo_usage_actor", default="public")


# ── identity ────────────────────────────────────────────────────────────────

def is_super_admin(user: Dict[str, Any]) -> bool:
    """Backend-only check: private, active admin account on the allowlist.

    Public-demo personas (including the demo "Admin") can never qualify.
    """
    if not user or user.get("is_public_demo") or not user.get("is_active", True):
        return False
    if user.get("role") not in {"admin", "c_level"}:
        return False
    allowed = {e.strip().lower() for e in (settings.super_admin_emails or []) if isinstance(e, str)}
    return (user.get("email") or "").strip().lower() in allowed


def edge_verified(request: Request) -> bool:
    secret = settings.edge_proxy_secret or ""
    presented = request.headers.get("x-finsyntra-edge", "")
    return bool(secret) and len(secret) >= 32 and hmac.compare_digest(presented.encode(), secret.encode())


def resolve_client_ip(request: Request) -> str:
    """Best-effort real client address behind trusted reverse proxies.

    ``X-Forwarded-For`` is read from the right: the last ``trusted_proxy_hops``
    entries were appended by infrastructure we trust, so the entry just before
    them is the address that infrastructure saw. Entries further left are
    client-supplied and are ignored. Falls back to the socket peer.
    """
    global _chain_logged
    chain = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if chain and _chain_logged < 12:
        _chain_logged += 1
        masked = [".".join(p.split(".")[:3] + ["x"]) if p.count(".") == 3 else "ipv6" for p in chain]
        logger.info("CLIENT_IP_CHAIN entries=%d trusted_hops=%d edge=%s masked=%s", len(chain), settings.trusted_proxy_hops, edge_verified(request), masked)
    hops = max(int(settings.trusted_proxy_hops), 0)
    # Vercel's edge middleware proves a request came through it with a shared
    # secret; only then is the extra (Vercel egress) hop trusted. Anything else
    # is attributed to the address our own proxies saw, which a client cannot
    # forge by sending its own X-Forwarded-For.
    if edge_verified(request):
        hops += 1
    if chain and hops:
        return chain[max(len(chain) - 1 - hops, 0)][:64]
    return (request.client.host if request.client else "unknown")[:64]


def _hmac(kind: str, value: str) -> str:
    key = (settings.secret_key or "").encode()
    return hmac.new(key, f"finsyntra-demo-usage:{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:48]


def visitor_key(vsid: str) -> str:
    return _hmac("visitor", vsid)


def ip_key(ip: str) -> str:
    return _hmac("ip", ip)


# ── time ────────────────────────────────────────────────────────────────────

def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def next_reset() -> datetime:
    now = datetime.now(timezone.utc)
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


# ── errors / messages ───────────────────────────────────────────────────────

class DemoLimitError(Exception):
    """A request was refused by a demo limit. ``message`` is user-facing."""

    def __init__(self, code: str, message: str, retry_after: int = 0):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after


_MESSAGES = {
    "visitor_limit": "You've used all {n} free demo messages for today. Your allowance resets at {reset}.",
    "ip_limit": "This network has reached today's demo limit. It resets at {reset}.",
    "global_limit": "The public demo has reached its daily capacity. It resets at {reset} — please come back then.",
    "token_budget": "The demo's daily AI budget is used up. It resets at {reset} — please come back then.",
    "admin_token_reserve": "The Super Admin token reserve for today is used up. It resets at {reset}.",
    "paused": "The public demo is paused for maintenance. Please check back soon.",
    "active_chat": "Please wait for your current answer to finish before sending another message.",
    "busy": "The demo is answering other visitors right now. Please try again in a few seconds.",
    "unavailable": "Usage tracking is temporarily unavailable, so the demo cannot take new messages. Please try again shortly.",
}


def _message(code: str) -> str:
    reset = next_reset().strftime("%H:%M UTC")
    return _MESSAGES[code].format(n=cfg("visitor_daily_limit"), reset=reset)


# ── tables / engine ─────────────────────────────────────────────────────────

def _table():
    from src.backend.database.database import DemoUsageCounter
    return DemoUsageCounter.__table__


def _settings_table():
    from src.backend.database.database import DemoRuntimeSetting
    return DemoRuntimeSetting.__table__


def _engine():
    from src.backend.database import database
    return database.engine


def _insert(conn):
    if conn.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert


# ── runtime configuration (Super Admin overrides over environment defaults) ─

def _bounds() -> Dict[str, tuple]:
    ceiling = max(int(settings.demo_daily_token_budget_ceiling), 1000)
    return {
        "visitor_daily_limit": (1, 100),
        "ip_daily_limit": (1, 500),
        "global_daily_limit": (1, 1000),
        "daily_token_budget": (1000, ceiling),
        "super_admin_token_reserve": (0, ceiling),
    }


_DEFAULT_ATTR = {
    "visitor_daily_limit": "demo_visitor_daily_limit",
    "ip_daily_limit": "demo_ip_daily_limit",
    "global_daily_limit": "demo_global_daily_limit",
    "daily_token_budget": "demo_daily_token_budget",
    "super_admin_token_reserve": "demo_super_admin_token_reserve",
}

_cfg_lock = threading.Lock()
_cfg_cache: Dict[str, Any] = {"at": 0.0, "values": {}}


def _load_overrides(force: bool = False) -> Dict[str, Any]:
    now = time.monotonic()
    with _cfg_lock:
        if not force and now - _cfg_cache["at"] < _CONFIG_TTL_SECONDS:
            return _cfg_cache["values"]
    values: Dict[str, Any] = {}
    try:
        t = _settings_table()
        with _engine().connect() as conn:
            for key, raw in conn.execute(select(t.c.key, t.c.value)).all():
                try:
                    values[key] = json.loads(raw)
                except ValueError:
                    continue
    except SQLAlchemyError:
        with _cfg_lock:  # keep the last known overrides rather than reverting
            return _cfg_cache["values"]
    with _cfg_lock:
        _cfg_cache.update(at=time.monotonic(), values=values)
    return values


def cfg(key: str) -> int:
    """Effective numeric limit: validated runtime override, else environment."""
    default = int(getattr(settings, _DEFAULT_ATTR[key]))
    override = _load_overrides().get(key)
    if isinstance(override, int) and not isinstance(override, bool):
        lo, hi = _bounds()[key]
        if lo <= override <= hi:
            return override
    return default


def pause_state() -> Dict[str, Any]:
    o = _load_overrides()
    until = o.get("paused_until")
    paused = bool(o.get("paused"))
    if paused and until:
        try:
            if datetime.fromisoformat(until) <= datetime.now(timezone.utc):
                paused = False  # a timed pause lapses by itself
        except ValueError:
            pass
    return {"paused": paused, "until": until if paused else None, "message": o.get("pause_message")}


def update_runtime_settings(changes: Dict[str, Any], actor: str) -> Dict[str, Any]:
    """Persist validated overrides. ``None`` clears one back to its default."""
    bounds = _bounds()
    rows: Dict[str, Optional[str]] = {}
    for key, value in changes.items():
        if key in bounds:
            if value is None:
                rows[key] = None
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} must be an integer")
            lo, hi = bounds[key]
            if not lo <= value <= hi:
                raise ValueError(f"{key} must be between {lo} and {hi}")
            rows[key] = json.dumps(value)
        elif key in {"paused", "paused_until", "pause_message"}:
            rows[key] = None if value is None else json.dumps(value)
        else:
            raise ValueError(f"unknown setting: {key}")
    merged = {**{k: cfg(k) for k in bounds}, **{k: json.loads(v) for k, v in rows.items() if v is not None and k in bounds}}
    if merged["super_admin_token_reserve"] > merged["daily_token_budget"]:
        raise ValueError("super_admin_token_reserve cannot exceed daily_token_budget")
    t = _settings_table()
    with _engine().begin() as conn:
        for key, raw in rows.items():
            if raw is None:
                conn.execute(t.delete().where(t.c.key == key))
            else:
                stmt = _insert(conn)(t).values(key=key, value=raw, updated_by=actor, updated_at=func.now())
                conn.execute(stmt.on_conflict_do_update(
                    index_elements=[t.c.key],
                    set_={"value": raw, "updated_by": actor, "updated_at": func.now()}))
    _load_overrides(force=True)
    logger.warning("DEMO_ADMIN_ACTION actor=%s action=update_settings keys=%s", actor, sorted(rows))
    return effective_config()


def effective_config() -> Dict[str, Any]:
    o = _load_overrides()
    return {
        **{k: cfg(k) for k in _bounds()},
        "bounds": {k: {"min": lo, "max": hi} for k, (lo, hi) in _bounds().items()},
        "overridden": sorted(k for k in _bounds() if k in o),
        "pause": pause_state(),
        "fixed": {"per_ip_per_minute": settings.public_demo_chat_rate_limit_per_minute,
                  "max_concurrent_ai": settings.demo_global_concurrency},
    }


# ── persistent counters ─────────────────────────────────────────────────────

def _upsert_increment(conn, scope: str, subject: str, day: str, limit: int) -> bool:
    """Atomically count+1 unless it already equals ``limit``. True if charged."""
    if limit <= 0:
        return False
    t = _table()
    stmt = _insert(conn)(t).values(scope=scope, subject=subject, day=day, count=1, tokens=0,
                                   updated_at=func.now())
    stmt = stmt.on_conflict_do_update(
        index_elements=[t.c.scope, t.c.subject, t.c.day],
        set_={"count": t.c.count + 1, "updated_at": func.now()},
        where=(t.c.count < limit),
    )
    return conn.execute(stmt).rowcount == 1


def _read(conn, scope: str, subject: str, day: str) -> Dict[str, int]:
    t = _table()
    row = conn.execute(select(t.c.count, t.c.tokens).where(
        (t.c.scope == scope) & (t.c.subject == subject) & (t.c.day == day))).first()
    return {"count": int(row[0]), "tokens": int(row[1])} if row else {"count": 0, "tokens": 0}


def _public_token_cap() -> int:
    return max(cfg("daily_token_budget") - cfg("super_admin_token_reserve"), 0)


def consume(visitor: str, ip: str) -> None:
    """Charge one message to visitor, IP and global. Raises DemoLimitError."""
    day = today()
    # Resolve configuration BEFORE the transaction: cfg() may open its own
    # connection, and nesting it inside a held one can exhaust the pool.
    limits = (cfg("visitor_daily_limit"), cfg("ip_daily_limit"), cfg("global_daily_limit"))
    token_cap = _public_token_cap()
    refused: Optional[str] = None
    try:
        with _engine().begin() as conn:
            if _read(conn, "global", "all", day)["tokens"] >= token_cap:
                refused = "token_budget"
            # Fixed order (visitor, ip, global) avoids deadlocks. Any refusal
            # rolls the whole transaction back, so nothing is charged.
            elif not _upsert_increment(conn, "visitor", visitor, day, limits[0]):
                refused = "visitor_limit"
            elif not _upsert_increment(conn, "ip", ip, day, limits[1]):
                refused = "ip_limit"
            elif not _upsert_increment(conn, "global", "all", day, limits[2]):
                refused = "global_limit"
            if refused:
                conn.rollback()
    except SQLAlchemyError as exc:
        logger.error("DEMO_USAGE_DB_ERROR op=consume err=%s", type(exc).__name__)
        raise DemoLimitError("unavailable", _message("unavailable"), retry_after=30) from exc
    if refused:
        raise DemoLimitError(refused, _message(refused))
    _prune_once()


def check_admin_reserve() -> None:
    """Super Admin may generate while their reserved token pool has room."""
    try:
        with _engine().connect() as conn:
            used = _read(conn, "global", "admin", today())["tokens"]
    except SQLAlchemyError as exc:
        raise DemoLimitError("unavailable", _message("unavailable"), retry_after=30) from exc
    if used >= cfg("super_admin_token_reserve"):
        raise DemoLimitError("admin_token_reserve", _message("admin_token_reserve"))


def refund(visitor: str, ip: str, day: Optional[str] = None) -> None:
    """Give back one message after a failed generation (best effort)."""
    day = day or today()
    t = _table()
    try:
        with _engine().begin() as conn:
            for scope, subject in (("visitor", visitor), ("ip", ip), ("global", "all")):
                conn.execute(update(t).where(
                    (t.c.scope == scope) & (t.c.subject == subject) & (t.c.day == day) & (t.c.count > 0)
                ).values(count=t.c.count - 1))
    except SQLAlchemyError as exc:
        logger.warning("DEMO_USAGE_DB_ERROR op=refund err=%s", type(exc).__name__)


def record_tokens(total_tokens: int) -> None:
    """Add actual provider token usage to today's pool (public or admin)."""
    if not settings.public_demo_enabled or not total_tokens or total_tokens < 0:
        return
    subject = "admin" if ACTOR.get() == "admin" else "all"
    t = _table()
    try:
        with _engine().begin() as conn:
            stmt = _insert(conn)(t).values(scope="global", subject=subject, day=today(), count=0,
                                           tokens=int(total_tokens), updated_at=func.now())
            conn.execute(stmt.on_conflict_do_update(
                index_elements=[t.c.scope, t.c.subject, t.c.day],
                set_={"tokens": t.c.tokens + int(total_tokens), "updated_at": func.now()}))
    except SQLAlchemyError as exc:
        logger.warning("DEMO_USAGE_DB_ERROR op=tokens err=%s", type(exc).__name__)


_last_prune = ""


def _prune_once() -> None:
    global _last_prune
    day = today()
    if _last_prune == day:
        return
    _last_prune = day
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_PRUNE_AFTER_DAYS)).strftime("%Y-%m-%d")
    try:
        with _engine().begin() as conn:
            conn.execute(_table().delete().where(_table().c.day < cutoff))
    except SQLAlchemyError:
        pass


def reset_counters(scope: str, actor: str) -> Dict[str, int]:
    """Super Admin reset of TODAY's message counters. Token usage is never
    reset: it mirrors the real upstream quota, which a counter reset cannot
    restore."""
    if scope not in {"visitors", "global_messages", "all_messages"}:
        raise ValueError("scope must be visitors, global_messages or all_messages")
    t = _table()
    day = today()
    removed = 0
    with _engine().begin() as conn:
        if scope in {"visitors", "all_messages"}:
            removed += conn.execute(t.delete().where(
                t.c.day == day, t.c.scope.in_(["visitor", "ip"]))).rowcount
        if scope in {"global_messages", "all_messages"}:
            removed += conn.execute(update(t).where(
                (t.c.scope == "global") & (t.c.subject == "all") & (t.c.day == day)
            ).values(count=0)).rowcount
    logger.warning("DEMO_ADMIN_ACTION actor=%s action=reset_counters scope=%s rows=%d", actor, scope, removed)
    return {"rows_affected": int(removed)}


# ── views ───────────────────────────────────────────────────────────────────

def _block_reason(visitor_used: int, ip_used: int, glob: Dict[str, int]) -> Optional[str]:
    if pause_state()["paused"]:
        return "paused"
    if visitor_used >= cfg("visitor_daily_limit"):
        return "visitor_limit"
    if ip_used >= cfg("ip_daily_limit"):
        return "ip_limit"
    if glob["count"] >= cfg("global_daily_limit"):
        return "global_limit"
    if glob["tokens"] >= _public_token_cap():
        return "token_budget"
    return None


def usage_snapshot(visitor: str, ip: str) -> Dict[str, Any]:
    """What the visitor's usage indicator shows. Never exposes other visitors."""
    day = today()
    try:
        with _engine().connect() as conn:
            v = _read(conn, "visitor", visitor, day)["count"]
            i = _read(conn, "ip", ip, day)["count"]
            g = _read(conn, "global", "all", day)
    except SQLAlchemyError:
        v = i = 0
        g = {"count": 0, "tokens": 0}
    limit = cfg("visitor_daily_limit")
    remaining = max(0, min(limit - v, cfg("ip_daily_limit") - i, cfg("global_daily_limit") - g["count"]))
    reason = _block_reason(v, i, g)
    if reason in {"paused", "token_budget"}:
        remaining = 0
    reset = next_reset()
    return {
        "enabled": True,
        "limit": limit,
        "used": min(v, limit),
        "remaining": remaining,
        "percent": round(100 * min(v, limit) / limit) if limit else 100,
        "limited_by": None if remaining > 0 or reason is None else reason,
        "shared_capacity_low": remaining < max(0, limit - v),
        "resets_at": reset.isoformat(),
        "seconds_until_reset": int((reset - datetime.now(timezone.utc)).total_seconds()),
        "active": visitor_is_active(visitor),
    }


def admin_overview() -> Dict[str, Any]:
    """Aggregate usage only: no visitor or IP identifiers leave the server."""
    day = today()
    t = _table()
    with _engine().connect() as conn:
        g = _read(conn, "global", "all", day)
        a = _read(conn, "global", "admin", day)
        visitors = conn.execute(select(func.count()).where((t.c.scope == "visitor") & (t.c.day == day))).scalar() or 0
        ips = conn.execute(select(func.count()).where((t.c.scope == "ip") & (t.c.day == day))).scalar() or 0
        history = conn.execute(select(t.c.day, t.c.count, t.c.tokens).where(
            (t.c.scope == "global") & (t.c.subject == "all")
            & (t.c.day >= (datetime.now(timezone.utc) - timedelta(days=6)).strftime("%Y-%m-%d"))
        ).order_by(t.c.day.desc())).all()
    reset = next_reset()
    limit = cfg("global_daily_limit")
    budget, reserve = cfg("daily_token_budget"), cfg("super_admin_token_reserve")
    return {
        "day": day,
        "resets_at": reset.isoformat(),
        "public_access": pause_state(),
        "messages": {"used": g["count"], "limit": limit, "remaining": max(0, limit - g["count"]),
                     "percent": round(100 * g["count"] / limit) if limit else 100},
        "tokens": {"public_used": g["tokens"], "public_cap": _public_token_cap(),
                   "public_remaining": max(0, _public_token_cap() - g["tokens"]),
                   "admin_used": a["tokens"], "admin_reserve": reserve,
                   "admin_remaining": max(0, reserve - a["tokens"]), "daily_budget": budget},
        "unique_visitors_today": int(visitors),
        "unique_networks_today": int(ips),
        "active_requests": active_count(),
        "config": effective_config(),
        "history": [{"day": d, "messages": int(c), "tokens": int(k)} for d, c, k in history],
    }


# ── concurrency (process-local) ─────────────────────────────────────────────

_active_lock = threading.Lock()
_active: Dict[str, float] = {}


def _expire_locked(now: float) -> None:
    for key in [k for k, ts in _active.items() if now - ts > _ACTIVE_TTL_SECONDS]:
        del _active[key]


def acquire_slot(visitor: str) -> None:
    now = time.monotonic()
    with _active_lock:
        _expire_locked(now)
        if visitor in _active:
            raise DemoLimitError("active_chat", _message("active_chat"), retry_after=3)
        if len(_active) >= max(1, settings.demo_global_concurrency):
            raise DemoLimitError("busy", _message("busy"), retry_after=5)
        _active[visitor] = now


def release_slot(visitor: str) -> None:
    with _active_lock:
        _active.pop(visitor, None)


def visitor_is_active(visitor: str) -> bool:
    with _active_lock:
        _expire_locked(time.monotonic())
        return visitor in _active


def active_count() -> int:
    with _active_lock:
        _expire_locked(time.monotonic())
        return len(_active)


# ── orchestration ───────────────────────────────────────────────────────────

@dataclass
class DemoLease:
    visitor: str
    ip: str
    day: str
    actor: str = "public"
    released: bool = False
    refunded: bool = False

    def activate(self) -> None:
        """Charge this generation's provider tokens to the right pool."""
        ACTOR.set(self.actor)

    def release(self) -> None:
        if not self.released:
            self.released = True
            release_slot(self.visitor)

    def refund_once(self) -> None:
        if not self.refunded and self.actor == "public":
            self.refunded = True
            refund(self.visitor, self.ip, self.day)


def admit(request: Request, vsid: Optional[str], user: Optional[Dict[str, Any]] = None) -> DemoLease:
    """Admit one chat message or raise DemoLimitError.

    A Super Admin skips the public message limits and the pause switch but
    still takes a concurrency slot and spends the reserved token pool.
    """
    if user is not None and is_super_admin(user):
        key = "admin:" + str(user.get("id"))
        check_admin_reserve()
        acquire_slot(key)
        return DemoLease(visitor=key, ip="", day=today(), actor="admin")
    if pause_state()["paused"]:
        custom = pause_state().get("message")
        raise DemoLimitError("paused", custom if isinstance(custom, str) and custom.strip() else _message("paused"), retry_after=60)
    visitor = visitor_key(vsid or "")
    ip = ip_key(resolve_client_ip(request))
    acquire_slot(visitor)
    try:
        lease = DemoLease(visitor=visitor, ip=ip, day=today())
        consume(visitor, ip)
        return lease
    except BaseException:
        release_slot(visitor)
        raise


def reset_for_tests() -> None:
    global _last_prune
    with _active_lock:
        _active.clear()
    with _cfg_lock:
        _cfg_cache.update(at=0.0, values={})
    _last_prune = ""
