"""Wave 2: explicit tenant ownership + honest citations.

Two invariants are pinned here.

TENANCY — for every persisted chunk:
    chunk.metadata["tenant_id"] == indexing tenant == authenticated user's tenant
There is no implicit "default" tenant; ambiguity is an error, not a fallback.

CITATIONS — a source may only be cited if it actually participated in the
retrieval that produced the answer. Zero retrieval => zero sources.

All Chroma work runs in the Wave 1 sandbox.
"""
import uuid

import pytest

from src.backend.services.vector_store import VectorStore
from src.backend.utils.document_processor import DocumentChunk
from src.config.roles import Role
from tests.conftest import reset_vector_store_singleton

ACME = "tenant_acme"
BETA = "tenant_beta"
DIM = 384


def make_chunk(content, source, department="finance", tenant_id=None, chunk_id=0):
    meta = {"source": source, "chunk_id": chunk_id, "department": department,
            "doc_type": "report", "content_type": "text"}
    if tenant_id is not None:
        meta["tenant_id"] = tenant_id
    return DocumentChunk(content, meta)


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "chroma_db"
    path.mkdir(parents=True, exist_ok=True)
    reset_vector_store_singleton()
    vs = VectorStore(collection_name="tenancy_%s" % uuid.uuid4().hex[:8],
                     persist_directory=str(path))
    yield vs
    reset_vector_store_singleton()


# ---------------------------------------------------------------------------
# Tenancy contract
# ---------------------------------------------------------------------------

class TestTenantOwnershipContract:
    def test_no_tenant_anywhere_is_rejected(self, store):
        """The old code silently filed these under 'default'."""
        chunks = [make_chunk("orphan content", "orphan.md")]
        with pytest.raises(ValueError) as e:
            store.add_documents(chunks)
        assert "no implicit 'default' tenant" in str(e.value)
        assert store.collection.count() == 0

    def test_conflicting_tenant_is_rejected(self, store):
        """Metadata tenant vs argument tenant must not be silently normalised."""
        chunks = [make_chunk("conflicted", "c.md", tenant_id=BETA)]
        with pytest.raises(ValueError) as e:
            store.add_documents(chunks, tenant_id=ACME)
        assert "Tenant ownership conflict" in str(e.value)
        assert store.collection.count() == 0

    def test_tenant_from_argument_only(self, store):
        store.add_documents([make_chunk("param owned", "p.md")], tenant_id=ACME)
        metas = store.collection.get(include=["metadatas"])["metadatas"]
        assert [m["tenant_id"] for m in metas] == [ACME]

    def test_tenant_from_metadata_only(self, store):
        store.add_documents([make_chunk("meta owned", "m.md", tenant_id=ACME)])
        metas = store.collection.get(include=["metadatas"])["metadatas"]
        assert [m["tenant_id"] for m in metas] == [ACME]

    def test_matching_tenant_in_both_is_accepted(self, store):
        store.add_documents([make_chunk("agreed", "a.md", tenant_id=ACME)],
                            tenant_id=ACME)
        metas = store.collection.get(include=["metadatas"])["metadatas"]
        assert [m["tenant_id"] for m in metas] == [ACME]

    def test_blank_tenant_is_rejected(self, store):
        with pytest.raises(ValueError):
            store.add_documents([make_chunk("blank", "b.md", tenant_id="  ")],
                                tenant_id="   ")
        assert store.collection.count() == 0

    def test_no_chunk_is_written_when_one_chunk_is_invalid(self, store):
        """Validation is up-front: a bad chunk aborts the whole batch."""
        chunks = [make_chunk("ok", "ok.md", tenant_id=ACME),
                  make_chunk("bad", "bad.md")]
        with pytest.raises(ValueError):
            store.add_documents(chunks)
        assert store.collection.count() == 0, "partial write occurred"

    def test_every_persisted_chunk_has_a_tenant(self, store):
        store.add_documents(
            [make_chunk("one", "s1.md", chunk_id=0), make_chunk("two", "s2.md", chunk_id=1)],
            tenant_id=ACME,
        )
        metas = store.collection.get(include=["metadatas"])["metadatas"]
        assert metas
        assert all(m.get("tenant_id") for m in metas)
        assert all(m["tenant_id"] != "default" for m in metas)


class TestBootstrapTenant:
    def test_bootstrap_tenant_is_acme_and_explicit(self):
        from src.backend.services.rag_service import RAGService
        assert RAGService._bootstrap_tenant_id() == ACME

    def test_bootstrap_tenant_fails_loudly_when_unset(self, monkeypatch):
        from src.backend.services.rag_service import RAGService
        from src.config import settings as settings_mod
        monkeypatch.setattr(settings_mod.settings, "bootstrap_tenant_id", "", raising=False)
        with pytest.raises(ValueError) as e:
            RAGService._bootstrap_tenant_id()
        assert "refusing to fall back" in str(e.value).lower()


# ---------------------------------------------------------------------------
# Tenant-scoped retrieval
# ---------------------------------------------------------------------------

class TestTenantScopedRetrieval:
    @pytest.fixture
    def two_tenant_store(self, store):
        store.add_documents([
            make_chunk("Total revenue for Q4 2024 was 12.5 million dollars.",
                       "financial_summary.md", "finance", chunk_id=0),
            make_chunk("Employees receive 20 days of paid annual leave.",
                       "employee_handbook.md", "general", chunk_id=1),
        ], tenant_id=ACME)
        store.add_documents([
            make_chunk("Beta Corp quarterly revenue reached 3.1 million dollars.",
                       "beta_financials.md", "finance", chunk_id=0),
        ], tenant_id=BETA)
        return store

    def test_acme_retrieves_only_acme(self, two_tenant_store):
        hits = two_tenant_store.search_documents(
            query="What was the total revenue?", user_role=Role.FINANCE,
            tenant_id=ACME, limit=10)
        assert hits, "tenant_acme retrieved nothing"
        assert all(h["metadata"]["tenant_id"] == ACME for h in hits)
        assert not any("beta" in h["source"].lower() for h in hits)

    def test_beta_retrieves_only_beta(self, two_tenant_store):
        hits = two_tenant_store.search_documents(
            query="What was the total revenue?", user_role=Role.FINANCE,
            tenant_id=BETA, limit=10)
        assert hits, "tenant_beta retrieved nothing"
        assert all(h["metadata"]["tenant_id"] == BETA for h in hits)

    def test_beta_asking_about_acme_content_gets_no_acme_hits(self, two_tenant_store):
        hits = two_tenant_store.search_documents(
            query="Total revenue for Q4 2024 was 12.5 million dollars",
            user_role=Role.FINANCE, tenant_id=BETA, limit=10)
        assert all(h["metadata"]["tenant_id"] == BETA for h in hits)
        assert not any(h["source"] == "financial_summary.md" for h in hits)

    def test_department_filter_still_applies_within_tenant(self, two_tenant_store):
        """HR role must not reach finance-only documents."""
        hits = two_tenant_store.search_documents(
            query="What was the total revenue?", user_role=Role.HR,
            tenant_id=ACME, limit=10)
        assert all(h["metadata"]["department"] in ("hr", "general") for h in hits), (
            "HR retrieved a finance document: %r" % [h["source"] for h in hits]
        )

    def test_unknown_tenant_retrieves_nothing(self, two_tenant_store):
        hits = two_tenant_store.search_documents(
            query="revenue", user_role=Role.FINANCE,
            tenant_id="tenant_does_not_exist", limit=10)
        assert hits == []

    def test_default_tenant_retrieves_nothing(self, two_tenant_store):
        """The phantom 'default' tenant must own no data."""
        hits = two_tenant_store.search_documents(
            query="revenue", user_role=Role.FINANCE, tenant_id="default", limit=10)
        assert hits == []


# ---------------------------------------------------------------------------
# Citation invariants
# ---------------------------------------------------------------------------

class TestCitationInvariants:
    def test_miss_produces_no_sources(self):
        """Zero retrieval => sources == [] (was: accessible_docs[:3])."""
        from src.backend.services.rag_service import RAGService
        stub = object.__new__(RAGService)
        stub.cuda_available = False
        resp = RAGService._create_no_results_response(
            self=stub,
            query="something absent",
            user_role=Role.FINANCE,
            user_name="Tester",
            accessible_docs=["financial_summary.md", "employee_handbook.md",
                             "company_policies.md"],
        )
        assert resp["documents_found"] == 0
        assert resp["sources"] == [], (
            "fabricated citations returned on a retrieval miss: %r" % resp["sources"]
        )

    def test_rbac_accessible_but_unretrieved_docs_are_not_cited(self):
        """The exact fabrication: RBAC filename lists must never be citations."""
        from src.config.roles import get_accessible_documents
        from src.backend.services.rag_service import RAGService
        accessible = get_accessible_documents(Role.C_LEVEL)
        assert accessible, "fixture precondition: C_LEVEL should have accessible docs"
        stub = object.__new__(RAGService)
        stub.cuda_available = False
        resp = RAGService._create_no_results_response(
            self=stub,
            query="unmatched query", user_role=Role.C_LEVEL,
            user_name="CEO", accessible_docs=accessible,
        )
        assert not set(resp["sources"]) & set(accessible)

    def test_hit_produces_only_retrieved_sources(self, store):
        """Citations must be drawn from the documents actually retrieved."""
        store.add_documents([
            make_chunk("Total revenue for Q4 2024 was 12.5 million dollars.",
                       "financial_summary.md", "finance", chunk_id=0),
        ], tenant_id=ACME)
        hits = store.search_documents(
            query="What was the total revenue in Q4 2024?",
            user_role=Role.FINANCE, tenant_id=ACME, limit=5)
        assert hits, "precondition: retrieval should hit"
        cited = list(dict.fromkeys(h.get("source", "") for h in hits))
        assert cited == ["financial_summary.md"]
        retrieved_sources = {h["source"] for h in hits}
        assert set(cited).issubset(retrieved_sources)

    def test_cross_tenant_source_can_never_be_cited(self, store):
        """tenant_beta must never receive a tenant_acme citation."""
        store.add_documents([
            make_chunk("Total revenue for Q4 2024 was 12.5 million dollars.",
                       "financial_summary.md", "finance", chunk_id=0),
        ], tenant_id=ACME)
        store.add_documents([
            make_chunk("Beta Corp revenue reached 3.1 million dollars.",
                       "beta_financials.md", "finance", chunk_id=0),
        ], tenant_id=BETA)

        hits = store.search_documents(
            query="What was the total revenue in Q4 2024?",
            user_role=Role.FINANCE, tenant_id=BETA, limit=5)
        cited = {h.get("source", "") for h in hits}
        assert "financial_summary.md" not in cited
        assert all(h["metadata"]["tenant_id"] == BETA for h in hits)
