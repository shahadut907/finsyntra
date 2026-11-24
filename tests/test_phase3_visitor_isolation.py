"""Phase 3: public-demo visitor conversation isolation (vsid).

Covers:
  A. Cookie lifecycle — demo login issues an httpOnly vsid cookie, normal
     login doesn't touch it, logout clears it, and it never appears as
     plaintext JSON.
  B. Two browsers sharing the same public-demo identity get fully isolated
     conversation lists/reads/writes.
  C. A public-demo request with NO vsid cookie fails closed — it must not
     expose legacy NULL-vsid history.
  D. A legacy (pre-Phase-3) NULL-vsid demo conversation is invisible to a new
     visitor; an existing NON-demo NULL-vsid conversation is unaffected.
  E. Even an (artificially) identical vsid string can never cross a tenant
     boundary — tenant_id is checked before visitor_session_id.
  F. Even an identical vsid string can never cross a different demo
     identity's (user_id) boundary.
  G. /chat and /chat/stream reject the wrong visitor BEFORE any RAG call —
     proven with a call-counting fake RAG service, no real LLM/embeddings.

No SentenceTransformer, no Chroma ingestion, no Docker, no installs.
"""
import pytest
from httpx import AsyncClient, ASGITransport

from src.backend.api.endpoints import app
from src.backend.database.database import (
    ChatSession, ConversationForbiddenError, ConversationNotFoundError,
    SessionLocal, create_tables, db_manager,
)
from src.backend.middleware.security import rate_limiter
from src.config.settings import settings

TENANT_DEMO = "tenant_demo"
TENANT_ACME = "tenant_acme"


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    create_tables()
    rate_limiter.reset()
    monkeypatch.setattr(settings, "public_demo_enabled", True)
    yield
    rate_limiter.reset()
    # Never leave a fake RAG installed on the shared app singleton.
    app.state.rag = None


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _demo_login(client: AsyncClient, identity: str = "general"):
    response = await client.post("/auth/demo-login", json={"role": identity})
    assert response.status_code == 200, response.text
    return response


def _set_cookie_headers(response):
    return response.headers.get_list("set-cookie")


def _csrf(client: AsyncClient) -> dict:
    """CSRF header required by security_middleware for every cookie-
    authenticated POST/PUT/PATCH/DELETE except /auth/login and
    /auth/demo-login themselves."""
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


# ---------------------------------------------------------------------------
# A. Cookie lifecycle
# ---------------------------------------------------------------------------

class TestCookieLifecycle:
    @pytest.mark.asyncio
    async def test_demo_login_issues_an_httponly_vsid_cookie(self):
        async with _client() as client:
            response = await _demo_login(client, "general")
            vsid_headers = [h for h in _set_cookie_headers(response) if h.lower().startswith("vsid=")]
            assert len(vsid_headers) == 1
            header = vsid_headers[0]
            assert "HttpOnly" in header
            assert "SameSite=lax" in header or "samesite=lax" in header.lower()
            assert client.cookies.get("vsid")

    @pytest.mark.asyncio
    async def test_normal_login_does_not_set_or_require_a_vsid_cookie(self):
        async with _client() as client:
            response = await client.post("/auth/login", json={
                "email": "finance.lead@finsolve.com", "password": "password123",
            })
            assert response.status_code == 200
            assert not any(
                h.lower().startswith("vsid=") for h in _set_cookie_headers(response)
            )
            assert client.cookies.get("vsid") is None
            # And the normal (non-demo) account must be fully usable with no vsid.
            listing = await client.get("/api/conversations")
            assert listing.status_code == 200

    @pytest.mark.asyncio
    async def test_logout_clears_the_vsid_cookie(self):
        async with _client() as client:
            await _demo_login(client, "general")
            assert client.cookies.get("vsid")
            response = await client.post("/auth/logout", headers=_csrf(client))
            assert response.status_code == 200
            cleared = [h for h in _set_cookie_headers(response) if h.lower().startswith("vsid=")]
            assert cleared, "logout must send a Set-Cookie clearing vsid"
            assert ("Max-Age=0" in cleared[0]) or ("max-age=0" in cleared[0].lower())

    @pytest.mark.asyncio
    async def test_demo_login_response_never_contains_the_vsid_value_as_json(self):
        async with _client() as client:
            response = await _demo_login(client, "general")
            vsid_value = client.cookies.get("vsid")
            assert vsid_value
            body_text = response.text
            assert vsid_value not in body_text
            assert '"vsid"' not in body_text.lower()
            me = await client.get("/auth/me")
            assert vsid_value not in me.text
            assert '"vsid"' not in me.text.lower()

    @pytest.mark.asyncio
    async def test_refresh_does_not_touch_the_vsid_cookie(self):
        async with _client() as client:
            await _demo_login(client, "general")
            vsid_before = client.cookies.get("vsid")
            response = await client.post("/auth/refresh", headers=_csrf(client))
            assert response.status_code == 200
            assert not any(
                h.lower().startswith("vsid=") for h in _set_cookie_headers(response)
            )
            assert client.cookies.get("vsid") == vsid_before


# ---------------------------------------------------------------------------
# B. Same shared identity, different visitors
# ---------------------------------------------------------------------------

class TestTwoVisitorsSameIdentity:
    @pytest.mark.asyncio
    async def test_each_visitor_lists_only_its_own_conversations(self):
        async with _client() as client_a, _client() as client_b:
            await _demo_login(client_a, "general")
            await _demo_login(client_b, "general")

            created_a = await client_a.post(
                "/api/conversations", json={"title": "A's chat"}, headers=_csrf(client_a))
            created_b = await client_b.post(
                "/api/conversations", json={"title": "B's chat"}, headers=_csrf(client_b))
            assert created_a.status_code == 200 and created_b.status_code == 200
            id_a, id_b = created_a.json()["id"], created_b.json()["id"]

            list_a = await client_a.get("/api/conversations")
            list_b = await client_b.get("/api/conversations")
            assert {s["id"] for s in list_a.json()["sessions"]} == {id_a}
            assert {s["id"] for s in list_b.json()["sessions"]} == {id_b}

    @pytest.mark.asyncio
    async def test_a_cannot_read_bs_conversation(self):
        async with _client() as client_a, _client() as client_b:
            await _demo_login(client_a, "general")
            await _demo_login(client_b, "general")
            id_b = (await client_b.post(
                "/api/conversations", json={"title": "B"}, headers=_csrf(client_b))).json()["id"]

            response = await client_a.get(f"/api/conversations/{id_b}")
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_a_cannot_append_to_bs_conversation_via_create_endpoint(self):
        async with _client() as client_a, _client() as client_b:
            await _demo_login(client_a, "general")
            await _demo_login(client_b, "general")
            id_b = (await client_b.post(
                "/api/conversations", json={"title": "B"}, headers=_csrf(client_b))).json()["id"]

            response = await client_a.post(
                "/api/conversations", json={"conversation_id": id_b, "title": "hijacked"},
                headers=_csrf(client_a),
            )
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_a_cannot_export_bs_conversation(self):
        async with _client() as client_a, _client() as client_b:
            await _demo_login(client_a, "general")
            await _demo_login(client_b, "general")
            id_b = (await client_b.post(
                "/api/conversations", json={"title": "B"}, headers=_csrf(client_b))).json()["id"]

            response = await client_a.get(f"/api/conversations/{id_b}/export?format=json")
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_b_is_equally_blocked_from_a(self):
        async with _client() as client_a, _client() as client_b:
            await _demo_login(client_a, "general")
            await _demo_login(client_b, "general")
            id_a = (await client_a.post(
                "/api/conversations", json={"title": "A"}, headers=_csrf(client_a))).json()["id"]

            assert (await client_b.get(f"/api/conversations/{id_a}")).status_code == 404
            assert (await client_b.post(
                "/api/conversations", json={"conversation_id": id_a}, headers=_csrf(client_b)
            )).status_code == 404

    @pytest.mark.asyncio
    async def test_conversation_note_no_rename_or_delete_endpoint_exists(self):
        """Documented gap, not a Phase 3 regression: there is currently no
        rename/update or delete route for conversations anywhere in the API
        (verified by inspection of conversations.py/chat.py/chat_stream.py
        before implementation). If one is added later it MUST reuse
        load_owned_session/_assert_session_owner so it inherits vsid
        enforcement automatically rather than re-implementing it."""
        async with _client() as client:
            await _demo_login(client, "general")
            sid = (await client.post(
                "/api/conversations", json={"title": "x"}, headers=_csrf(client))).json()["id"]
            assert (await client.delete(
                f"/api/conversations/{sid}", headers=_csrf(client))).status_code in (404, 405)
            assert (await client.put(
                f"/api/conversations/{sid}", headers=_csrf(client))).status_code in (404, 405)


# ---------------------------------------------------------------------------
# C. Missing vsid fails closed
# ---------------------------------------------------------------------------

class TestMissingVsidFailsClosed:
    @pytest.mark.asyncio
    async def test_list_fails_closed_without_a_vsid_cookie(self):
        async with _client() as client:
            await _demo_login(client, "general")
            del client.cookies["vsid"]

            response = await client.get("/api/conversations")
            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "DEMO_VISITOR_SESSION_REQUIRED"

    @pytest.mark.asyncio
    async def test_missing_vsid_does_not_expose_legacy_null_vsid_conversations(self):
        """The critical anti-fallback guarantee: losing the vsid cookie must
        403, never silently widen the query to legacy visitor_session_id IS
        NULL rows."""
        async with _client() as client:
            await _demo_login(client, "general")
            user_id = (await client.get("/auth/me")).json()["id"]

        # A legacy public-demo conversation with NULL visitor_session_id,
        # created directly (bypassing HTTP) the way a pre-Phase-3 row would
        # have looked.
        db_manager.create_chat_session(
            user_id=user_id, session_id="legacy-demo-session-null-vsid",
            metadata={"tenant_id": TENANT_DEMO},
        )

        async with _client() as client:
            await _demo_login(client, "general")
            del client.cookies["vsid"]
            listing = await client.get("/api/conversations")
            assert listing.status_code == 403
            direct_read = await client.get("/api/conversations/legacy-demo-session-null-vsid")
            assert direct_read.status_code == 403  # fails closed before even querying


# ---------------------------------------------------------------------------
# D. Legacy data
# ---------------------------------------------------------------------------

class TestLegacyData:
    @pytest.mark.asyncio
    async def test_legacy_null_vsid_demo_conversation_is_invisible_to_a_new_visitor(self):
        async with _client() as bootstrap:
            await _demo_login(bootstrap, "general")
            user_id = (await bootstrap.get("/auth/me")).json()["id"]

        legacy = db_manager.create_chat_session(
            user_id=user_id, session_id="legacy-null-vsid-conv",
            metadata={"tenant_id": TENANT_DEMO},
        )
        assert legacy.visitor_session_id is None

        async with _client() as visitor:
            await _demo_login(visitor, "general")  # fresh, valid vsid
            listing = await visitor.get("/api/conversations")
            assert listing.status_code == 200
            assert "legacy-null-vsid-conv" not in {s["id"] for s in listing.json()["sessions"]}
            direct = await visitor.get("/api/conversations/legacy-null-vsid-conv")
            assert direct.status_code == 404

    @pytest.mark.asyncio
    async def test_existing_non_demo_null_vsid_conversation_still_works(self):
        """Non-demo accounts never had, and never get, a vsid — their
        pre-existing NULL-vsid rows must keep working exactly as before."""
        async with _client() as client:
            login = await client.post("/auth/login", json={
                "email": "finance.lead@finsolve.com", "password": "password123",
            })
            assert login.status_code == 200
            created = await client.post(
                "/api/conversations", json={"title": "Acme convo"}, headers=_csrf(client))
            assert created.status_code == 200
            sid = created.json()["id"]

            db = SessionLocal()
            try:
                row = db.query(ChatSession).filter(ChatSession.id == sid).first()
                assert row.visitor_session_id is None
                assert row.tenant_id == TENANT_ACME
            finally:
                db.close()

            fetched = await client.get(f"/api/conversations/{sid}")
            assert fetched.status_code == 200
            listing = await client.get("/api/conversations")
            assert sid in {s["id"] for s in listing.json()["sessions"]}


# ---------------------------------------------------------------------------
# E / F. vsid can never cross a tenant or identity boundary
# ---------------------------------------------------------------------------

class TestVsidNeverOverridesTenantOrIdentity:
    def test_identical_vsid_cannot_cross_a_tenant_boundary(self):
        """Direct proof against the authoritative helper: tenant mismatch is
        checked (and rejected) before visitor_session_id is ever compared."""
        session = ChatSession(
            id="s1", user_id="shared-user", tenant_id="tenant_A",
            visitor_session_id="SAME-VSID",
        )
        with pytest.raises(ConversationNotFoundError):
            db_manager._assert_session_owner(
                session, user_id="shared-user", tenant_id="tenant_B",
                visitor_session_id="SAME-VSID",
            )

    def test_identical_vsid_cannot_cross_a_different_demo_identity(self):
        """Same tenant, same vsid string, but a DIFFERENT public-demo user_id
        (e.g. finance vs hr) must still hit the existing user_id check."""
        session = ChatSession(
            id="s2", user_id="portfolio.finance@finsolve.demo", tenant_id=TENANT_DEMO,
            visitor_session_id="SAME-VSID",
        )
        with pytest.raises(ConversationForbiddenError):
            db_manager._assert_session_owner(
                session, user_id="portfolio.hr@finsolve.demo", tenant_id=TENANT_DEMO,
                visitor_session_id="SAME-VSID",
            )

    @pytest.mark.asyncio
    async def test_different_demo_identities_do_not_share_conversations_over_http(self):
        async with _client() as finance_client, _client() as hr_client:
            await _demo_login(finance_client, "finance")
            await _demo_login(hr_client, "hr")

            fin_id = (await finance_client.post(
                "/api/conversations", json={"title": "finance chat"},
                headers=_csrf(finance_client),
            )).json()["id"]

            # Different demo user_id, same tenant: this is the PRE-EXISTING
            # same-tenant-different-user contract (403), not the vsid rule —
            # it was already correct before Phase 3 and is unchanged by it.
            response = await hr_client.get(f"/api/conversations/{fin_id}")
            assert response.status_code == 403
            listing = await hr_client.get("/api/conversations")
            assert fin_id not in {s["id"] for s in listing.json()["sessions"]}


# ---------------------------------------------------------------------------
# G. /chat and /chat/stream reject the wrong visitor before generation
# ---------------------------------------------------------------------------

class _CountingRag:
    """Stands in for RAGService without ever loading SentenceTransformer."""
    def __init__(self):
        self.calls = 0
        self.last_history = None

    def process_query(self, **kwargs):
        self.calls += 1
        self.last_history = kwargs.get("conversation_history")
        return {
            "response": "fake grounded answer", "sources": [],
            "documents_found": 1, "success": True,
        }


class TestChatAndStreamRejectWrongVisitorBeforeGeneration:
    @pytest.mark.asyncio
    async def test_chat_endpoint_rejects_wrong_visitor_without_calling_rag(self):
        fake = _CountingRag()
        app.state.rag = fake
        async with _client() as client_a, _client() as client_b:
            await _demo_login(client_a, "general")
            await _demo_login(client_b, "general")

            first = await client_a.post(
                "/api/chat", json={"message": "hello"}, headers=_csrf(client_a))
            assert first.status_code == 200
            assert fake.calls == 1
            sid = first.json()["session_id"]

            hijack = await client_b.post(
                "/api/chat", json={"message": "hijack attempt", "session_id": sid},
                headers=_csrf(client_b),
            )
            assert hijack.status_code in (403, 404)
            assert fake.calls == 1, "RAG must never be invoked for a rejected visitor"

    @pytest.mark.asyncio
    async def test_chat_stream_endpoint_rejects_wrong_visitor_without_calling_rag(self):
        fake = _CountingRag()
        app.state.rag = fake
        async with _client() as client_a, _client() as client_b:
            await _demo_login(client_a, "general")
            await _demo_login(client_b, "general")

            first = await client_a.post(
                "/api/chat/stream", json={"message": "hello there"}, headers=_csrf(client_a))
            assert first.status_code == 200
            # Consume the stream so persistence/generation actually completes.
            _ = first.text
            assert fake.calls == 1

            db = SessionLocal()
            try:
                sid = db.query(ChatSession).filter(
                    ChatSession.user_id == "portfolio.employee@finsolve.demo",
                    ChatSession.visitor_session_id == client_a.cookies.get("vsid"),
                ).order_by(ChatSession.created_at.desc()).first().id
            finally:
                db.close()

            hijack = await client_b.post(
                "/api/chat/stream", json={"message": "hijack", "session_id": sid},
                headers=_csrf(client_b),
            )
            assert hijack.status_code in (403, 404)
            assert fake.calls == 1, "RAG must never be invoked for a rejected visitor"
            assert "text/event-stream" not in hijack.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_no_missing_vsid_reaches_rag_either(self):
        fake = _CountingRag()
        app.state.rag = fake
        async with _client() as client:
            await _demo_login(client, "general")
            del client.cookies["vsid"]
            response = await client.post(
                "/api/chat", json={"message": "should never run"}, headers=_csrf(client))
            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "DEMO_VISITOR_SESSION_REQUIRED"
            assert fake.calls == 0
