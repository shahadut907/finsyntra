"""Daily demo usage and abuse protection: limits, atomicity, isolation, API."""
import threading

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine

from src.backend.api.endpoints import app
from src.backend.database.database import DemoRuntimeSetting, DemoUsageCounter, create_tables
from src.backend.middleware.security import rate_limiter
from src.backend.services import demo_usage
from src.config.settings import settings


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'usage.db'}", connect_args={"timeout": 30})
    DemoUsageCounter.__table__.create(engine)
    DemoRuntimeSetting.__table__.create(engine)
    monkeypatch.setattr(demo_usage, "_engine", lambda: engine)
    monkeypatch.setattr(settings, "demo_visitor_daily_limit", 10)
    monkeypatch.setattr(settings, "demo_ip_daily_limit", 20)
    monkeypatch.setattr(settings, "demo_global_daily_limit", 60)
    monkeypatch.setattr(settings, "demo_daily_token_budget", 1000)
    monkeypatch.setattr(settings, "demo_global_concurrency", 2)
    monkeypatch.setattr(settings, "demo_super_admin_token_reserve", 0)
    monkeypatch.setattr(settings, "public_demo_enabled", True)
    demo_usage.reset_for_tests()
    return engine


def _counts(engine):
    with engine.connect() as conn:
        return {(r[0], r[1][:6]): r[2] for r in conn.exec_driver_sql(
            "select scope, subject, count from demo_usage_counters")}


def test_visitor_limit_is_ten_and_refusal_charges_nothing(db):
    for _ in range(10):
        demo_usage.consume("v1", "ip1")
    with pytest.raises(demo_usage.DemoLimitError) as err:
        demo_usage.consume("v1", "ip1")
    assert err.value.code == "visitor_limit"
    counts = _counts(db)
    assert counts[("visitor", "v1")] == 10 and counts[("ip", "ip1")] == 10 and counts[("global", "all")] == 10


def test_ip_limit_applies_across_new_visitors(db):
    """Clearing cookies mints a new visitor id but not a new IP."""
    for i in range(20):
        demo_usage.consume(f"visitor{i}", "same-ip")
    with pytest.raises(demo_usage.DemoLimitError) as err:
        demo_usage.consume("brand-new-visitor", "same-ip")
    assert err.value.code == "ip_limit"
    assert ("visitor", "brand-n") not in _counts(db)  # rolled back


def test_global_limit_and_token_budget(db, monkeypatch):
    monkeypatch.setattr(settings, "demo_global_daily_limit", 3)
    for i in range(3):
        demo_usage.consume(f"v{i}", f"ip{i}")
    with pytest.raises(demo_usage.DemoLimitError) as err:
        demo_usage.consume("v9", "ip9")
    assert err.value.code == "global_limit"

    monkeypatch.setattr(settings, "demo_global_daily_limit", 60)
    demo_usage.record_tokens(999)
    demo_usage.consume("v10", "ip10")
    demo_usage.record_tokens(5)
    with pytest.raises(demo_usage.DemoLimitError) as err:
        demo_usage.consume("v11", "ip11")
    assert err.value.code == "token_budget"


def test_concurrent_requests_never_exceed_the_limit(db):
    results = []

    def worker():
        try:
            demo_usage.consume("racer", "ip-racer")
            results.append("ok")
        except demo_usage.DemoLimitError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=worker) for _ in range(25)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 10
    assert _counts(db)[("visitor", "racer")] == 10


def test_refund_returns_one_message(db):
    demo_usage.consume("v", "ip")
    demo_usage.refund("v", "ip")
    assert _counts(db)[("visitor", "v")] == 0
    demo_usage.refund("v", "ip")  # never goes negative
    assert _counts(db)[("visitor", "v")] == 0


def test_one_active_chat_per_visitor_and_two_globally(db):
    demo_usage.acquire_slot("a")
    with pytest.raises(demo_usage.DemoLimitError) as err:
        demo_usage.acquire_slot("a")
    assert err.value.code == "active_chat"
    demo_usage.acquire_slot("b")
    with pytest.raises(demo_usage.DemoLimitError) as err:
        demo_usage.acquire_slot("c")
    assert err.value.code == "busy"
    demo_usage.release_slot("a")
    demo_usage.acquire_slot("c")
    assert demo_usage.active_count() == 2


class _Req:
    def __init__(self, xff=None, host="10.1.1.1"):
        self.headers = {"x-forwarded-for": xff} if xff else {}
        self.client = type("C", (), {"host": host})()


def test_admit_releases_slot_when_the_quota_refuses(db, monkeypatch):
    monkeypatch.setattr(settings, "demo_visitor_daily_limit", 1)
    lease = demo_usage.admit(_Req(), "vsid-1")
    lease.release()
    with pytest.raises(demo_usage.DemoLimitError):
        demo_usage.admit(_Req(), "vsid-1")
    assert demo_usage.active_count() == 0


def test_client_ip_ignores_client_supplied_forwarded_entries(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    assert demo_usage.resolve_client_ip(_Req("203.0.113.5, 198.51.100.9")) == "203.0.113.5"
    # A client prepending a forged address cannot change the trusted entry.
    assert demo_usage.resolve_client_ip(_Req("6.6.6.6, 203.0.113.5, 198.51.100.9")) == "203.0.113.5"
    assert demo_usage.resolve_client_ip(_Req(None, host="10.9.9.9")) == "10.9.9.9"
    monkeypatch.setattr(settings, "trusted_proxy_hops", 0)
    assert demo_usage.resolve_client_ip(_Req("6.6.6.6, 1.1.1.1")) == "10.1.1.1"


def test_stored_subjects_are_hmacs_not_raw_ids():
    assert "203.0.113.5" not in demo_usage.ip_key("203.0.113.5")
    assert demo_usage.visitor_key("vsid-x") != demo_usage.visitor_key("vsid-y")
    assert len(demo_usage.visitor_key("vsid-x")) == 48


# -- HTTP level --------------------------------------------------------------

class _FakeRag:
    def process_query(self, **kw):
        return {"response": "ok", "sources": ["demo_employee_handbook.md"], "documents_found": 1,
                "success": True, "generation_status": "ok", "retrieval_status": "hit"}


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def demo_app(monkeypatch, db):
    create_tables()
    rate_limiter.reset()
    monkeypatch.setattr(settings, "public_demo_enabled", True)
    monkeypatch.setattr(settings, "public_demo_chat_rate_limit_per_minute", 1000)
    app.state.rag = _FakeRag()
    yield
    app.state.rag = None
    rate_limiter.reset()


async def _login(client, role="employee"):
    r = await client.post("/auth/demo-login", json={"role": role})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


@pytest.mark.asyncio
async def test_usage_endpoint_and_post_chat_limit(demo_app, monkeypatch):
    monkeypatch.setattr(settings, "demo_visitor_daily_limit", 2)
    async with _client() as c:
        h = await _login(c)
        u = (await c.get("/api/demo/usage")).json()
        assert (u["used"], u["limit"], u["remaining"], u["percent"]) == (0, 2, 2, 0)
        assert u["resets_at"] and u["seconds_until_reset"] > 0
        for _ in range(2):
            r = await c.post("/api/chat", json={"message": "How many leave days?"}, headers=h)
            assert r.status_code == 200, r.text
        u = (await c.get("/api/demo/usage")).json()
        assert (u["used"], u["remaining"], u["percent"], u["limited_by"]) == (2, 0, 100, "visitor_limit")
        r = await c.post("/api/chat", json={"message": "one more"}, headers=h)
        assert r.status_code == 429
        assert r.json()["detail"]["code"] == "VISITOR_LIMIT"
        assert "resets at" in r.json()["detail"]["message"]


@pytest.mark.asyncio
async def test_stream_refusal_is_a_friendly_sse_error_event(demo_app, monkeypatch):
    monkeypatch.setattr(settings, "demo_visitor_daily_limit", 0)
    async with _client() as c:
        await _login(c)
        r = await c.get("/api/chat/stream", params={"q": "hello there friend"})
        assert r.status_code == 200
        assert '"type": "error"' in r.text and "VISITOR_LIMIT" in r.text and "[DONE]" in r.text


@pytest.mark.asyncio
async def test_new_login_does_not_reset_the_ip_allowance(demo_app, monkeypatch):
    monkeypatch.setattr(settings, "demo_ip_daily_limit", 2)
    for _ in range(2):  # a fresh "incognito" visitor each time, same address
        async with _client() as c:
            h = await _login(c)
            assert (await c.post("/api/chat", json={"message": "leave days"}, headers=h)).status_code == 200
    async with _client() as c:
        h = await _login(c)
        r = await c.post("/api/chat", json={"message": "leave days"}, headers=h)
        assert r.status_code == 429 and r.json()["detail"]["code"] == "IP_LIMIT"


@pytest.mark.asyncio
async def test_visitors_are_counted_separately(demo_app, monkeypatch):
    monkeypatch.setattr(settings, "demo_visitor_daily_limit", 1)
    async with _client() as a, _client() as b:
        ha, hb = await _login(a), await _login(b)
        assert (await a.post("/api/chat", json={"message": "leave days"}, headers=ha)).status_code == 200
        assert (await a.post("/api/chat", json={"message": "again"}, headers=ha)).status_code == 429
        assert (await b.post("/api/chat", json={"message": "leave days"}, headers=hb)).status_code == 200
        assert (await b.get("/api/demo/usage")).json()["used"] == 1


@pytest.mark.asyncio
async def test_usage_endpoint_requires_authentication(demo_app):
    async with _client() as anon:
        assert (await anon.get("/api/demo/usage")).status_code == 401


# -- Super Admin -----------------------------------------------------------------

SUPER = "owner.super@example.test"


def _make_account(email, role="admin", demo=False):
    from src.backend.database.database import SessionLocal, User
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.email == email).first():
            db.add(User(id=email, username=email, email=email, hashed_password="!unusable",
                        full_name="Owner", role=role, tenant_id="tenant_demo",
                        is_active=True, is_public_demo=demo))
            db.commit()
    finally:
        db.close()


async def _as(email):
    """Client authenticated as a real (non-demo) account via a signed token."""
    from src.backend.auth.authentication import create_access_token
    _make_account(email)
    c = _client()
    c.cookies.set("session_token", create_access_token({"sub": email, "type": "access"}))
    c.cookies.set("csrf_token", "csrf-test")
    return c, {"X-CSRF-Token": "csrf-test"}


@pytest.fixture
def super_admin(monkeypatch):
    monkeypatch.setattr(settings, "super_admin_emails", [SUPER])
    monkeypatch.setattr(settings, "demo_daily_token_budget", 5000)
    monkeypatch.setattr(settings, "demo_super_admin_token_reserve", 1000)


def test_is_super_admin_requires_allowlist_private_account_and_admin_role(super_admin):
    base = {"email": SUPER, "role": "admin", "is_active": True, "is_public_demo": False}
    assert demo_usage.is_super_admin(base)
    assert demo_usage.is_super_admin({**base, "email": SUPER.upper()})
    assert not demo_usage.is_super_admin({**base, "is_public_demo": True})   # demo persona
    assert not demo_usage.is_super_admin({**base, "role": "employee"})
    assert not demo_usage.is_super_admin({**base, "email": "other@example.test"})
    assert not demo_usage.is_super_admin({**base, "is_active": False})
    assert not demo_usage.is_super_admin({})


@pytest.mark.asyncio
async def test_demo_admin_persona_is_not_a_super_admin(demo_app, monkeypatch):
    monkeypatch.setattr(settings, "super_admin_emails", ["portfolio.admin@finsolve.demo"])
    async with _client() as c:
        h = await _login(c, "admin")
        assert (await c.get("/api/admin/demo-usage")).status_code == 403
        assert (await c.put("/api/admin/demo-usage/limits", json={"visitor_daily_limit": 99}, headers=h)).status_code == 403
        assert (await c.put("/api/admin/demo-usage/access", json={"enabled": False}, headers=h)).status_code == 403
        assert (await c.post("/api/admin/demo-usage/reset", json={"scope": "all_messages"}, headers=h)).status_code == 403


@pytest.mark.asyncio
async def test_super_admin_endpoints_reject_everyone_else(demo_app, super_admin):
    async with _client() as anon:
        assert (await anon.get("/api/admin/demo-usage")).status_code == 401
    other, h = await _as("someone.else@example.test")
    async with other:
        assert (await other.get("/api/admin/demo-usage")).status_code == 403
        assert (await other.put("/api/admin/demo-usage/limits", json={"visitor_daily_limit": 5}, headers=h)).status_code == 403


@pytest.mark.asyncio
async def test_super_admin_is_exempt_from_message_limits_but_not_the_token_reserve(demo_app, super_admin, monkeypatch):
    monkeypatch.setattr(settings, "demo_visitor_daily_limit", 1)
    monkeypatch.setattr(settings, "demo_ip_daily_limit", 1)
    monkeypatch.setattr(settings, "demo_global_daily_limit", 1)
    monkeypatch.setattr(settings, "demo_super_admin_token_reserve", 500)
    c, h = await _as(SUPER)
    async with c:
        for _ in range(4):  # far beyond every public limit
            assert (await c.post("/api/chat", json={"message": "leave days"}, headers=h)).status_code == 200
        assert (await c.get("/api/demo/usage")).json() == {"enabled": False, "super_admin": True}
        demo_usage.ACTOR.set("admin")
        demo_usage.record_tokens(500)
        demo_usage.ACTOR.set("public")
        r = await c.post("/api/chat", json={"message": "leave days"}, headers=h)
        assert r.status_code == 429 and r.json()["detail"]["code"] == "ADMIN_TOKEN_RESERVE"


@pytest.mark.asyncio
async def test_public_visitors_cannot_spend_the_admin_reserve(demo_app, monkeypatch):
    monkeypatch.setattr(settings, "demo_daily_token_budget", 1000)
    monkeypatch.setattr(settings, "demo_super_admin_token_reserve", 400)
    demo_usage.record_tokens(600)  # public pool = 1000 - 400
    async with _client() as c:
        h = await _login(c)
        r = await c.post("/api/chat", json={"message": "leave days"}, headers=h)
        assert r.status_code == 429 and r.json()["detail"]["code"] == "TOKEN_BUDGET"


@pytest.mark.asyncio
async def test_super_admin_available_while_public_quota_exhausted_and_paused(demo_app, super_admin, monkeypatch):
    monkeypatch.setattr(settings, "demo_global_daily_limit", 1)
    c, h = await _as(SUPER)
    async with c, _client() as visitor:
        vh = await _login(visitor)
        assert (await visitor.post("/api/chat", json={"message": "leave days"}, headers=vh)).status_code == 200
        r = await visitor.post("/api/chat", json={"message": "again"}, headers=vh)
        assert r.status_code == 429 and r.json()["detail"]["code"] == "GLOBAL_LIMIT"
        r = await c.put("/api/admin/demo-usage/access", json={"enabled": False, "message": "Back at 9."}, headers=h)
        assert r.status_code == 200 and r.json()["public_access"]["paused"] is True
        r = await visitor.post("/api/chat", json={"message": "again"}, headers=vh)
        assert r.status_code == 429 and r.json()["detail"]["code"] == "PAUSED"
        assert r.json()["detail"]["message"] == "Back at 9."
        assert (await visitor.get("/api/demo/usage")).json()["limited_by"] == "paused"
        assert (await c.post("/api/chat", json={"message": "admin works"}, headers=h)).status_code == 200
        assert (await c.put("/api/admin/demo-usage/access", json={"enabled": True}, headers=h)).status_code == 200
        assert demo_usage.pause_state()["paused"] is False


@pytest.mark.asyncio
async def test_timed_pause_lapses_by_itself(demo_app, super_admin):
    c, h = await _as(SUPER)
    async with c:
        r = await c.put("/api/admin/demo-usage/access", json={"enabled": False, "pause_minutes": 5}, headers=h)
        assert r.json()["public_access"]["paused"] is True and r.json()["public_access"]["until"]
        demo_usage.update_runtime_settings({"paused_until": "2000-01-01T00:00:00+00:00"}, "test")
        assert demo_usage.pause_state()["paused"] is False


@pytest.mark.asyncio
async def test_super_admin_tunes_limits_within_bounds(demo_app, super_admin):
    c, h = await _as(SUPER)
    async with c, _client() as visitor:
        r = await c.put("/api/admin/demo-usage/limits", json={"visitor_daily_limit": 1}, headers=h)
        assert r.status_code == 200 and r.json()["visitor_daily_limit"] == 1
        vh = await _login(visitor)
        assert (await visitor.post("/api/chat", json={"message": "a b c"}, headers=vh)).status_code == 200
        assert (await visitor.post("/api/chat", json={"message": "d e f"}, headers=vh)).status_code == 429
        for bad in ({"visitor_daily_limit": 0}, {"visitor_daily_limit": 10000},
                    {"daily_token_budget": 10000000}, {"nope": 1},
                    {"super_admin_token_reserve": 150000, "daily_token_budget": 1000}):
            assert (await c.put("/api/admin/demo-usage/limits", json=bad, headers=h)).status_code == 422, bad
        assert (await c.put("/api/admin/demo-usage/limits", json={}, headers=h)).status_code == 400
        r = await c.put("/api/admin/demo-usage/limits", json={"visitor_daily_limit": None}, headers=h)
        assert r.json()["visitor_daily_limit"] == settings.demo_visitor_daily_limit
        assert "visitor_daily_limit" not in r.json()["overridden"]


@pytest.mark.asyncio
async def test_super_admin_resets_counters_but_never_tokens(demo_app, super_admin):
    c, h = await _as(SUPER)
    async with c, _client() as visitor:
        vh = await _login(visitor)
        await visitor.post("/api/chat", json={"message": "leave days"}, headers=vh)
        demo_usage.record_tokens(77)
        assert (await visitor.get("/api/demo/usage")).json()["used"] == 1
        r = await c.post("/api/admin/demo-usage/reset", json={"scope": "all_messages"}, headers=h)
        assert r.status_code == 200 and r.json()["rows_affected"] >= 2
        assert (await visitor.get("/api/demo/usage")).json()["used"] == 0
        ov = (await c.get("/api/admin/demo-usage")).json()
        assert ov["messages"]["used"] == 0 and ov["tokens"]["public_used"] == 77
        assert (await c.post("/api/admin/demo-usage/reset", json={"scope": "tokens"}, headers=h)).status_code == 422
        assert "vsid" not in str(ov) and "subject" not in str(ov)
