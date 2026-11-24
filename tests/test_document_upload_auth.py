"""
Tests for Document Upload Authentication (BUG-001)
These tests MUST FAIL before fix, PASS after fix.

BUG-001: All document endpoints have NO authentication
- POST /api/documents/upload
- POST /api/documents/refresh
- DELETE /api/documents/clear
- GET /api/documents/status
- GET /api/documents/list
"""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def mock_rag_service():
    """Mock RAG service to avoid actual vector store operations"""
    with patch('src.backend.api.document_upload.get_rag_service') as mock:
        mock_service = MagicMock()
        mock_service.vector_store.get_collection_stats.return_value = {"total_documents": 0}
        mock_service.vector_store.add_documents.return_value = True
        mock_service.force_document_refresh.return_value = {"success": True}
        mock.return_value = mock_service
        yield mock_service


@pytest.fixture
def mock_document_processor():
    """Mock document processor"""
    from src.backend.utils.document_processor import DocumentChunk
    with patch('src.backend.api.document_upload.document_processor') as mock:
        # The endpoint rejects documents that yield no chunks, so the positive
        # path needs one; auth-negative tests fail before parsing anyway.
        mock.process_markdown.return_value = [
            DocumentChunk("A paragraph long enough to be indexed as a real chunk of text.",
                          {"source": "test.md", "chunk_id": 0, "department": "general"})
        ]
        mock.process_pdf.return_value = []
        mock.process_csv.return_value = []
        yield mock


@pytest.fixture
async def app():
    """Create test app with mocked dependencies"""
    # Patch auth bypass to False
    with patch.dict(os.environ, {"BYPASS_AUTH": "false"}):
        from src.backend.api.endpoints import app
        yield app


@pytest.mark.asyncio
async def test_upload_requires_auth_no_token(app, mock_rag_service, mock_document_processor):
    """
    BUG-001: Upload endpoint should require authentication

    EXPECTED: 401 Unauthorized when no token provided
    ACTUAL (before fix): 200 OK - anyone can upload
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create a minimal test file
        files = {"file": ("test.md", b"# Test content", "text/markdown")}
        data = {"department": "general"}

        response = await client.post("/api/documents/upload", files=files, data=data)

        # MUST return 401 Unauthorized without valid token
        assert response.status_code == 401, (
            f"BUG-001: Upload endpoint accepts unauthenticated requests! "
            f"Got {response.status_code} instead of 401"
        )


@pytest.mark.asyncio
async def test_upload_requires_auth_invalid_token(app, mock_rag_service, mock_document_processor):
    """
    BUG-001: Upload should reject invalid tokens
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        files = {"file": ("test.md", b"# Test content", "text/markdown")}
        data = {"department": "general"}
        headers = {"Authorization": "Bearer invalid_token_12345"}

        response = await client.post(
            "/api/documents/upload",
            files=files,
            data=data,
            headers=headers
        )

        assert response.status_code == 401, (
            f"BUG-001: Upload accepts invalid tokens! Got {response.status_code}"
        )


@pytest.mark.asyncio
async def test_clear_requires_admin_role(app, mock_rag_service):
    """
    BUG-001: DELETE /api/documents/clear MUST require admin role

    This is CRITICAL - clearing the entire database should require admin privileges.
    EXPECTED: 401 without auth, 403 for non-admin users
    ACTUAL (before fix): 200 OK - anyone can wipe database
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test 1: No authentication
        response = await client.delete("/api/documents/clear")

        assert response.status_code == 401, (
            f"CRITICAL BUG-001: DELETE /api/documents/clear accepts unauthenticated requests! "
            f"Anyone can wipe the entire database! Got {response.status_code}"
        )


@pytest.mark.asyncio
async def test_clear_rejects_non_admin_user(app, mock_rag_service):
    """
    BUG-001: Clear endpoint should reject non-admin users
    """
    # Create a valid token for a non-admin user
    from src.backend.auth.authentication import create_access_token
    token = create_access_token({"sub": "employee@finsolve.com", "type": "access"})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {token}"}
        response = await client.delete("/api/documents/clear", headers=headers)

        assert response.status_code == 403, (
            f"BUG-001: Non-admin user can clear database! Got {response.status_code}"
        )


@pytest.mark.asyncio
async def test_refresh_requires_auth(app, mock_rag_service):
    """
    BUG-001: Refresh endpoint should require authentication
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/documents/refresh")

        assert response.status_code == 401, (
            f"BUG-001: Refresh accepts unauthenticated requests! Got {response.status_code}"
        )


@pytest.mark.asyncio
async def test_status_requires_auth(app, mock_rag_service):
    """
    BUG-001: Status endpoint should require authentication (info leakage)
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/documents/status")

        assert response.status_code == 401, (
            f"BUG-001: Status leaks information without auth! Got {response.status_code}"
        )


@pytest.mark.asyncio
async def test_list_requires_auth(app, mock_rag_service):
    """
    BUG-001: List endpoint should require authentication (info leakage)
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/documents/list")

        assert response.status_code == 401, (
            f"BUG-001: List leaks document inventory without auth! Got {response.status_code}"
        )


@pytest.mark.asyncio
async def test_upload_accepts_valid_admin_token(app, mock_rag_service, mock_document_processor):
    """
    Positive test: Upload should work with valid admin token
    """
    from src.backend.auth.authentication import create_access_token
    token = create_access_token({"sub": "admin@finsolve.com", "type": "access"})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Chunks of 50 characters or fewer are not indexed by design; use a real paragraph.
        files = {"file": ("test.md", b"# Test content\n\nThis paragraph is long enough to be indexed as a real chunk.", "text/markdown")}
        data = {"department": "general"}
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            "/api/documents/upload",
            files=files,
            data=data,
            headers=headers
        )

        # Should succeed with valid admin token
        assert response.status_code in [200, 201], (
            f"Valid admin token rejected! Got {response.status_code}: {response.text}"
        )
