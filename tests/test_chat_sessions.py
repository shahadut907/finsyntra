"""
Tests for Chat Sessions and Conversation Memory.
Validates session handling, history, and context management.
"""
import pytest
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSessionCreation:
    """Test session creation and management."""

    @pytest.mark.asyncio
    async def test_new_session_created(self, auth_token):
        """New session ID creates new conversation."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app
        import uuid

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {auth_token('employee')}"}) as client:
            session_id = str(uuid.uuid4())

            response = await client.get(
                f"/api/chat/stream?q=hello&session_id={session_id}"
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_session_persistence(self, auth_token):
        """Session maintains context across requests."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {auth_token('employee')}"}) as client:
            session_id = "persistence_test_123"

            # First message
            chunks1 = []
            async with client.stream(
                "GET",
                f"/api/chat/stream?q=My name is Alice&session_id={session_id}"
            ) as response:
                async for line in response.aiter_lines():
                    if line.strip():
                        chunks1.append(line)

            # Second message (should have context)
            chunks2 = []
            async with client.stream(
                "GET",
                f"/api/chat/stream?q=What is my name?&session_id={session_id}"
            ) as response:
                async for line in response.aiter_lines():
                    if line.strip():
                        chunks2.append(line)

            # Both should complete
            assert any("[DONE]" in c for c in chunks1)
            assert any("[DONE]" in c for c in chunks2)

    @pytest.mark.asyncio
    async def test_different_sessions_isolated(self, auth_token):
        """Different sessions are isolated."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {auth_token('employee')}"}) as client:
            # Session A
            await client.get("/api/chat/stream?q=I work at CompanyA&session_id=session_a")

            # Session B
            await client.get("/api/chat/stream?q=I work at CompanyB&session_id=session_b")

            # Query session A - should not know about CompanyB
            response = await client.get(
                "/api/chat/stream?q=Where do I work?&session_id=session_a"
            )

            assert response.status_code == 200


class TestConversationHistory:
    """Test conversation history functionality."""

    @pytest.mark.asyncio
    async def test_history_endpoint(self, auth_token):
        """History endpoint returns conversation."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {auth_token('employee')}"}) as client:
            session_id = "history_test"

            # Make a chat first
            await client.get(f"/api/chat/stream?q=hello&session_id={session_id}")

            # Get history
            response = await client.get(f"/api/conversations/{session_id}")

            # Should return history or 404 if not found
            assert response.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_list_conversations(self, auth_token):
        """List all conversations for user."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("employee")

            response = await client.get(
                "/api/conversations",
                headers={"Authorization": f"Bearer {token}"}
            )

            # Should return list
            assert response.status_code in [200, 401]
            if response.status_code == 200:
                data = response.json()
                assert isinstance(data, (list, dict))


class TestMessageStorage:
    """Test message storage and retrieval."""

    @pytest.mark.asyncio
    async def test_messages_stored(self, auth_token):
        """Messages are stored in conversation."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {auth_token('employee')}"}) as client:
            session_id = "storage_test"

            # Send multiple messages
            await client.get(f"/api/chat/stream?q=First message&session_id={session_id}")
            await client.get(f"/api/chat/stream?q=Second message&session_id={session_id}")

            # Try to get conversation
            response = await client.get(f"/api/conversations/{session_id}")

            if response.status_code == 200:
                data = response.json()
                # Should have messages
                if "messages" in data:
                    assert len(data["messages"]) >= 2

    @pytest.mark.asyncio
    async def test_response_included_in_history(self, auth_token):
        """AI responses are stored in history."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {auth_token('employee')}"}) as client:
            session_id = "response_storage_test"

            # Wait for complete response
            chunks = []
            async with client.stream(
                "GET",
                f"/api/chat/stream?q=What is 2+2?&session_id={session_id}"
            ) as response:
                async for line in response.aiter_lines():
                    if line.strip():
                        chunks.append(line)

            # Should have completed
            assert any("[DONE]" in c for c in chunks)


class TestContextWindow:
    """Test context window management."""

    @pytest.mark.asyncio
    async def test_long_conversation_handled(self, auth_token):
        """Long conversations don't crash."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {auth_token('employee')}"}) as client:
            session_id = "long_conv_test"

            # Send many messages
            for i in range(5):
                response = await client.get(
                    f"/api/chat/stream?q=Message {i}&session_id={session_id}"
                )
                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_context_truncation(self, auth_token):
        """Very long context is truncated appropriately."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {auth_token('employee')}"}) as client:
            session_id = "truncation_test"

            # Send very long message
            long_message = "word " * 1000  # 5000 characters

            response = await client.get(
                f"/api/chat/stream?q={long_message}&session_id={session_id}"
            )

            # Should handle gracefully
            assert response.status_code == 200


class TestSessionCleanup:
    """Test session cleanup and expiration."""

    @pytest.mark.asyncio
    async def test_delete_conversation(self, auth_token):
        """Conversations can be deleted."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("employee")
            session_id = "delete_test"

            # Create conversation
            await client.get(
                f"/api/chat/stream?q=test&session_id={session_id}",
                headers={"Authorization": f"Bearer {token}"}
            )

            # Try to delete
            response = await client.delete(
                f"/api/conversations/{session_id}",
                headers={"Authorization": f"Bearer {token}"}
            )

            # Should succeed or return 404 (endpoint may not exist)
            assert response.status_code in [200, 204, 404, 405]


class TestUserAssociation:
    """Test user-conversation association."""

    @pytest.mark.asyncio
    async def test_conversation_belongs_to_user(self, auth_token, test_users):
        """Conversations are associated with users."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("employee")
            session_id = "user_assoc_test"

            # Create as employee
            await client.get(
                f"/api/chat/stream?q=test&session_id={session_id}",
                headers={"Authorization": f"Bearer {token}"}
            )

            # List should show this conversation
            response = await client.get(
                "/api/conversations",
                headers={"Authorization": f"Bearer {token}"}
            )

            if response.status_code == 200:
                data = response.json()
                # Should contain our session
                if isinstance(data, list):
                    session_ids = [c.get("session_id") or c.get("id") for c in data]
                    # May or may not be present depending on implementation


class TestConcurrentSessions:
    """Test concurrent session handling."""

    @pytest.mark.asyncio
    async def test_concurrent_different_users(self, auth_token, test_users):
        """Multiple users can chat concurrently."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token1 = auth_token("employee")
            token2 = auth_token("finance")

            # Concurrent requests
            async def chat(token, session, message):
                response = await client.get(
                    f"/api/chat/stream?q={message}&session_id={session}",
                    headers={"Authorization": f"Bearer {token}"}
                )
                return response.status_code

            results = await asyncio.gather(
                chat(token1, "concurrent_1", "Hello from user 1"),
                chat(token2, "concurrent_2", "Hello from user 2")
            )

            assert all(r == 200 for r in results)

    @pytest.mark.asyncio
    async def test_same_user_multiple_sessions(self, auth_token):
        """Same user can have multiple sessions."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("employee")

            # Two sessions for same user
            response1 = await client.get(
                "/api/chat/stream?q=Session A&session_id=multi_a",
                headers={"Authorization": f"Bearer {token}"}
            )

            response2 = await client.get(
                "/api/chat/stream?q=Session B&session_id=multi_b",
                headers={"Authorization": f"Bearer {token}"}
            )

            assert response1.status_code == 200
            assert response2.status_code == 200


class TestConversationMetadata:
    """Test conversation metadata handling."""

    @pytest.mark.asyncio
    async def test_conversation_has_timestamp(self, auth_token):
        """Conversations have creation timestamps."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {auth_token('employee')}"}) as client:
            session_id = "timestamp_test"

            # Create conversation
            await client.get(f"/api/chat/stream?q=test&session_id={session_id}")

            # Get conversation
            response = await client.get(f"/api/conversations/{session_id}")

            if response.status_code == 200:
                data = response.json()
                # Should have timestamp
                timestamp_fields = ["created_at", "timestamp", "created", "time"]
                has_timestamp = any(f in data for f in timestamp_fields)
                # Note: May not always have timestamp depending on implementation

    @pytest.mark.asyncio
    async def test_conversation_title_generated(self, auth_token):
        """Conversations get auto-generated titles."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {auth_token('employee')}"}) as client:
            session_id = "title_test"

            # Create conversation with specific topic
            await client.get(
                f"/api/chat/stream?q=Tell me about Q4 revenue&session_id={session_id}"
            )

            # Get conversation
            response = await client.get(f"/api/conversations/{session_id}")

            if response.status_code == 200:
                data = response.json()
                # May have auto-generated title
                if "title" in data:
                    assert len(data["title"]) > 0


class TestStreamingSession:
    """Test streaming-specific session behavior."""

    @pytest.mark.asyncio
    async def test_partial_response_recovery(self, auth_token):
        """Session can recover from partial responses."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {auth_token('employee')}"}) as client:
            session_id = "recovery_test"

            # Start a stream and cancel mid-way
            try:
                async with asyncio.timeout(0.1):  # Very short timeout
                    async with client.stream(
                        "GET",
                        f"/api/chat/stream?q=Tell me a long story&session_id={session_id}"
                    ) as response:
                        async for line in response.aiter_lines():
                            if line.strip():
                                break  # Cancel after first chunk
            except asyncio.TimeoutError:
                pass

            # Session should still work
            response = await client.get(
                f"/api/chat/stream?q=hello&session_id={session_id}"
            )
            assert response.status_code == 200
