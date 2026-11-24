"""Wave 3: an unclassified bundled document must not gain broad access.

The document processors default an unknown filename to Department.GENERAL.
That is correct for authenticated uploads (the request's validated department
overwrites it) but unsafe for the bundled corpus, where it silently makes an
unknown file readable by every role. Wave 2 showed the real consequence:
`test_financial_*.txt` were indexed as `general`, so `employee@finsolve.com`
retrieved revenue figures it should never have seen.

Bootstrap indexing is now fail-closed. These tests pin that.
"""
import uuid

import pytest

from src.config.roles import (
    Department,
    Role,
    get_bootstrap_department,
    is_bootstrap_classified,
)
from src.backend.services.rag_service import RAGService
from src.backend.services.vector_store import VectorStore
from src.backend.utils.document_processor import DocumentChunk
from tests.conftest import reset_vector_store_singleton

ACME = "tenant_acme"


def chunk(source, content="body text", department=None, chunk_id=0):
    meta = {"source": source, "chunk_id": chunk_id, "doc_type": "report",
            "content_type": "text",
            "department": department if department is not None else Department.GENERAL}
    return DocumentChunk(content, meta)


class TestBootstrapDepartmentPolicy:
    def test_known_finance_file_maps_to_finance(self):
        assert get_bootstrap_department("financial_summary.md") is Department.FINANCE

    def test_known_hr_file_maps_to_hr(self):
        assert get_bootstrap_department("sample_hr_data.csv") is Department.HR

    def test_known_general_files_map_to_general(self):
        assert get_bootstrap_department("employee_handbook.md") is Department.GENERAL
        assert get_bootstrap_department("company_policies.md") is Department.GENERAL

    def test_known_executive_file_maps_to_executive(self):
        assert get_bootstrap_department("strategic_plan_2025_2027.md") is Department.EXECUTIVE

    @pytest.mark.parametrize("name", [
        "test_financial_20260203_200330.txt",   # the real Wave 2 offender
        "newsletter-subscribers-2026-02-04_20260210_024848.csv",
        "unknown_document.md",
        "salary_bands_confidential.csv",
        "board_minutes.pdf",
    ])
    def test_unknown_file_is_unclassified(self, name):
        assert get_bootstrap_department(name) is None
        assert not is_bootstrap_classified(name)

    def test_classification_is_not_keyword_guessed(self):
        """A 'finance'-looking filename must not be inferred as finance."""
        for name in ("finance_secret.md", "hr_payroll.csv", "executive_notes.md"):
            assert get_bootstrap_department(name) is None


class TestBootstrapChunkFiltering:
    def test_unclassified_chunks_are_dropped(self):
        kept = RAGService._filter_classified_chunks([
            chunk("financial_summary.md"),
            chunk("test_financial_20260203_200330.txt"),
            chunk("unknown_document.md"),
        ])
        sources = [c.metadata["source"] for c in kept]
        assert sources == ["financial_summary.md"]

    def test_kept_chunks_get_the_configured_department(self):
        """Department comes from configuration, not from the processor default."""
        kept = RAGService._filter_classified_chunks([
            chunk("financial_summary.md", department=Department.GENERAL),  # wrong default
            chunk("sample_hr_data.csv", department=Department.GENERAL),
        ])
        got = {c.metadata["source"]: c.metadata["department"] for c in kept}
        assert got["financial_summary.md"] is Department.FINANCE
        assert got["sample_hr_data.csv"] is Department.HR

    def test_all_unclassified_yields_empty(self):
        assert RAGService._filter_classified_chunks([
            chunk("a_test_file.txt"), chunk("another.txt")]) == []

    def test_empty_input_is_safe(self):
        assert RAGService._filter_classified_chunks([]) == []


class TestUnknownFileCannotBecomeEmployeeReadable:
    """End-to-end: the Wave 2 failure mode must be impossible."""

    @pytest.fixture
    def store(self, tmp_path):
        path = tmp_path / "chroma_db"
        path.mkdir(parents=True, exist_ok=True)
        reset_vector_store_singleton()
        vs = VectorStore(collection_name="cls_%s" % uuid.uuid4().hex[:8],
                         persist_directory=str(path))
        yield vs
        reset_vector_store_singleton()

    def test_unclassified_sensitive_file_never_reaches_employee(self, store):
        raw = [
            chunk("financial_summary.md",
                  "Total Revenue: $12.5M with YoY growth of 23 percent."),
            chunk("test_financial_20260203_200330.txt",
                  "Q4 2024 Summary: Revenue was $4.5 million."),
            chunk("salary_bands_confidential.csv",
                  "Director band salary range 200000 to 260000 USD."),
        ]
        indexed = RAGService._filter_classified_chunks(raw)
        assert [c.metadata["source"] for c in indexed] == ["financial_summary.md"]

        store.add_documents(indexed, tenant_id=ACME)

        emp = store.search_documents(query="What was the revenue?",
                                     user_role=Role.EMPLOYEE,
                                     tenant_id=ACME, limit=10)
        emp_sources = {h["source"] for h in emp}
        assert "test_financial_20260203_200330.txt" not in emp_sources
        assert "salary_bands_confidential.csv" not in emp_sources
        assert "financial_summary.md" not in emp_sources, (
            "employee reached a finance-department document"
        )

        fin = store.search_documents(query="What was the revenue?",
                                     user_role=Role.FINANCE,
                                     tenant_id=ACME, limit=10)
        assert "financial_summary.md" in {h["source"] for h in fin}

    def test_upload_path_is_unaffected_by_the_bootstrap_policy(self, store):
        """Uploads supply their own validated department and must still work."""
        uploaded = chunk("arbitrary_user_upload.md",
                         "Quarterly marketing spend was 1.2 million.",
                         department="marketing")
        uploaded.metadata["tenant_id"] = ACME
        store.add_documents([uploaded], tenant_id=ACME)

        hits = store.search_documents(query="marketing spend",
                                      user_role=Role.MARKETING,
                                      tenant_id=ACME, limit=5)
        assert "arbitrary_user_upload.md" in {h["source"] for h in hits}

        emp = store.search_documents(query="marketing spend",
                                     user_role=Role.EMPLOYEE,
                                     tenant_id=ACME, limit=5)
        assert "arbitrary_user_upload.md" not in {h["source"] for h in emp}
