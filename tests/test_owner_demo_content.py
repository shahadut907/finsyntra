"""Owner-managed public-demo content.

A real (password-authenticated, is_public_demo=False) tenant admin of the demo
tenant can upload content; public-demo personas stay read-only; cited sources
open only under retrieval's own tenant + department visibility.

Runs on the root conftest's temporary SQLite/Chroma. The vector store is a
fake that applies the same tenant/department rules as Chroma's `where` filter,
and that filter itself is asserted separately against get_source_passages.
"""
import secrets
import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.backend.api.endpoints import app
from src.backend.auth.authentication import get_password_hash
from src.backend.database.database import Document, SessionLocal, User, create_tables
from src.backend.middleware.security import rate_limiter
from src.backend.utils.document_processor import DocumentChunk
from src.config.settings import settings

OWNER_EMAIL = f"owner-{uuid.uuid4().hex[:8]}@example.test"
OWNER_PASSWORD = secrets.token_urlsafe(24)  # per-run, never persisted outside the temp DB
FACT = "The synthetic Zephyr ledger closes on day 17."


class FakeVectorStore:
    """Indexes chunks in memory and filters exactly like the Chroma query."""

    def __init__(self):
        self.chunks = []
        self.fail_sources = set()  # simulate a failed (unverified) vector delete

    def add_documents(self, chunks, tenant_id=None):
        for chunk in chunks:
            assert chunk.metadata["tenant_id"] == tenant_id
            self.chunks.append((chunk.content, dict(chunk.metadata)))
        return True

    def get_source_passages(self, source, tenant_id, departments):
        return [text for text, meta in self.chunks
                if meta["source"] == source and meta["tenant_id"] == tenant_id
                and meta["department"] in departments]

    def get_collection_stats(self, tenant_id=None, departments=None):
        return {"total_documents": len(self.chunks), "departments": {}, "sources": {}}

    def delete_documents_by_sources(self, sources, tenant_id=None, raise_on_error=False):
        if self.fail_sources.intersection(sources):
            raise RuntimeError("vector chunks still present after delete")
        self.chunks = [c for c in self.chunks
                       if not (c[1]["source"] in sources and c[1]["tenant_id"] == tenant_id)]
        return True

    def get_unique_sources(self, tenant_id=None):
        return sorted({m["source"] for _, m in self.chunks if m["tenant_id"] == tenant_id})


@pytest.fixture
def store():
    fake = FakeVectorStore()
    rag = MagicMock()
    rag.vector_store = fake

    def parse(path):
        from pathlib import Path
        # PDFs stand in for the FACT document; text files index their own text.
        text = (FACT if path.endswith(".pdf")
                else Path(path).read_text(encoding="utf-8"))
        return [DocumentChunk(text + " Padding text to make a substantial chunk.",
                              {"source": Path(path).name, "chunk_id": 0, "department": None})]

    with patch("src.backend.api.document_upload.get_rag_service", return_value=rag), \
         patch("src.backend.api.admin.RAGService", return_value=rag), \
         patch("src.backend.api.document_upload.document_processor") as processor:
        processor.process_pdf.side_effect = parse
        processor.process_markdown.side_effect = parse
        yield fake


@pytest.fixture
async def client(monkeypatch):
    create_tables()
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.email == OWNER_EMAIL).first():
            db.add(User(id=OWNER_EMAIL, username=OWNER_EMAIL, email=OWNER_EMAIL,
                        hashed_password=get_password_hash(OWNER_PASSWORD),
                        full_name="Test Owner", role="admin",
                        tenant_id=settings.demo_tenant_id, department="Administration",
                        is_active=True, is_public_demo=False))
            db.commit()
    finally:
        db.close()
    rate_limiter.reset()
    monkeypatch.setattr(settings, "public_demo_enabled", True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        yield value
    rate_limiter.reset()
    _remove_disposable_rows()


def _remove_disposable_rows():
    """Other suites pin tenant_demo's exact users/documents; leave none behind."""
    from src.backend.database.database import RefreshToken
    db = SessionLocal()
    try:
        disposable = [u.id for u in db.query(User).filter(User.email.like("%@example.test")).all()]
        db.query(Document).filter(Document.uploaded_by.in_(disposable)).delete(
            synchronize_session=False)
        db.query(RefreshToken).filter(RefreshToken.user_id.in_(disposable)).delete(
            synchronize_session=False)
        db.query(User).filter(User.id.in_(disposable)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


async def _owner_login(client):
    response = await client.post("/auth/login",
                                 json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["user"]


async def _demo_login(client, identity):
    client.cookies.clear()
    response = await client.post("/auth/demo-login", json={"role": identity})
    assert response.status_code == 200, response.text
    return response.json()["user"]


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


async def _owner_upload(client, department="finance"):
    pdf = b"%PDF-1.4\n" + uuid.uuid4().hex.encode() + b"\n%%EOF"
    response = await client.post(
        "/api/admin/upload-department-data", headers=_csrf(client),
        data={"department": department},
        files={"files": ("zephyr.pdf", pdf, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True, body
    return body["results"][0]["file_info"]["saved_filename"]


class TestOwnerAccount:
    @pytest.mark.asyncio
    async def test_owner_logs_in_with_password_as_real_demo_tenant_admin(self, client):
        user = await _owner_login(client)
        assert user["role"] == "admin"
        assert user["tenant_id"] == settings.demo_tenant_id
        assert user["is_public_demo"] is False
        assert user["tenant_serves_public_demo"] is True

    @pytest.mark.asyncio
    async def test_public_demo_persona_cannot_use_password_login(self, client):
        response = await client.post("/auth/login", json={
            "email": "portfolio.admin@finsolve.demo", "password": OWNER_PASSWORD})
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_owner_upload_is_indexed_into_demo_tenant(self, client, store):
        await _owner_login(client)
        source = await _owner_upload(client)
        metas = [m for _, m in store.chunks if m["source"] == source]
        assert metas and all(m["tenant_id"] == settings.demo_tenant_id for m in metas)
        assert all(m["department"] == "finance" for m in metas)
        db = SessionLocal()
        try:
            row = db.query(Document).filter(Document.storage_path == source).one()
            assert row.tenant_id == settings.demo_tenant_id and row.chunk_count == 1
            assert row.processed_at is not None and row.is_protected_demo is False
        finally:
            db.close()


class TestCitationVisibility:
    @pytest.mark.asyncio
    async def test_demo_admin_sees_owner_document_in_admin_list(self, client, store):
        await _owner_login(client)
        source = await _owner_upload(client)
        await _demo_login(client, "admin")
        listing = await client.get("/api/admin/documents")
        assert listing.status_code == 200
        row = next(d for d in listing.json() if d["filename"] == "zephyr.pdf"
                   and d["status"] == "indexed")
        assert row["department"] == "finance" and row["chunk_count"] == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("identity", ["finance", "ceo", "admin"])
    async def test_authorized_demo_personas_open_the_citation(self, client, store, identity):
        await _owner_login(client)
        source = await _owner_upload(client)
        await _demo_login(client, identity)
        response = await client.get(f"/api/documents/source/{source}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["filename"] == "zephyr.pdf"
        assert any(FACT in passage for passage in body["passages"])

    @pytest.mark.asyncio
    @pytest.mark.parametrize("identity", ["hr", "engineering", "general"])
    async def test_other_department_personas_get_404(self, client, store, identity):
        await _owner_login(client)
        source = await _owner_upload(client)
        await _demo_login(client, identity)
        response = await client.get(f"/api/documents/source/{source}")
        assert response.status_code == 404
        assert FACT not in response.text

    @pytest.mark.asyncio
    async def test_other_tenant_admin_gets_404_on_source_and_admin_routes(self, client, store):
        await _owner_login(client)
        source = await _owner_upload(client)
        db = SessionLocal()
        try:
            doc_id = db.query(Document).filter(Document.storage_path == source).one().id
            other = f"other-{uuid.uuid4().hex[:8]}@example.test"
            password = secrets.token_urlsafe(24)
            db.add(User(id=other, username=other, email=other,
                        hashed_password=get_password_hash(password), full_name="Other",
                        role="admin", tenant_id="tenant_beta", department="IT",
                        is_active=True, is_public_demo=False))
            db.commit()
        finally:
            db.close()
        client.cookies.clear()
        login = await client.post("/auth/login", json={"email": other, "password": password})
        assert login.status_code == 200
        responses = [
            await client.get(f"/api/documents/source/{source}"),
            await client.get(f"/api/admin/documents/{doc_id}/content"),
            await client.get(f"/api/admin/documents/{doc_id}/download"),
        ]
        assert [r.status_code for r in responses] == [404, 404, 404]
        assert all(FACT not in r.text for r in responses)

    @pytest.mark.asyncio
    async def test_unauthenticated_source_request_is_rejected(self, client, store):
        response = await client.get("/api/documents/source/anything.pdf")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_deleted_document_source_is_gone(self, client, store):
        await _owner_login(client)
        source = await _owner_upload(client)
        db = SessionLocal()
        try:
            doc_id = db.query(Document).filter(Document.storage_path == source).one().id
        finally:
            db.close()
        with patch("src.backend.api.admin.RAGService") as rag_cls:
            rag_cls.return_value.vector_store = store
            deleted = await client.delete(f"/api/admin/documents/{doc_id}", headers=_csrf(client))
        assert deleted.status_code == 200, deleted.text
        await _demo_login(client, "finance")
        assert (await client.get(f"/api/documents/source/{source}")).status_code == 404


class TestDemoPersonasStayReadOnly:
    """Every probe uses a body the route accepts, so 403 is the auth check."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("identity", ["admin", "ceo", "finance"])
    async def test_demo_writes_are_refused_and_change_nothing(self, client, store, identity):
        await _owner_login(client)
        source = await _owner_upload(client)
        db = SessionLocal()
        try:
            doc_id = db.query(Document).filter(Document.storage_path == source).one().id
        finally:
            db.close()
        before_chunks = list(store.chunks)

        await _demo_login(client, identity)
        headers = _csrf(client)
        pdf = ("again.pdf", b"%PDF-1.4\nnew\n%%EOF", "application/pdf")
        probes = {
            "upload": await client.post("/api/documents/upload", headers=headers,
                                        data={"department": "general"}, files={"file": pdf}),
            "admin_upload": await client.post("/api/admin/upload-department-data",
                                              headers=headers, data={"department": "general"},
                                              files={"files": pdf}),
            "refresh": await client.post("/api/documents/refresh", headers=headers),
            "clear": await client.delete("/api/documents/clear", headers=headers),
            "delete_doc": await client.delete(f"/api/admin/documents/{doc_id}", headers=headers),
            "create_user": await client.post("/api/admin/users", headers=headers, json={
                "email": "probe@example.test", "name": "Probe", "role": "employee",
                "department": "General", "password": secrets.token_urlsafe(16)}),
            "update_user": await client.put(f"/api/admin/users/{OWNER_EMAIL}", headers=headers,
                                            json={"role": "employee"}),
            "delete_user": await client.delete(f"/api/admin/users/{OWNER_EMAIL}",
                                               headers=headers),
            "toggle_status": await client.patch(
                f"/api/admin/users/{OWNER_EMAIL}/toggle-status", headers=headers,
                json={"is_active": False}),
        }
        codes = {name: r.status_code for name, r in probes.items()}
        assert codes == {name: 403 for name in probes}, codes
        # Admin personas hit the demo guard; the finance persona is stopped
        # one step earlier on admin-only routes.
        for name, response in probes.items():
            assert response.json()["detail"]["code"] in {
                "PUBLIC_DEMO_READ_ONLY", "ADMIN_REQUIRED"}, name

        assert store.chunks == before_chunks
        db = SessionLocal()
        try:
            owner = db.query(User).filter(User.email == OWNER_EMAIL).one()
            assert owner.is_active and owner.role == "admin"
            assert db.query(Document).filter(Document.id == doc_id).one().is_active
            assert not db.query(User).filter(User.email == "probe@example.test").first()
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_same_toggle_body_succeeds_for_the_owner(self, client):
        """Guards the probe above: the identical body is accepted for a real
        admin, so the demo 403 is an authorization result, not a hidden 422."""
        target = f"disposable-{uuid.uuid4().hex[:8]}@example.test"
        db = SessionLocal()
        try:
            db.add(User(id=target, username=target, email=target, hashed_password="x",
                        full_name="Disposable", role="employee",
                        tenant_id=settings.demo_tenant_id, department="General",
                        is_active=True, is_public_demo=False))
            db.commit()
        finally:
            db.close()
        await _owner_login(client)
        response = await client.patch(f"/api/admin/users/{target}/toggle-status",
                                      headers=_csrf(client), json={"is_active": False})
        assert response.status_code == 200, response.text
        db = SessionLocal()
        try:
            assert db.query(User).filter(User.email == target).one().is_active is False
        finally:
            db.close()


def test_source_passages_filter_matches_retrieval():
    from src.backend.services.vector_store import VectorStore
    instance = object.__new__(VectorStore)
    instance.collection = MagicMock()
    instance.collection.get.return_value = {
        "documents": ["second", "first"],
        "metadatas": [{"chunk_id": 1}, {"chunk_id": 0}],
    }
    passages = VectorStore.get_source_passages(instance, "a.pdf", "tenant_demo", ["finance"])
    assert passages == ["first", "second"]
    where = instance.collection.get.call_args.kwargs["where"]
    assert where == {"$and": [{"tenant_id": "tenant_demo"}, {"source": "a.pdf"},
                              {"department": {"$in": ["finance"]}}]}
    assert VectorStore.get_source_passages(instance, "a.pdf", "tenant_demo", []) == []


# ---------------------------------------------------------------------------
# Owner lifecycle: replace, delete, bundled samples, startup tombstones
# ---------------------------------------------------------------------------

async def _owner_upload_md(client, text, name="lifecycle.md", department="finance"):
    response = await client.post(
        "/api/admin/upload-department-data", headers=_csrf(client),
        data={"department": department},
        files={"files": (name, text.encode(), "text/markdown")},
    )
    assert response.status_code == 200 and response.json()["success"], response.text
    info = response.json()["results"][0]["file_info"]
    return info["document_id"], info["saved_filename"]


def _row(doc_id):
    db = SessionLocal()
    try:
        row = db.query(Document).filter(Document.id == doc_id).one()
        db.expunge(row)
        return row
    finally:
        db.close()


@pytest.fixture
def sample_corpus(tmp_path, store):
    """A disposable bundled sample in a temp corpus dir, never the real one."""
    from datetime import datetime
    name = f"disposable_sample_{uuid.uuid4().hex[:8]}.md"
    text = "Bundled sample says the Orion fee is 11 percent."
    (tmp_path / name).write_text(text, encoding="utf-8")
    doc_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(Document(id=doc_id, filename=name, tenant_id=settings.demo_tenant_id,
                        storage_path=name, content_type="text/markdown", file_size=len(text),
                        department="general", uploaded_by="test-disposable-sample",
                        processed_at=datetime.utcnow(),
                        is_active=True, is_protected_demo=True, meta={}))
        db.commit()
    finally:
        db.close()
    store.chunks.append((text, {"source": name, "tenant_id": settings.demo_tenant_id,
                                "department": "general", "chunk_id": 0}))
    with patch("src.backend.api.admin.get_demo_documents_path", return_value=str(tmp_path)):
        yield {"id": doc_id, "name": name, "path": tmp_path / name}
    db = SessionLocal()
    try:
        db.query(Document).filter(Document.id == doc_id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


async def _login_disposable(client, role, tenant_id, department):
    email = f"{role}-{uuid.uuid4().hex[:8]}@example.test"
    password = secrets.token_urlsafe(24)
    db = SessionLocal()
    try:
        db.add(User(id=email, username=email, email=email,
                    hashed_password=get_password_hash(password), full_name="Disposable",
                    role=role, tenant_id=tenant_id, department=department,
                    is_active=True, is_public_demo=False))
        db.commit()
    finally:
        db.close()
    client.cookies.clear()
    response = await client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


class TestOwnerDocumentLifecycle:
    @pytest.mark.asyncio
    async def test_upload_replace_delete_moves_answers_and_sources(self, client, store):
        await _owner_login(client)
        old_id, old_source = await _owner_upload_md(
            client, f"Lifecycle {uuid.uuid4().hex}: the Vega cutoff is day 9.")

        response = await client.post(
            f"/api/admin/documents/{old_id}/replace", headers=_csrf(client),
            files={"file": ("lifecycle-v2.md",
                            f"Lifecycle {uuid.uuid4().hex}: the Vega cutoff is day 12.".encode(),
                            "text/markdown")},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        new_id = body["document_id"]
        assert body["department"] == "finance" and body["file_removed"] is True

        old, new = _row(old_id), _row(new_id)
        assert old.is_active is False and old.meta["replaced_by"] == new_id
        assert new.is_active is True and new.department == "finance"
        assert new.meta["replaces"] == old_id
        texts = " ".join(t for t, m in store.chunks if m["tenant_id"] == settings.demo_tenant_id)
        assert "day 12" in texts and "day 9" not in texts  # no stale chunks

        await _demo_login(client, "finance")
        assert (await client.get(f"/api/documents/source/{old_source}")).status_code == 404
        current = await client.get(f"/api/documents/source/{new.storage_path}")
        assert current.status_code == 200 and "day 12" in current.text

        client.cookies.clear()
        await _owner_login(client)
        deleted = await client.delete(f"/api/admin/documents/{new_id}", headers=_csrf(client))
        assert deleted.status_code == 200 and deleted.json()["file_removed"] is True
        assert not [m for _, m in store.chunks if m["source"] == new.storage_path]
        listing = await client.get("/api/admin/documents")
        assert all(d["id"] not in {old_id, new_id} for d in listing.json())
        await _demo_login(client, "finance")
        assert (await client.get(f"/api/documents/source/{new.storage_path}")).status_code == 404

    @pytest.mark.asyncio
    async def test_failed_old_version_removal_withdraws_the_new_version(self, client, store):
        await _owner_login(client)
        old_id, old_source = await _owner_upload_md(client, f"Rollback {uuid.uuid4().hex} v1")
        store.fail_sources.add(old_source)
        response = await client.post(
            f"/api/admin/documents/{old_id}/replace", headers=_csrf(client),
            files={"file": ("v2.md", f"Rollback {uuid.uuid4().hex} v2".encode(), "text/markdown")},
        )
        store.fail_sources.clear()
        assert response.status_code == 503
        assert "original document is unchanged" in response.json()["detail"]
        assert _row(old_id).is_active is True
        texts = [t for t, m in store.chunks if m["tenant_id"] == settings.demo_tenant_id]
        assert any(" v1" in t for t in texts) and not any(" v2" in t for t in texts)

    @pytest.mark.asyncio
    async def test_failed_vector_delete_changes_nothing(self, client, store):
        await _owner_login(client)
        doc_id, source = await _owner_upload_md(client, f"Partial {uuid.uuid4().hex}")
        store.fail_sources.add(source)
        response = await client.delete(f"/api/admin/documents/{doc_id}", headers=_csrf(client))
        store.fail_sources.clear()
        assert response.status_code == 503
        assert _row(doc_id).is_active is True


class TestBundledSamples:
    @pytest.mark.asyncio
    async def test_owner_deletes_a_bundled_sample_without_touching_its_file(
            self, client, store, sample_corpus):
        await _owner_login(client)
        response = await client.delete(f"/api/admin/documents/{sample_corpus['id']}",
                                       headers=_csrf(client))
        assert response.status_code == 200, response.text
        assert response.json()["bundled_sample"] is True
        assert response.json()["file_removed"] is False
        row = _row(sample_corpus["id"])
        assert row.is_active is False and "retired_at" in row.meta
        assert sample_corpus["path"].is_file()  # packaged source file is kept
        assert not [m for _, m in store.chunks if m["source"] == sample_corpus["name"]]
        await _demo_login(client, "general")
        assert (await client.get(f"/api/documents/source/{sample_corpus['name']}")).status_code == 404

    @pytest.mark.asyncio
    async def test_owner_replaces_a_bundled_sample(self, client, store, sample_corpus):
        await _owner_login(client)
        response = await client.post(
            f"/api/admin/documents/{sample_corpus['id']}/replace", headers=_csrf(client),
            files={"file": ("orion.md", f"Orion fee {uuid.uuid4().hex} is 14 percent.".encode(),
                            "text/markdown")},
        )
        assert response.status_code == 200, response.text
        assert _row(sample_corpus["id"]).is_active is False
        new = _row(response.json()["document_id"])
        assert new.department == "general" and new.is_protected_demo is False
        texts = " ".join(t for t, m in store.chunks if m["tenant_id"] == settings.demo_tenant_id)
        assert "14 percent" in texts and "11 percent" not in texts

    @pytest.mark.asyncio
    @pytest.mark.parametrize("identity", ["admin", "ceo"])
    async def test_demo_personas_cannot_delete_or_replace_samples(
            self, client, store, sample_corpus, identity):
        await _demo_login(client, identity)
        headers = _csrf(client)
        responses = [
            await client.delete(f"/api/admin/documents/{sample_corpus['id']}", headers=headers),
            await client.post(f"/api/admin/documents/{sample_corpus['id']}/replace", headers=headers,
                              files={"file": ("x.md", b"Valid replacement text body.", "text/markdown")}),
        ]
        assert [r.status_code for r in responses] == [403, 403]
        assert all(r.json()["detail"]["code"] == "PUBLIC_DEMO_READ_ONLY" for r in responses)
        assert _row(sample_corpus["id"]).is_active is True

    @pytest.mark.asyncio
    async def test_other_tenant_admin_cannot_touch_samples(self, client, store, sample_corpus):
        await _login_disposable(client, "admin", "tenant_beta", "IT")
        headers = _csrf(client)
        codes = [
            (await client.delete(f"/api/admin/documents/{sample_corpus['id']}", headers=headers)).status_code,
            (await client.post(f"/api/admin/documents/{sample_corpus['id']}/replace", headers=headers,
                               files={"file": ("x.md", b"Valid replacement text body.",
                                               "text/markdown")})).status_code,
        ]
        assert codes == [404, 404]
        assert _row(sample_corpus["id"]).is_active is True

    @pytest.mark.asyncio
    async def test_non_demo_c_level_cannot_manage_samples(self, client, store, sample_corpus):
        await _login_disposable(client, "c_level", settings.demo_tenant_id, "Executive")
        response = await client.delete(f"/api/admin/documents/{sample_corpus['id']}",
                                       headers=_csrf(client))
        assert response.status_code == 403
        assert _row(sample_corpus["id"]).is_active is True


def test_startup_indexing_skips_tombstoned_samples(tmp_path):
    """A deleted/replaced sample must not be re-indexed by the next startup."""
    from src.backend.services.rag_service import RAGService
    from src.backend.utils.document_processor import DocumentProcessor

    create_tables()
    retired_name, live_name = "demo_company_policies.md", "demo_employee_handbook.md"
    body = "Synthetic sample text that is long enough to become one indexed chunk of content."
    for name in (retired_name, live_name):
        (tmp_path / name).write_text(f"# {name}\n\n{body}", encoding="utf-8")

    def set_active(value):
        db = SessionLocal()
        try:
            row = db.query(Document).filter(Document.tenant_id == settings.demo_tenant_id,
                                            Document.storage_path == retired_name).one()
            previous = row.is_active
            row.is_active = value
            db.commit()
            return previous
        finally:
            db.close()

    was_active = set_active(False)
    try:
        service = object.__new__(RAGService)
        service.vector_store = FakeVectorStore()
        service.document_processor = DocumentProcessor()
        with patch("src.config.settings.get_demo_documents_path", return_value=str(tmp_path)):
            RAGService._ensure_public_demo_corpus(service)
        sources = {m["source"] for _, m in service.vector_store.chunks}
        assert live_name in sources
        assert retired_name not in sources
    finally:
        set_active(was_active)
