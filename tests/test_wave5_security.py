"""Behavioral regression matrix for Wave 5 security closure."""
import asyncio
import os
import subprocess
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.backend.api.endpoints import app
from src.backend.auth.authentication import create_access_token
from src.backend.database.database import (
    ChatMessage, ChatSession, Document, RefreshToken, SessionLocal, User, create_tables,
)
from src.backend.middleware.security import rate_limiter
from src.config.roles import DEMO_USERS
from src.config.settings import get_raw_documents_path


def access(email: str, **claims) -> str:
    payload = {"sub": email, "type": "access", **claims}
    return create_access_token(payload)


def refresh_claim(email: str) -> str:
    return create_access_token({"sub": email, "type": "refresh"}, expires_delta=timedelta(days=7))


def auth(email: str, **claims) -> dict:
    return {"Authorization": f"Bearer {access(email, **claims)}"}


@pytest.fixture(autouse=True)
def authoritative_store():
    create_tables()
    rate_limiter.reset()
    db = SessionLocal()
    try:
        for email, expected in DEMO_USERS.items():
            row = db.query(User).filter(User.email == email).first()
            if row:
                row.role = expected["role"]
                row.tenant_id = expected["tenant_id"]
                row.is_active = True
        db.query(Document).filter(Document.meta["wave5_test"].as_boolean() == True).delete(
            synchronize_session=False
        )
        db.commit()
    finally:
        db.close()
    yield
    rate_limiter.reset()


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        yield value


@pytest.mark.asyncio
async def test_role_claim_escalation_is_server_resolved(client):
    response = await client.get("/api/admin/users", headers=auth(
        "employee@finsolve.com", role="admin", tenant_id="tenant_beta"
    ))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_tenant_claim_tampering_is_ignored(client):
    response = await client.get("/api/admin/users", headers=auth(
        "beta.admin@finsolve.com", role="admin", tenant_id="tenant_acme"
    ))
    assert response.status_code == 200
    emails = {item["email"] for item in response.json()}
    assert "beta.employee@finsolve.com" in emails
    assert "employee@finsolve.com" not in emails


@pytest.mark.asyncio
async def test_unknown_and_inactive_users_are_rejected(client):
    unknown = await client.get("/auth/me", headers=auth("missing@finsolve.com"))
    assert unknown.status_code == 401
    db = SessionLocal()
    db.query(User).filter(User.email == "employee@finsolve.com").update({"is_active": False})
    db.commit()
    db.close()
    inactive = await client.get("/auth/me", headers=auth("employee@finsolve.com"))
    assert inactive.status_code == 401


@pytest.mark.asyncio
async def test_deactivated_user_cannot_refresh(client):
    login = await client.post("/auth/login", json={
        "email": "employee@finsolve.com", "password": "password123"
    })
    assert login.status_code == 200
    csrf = client.cookies.get("csrf_token")
    db = SessionLocal()
    db.query(User).filter(User.email == "employee@finsolve.com").update({"is_active": False})
    db.commit()
    db.close()
    response = await client.post("/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_access_token_cannot_be_used_at_refresh_endpoint(client):
    client.cookies.set("refresh_token", access("employee@finsolve.com"))
    client.cookies.set("csrf_token", "type-check")
    response = await client.post("/auth/refresh", headers={"X-CSRF-Token": "type-check"})
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/auth/me", "/api/conversations", "/api/admin/users", "/api/documents/list",
    "/api/chat/stream?q=test&session_id=refresh-denied",
])
async def test_refresh_token_rejected_on_every_access_path(client, path):
    response = await client.get(path, headers={
        "Authorization": f"Bearer {refresh_claim('admin@finsolve.com')}"
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotation_replay_and_logout_revocation(client):
    login = await client.post("/auth/login", json={
        "email": "admin@finsolve.com", "password": "admin123"
    })
    assert login.status_code == 200
    old_refresh = client.cookies.get("refresh_token")
    old_csrf = client.cookies.get("csrf_token")
    rotated = await client.post("/auth/refresh", headers={"X-CSRF-Token": old_csrf})
    assert rotated.status_code == 200
    new_refresh = client.cookies.get("refresh_token")
    assert new_refresh != old_refresh

    replay_client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    replay_client.cookies.set("refresh_token", old_refresh)
    replay_client.cookies.set("csrf_token", "replay-csrf")
    replay = await replay_client.post("/auth/refresh", headers={"X-CSRF-Token": "replay-csrf"})
    await replay_client.aclose()
    assert replay.status_code == 401

    csrf = client.cookies.get("csrf_token")
    logout = await client.post("/auth/logout", headers={"X-CSRF-Token": csrf})
    assert logout.status_code == 200
    revoked_client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    revoked_client.cookies.set("refresh_token", new_refresh)
    revoked_client.cookies.set("csrf_token", "logout-replay")
    revoked = await revoked_client.post("/auth/refresh", headers={"X-CSRF-Token": "logout-replay"})
    await revoked_client.aclose()
    assert revoked.status_code == 401


@pytest.mark.asyncio
async def test_simultaneous_refresh_only_one_succeeds(client):
    login = await client.post("/auth/login", json={
        "email": "beta.admin@finsolve.com", "password": "admin123"
    })
    assert login.status_code == 200
    token = client.cookies.get("refresh_token")

    async def attempt():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as contender:
            contender.cookies.set("refresh_token", token)
            contender.cookies.set("csrf_token", "race")
            return await contender.post("/auth/refresh", headers={"X-CSRF-Token": "race"})

    results = await asyncio.gather(attempt(), attempt())
    assert sorted(item.status_code for item in results) == [200, 401]


def _seed_documents():
    root = Path(get_raw_documents_path())
    root.mkdir(parents=True, exist_ok=True)
    acme_name = f"wave5-acme-{uuid.uuid4().hex}.md"
    beta_name = f"wave5-beta-{uuid.uuid4().hex}.md"
    (root / acme_name).write_text("ACME SECRET REVENUE", encoding="utf-8")
    (root / beta_name).write_text("BETA SAFE", encoding="utf-8")
    db = SessionLocal()
    acme_id, beta_id = str(uuid.uuid4()), str(uuid.uuid4())
    db.add_all([
        Document(id=acme_id, filename="acme-secret.md", storage_path=acme_name,
                 tenant_id="tenant_acme", content_type="text/markdown", file_size=19,
                 department="finance", uploaded_by="admin@finsolve.com", is_active=True,
                 meta={"wave5_test": True}),
        Document(id=beta_id, filename="beta-safe.md", storage_path=beta_name,
                 tenant_id="tenant_beta", content_type="text/markdown", file_size=9,
                 department="general", uploaded_by="beta.admin@finsolve.com", is_active=True,
                 meta={"wave5_test": True}),
    ])
    db.commit()
    db.close()
    return acme_id, beta_id, root / acme_name


@pytest.mark.asyncio
async def test_document_content_download_delete_and_filenames_are_tenant_scoped(client):
    acme_id, _, acme_path = _seed_documents()
    headers = auth("beta.admin@finsolve.com")
    for suffix, method in (("content", client.get), ("download", client.get)):
        response = await method(f"/api/admin/documents/{acme_id}/{suffix}", headers=headers)
        assert response.status_code == 404
        assert "ACME SECRET" not in response.text
    denied_delete = await client.delete(f"/api/admin/documents/{acme_id}", headers=headers)
    assert denied_delete.status_code == 404
    assert acme_path.exists()
    listing = await client.get("/api/admin/documents", headers=headers)
    assert "acme-secret.md" not in listing.text
    normal_listing = await client.get("/api/documents/list", headers=auth("beta.employee@finsolve.com"))
    assert "acme-secret.md" not in normal_listing.text


@pytest.mark.asyncio
async def test_recent_activity_and_user_mutation_are_tenant_scoped(client):
    db = SessionLocal()
    acme_session, beta_session = str(uuid.uuid4()), str(uuid.uuid4())
    db.add_all([
        ChatSession(id=acme_session, user_id="employee@finsolve.com", tenant_id="tenant_acme"),
        ChatSession(id=beta_session, user_id="beta.employee@finsolve.com", tenant_id="tenant_beta"),
        ChatMessage(id=str(uuid.uuid4()), session_id=acme_session,
                    user_id="employee@finsolve.com", message_type="user", content="ACME CHAT SECRET"),
        ChatMessage(id=str(uuid.uuid4()), session_id=beta_session,
                    user_id="beta.employee@finsolve.com", message_type="user", content="BETA CHAT"),
    ])
    db.commit()
    db.close()
    headers = auth("beta.admin@finsolve.com")
    activity = await client.get("/api/admin/recent-activity", headers=headers)
    assert activity.status_code == 200
    assert "BETA CHAT" in activity.text and "ACME CHAT SECRET" not in activity.text
    mutation = await client.put("/api/admin/users/employee@finsolve.com",
                                headers=headers, json={"role": "admin"})
    assert mutation.status_code == 404


@pytest.mark.asyncio
async def test_chat_paths_use_authoritative_tenant(client):
    rag = MagicMock()
    rag.process_query.return_value = {"success": True, "response": "safe", "sources": [], "documents_found": 0}
    app.state.rag = rag
    session_id = f"wave5-chat-{uuid.uuid4().hex}"
    response = await client.post("/api/chat", headers=auth(
        "beta.employee@finsolve.com", tenant_id="tenant_acme"
    ), json={"message": "test", "session_id": session_id})
    assert response.status_code == 200
    assert rag.process_query.call_args.kwargs["tenant_id"] == "tenant_beta"

    with patch("src.backend.api.chat_stream.unified_chat_stream_handler", new=AsyncMock(
        return_value={"ok": True}
    )) as handler:
        stream = await client.get("/api/chat/stream?q=test", headers=auth(
            "beta.employee@finsolve.com", tenant_id="tenant_acme"
        ))
        assert stream.status_code == 200
        assert handler.await_args.kwargs["current_user"]["tenant_id"] == "tenant_beta"


@pytest.mark.asyncio
async def test_cors_csrf_security_headers_and_health(client):
    preflight = await client.options("/api/chat", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "POST",
    })
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"
    disallowed = await client.options("/api/chat", headers={
        "Origin": "https://evil.example",
        "Access-Control-Request-Method": "POST",
    })
    assert "access-control-allow-origin" not in disallowed.headers

    token = access("employee@finsolve.com")
    client.cookies.set("session_token", token)
    client.cookies.set("csrf_token", "expected")
    denied = await client.post("/api/conversations", json={})
    assert denied.status_code == 403
    allowed = await client.post("/api/conversations", headers={"X-CSRF-Token": "expected"}, json={})
    assert allowed.status_code == 200
    assert allowed.headers["x-content-type-options"] == "nosniff"
    assert allowed.headers["x-frame-options"] == "DENY"

    shallow = await client.get("/health")
    assert shallow.json() == {"status": "ok", "service": "finsyntra-api"}
    deep = await client.get("/health/deep", headers=auth("employee@finsolve.com"))
    assert deep.status_code == 403


@pytest.mark.asyncio
async def test_login_rate_limiter_is_active(client, monkeypatch):
    monkeypatch.setattr("src.backend.middleware.security.settings.login_rate_limit_per_minute", 2)
    for _ in range(2):
        response = await client.post("/auth/login", json={
            "email": "nobody@finsolve.com", "password": "wrong"
        })
        assert response.status_code == 401
    limited = await client.post("/auth/login", json={
        "email": "nobody@finsolve.com", "password": "wrong"
    })
    assert limited.status_code == 429


@pytest.mark.asyncio
@pytest.mark.parametrize("filename,content,department", [
    ("../escape.md", b"safe text", "general"),
    ("fake.pdf", b"not a pdf", "general"),
    ("unsupported.docx", b"PK fake zip", "general"),
    ("safe.md", b"safe text", "unknown"),
])
async def test_upload_rejects_unsafe_inputs_before_processing(client, filename, content, department):
    response = await client.post(
        "/api/documents/upload", headers=auth("admin@finsolve.com"),
        files={"file": (filename, content, "application/octet-stream")},
        data={"department": department},
    )
    assert response.status_code == 400
    assert "Traceback" not in response.text and "E:\\" not in response.text


@pytest.mark.asyncio
async def test_upload_rejects_oversize(client):
    response = await client.post(
        "/api/documents/upload", headers=auth("admin@finsolve.com"),
        files={"file": ("large.md", b"a" * (10 * 1024 * 1024 + 1), "text/markdown")},
        data={"department": "general"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_document_with_no_indexable_content(client):
    rag = MagicMock()
    with patch("src.backend.api.document_upload.get_rag_service", return_value=rag), patch(
        "src.backend.api.document_upload.document_processor.process_markdown", return_value=[]
    ):
        response = await client.post(
            "/api/documents/upload", headers=auth("admin@finsolve.com"),
            files={"file": ("malformed.md", b"not indexable", "text/markdown")},
            data={"department": "general"},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "Document contained no indexable content"


@pytest.mark.asyncio
async def test_client_error_does_not_leak_internal_exception(client):
    with patch("src.backend.api.document_upload.get_rag_service",
               side_effect=RuntimeError("sqlite:///E:/secret.db ollama://internal")):
        response = await client.get("/api/documents/list", headers=auth("employee@finsolve.com"))
    assert response.status_code == 500
    assert "secret.db" not in response.text and "internal" not in response.text


def test_production_auth_bypass_is_impossible():
    environment = os.environ.copy()
    environment.update({
        "ENV": "production",
        "BYPASS_AUTH": "true",
        "SECRET_KEY": "wave5-production-test-key-with-more-than-32-characters",
        "ALLOWED_ORIGINS": '["https://app.example.test"]',
        "DEBUG": "false",
    })
    result = subprocess.run(
        [sys.executable, "-c", "import src.config.settings"],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        text=True, capture_output=True,
    )
    assert result.returncode != 0
    assert "BYPASS_AUTH=true is not allowed" in (result.stdout + result.stderr)
