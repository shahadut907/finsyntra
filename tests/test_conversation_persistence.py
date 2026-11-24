"""Wave 4: tenant-aware conversation persistence and read authorization.

Runs entirely against the Wave 1 temporary SQLite database.
"""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from src.backend.database.database import (
    ChatMessage, ChatSession, DatabaseManager, create_tables, db_manager,
)

ACME_USER = "employee@finsolve.com"
ACME_USER2 = "finance.lead@finsolve.com"
BETA_USER = "beta.employee@finsolve.com"
ACME = "tenant_acme"
BETA = "tenant_beta"


@pytest.fixture(autouse=True)
def schema():
    create_tables()
    yield


def new_id(prefix="c"):
    return "%s-%s" % (prefix, uuid.uuid4().hex[:10])


def seed(session_id, user_id, tenant_id, n_messages=2):
    db_manager.ensure_chat_session(
        user_id=user_id, session_id=session_id,
        metadata={"tenant_id": tenant_id, "user_role": "employee"})
    for i in range(n_messages):
        db_manager.add_chat_message(
            session_id=session_id, user_id=user_id,
            message_type="user" if i % 2 == 0 else "assistant",
            content="message %d" % i, sources=[],
            metadata={"tenant_id": tenant_id})
    return session_id


# ---------------------------------------------------------------------------
# Fail-closed session creation
# ---------------------------------------------------------------------------

class TestSessionCreationFailsClosed:
    def test_session_persists_with_tenant(self):
        sid = seed(new_id(), ACME_USER, ACME)
        db = db_manager.get_db()
        try:
            row = db.query(ChatSession).filter(ChatSession.id == sid).first()
            assert row is not None
            assert row.tenant_id == ACME
            assert db.query(ChatMessage).filter(ChatMessage.session_id == sid).count() == 2
        finally:
            db_manager.close_db(db)

    def test_missing_tenant_is_rejected(self):
        with pytest.raises(ValueError, match="without an authenticated tenant"):
            db_manager.ensure_chat_session(user_id=ACME_USER, session_id=new_id(), metadata={})

    def test_none_metadata_is_rejected(self):
        with pytest.raises(ValueError):
            db_manager.ensure_chat_session(user_id=ACME_USER, session_id=new_id(), metadata=None)

    def test_phantom_default_tenant_is_rejected(self):
        """The exact value 157 historical rows carried."""
        with pytest.raises(ValueError, match="not a real tenant"):
            db_manager.ensure_chat_session(
                user_id=ACME_USER, session_id=new_id(), metadata={"tenant_id": "default"})

    def test_blank_tenant_is_rejected(self):
        with pytest.raises(ValueError):
            db_manager.ensure_chat_session(
                user_id=ACME_USER, session_id=new_id(), metadata={"tenant_id": "   "})

    def test_missing_user_identity_is_rejected(self):
        with pytest.raises(ValueError, match="without a user identity"):
            db_manager.ensure_chat_session(
                user_id="", session_id=new_id(), metadata={"tenant_id": ACME})

    def test_rejected_session_is_not_written(self):
        sid = new_id()
        with pytest.raises(ValueError):
            db_manager.ensure_chat_session(user_id=ACME_USER, session_id=sid, metadata={})
        db = db_manager.get_db()
        try:
            assert db.query(ChatSession).filter(ChatSession.id == sid).first() is None
        finally:
            db_manager.close_db(db)

    def test_create_chat_session_enforces_the_same_rule(self):
        with pytest.raises(ValueError):
            db_manager.create_chat_session(user_id=ACME_USER, session_id=new_id(), metadata={})


class TestSessionOwnershipOnReuse:
    def test_other_user_cannot_reuse_session_id(self):
        sid = seed(new_id(), ACME_USER, ACME)
        with pytest.raises(ValueError, match="belongs to another user"):
            db_manager.ensure_chat_session(
                user_id=ACME_USER2, session_id=sid, metadata={"tenant_id": ACME})

    def test_other_tenant_cannot_reuse_session_id(self):
        sid = seed(new_id(), ACME_USER, ACME)
        with pytest.raises(ValueError):
            db_manager.ensure_chat_session(
                user_id=ACME_USER, session_id=sid, metadata={"tenant_id": BETA})

    def test_unresolved_legacy_session_cannot_be_claimed(self):
        sid = new_id("legacy")
        db = db_manager.get_db()
        try:
            db.add(ChatSession(id=sid, user_id=ACME_USER, tenant_id=None, meta={}))
            db.commit()
        finally:
            db_manager.close_db(db)

        with pytest.raises(ValueError, match="unresolved ownership"):
            db_manager.ensure_chat_session(
                user_id=ACME_USER, session_id=sid,
                metadata={"tenant_id": ACME})

        db = db_manager.get_db()
        try:
            assert db.query(ChatSession).filter(ChatSession.id == sid).one().tenant_id is None
        finally:
            db_manager.close_db(db)


class TestAtomicExchangePersistence:
    def test_exchange_is_written_atomically(self):
        sid = new_id("atomic")
        db_manager.persist_chat_exchange(
            session_id=sid,
            user_id=ACME_USER,
            tenant_id=ACME,
            user_role="employee",
            query="প্রশ্ন",
            response="উত্তর",
            sources=[{"source": "employee_handbook.md"}],
        )

        db = db_manager.get_db()
        try:
            session = db.query(ChatSession).filter(ChatSession.id == sid).one()
            messages = (db.query(ChatMessage)
                        .filter(ChatMessage.session_id == sid)
                        .order_by(ChatMessage.timestamp.asc(), ChatMessage.id.asc())
                        .all())
            assert session.tenant_id == ACME
            assert [m.message_type for m in messages] == ["user", "assistant"]
            assert [m.content for m in messages] == ["প্রশ্ন", "উত্তর"]
            assert messages[1].sources == [{"source": "employee_handbook.md"}]
        finally:
            db_manager.close_db(db)

    def test_exchange_rolls_back_session_and_both_messages_on_flush_failure(self):
        sid = new_id("rollback")

        def fail_assistant(_session, _flush_context, _instances):
            if any(isinstance(row, ChatMessage) and row.message_type == "assistant"
                   for row in _session.new):
                raise RuntimeError("forced assistant insert failure")

        event.listen(Session, "before_flush", fail_assistant)
        try:
            with pytest.raises(RuntimeError, match="forced assistant"):
                db_manager.persist_chat_exchange(
                    session_id=sid,
                    user_id=ACME_USER,
                    tenant_id=ACME,
                    user_role="employee",
                    query="question",
                    response="answer",
                    sources=[],
                )
        finally:
            event.remove(Session, "before_flush", fail_assistant)

        db = db_manager.get_db()
        try:
            assert db.query(ChatSession).filter(ChatSession.id == sid).first() is None
            assert db.query(ChatMessage).filter(ChatMessage.session_id == sid).count() == 0
        finally:
            db_manager.close_db(db)

    @pytest.mark.parametrize(
        ("user_id", "tenant_id"),
        [(ACME_USER2, ACME), (ACME_USER, BETA)],
    )
    def test_direct_message_insert_requires_exact_session_owner(self, user_id, tenant_id):
        sid = seed(new_id("owner"), ACME_USER, ACME, n_messages=0)
        with pytest.raises(ValueError):
            db_manager.add_chat_message(
                session_id=sid,
                user_id=user_id,
                message_type="user",
                content="must not be inserted",
                metadata={"tenant_id": tenant_id},
            )
        db = db_manager.get_db()
        try:
            assert db.query(ChatMessage).filter(ChatMessage.session_id == sid).count() == 0
        finally:
            db_manager.close_db(db)


# ---------------------------------------------------------------------------
# Conversation API authorization
# ---------------------------------------------------------------------------

def token_for(email):
    from src.backend.auth.authentication import create_access_token
    from src.config.roles import DEMO_USERS
    u = DEMO_USERS[email]
    return create_access_token({"sub": email, "role": u["role"],
                                "tenant_id": u["tenant_id"], "type": "access"})


async def api(method, path, email, **kw):
    from src.backend.api.endpoints import app
    raise_app_exceptions = kw.pop("raise_app_exceptions", True)
    transport = ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.request(method, path,
                               headers={"Authorization": "Bearer %s" % token_for(email)}, **kw)


class TestConversationReadAuthorization:
    @pytest.mark.asyncio
    async def test_owner_can_list_and_read(self):
        sid = seed(new_id(), ACME_USER, ACME)
        r = await api("GET", "/api/conversations", ACME_USER)
        assert r.status_code == 200
        assert sid in [s["id"] for s in r.json()["sessions"]]

        r = await api("GET", "/api/conversations/%s" % sid, ACME_USER)
        assert r.status_code == 200
        body = r.json()
        assert len(body["messages"]) == 2
        assert [m["content"] for m in body["messages"]] == ["message 0", "message 1"]

    @pytest.mark.asyncio
    async def test_cross_tenant_read_is_404_not_403(self):
        """404, so a probe cannot confirm the id exists in another tenant."""
        sid = seed(new_id(), ACME_USER, ACME)
        r = await api("GET", "/api/conversations/%s" % sid, BETA_USER)
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_same_tenant_other_user_is_403(self):
        sid = seed(new_id(), ACME_USER, ACME)
        r = await api("GET", "/api/conversations/%s" % sid, ACME_USER2)
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_random_session_id_is_404(self):
        r = await api("GET", "/api/conversations/%s" % new_id("guess"), ACME_USER)
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_listing_never_shows_other_tenants(self):
        acme_sid = seed(new_id(), ACME_USER, ACME)
        beta_sid = seed(new_id(), BETA_USER, BETA)

        r = await api("GET", "/api/conversations", BETA_USER)
        ids = [s["id"] for s in r.json()["sessions"]]
        assert beta_sid in ids
        assert acme_sid not in ids

    @pytest.mark.asyncio
    async def test_unresolved_null_tenant_sessions_are_unreachable(self):
        """Historical rows left NULL by the migration must not be readable."""
        sid = new_id("legacy")
        db = db_manager.get_db()
        try:
            db.add(ChatSession(id=sid, user_id=ACME_USER, tenant_id=None, meta={}))
            db.commit()
        finally:
            db_manager.close_db(db)
        r = await api("GET", "/api/conversations/%s" % sid, ACME_USER)
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_client_supplied_id_cannot_hijack_another_tenant(self):
        sid = seed(new_id(), ACME_USER, ACME)
        r = await api("POST", "/api/conversations", BETA_USER,
                      json={"conversation_id": sid, "title": "hijack"})
        assert r.status_code == 404
        db = db_manager.get_db()
        try:
            assert db.query(ChatSession).filter(ChatSession.id == sid).first().tenant_id == ACME
        finally:
            db_manager.close_db(db)

    @pytest.mark.asyncio
    async def test_chat_conversations_route_shares_the_rule(self):
        sid = seed(new_id(), ACME_USER, ACME)
        assert (await api("GET", "/api/chat/conversations/%s" % sid, ACME_USER)).status_code == 200
        assert (await api("GET", "/api/chat/conversations/%s" % sid, BETA_USER)).status_code == 404


class TestChatWritePersistence:
    @pytest.mark.asyncio
    async def test_non_stream_chat_generates_real_session_id_and_persists_pair(self):
        from src.backend.api.endpoints import app

        class FakeRag:
            def process_query(self, **_kwargs):
                return {
                    "success": True,
                    "response": "বাংলা উত্তর",
                    "sources": ["policy.md"],
                    "documents_found": 1,
                }

        previous = getattr(app.state, "rag", None)
        app.state.rag = FakeRag()
        try:
            r = await api("POST", "/api/chat", ACME_USER,
                          json={"message": "বাংলা প্রশ্ন"})
        finally:
            if previous is None:
                delattr(app.state, "rag")
            else:
                app.state.rag = previous

        assert r.status_code == 200, r.text
        sid = r.json()["session_id"]
        assert sid and sid != "default"

        db = db_manager.get_db()
        try:
            session = db.query(ChatSession).filter(ChatSession.id == sid).one()
            messages = (db.query(ChatMessage)
                        .filter(ChatMessage.session_id == sid)
                        .order_by(ChatMessage.timestamp.asc(), ChatMessage.id.asc())
                        .all())
            assert session.tenant_id == ACME
            assert [m.content for m in messages] == ["বাংলা প্রশ্ন", "বাংলা উত্তর"]
        finally:
            db_manager.close_db(db)

    @pytest.mark.asyncio
    async def test_inventory_stream_persists_delivered_exchange(self):
        from src.backend.api.endpoints import app

        class FakeRag:
            def get_document_inventory(self, tenant_id, user_role):
                assert tenant_id == ACME
                return "Available: employee_handbook.md"

        sid = new_id("inventory")
        previous = getattr(app.state, "rag", None)
        app.state.rag = FakeRag()
        try:
            r = await api("GET", "/api/chat/stream", ACME_USER,
                          params={"q": "list documents", "session_id": sid})
        finally:
            if previous is None:
                delattr(app.state, "rag")
            else:
                app.state.rag = previous

        assert r.status_code == 200
        assert "data: [DONE]" in r.text
        db = db_manager.get_db()
        try:
            rows = (db.query(ChatMessage)
                    .filter(ChatMessage.session_id == sid)
                    .order_by(ChatMessage.timestamp.asc(), ChatMessage.id.asc())
                    .all())
            assert [m.content for m in rows] == [
                "list documents", "Available: employee_handbook.md"]
        finally:
            db_manager.close_db(db)

    @pytest.mark.asyncio
    async def test_disconnect_before_complete_does_not_persist_fallback(self, monkeypatch):
        from src.backend.api import chat_stream
        from src.config.roles import Role

        class FailingRag:
            def process_query(self, **_kwargs):
                raise RuntimeError("forced RAG failure")

        class DisconnectDuringTokens:
            def __init__(self):
                self.calls = 0

            async def is_disconnected(self):
                self.calls += 1
                return self.calls >= 3

        async def fallback(*_args, **_kwargs):
            return " ".join("word%d" % i for i in range(40))

        monkeypatch.setattr(chat_stream, "generate_general_response", fallback)
        sid = new_id("disconnect")
        events = []
        async for item in chat_stream.generate_sse_response(
            query="nonexistent content query",
            user_role=Role.EMPLOYEE,
            user_name="Employee",
            user_email=ACME_USER,
            session_id=sid,
            rag_service=FailingRag(),
            request=DisconnectDuringTokens(),
            user_id=ACME_USER,
            tenant_id=ACME,
        ):
            events.append(item)

        assert not any('"type": "complete"' in item for item in events)
        db = db_manager.get_db()
        try:
            assert db.query(ChatMessage).filter(ChatMessage.session_id == sid).count() == 0
        finally:
            db_manager.close_db(db)


class TestExportAuthorization:
    @pytest.mark.asyncio
    async def test_owner_json_export(self):
        sid = seed(new_id(), ACME_USER, ACME)
        r = await api("GET", "/api/conversations/%s/export?format=json" % sid, ACME_USER)
        assert r.status_code == 200
        import json as _j
        assert len(_j.loads(r.text)["messages"]) == 2

    @pytest.mark.asyncio
    async def test_owner_markdown_export(self):
        sid = seed(new_id(), ACME_USER, ACME)
        r = await api("GET", "/api/conversations/%s/export?format=md" % sid, ACME_USER)
        assert r.status_code == 200
        assert "message 0" in r.text

    @pytest.mark.asyncio
    async def test_owner_pdf_export_is_authorized_and_renderer_is_invoked(self, monkeypatch):
        from src.backend.api import conversations

        sid = seed(new_id(), ACME_USER, ACME)
        calls = []

        def render(**kwargs):
            calls.append(kwargs)
            return b"%PDF-1.4\n% isolated authorization proof\n"

        monkeypatch.setattr(conversations.pdf_exporter, "export_chat", render)
        r = await api("GET", "/api/conversations/%s/export?format=pdf" % sid, ACME_USER)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content.startswith(b"%PDF-1.4")
        assert len(calls) == 1
        assert calls[0]["session_id"] == sid

    @pytest.mark.asyncio
    async def test_pdf_authorization_precedes_renderer_availability(self, monkeypatch):
        from src.backend.api import conversations

        sid = seed(new_id(), ACME_USER, ACME)
        calls = []

        def unavailable(**kwargs):
            calls.append(kwargs)
            raise RuntimeError("renderer unavailable")

        monkeypatch.setattr(conversations.pdf_exporter, "export_chat", unavailable)

        beta = await api("GET", "/api/conversations/%s/export?format=pdf" % sid, BETA_USER)
        assert beta.status_code == 404
        assert calls == [], "cross-tenant denial must happen before PDF rendering"

        owner = await api(
            "GET",
            "/api/conversations/%s/export?format=pdf" % sid,
            ACME_USER,
            raise_app_exceptions=False,
        )
        assert owner.status_code == 500
        assert len(calls) == 1, "owner authorization should reach the renderer"
        assert "renderer unavailable" not in owner.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("fmt", ["json", "md", "pdf"])
    async def test_cross_tenant_export_denied(self, fmt):
        sid = seed(new_id(), ACME_USER, ACME)
        r = await api("GET", "/api/conversations/%s/export?format=%s" % (sid, fmt), BETA_USER)
        assert r.status_code == 404, "cross-tenant %s export was not denied" % fmt

    @pytest.mark.asyncio
    async def test_same_tenant_other_user_export_denied(self):
        sid = seed(new_id(), ACME_USER, ACME)
        r = await api("GET", "/api/conversations/%s/export?format=json" % sid, ACME_USER2)
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_export_filename_cannot_inject_headers(self):
        """conversation_id reaches Content-Disposition; it must be sanitized."""
        from src.backend.api.conversations import _sanitize_filename
        nasty = 'a"\r\nX-Injected: yes'
        cleaned = _sanitize_filename(nasty)
        assert '"' not in cleaned and "\r" not in cleaned and "\n" not in cleaned
        assert ":" not in cleaned

    @pytest.mark.asyncio
    async def test_export_headers_are_clean_for_a_real_session(self):
        sid = seed(new_id(), ACME_USER, ACME)
        for fmt in ("json", "md"):
            r = await api("GET", "/api/conversations/%s/export?format=%s" % (sid, fmt), ACME_USER)
            cd = r.headers.get("content-disposition", "")
            assert "\r" not in cd and "\n" not in cd
            assert cd.count('"') == 2
