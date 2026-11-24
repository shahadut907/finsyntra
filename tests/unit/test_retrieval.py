import pytest

from src.backend.services.rag_service import RAGService
from src.config.roles import Role


@pytest.fixture(scope="session", autouse=True)
def load_documents_once():
    """Load documents into the vector store once for the entire test session."""
    rag = RAGService()
    # Load docs only if collection is empty to save time during CI
    stats = rag.vector_store.get_collection_stats()
    if stats.get("total_documents", 0) == 0:
        rag.load_documents("src/data/raw")
    return rag


def _assert_retrieval(query: str, role: Role, rag: RAGService):
    results = rag._search_documents_gpu_optimized(query=query, user_role=role, accessible_docs=[], limit=3)
    assert len(results) > 0, f"No documents retrieved for query='{query}' and role='{role.value}'"


@pytest.mark.parametrize(
    "query, role",
    [
        ("What is the company vacation policy?", Role.EMPLOYEE),
        ("Provide the latest financial summary", Role.FINANCE),
        ("Explain the steps for onboarding a new employee", Role.HR),
        ("List current engineering projects", Role.ENGINEERING),
        ("Show recent marketing campaign metrics", Role.MARKETING),
        ("Tell me about Tanvir", Role.HR),
        ("Provide details on Prince", Role.HR),
    ],
)
def test_retrieval_queries(query, role, load_documents_once):
    _assert_retrieval(query, role, load_documents_once) 