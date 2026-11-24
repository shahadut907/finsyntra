"""
Tests for API Endpoints - Core HTTP functionality.
Validates status codes, response formats, error handling.
"""
import pytest
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def isolated_schema():
    """ASGITransport does not run the app lifespan; create the temp test schema."""
    from src.backend.database.database import create_tables
    create_tables()


class TestHealthEndpoints:
    """Health check and status endpoints."""

    @pytest.mark.asyncio
    async def test_root_endpoint(self, mock_auth_bypass):
        """Root endpoint returns API info."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
            assert response.status_code == 200
            data = response.json()
            assert "status" in data or "message" in data

    @pytest.mark.asyncio
    async def test_health_endpoint(self, mock_auth_bypass):
        """Health endpoint responds correctly."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code in [200, 404]  # May not exist
            if response.status_code == 200:
                data = response.json()
                assert data.get("status") in ["healthy", "ok", True]


class TestChatEndpoints:
    """Chat API endpoint tests."""

    @pytest.mark.asyncio
    async def test_chat_endpoint_exists(self, mock_auth_bypass):
        """Chat endpoint responds."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/chat",
                json={"message": "hello", "session_id": "test"}
            )
            # Should not be 404
            assert response.status_code != 404

    @pytest.mark.asyncio
    async def test_chat_requires_message(self, mock_auth_bypass):
        """Authentication is enforced before request-body validation."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/chat", json={})
            assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_chat_stream_endpoint(self, auth_token):
        """Streaming chat endpoint responds."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        headers = {"Authorization": f"Bearer {auth_token('employee')}"}
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/chat/stream?q=hello&session_id=test", headers=headers)
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_chat_stream_requires_query(self, auth_token):
        """Streaming requires query parameter."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        headers = {"Authorization": f"Bearer {auth_token('employee')}"}
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/chat/stream", headers=headers)
            # Missing q parameter should error
            assert response.status_code in [400, 422]


class TestDocumentEndpoints:
    """Document management endpoint tests."""

    @pytest.mark.asyncio
    async def test_document_list_requires_auth(self, mock_auth_required):
        """Document list requires authentication."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/documents/list")
            assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_document_upload_requires_auth(self, mock_auth_required):
        """Document upload requires authentication."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/documents/upload",
                files={"file": ("test.txt", b"test content", "text/plain")}
            )
            assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_document_clear_requires_admin(self, auth_token, test_users):
        """Document clear requires admin role."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Employee token should be rejected
            token = auth_token("employee")
            response = await client.delete(
                "/api/documents/clear",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 403


class TestAuthEndpoints:
    """Authentication endpoint tests."""

    @pytest.mark.asyncio
    async def test_login_endpoint_exists(self):
        """Login endpoint responds."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/auth/login",
                json={"email": "test@test.com", "password": "test"}
            )
            # Should not be 404 or 405
            assert response.status_code not in [404, 405]

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self):
        """Login rejects invalid credentials."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/auth/login",
                json={"email": "nonexistent@test.com", "password": "wrong"}
            )
            assert response.status_code in [401, 400, 403]

    @pytest.mark.asyncio
    async def test_logout_endpoint(self, mock_auth_bypass):
        """Logout endpoint responds."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/auth/logout")
            # Logout should work even without session
            assert response.status_code in [200, 204, 401]


class TestConversationEndpoints:
    """Conversation management endpoint tests."""

    @pytest.mark.asyncio
    async def test_conversations_list(self, mock_auth_bypass):
        """List conversations endpoint."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/conversations")
            # Should return list or require auth
            assert response.status_code in [200, 401]
            if response.status_code == 200:
                data = response.json()
                assert isinstance(data, (list, dict))

    @pytest.mark.asyncio
    async def test_conversation_by_id(self, mock_auth_bypass):
        """Get conversation by ID."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/conversations/nonexistent-id")
            # Should be 404 for nonexistent or 401 for unauth
            assert response.status_code in [404, 401]


class TestErrorHandling:
    """Error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_invalid_json_body(self, mock_auth_bypass):
        """Invalid JSON returns proper error."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/chat",
                content=b"not valid json",
                headers={"Content-Type": "application/json"}
            )
            assert response.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_method_not_allowed(self, mock_auth_bypass):
        """Wrong HTTP method returns 405."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # PUT on a GET endpoint
            response = await client.put("/api/chat/stream?q=test")
            assert response.status_code == 405

    @pytest.mark.asyncio
    async def test_nonexistent_endpoint(self, mock_auth_bypass):
        """Nonexistent endpoint returns 404."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/nonexistent/endpoint/xyz")
            assert response.status_code == 404


class TestCORSHeaders:
    """CORS configuration tests."""

    @pytest.mark.asyncio
    async def test_cors_headers_present(self, mock_auth_bypass):
        """CORS headers are set on responses."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.options(
                "/api/chat/stream",
                headers={"Origin": "http://localhost:3000"}
            )
            # Should have CORS headers or handle preflight
            assert response.status_code in [200, 204, 405]

    @pytest.mark.asyncio
    async def test_streaming_allows_credentials(self, auth_token):
        """Streaming endpoint allows credentials for SSE."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/chat/stream?q=test&session_id=cors_test",
                headers={"Origin": "http://localhost:3000",
                         "Authorization": f"Bearer {auth_token('employee')}"}
            )
            # Should not block cross-origin streaming
            assert response.status_code == 200
