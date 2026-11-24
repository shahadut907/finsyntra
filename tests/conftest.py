"""
Pytest fixtures for FinSyntra RAG testing.
Provides mocked services, test users, and isolated database.

Data isolation (temp SQLite / temp Chroma / temp document dir) is configured by
the ROOT conftest.py, which pytest imports before this file. See that module for
why the redirection has to happen at import time rather than in a fixture.
"""
import pytest
import asyncio
import sys
import os
import uuid
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Dict, Any, AsyncIterator

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Isolation primitives owned by the root conftest.
from conftest import (  # noqa: E402
    TEST_SANDBOX,
    TEST_CHROMA_PATH,
    TEST_RAW_PATH,
    DEV_CHROMA_PATH,
    DEV_DB_PATH,
    DEV_RAW_PATH,
    assert_not_dev_chroma,
    assert_not_dev_db,
    assert_not_dev_raw,
    is_dev_path,
)


@pytest.fixture(autouse=True)
def _reset_demo_usage_state():
    """Daily demo counters live in the shared per-process test database; every
    test starts from a clean allowance and with no active chat leases."""
    def _clear():
        try:
            from sqlalchemy import inspect as _inspect
            from src.backend.database import database
            from src.backend.services import demo_usage
            demo_usage.reset_for_tests()
            with database.engine.begin() as conn:
                if "demo_usage_counters" in _inspect(conn).get_table_names():
                    conn.execute(database.DemoUsageCounter.__table__.delete())
        except Exception:
            pass
    _clear()
    yield
    _clear()


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Data-isolation fixtures
# ---------------------------------------------------------------------------

def reset_vector_store_singleton():
    """Drop the process-wide VectorStore singleton.

    VectorStore.__new__ caches one instance and __init__ early-returns once
    `_initialized` is truthy, so the FIRST construction in a process pins the
    Chroma path forever. Clearing both class attributes lets the next
    construction pick up a different (temporary) directory.
    """
    from src.backend.services.vector_store import VectorStore
    VectorStore._instance = None
    VectorStore._initialized = False


@pytest.fixture(scope="session", autouse=True)
def _isolated_schema():
    """Create the (temporary, isolated) schema and seed identities once.

    ASGITransport does not run the app lifespan, so without this any test
    file run on its own hit "no such table" unless an earlier file happened
    to call create_tables().
    """
    from src.backend.database.database import create_tables
    create_tables()
    yield


@pytest.fixture(autouse=True)
def _fresh_rate_limiter():
    """Each test starts with empty rate-limit buckets.

    The limiter is process-wide and every TestClient request shares one client
    address, so without this a long run trips the 60/min bucket and later,
    unrelated tests see 429s. Tests that exercise limiting fill the bucket
    themselves within the test.
    """
    from src.backend.middleware.security import rate_limiter
    rate_limiter.reset()
    yield


def reset_rag_service_singleton():
    """Drop the process-wide RAGService singleton (same pattern as above)."""
    from src.backend.services.rag_service import RAGService
    RAGService._instance = None
    RAGService._initialized = False


@pytest.fixture
def isolated_chroma_dir(tmp_path):
    """A throwaway Chroma directory, proven not to be the development store."""
    path = tmp_path / "chroma_db"
    path.mkdir(parents=True, exist_ok=True)
    assert_not_dev_chroma(path, "allocate a test fixture at")
    return str(path)


@pytest.fixture
def isolated_vector_store(isolated_chroma_dir):
    """A real VectorStore bound to a temporary directory and unique collection.

    Use this anywhere a test needs genuine Chroma behaviour. Destructive calls
    such as clear_collection() are safe here and are additionally screened by
    the fail-closed guard installed in the root conftest.
    """
    from src.backend.services.vector_store import VectorStore

    reset_vector_store_singleton()
    collection = "test_%s" % uuid.uuid4().hex[:12]
    store = VectorStore(collection_name=collection,
                        persist_directory=isolated_chroma_dir)

    # Belt and braces: prove the instance really is isolated before use.
    assert not is_dev_path(store.persist_directory, DEV_CHROMA_PATH), (
        "isolated_vector_store resolved to the development Chroma directory"
    )

    yield store

    try:
        store.clear_collection()
    except Exception:
        pass
    reset_vector_store_singleton()


@pytest.fixture
def isolated_raw_docs(tmp_path):
    """A throwaway document directory standing in for src/data/raw."""
    path = tmp_path / "raw_docs"
    path.mkdir(parents=True, exist_ok=True)
    assert_not_dev_raw(path, "allocate a test fixture at")
    return path


@pytest.fixture
def dev_data_paths():
    """Expose the protected development paths to tests that assert on them."""
    return {
        "db": DEV_DB_PATH,
        "chroma": DEV_CHROMA_PATH,
        "raw": DEV_RAW_PATH,
        "sandbox": TEST_SANDBOX,
    }


@pytest.fixture
def test_users() -> Dict[str, Dict[str, Any]]:
    """Test users with different roles and tenants."""
    return {
        "employee": {
            "id": "emp@test.com",
            "email": "emp@test.com",
            "name": "Test Employee",
            "role": "employee",
            "department": "General",
            "tenant_id": "tenant1",
            "organization_id": "tenant1"
        },
        "finance": {
            "id": "fin@test.com",
            "email": "fin@test.com",
            "name": "Finance Lead",
            "role": "finance",
            "department": "Finance",
            "tenant_id": "tenant1",
            "organization_id": "tenant1"
        },
        "c_level": {
            "id": "ceo@test.com",
            "email": "ceo@test.com",
            "name": "CEO",
            "role": "c_level",
            "department": "Executive",
            "tenant_id": "tenant1",
            "organization_id": "tenant1"
        },
        "admin": {
            "id": "admin@test.com",
            "email": "admin@test.com",
            "name": "Admin",
            "role": "admin",
            "department": "IT",
            "tenant_id": "tenant1",
            "organization_id": "tenant1",
            "is_admin": True
        },
        "other_tenant": {
            "id": "other@test.com",
            "email": "other@test.com",
            "name": "Other Tenant User",
            "role": "employee",
            "department": "General",
            "tenant_id": "tenant2",
            "organization_id": "tenant2"
        },
    }


@pytest.fixture
def mock_ollama():
    """Mock Ollama LLM to avoid GPU dependency."""
    mock = MagicMock()

    async def mock_generate(*args, **kwargs):
        """Simulate streaming response."""
        yield {"content": "Test response from Ollama. "}
        yield {"content": "This is mocked."}

    mock.generate = mock_generate
    return mock


@pytest.fixture
def mock_chroma():
    """Mock ChromaDB with in-memory collection."""
    mock = MagicMock()

    # Mock query response
    mock.query.return_value = {
        "documents": [["Test document content about Q4 revenue."]],
        "metadatas": [[{"source": "test.md", "department": "general", "tenant_id": "tenant1"}]],
        "distances": [[0.3]]  # Low distance = high similarity
    }

    mock.count.return_value = 100
    mock.get.return_value = {
        "ids": [],
        "documents": [],
        "metadatas": []
    }

    return mock


@pytest.fixture
def mock_vector_store(mock_chroma):
    """Mock VectorStore with controlled search results."""
    with patch('src.backend.services.vector_store.VectorStore') as MockVS:
        mock_instance = MagicMock()
        mock_instance.collection = mock_chroma
        mock_instance._initialized = True
        mock_instance.device = "cpu"
        mock_instance.cuda_available = False

        def mock_search(query, user_role=None, tenant_id="default", limit=5, **kwargs):
            """Return test documents filtered by tenant."""
            # Simulate tenant isolation
            if tenant_id == "tenant1":
                return [
                    {
                        "content": "Q4 2024 revenue was $4.5 million.",
                        "metadata": {"source": "financial_summary.md", "department": "finance", "tenant_id": "tenant1"},
                        "similarity": 0.85,
                        "source": "financial_summary.md"
                    },
                    {
                        "content": "Employee handbook section on PTO.",
                        "metadata": {"source": "employee_handbook.md", "department": "general", "tenant_id": "tenant1"},
                        "similarity": 0.72,
                        "source": "employee_handbook.md"
                    }
                ][:limit]
            else:
                # Different tenant gets different docs
                return [
                    {
                        "content": "Tenant 2 confidential data.",
                        "metadata": {"source": "tenant2_data.md", "department": "general", "tenant_id": "tenant2"},
                        "similarity": 0.80,
                        "source": "tenant2_data.md"
                    }
                ][:limit]

        mock_instance.search_documents = mock_search
        mock_instance.get_collection_stats.return_value = {"total_documents": 100}
        mock_instance.add_documents.return_value = True

        MockVS.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_rag_service(mock_vector_store):
    """Mock RAGService with controlled responses."""
    with patch('src.backend.services.rag_service.RAGService') as MockRAG:
        mock_instance = MagicMock()
        mock_instance.vector_store = mock_vector_store
        mock_instance._initialized = True
        mock_instance.cuda_available = False

        def mock_process_query(query, user_id, tenant_id="default", **kwargs):
            """Return controlled RAG response."""
            # Check for empty result triggers
            if "nonexistent" in query.lower() or "xyz" in query.lower():
                return {
                    "success": True,
                    "response": "I couldn't find documents matching your query.",
                    "sources": [],
                    "documents_found": 0,
                    "used_rag": False
                }

            return {
                "success": True,
                "response": "Based on the documents, Q4 2024 revenue was $4.5 million.",
                "sources": [{"filename": "financial_summary.md", "department": "finance"}],
                "documents_found": 2,
                "used_rag": True
            }

        mock_instance.process_query = mock_process_query
        mock_instance.is_ready.return_value = True

        MockRAG.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_auth_bypass():
    """Temporarily enable auth bypass for testing."""
    original = os.environ.get("BYPASS_AUTH")
    os.environ["BYPASS_AUTH"] = "true"
    yield
    if original:
        os.environ["BYPASS_AUTH"] = original
    else:
        os.environ.pop("BYPASS_AUTH", None)


@pytest.fixture
def mock_auth_required():
    """Ensure auth is required (no bypass)."""
    original = os.environ.get("BYPASS_AUTH")
    os.environ["BYPASS_AUTH"] = "false"
    yield
    if original:
        os.environ["BYPASS_AUTH"] = original
    else:
        os.environ.pop("BYPASS_AUTH", None)


def _ensure_test_user_row(user: Dict[str, Any]) -> None:
    """Auth resolves identity from the DB (server-authoritative), so a minted
    token only works if the matching user row exists. Seed it into the isolated
    test database; the password hash is unusable, so it cannot be logged into."""
    from src.backend.database.database import SessionLocal, User, create_tables

    create_tables()
    db = SessionLocal()
    try:
        email = user["email"].lower()
        row = db.query(User).filter(User.email == email).first()
        if row is None:
            row = User(id=user["id"], username=email, email=email, hashed_password="!unusable")
            db.add(row)
        row.full_name = user.get("name")
        row.role = user["role"]
        row.tenant_id = user["tenant_id"]
        row.department = user.get("department")
        row.is_active = True
        db.commit()
    finally:
        db.close()


@pytest.fixture
def auth_token(test_users):
    """Generate valid JWT token for testing."""
    from src.backend.auth.authentication import create_access_token

    def _make_token(user_key: str = "employee"):
        user = test_users[user_key]
        _ensure_test_user_row(user)
        return create_access_token({
            "sub": user["email"],
            "type": "access",
            "role": user["role"],
            "tenant_id": user["tenant_id"]
        })

    return _make_token


@pytest.fixture
async def async_client(mock_auth_bypass):
    """FastAPI test client with mocked dependencies."""
    from httpx import AsyncClient, ASGITransport

    # Import app after setting up mocks
    from src.backend.api.endpoints import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
