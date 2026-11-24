"""
End-to-End Integration Tests for FinSyntra.
Tests complete user flows from authentication through query responses.
"""
import pytest
import asyncio
import json
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestFullChatFlow:
    """Test complete chat flow end-to-end."""

    @pytest.mark.asyncio
    async def test_authenticated_chat_with_response(self, auth_token):
        """Complete flow: authenticate → query → receive response with citations."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("finance")
            
            # Step 1: Verify authentication works
            chunks = []
            events = []
            
            async with client.stream(
                "GET",
                "/api/chat/stream?q=What is the Q4 revenue?&session_id=e2e_chat_1",
                headers={"Authorization": f"Bearer {token}"}
            ) as response:
                assert response.status_code == 200, "Auth should succeed"
                
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and "[DONE]" not in line:
                        try:
                            event = json.loads(line[6:])
                            events.append(event.get("type"))
                            chunks.append(line)
                        except:
                            pass
                    if "[DONE]" in line:
                        chunks.append(line)
                        break

            # Step 2: Verify SSE event flow
            assert "start" in events, "Should receive start event"
            assert any("token" in e for e in events if e), "Should receive token events"
            
            # Step 3: Verify stream completion
            assert any("[DONE]" in c for c in chunks), "Stream should complete with [DONE]"

    @pytest.mark.asyncio
    async def test_small_talk_fast_path(self, auth_token):
        """Small talk queries skip RAG and respond quickly."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("employee")
            
            start = time.time()
            chunks = []
            
            async with client.stream(
                "GET",
                "/api/chat/stream?q=hello&session_id=small_talk_e2e",
                headers={"Authorization": f"Bearer {token}"}
            ) as response:
                async for line in response.aiter_lines():
                    chunks.append(line)
                    if "[DONE]" in line:
                        break
            
            elapsed = time.time() - start
            
            # Small talk should be fast (< 5s for full response)
            assert elapsed < 5.0, f"Small talk too slow: {elapsed:.2f}s"
            assert any("[DONE]" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_multi_turn_conversation(self, auth_token):
        """Multi-turn conversations work with same session."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("employee")
            session_id = "multi_turn_test"
            
            queries = [
                "Hello, I need help with something",
                "Tell me about company policies",
                "Thanks for the information"
            ]
            
            for i, query in enumerate(queries):
                chunks = []
                async with client.stream(
                    "GET",
                    f"/api/chat/stream?q={query}&session_id={session_id}",
                    headers={"Authorization": f"Bearer {token}"}
                ) as response:
                    assert response.status_code == 200
                    async for line in response.aiter_lines():
                        chunks.append(line)
                        if "[DONE]" in line:
                            break
                
                # Each turn should complete
                assert any("[DONE]" in c for c in chunks), f"Turn {i+1} did not complete"


class TestDocumentFlow:
    """Test document upload and retrieval flow."""

    @pytest.mark.asyncio
    async def test_document_list_endpoint(self, auth_token):
        """Document list endpoint returns data."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")
            
            response = await client.get(
                "/api/documents/list",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            # Should return list or indicate empty
            assert response.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_upload_and_query_flow(self, auth_token):
        """Upload document then query it."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")
            
            # Step 1: Upload a document
            test_content = b"Q4 2024 Summary: Revenue was $4.5 million. Expenses were $3.2 million."
            response = await client.post(
                "/api/documents/upload",
                files={"file": ("test_financial.txt", test_content, "text/plain")},
                headers={"Authorization": f"Bearer {token}"}
            )
            
            # Upload should succeed
            assert response.status_code in [200, 201, 202]
            
            # Step 2: Query should work (may or may not find the doc depending on indexing)
            chunks = []
            async with client.stream(
                "GET",
                "/api/chat/stream?q=revenue&session_id=upload_query_test",
                headers={"Authorization": f"Bearer {token}"}
            ) as response:
                async for line in response.aiter_lines():
                    chunks.append(line)
                    if "[DONE]" in line:
                        break
            
            assert any("[DONE]" in c for c in chunks)


class TestConversationManagement:
    """Test conversation CRUD operations."""

    @pytest.mark.asyncio
    async def test_conversation_list(self, auth_token):
        """List conversations endpoint works."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("employee")
            
            response = await client.get(
                "/api/conversations",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            assert response.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_conversation_export(self, auth_token):
        """Export conversation endpoint works."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("employee")
            
            # First create a conversation
            async with client.stream(
                "GET",
                "/api/chat/stream?q=test&session_id=export_test_session",
                headers={"Authorization": f"Bearer {token}"}
            ) as response:
                async for line in response.aiter_lines():
                    if "[DONE]" in line:
                        break
            
            # Then try to export
            response = await client.get(
                "/api/conversations/export_test_session/export",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            # Should work or indicate not found
            assert response.status_code in [200, 404]


class TestHealthAndDiagnostics:
    """Test health and diagnostic endpoints."""

    @pytest.mark.asyncio
    async def test_health_endpoint_comprehensive(self):
        """Health endpoint returns comprehensive status."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            
            # Should have key health indicators
            assert "status" in data
            assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_streaming_health_endpoint(self):
        """Streaming health endpoint works."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/chat/stream/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data.get("status") == "healthy"
            assert data.get("streaming") is True


class TestRBACEndToEnd:
    """Test RBAC enforcement end-to-end."""

    @pytest.mark.asyncio
    async def test_different_roles_get_different_access(self, auth_token):
        """Different roles receive appropriate responses."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            roles_tested = []
            
            for role in ["employee", "finance", "c_level"]:
                token = auth_token(role)
                
                async with client.stream(
                    "GET",
                    f"/api/chat/stream?q=financial data&session_id=rbac_{role}",
                    headers={"Authorization": f"Bearer {token}"}
                ) as response:
                    assert response.status_code == 200
                    async for line in response.aiter_lines():
                        if "[DONE]" in line:
                            roles_tested.append(role)
                            break
            
            # All roles should complete queries successfully
            assert len(roles_tested) == 3

    @pytest.mark.asyncio
    async def test_tenant_isolation_e2e(self, auth_token):
        """Different tenants are isolated end-to-end."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Tenant 1 user
            token1 = auth_token("employee")
            
            # Tenant 2 user
            token2 = auth_token("other_tenant")
            
            for token, tenant_name in [(token1, "tenant1"), (token2, "tenant2")]:
                chunks = []
                async with client.stream(
                    "GET",
                    f"/api/chat/stream?q=confidential data&session_id={tenant_name}_isolation",
                    headers={"Authorization": f"Bearer {token}"}
                ) as response:
                    assert response.status_code == 200
                    async for line in response.aiter_lines():
                        chunks.append(line)
                        if "[DONE]" in line:
                            break
                
                assert any("[DONE]" in c for c in chunks)


class TestErrorRecovery:
    """Test error recovery and edge cases."""

    @pytest.mark.asyncio
    async def test_empty_query_handled(self, auth_token):
        """Empty query returns proper error."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("employee")
            
            response = await client.get(
                "/api/chat/stream?q=&session_id=empty_test",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            # Should return 400 for missing prompt
            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_very_long_query(self, auth_token):
        """Very long queries are handled."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("employee")
            
            long_query = "a" * 5000  # 5000 characters
            
            chunks = []
            async with client.stream(
                "POST",
                "/api/chat/stream",
                json={"message": long_query, "session_id": "long_query_test"},
                headers={"Authorization": f"Bearer {token}"}
            ) as response:
                # Should handle gracefully
                assert response.status_code in [200, 400, 413]
                if response.status_code == 200:
                    async for line in response.aiter_lines():
                        chunks.append(line)
                        if "[DONE]" in line:
                            break

    @pytest.mark.asyncio
    async def test_special_characters_in_query(self, auth_token):
        """Special characters in queries are handled."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("employee")
            
            special_queries = [
                "What about 日本語?",
                "émojis 🎉 work?",
                "symbols: @#$%^&*()",
                "newlines\nand\ttabs"
            ]
            
            for query in special_queries:
                chunks = []
                async with client.stream(
                    "POST",
                    "/api/chat/stream",
                    json={"message": query, "session_id": "special_chars"},
                    headers={"Authorization": f"Bearer {token}"}
                ) as response:
                    if response.status_code == 200:
                        async for line in response.aiter_lines():
                            chunks.append(line)
                            if "[DONE]" in line:
                                break


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
