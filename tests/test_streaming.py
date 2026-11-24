"""
Tests for SSE/EventSource Streaming (CRITICAL)
Ensures streaming always completes with [DONE] - fixes ASGI crash.
"""
import pytest
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.asyncio
async def test_streaming_always_ends_with_done(auth_token):
    """
    CRITICAL: Stream MUST always end with [DONE] to complete ASGI response.
    This prevents "ASGI callable returned without completing response" errors.
    """
    from httpx import AsyncClient, ASGITransport
    from src.backend.api.endpoints import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {auth_token('employee')}"}) as client:
        chunks = []
        async with client.stream("GET", "/api/chat/stream?q=hello&session_id=test123") as response:
            async for line in response.aiter_lines():
                if line.strip():
                    chunks.append(line)

        # Must have received some data
        assert len(chunks) > 0, "Stream returned no data"

        # CRITICAL: Must end with [DONE]
        done_found = any("[DONE]" in chunk for chunk in chunks)
        assert done_found, (
            f"ASGI BUG: Stream did not end with [DONE]. "
            f"Last chunks: {chunks[-3:] if len(chunks) >= 3 else chunks}"
        )


@pytest.mark.asyncio
async def test_streaming_error_yields_done(auth_token):
    """
    Even on errors, stream must yield [DONE] to complete response.
    """
    from httpx import AsyncClient, ASGITransport
    from src.backend.api.endpoints import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {auth_token('employee')}"}) as client:
        # Empty query should still complete properly
        chunks = []
        async with client.stream("GET", "/api/chat/stream?q=&session_id=err_test") as response:
            async for line in response.aiter_lines():
                if line.strip():
                    chunks.append(line)

        # Even error responses must include [DONE] or be a proper error response
        # (400 status would not stream, but if it does stream, must have [DONE])
        if response.status_code == 200 and chunks:
            done_found = any("[DONE]" in chunk for chunk in chunks)
            assert done_found, "Error path did not yield [DONE]"


@pytest.mark.asyncio
async def test_streaming_small_talk_completes(auth_token):
    """
    Small talk queries should complete quickly with [DONE].
    """
    from httpx import AsyncClient, ASGITransport
    from src.backend.api.endpoints import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {auth_token('employee')}"}) as client:
        chunks = []
        async with client.stream("GET", "/api/chat/stream?q=hello&session_id=small_talk") as response:
            async for line in response.aiter_lines():
                if line.strip():
                    chunks.append(line)

        # Should complete with [DONE]
        assert any("[DONE]" in c for c in chunks), "Small talk did not complete"

        # Should have token events
        has_tokens = any("token" in c for c in chunks)
        assert has_tokens, "No token events in small talk response"


@pytest.mark.asyncio
async def test_streaming_sse_format(auth_token):
    """
    Verify SSE format: "data: {...}\n\n"
    """
    from httpx import AsyncClient, ASGITransport
    from src.backend.api.endpoints import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {auth_token('employee')}"}) as client:
        async with client.stream("GET", "/api/chat/stream?q=hi&session_id=sse_test") as response:
            async for line in response.aiter_lines():
                if line.strip() and not line.startswith("data:"):
                    # All non-empty lines should start with "data:"
                    if line != "":
                        pytest.fail(f"Invalid SSE format: {line[:50]}")


@pytest.mark.asyncio
async def test_streaming_json_events(auth_token):
    """
    Verify JSON events are parseable.
    """
    from httpx import AsyncClient, ASGITransport
    from src.backend.api.endpoints import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {auth_token('employee')}"}) as client:
        async with client.stream("GET", "/api/chat/stream?q=test&session_id=json_test") as response:
            async for line in response.aiter_lines():
                if line.startswith("data: ") and "[DONE]" not in line:
                    json_str = line[6:]  # Remove "data: " prefix
                    try:
                        parsed = json.loads(json_str)
                        assert "type" in parsed, f"Event missing 'type': {parsed}"
                    except json.JSONDecodeError as e:
                        pytest.fail(f"Invalid JSON in SSE: {json_str[:100]} - {e}")


@pytest.mark.asyncio
async def test_streaming_has_start_event(auth_token):
    """
    Stream should emit start event immediately.
    """
    from httpx import AsyncClient, ASGITransport
    from src.backend.api.endpoints import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {auth_token('employee')}"}) as client:
        events = []
        async with client.stream("GET", "/api/chat/stream?q=test&session_id=start_test") as response:
            async for line in response.aiter_lines():
                if line.startswith("data: ") and "[DONE]" not in line:
                    try:
                        parsed = json.loads(line[6:])
                        events.append(parsed.get("type"))
                    except:
                        pass

        assert "start" in events, f"No 'start' event found. Events: {events[:5]}"


@pytest.mark.asyncio
async def test_streaming_has_complete_event(auth_token):
    """
    Stream should emit complete event before [DONE].
    """
    from httpx import AsyncClient, ASGITransport
    from src.backend.api.endpoints import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {auth_token('employee')}"}) as client:
        events = []
        async with client.stream("GET", "/api/chat/stream?q=hello&session_id=complete_test") as response:
            async for line in response.aiter_lines():
                if line.startswith("data: ") and "[DONE]" not in line:
                    try:
                        parsed = json.loads(line[6:])
                        events.append(parsed.get("type"))
                    except:
                        pass

        assert "complete" in events, f"No 'complete' event found. Events: {events}"


class TestStreamingHealthCheck:
    """Test streaming endpoint health."""

    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        """Streaming health endpoint responds."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/chat/stream/health")
            assert response.status_code == 200
            data = response.json()
            assert data.get("status") == "healthy"
            assert data.get("streaming") is True
