"""Phase 3 security correction: the default SSE session_id for a public-demo
visitor must be a deterministic, ONE-WAY derivation — never the raw vsid (or
raw user_id/email) embedded verbatim — because session_id is returned to the
client via ordinary conversation-list/get API responses.

Covers the numbered requirements from the correction-pass task:
  1. same user + same vsid -> same default session_id
  2. same user + different vsid -> different session_id
  3. same vsid + different user -> different session_id
  4. derived id shape: no raw vsid, no raw user_id/email, `demo_<sha256hex>`
  5. conversation list/get after an SSE-created demo conversation never
     contains the raw vsid anywhere in the response JSON
  6. SSE event payloads still contain no vsid
  7. logs/errors introduce no vsid exposure
  8. ownership: knowing another visitor's derived session_id still doesn't
     grant access
  9. a client-crafted, correctly-shaped session_id can't bypass tenant/user/
     vsid ownership
  10. Redis cache-key/invalidation code is untouched by this pass (verified
      by re-running the existing Phase 3 suite, not by starting Redis)

No SentenceTransformer, no Chroma ingestion, no Docker, no installs, no Redis.
"""
import hashlib
import logging
import re

import pytest
from httpx import AsyncClient, ASGITransport

from src.backend.api.chat_stream import _derive_public_demo_session_id
from src.backend.api.endpoints import app
from src.backend.database.database import ChatSession, SessionLocal, create_tables
from src.backend.middleware.security import rate_limiter
from src.config.settings import settings

DEMO_ID_RE = re.compile(r"^demo_[0-9a-f]{64}$")


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    create_tables()
    rate_limiter.reset()
    monkeypatch.setattr(settings, "public_demo_enabled", True)
    yield
    rate_limiter.reset()
    app.state.rag = None


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _demo_login(client: AsyncClient, identity: str = "general"):
    response = await client.post("/auth/demo-login", json={"role": identity})
    assert response.status_code == 200, response.text
    return response


def _csrf(client: AsyncClient) -> dict:
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


class _CountingRag:
    def __init__(self):
        self.calls = 0

    def process_query(self, **kwargs):
        self.calls += 1
        return {
            "response": "fake grounded answer", "sources": [],
            "documents_found": 1, "success": True,
        }


# ---------------------------------------------------------------------------
# 1-3. Determinism / distinctness at the unit level
# ---------------------------------------------------------------------------

class TestDerivationDeterminism:
    def test_same_user_same_vsid_gives_same_session_id(self):
        a1 = _derive_public_demo_session_id("portfolio.employee@finsolve.demo", "vsidA")
        a2 = _derive_public_demo_session_id("portfolio.employee@finsolve.demo", "vsidA")
        assert a1 == a2

    def test_same_user_different_vsid_gives_different_session_id(self):
        a = _derive_public_demo_session_id("portfolio.employee@finsolve.demo", "vsidA")
        b = _derive_public_demo_session_id("portfolio.employee@finsolve.demo", "vsidB")
        assert a != b

    def test_same_vsid_different_user_gives_different_session_id(self):
        a = _derive_public_demo_session_id("portfolio.finance@finsolve.demo", "SAME-VSID")
        b = _derive_public_demo_session_id("portfolio.hr@finsolve.demo", "SAME-VSID")
        assert a != b

    def test_matches_the_documented_construction_exactly(self):
        user_id = "portfolio.employee@finsolve.demo"
        vsid = "some-opaque-vsid-value"
        expected = "demo_" + hashlib.sha256(
            f"finsolve-demo-session-v1:{user_id}:{vsid}".encode("utf-8")
        ).hexdigest()
        assert _derive_public_demo_session_id(user_id, vsid) == expected


# ---------------------------------------------------------------------------
# 4. Shape / no raw material inside the derived id
# ---------------------------------------------------------------------------

class TestDerivedIdShape:
    def test_derived_id_matches_demo_sha256_hex_format(self):
        sid = _derive_public_demo_session_id("portfolio.employee@finsolve.demo", "abc123")
        assert DEMO_ID_RE.match(sid), sid

    def test_derived_id_never_contains_the_raw_vsid(self):
        vsid = "totally-unique-raw-vsid-marker-zzz"
        sid = _derive_public_demo_session_id("portfolio.employee@finsolve.demo", vsid)
        assert vsid not in sid

    def test_derived_id_never_contains_the_raw_user_id_or_email(self):
        user_id = "portfolio.engineering@finsolve.demo"
        sid = _derive_public_demo_session_id(user_id, "some-vsid")
        assert user_id not in sid
        assert "portfolio.engineering" not in sid
        assert "@finsolve.demo" not in sid
        assert "user_" not in sid


# ---------------------------------------------------------------------------
# 5 / 6. HTTP-level: no raw vsid leaks through any response surface
# ---------------------------------------------------------------------------

class TestNoRawVsidLeaksOverHttp:
    @pytest.mark.asyncio
    async def test_sse_created_conversation_id_is_derived_and_reused(self):
        fake = _CountingRag()
        app.state.rag = fake
        async with _client() as client:
            await _demo_login(client, "general")
            vsid = client.cookies.get("vsid")
            assert vsid

            first = await client.post(
                "/api/chat/stream", json={"message": "hello there"}, headers=_csrf(client))
            assert first.status_code == 200
            _ = first.text  # drain the stream so persistence completes
            second = await client.post(
                "/api/chat/stream", json={"message": "hello again"}, headers=_csrf(client))
            assert second.status_code == 200
            _ = second.text

            db = SessionLocal()
            try:
                rows = db.query(ChatSession).filter(
                    ChatSession.visitor_session_id == vsid
                ).all()
            finally:
                db.close()

            assert len(rows) == 1, "both omitted-session_id messages must land in ONE conversation"
            sid = rows[0].id
            assert DEMO_ID_RE.match(sid), sid
            assert vsid not in sid

            listing = await client.get("/api/conversations")
            assert listing.status_code == 200
            body_text = listing.text
            assert vsid not in body_text
            assert sid in {s["id"] for s in listing.json()["sessions"]}

            detail = await client.get(f"/api/conversations/{sid}")
            assert detail.status_code == 200
            assert vsid not in detail.text
            assert detail.json()["session"]["id"] == sid

    @pytest.mark.asyncio
    async def test_sse_event_stream_text_never_contains_the_raw_vsid(self):
        fake = _CountingRag()
        app.state.rag = fake
        async with _client() as client:
            await _demo_login(client, "general")
            vsid = client.cookies.get("vsid")
            response = await client.post(
                "/api/chat/stream", json={"message": "hello there"}, headers=_csrf(client))
            assert response.status_code == 200
            assert vsid not in response.text

    @pytest.mark.asyncio
    async def test_normal_chat_response_never_contains_the_raw_vsid(self):
        """/api/chat (chat.py) was out of scope for this correction — it
        already used a random uuid4() default, never the raw vsid — so it
        need only be proven to still carry no vsid, not to match the
        demo_<hash> shape (that shape is chat_stream.py-specific)."""
        fake = _CountingRag()
        app.state.rag = fake
        async with _client() as client:
            await _demo_login(client, "general")
            vsid = client.cookies.get("vsid")
            response = await client.post(
                "/api/chat", json={"message": "hello"}, headers=_csrf(client))
            assert response.status_code == 200
            assert vsid not in response.text


# ---------------------------------------------------------------------------
# 7. Logs / errors carry no vsid
# ---------------------------------------------------------------------------

class TestNoVsidInLogsOrErrors:
    @pytest.mark.asyncio
    async def test_error_paths_never_echo_the_vsid(self, caplog):
        fake = _CountingRag()
        app.state.rag = fake
        async with _client() as client_a, _client() as client_b:
            await _demo_login(client_a, "general")
            await _demo_login(client_b, "general")
            vsid_a = client_a.cookies.get("vsid")
            vsid_b = client_b.cookies.get("vsid")

            with caplog.at_level(logging.DEBUG):
                first = await client_a.post(
                    "/api/chat", json={"message": "hello"}, headers=_csrf(client_a))
                sid = first.json()["session_id"]
                hijack = await client_b.post(
                    "/api/chat", json={"message": "hijack", "session_id": sid},
                    headers=_csrf(client_b),
                )
            assert hijack.status_code in (403, 404)
            assert vsid_a not in hijack.text
            assert vsid_b not in hijack.text
            # Application-level logging only. The SQLAlchemy engine's own
            # `echo=settings.debug` SQL trace legitimately logs every bound
            # column value for every table (including visitor_session_id) —
            # that is pre-existing dev/test infrastructure behavior, not new
            # application-level exposure introduced by this correction, and
            # disabling it is out of this task's scope.
            for record in caplog.records:
                if record.name.startswith("sqlalchemy"):
                    continue
                message = record.getMessage()
                assert vsid_a not in message
                assert vsid_b not in message


# ---------------------------------------------------------------------------
# 8 / 9. Ownership cannot be bypassed by knowing/crafting a session_id
# ---------------------------------------------------------------------------

class TestOwnershipNotWeakenedByDerivedId:
    @pytest.mark.asyncio
    async def test_knowing_another_visitors_derived_session_id_grants_nothing(self):
        fake = _CountingRag()
        app.state.rag = fake
        async with _client() as client_a, _client() as client_b:
            await _demo_login(client_a, "general")
            await _demo_login(client_b, "general")

            created = await client_a.post(
                "/api/chat/stream", json={"message": "hello there"}, headers=_csrf(client_a))
            assert created.status_code == 200
            _ = created.text  # drain so persistence completes
            db = SessionLocal()
            try:
                sid_a = db.query(ChatSession).filter(
                    ChatSession.visitor_session_id == client_a.cookies.get("vsid")
                ).one().id
            finally:
                db.close()
            assert DEMO_ID_RE.match(sid_a)

            # B now KNOWS A's exact derived session_id (e.g. leaked out of band)
            # and tries every surface with it.
            read = await client_b.get(f"/api/conversations/{sid_a}")
            assert read.status_code == 404
            append = await client_b.post(
                "/api/chat", json={"message": "hijack", "session_id": sid_a},
                headers=_csrf(client_b),
            )
            assert append.status_code in (403, 404)
            stream_append = await client_b.post(
                "/api/chat/stream", json={"message": "hijack", "session_id": sid_a},
                headers=_csrf(client_b),
            )
            assert stream_append.status_code in (403, 404)
            assert fake.calls == 1, "only A's own message should ever have reached RAG"

    @pytest.mark.asyncio
    async def test_a_client_crafted_correctly_shaped_session_id_cannot_hijack(self):
        """An attacker who guesses/forges a demo_<hash>-shaped id for someone
        else's (user_id, vsid) pair still hits the real ownership check —
        the id format itself carries no authority."""
        async with _client() as client:
            await _demo_login(client, "general")
            forged = _derive_public_demo_session_id(
                "portfolio.employee@finsolve.demo", "a-vsid-this-client-never-had"
            )
            response = await client.post(
                "/api/conversations", json={"conversation_id": forged, "title": "forged"},
                headers=_csrf(client),
            )
            # Either a brand-new (empty) conversation is created under the
            # caller's OWN real vsid, or — if it already existed under a
            # different vsid — access is refused. Either way it must not
            # silently attach the caller to someone else's history.
            if response.status_code == 200:
                db = SessionLocal()
                try:
                    row = db.query(ChatSession).filter(ChatSession.id == forged).first()
                    assert row.visitor_session_id == client.cookies.get("vsid")
                finally:
                    db.close()
            else:
                assert response.status_code == 404


# ---------------------------------------------------------------------------
# 10. Redis cache-key/invalidation code untouched — re-verify shape only.
# ---------------------------------------------------------------------------

class TestRedisCacheKeyCodeUnchanged:
    def test_cache_key_and_invalidation_still_include_all_isolation_dimensions(self):
        import inspect
        from src.backend.database.database import DatabaseManager

        history_src = inspect.getsource(DatabaseManager.get_chat_history)
        assert "f\"chat_history:{tenant_id}:{user_id}:{visitor_session_id or ''}:{session_id}:{limit}\"" in history_src

        invalidate_src = inspect.getsource(DatabaseManager._invalidate_chat_history)
        assert "f\"chat_history:{tenant_id}:{user_id}:{visitor_session_id or ''}:{session_id}:*\"" in invalidate_src
