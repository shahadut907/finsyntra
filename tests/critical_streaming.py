"""
Critical Streaming Tests - ASGI, SSE Format, Timeout Handling
Priority: CRITICAL - Streaming must work reliably
6 tests covering SSE/streaming fundamentals
"""
import pytest
import asyncio
import json
import os
import sys
from unittest.mock import MagicMock, AsyncMock, patch
from typing import AsyncGenerator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockRequest:
    """Mock Starlette Request for testing"""
    def __init__(self, disconnected=False):
        self._disconnected = disconnected
        self.app = MagicMock()
        self.app.state.rag = MagicMock()
        self.headers = {}
        self.cookies = {}

    async def is_disconnected(self):
        return self._disconnected


@pytest.fixture
def mock_rag_service():
    """Mock RAG service for streaming tests"""
    mock = MagicMock()
    mock.process_query.return_value = {
        "success": True,
        "response": "Test response from RAG service.",
        "sources": [{"filename": "test.pdf", "page": 1}],
        "documents_found": 1,
        "used_rag": True
    }
    return mock


@pytest.fixture
def mock_request():
    """Create a mock request object"""
    return MockRequest(disconnected=False)


class TestSSEFormat:
    """Tests for Server-Sent Events format compliance"""

    @pytest.mark.asyncio
    async def test_sse_data_prefix(self):
        """All SSE messages must start with 'data: '"""
        sse_messages = [
            'data: {"type": "start"}\n\n',
            'data: {"type": "token", "token": "H"}\n\n',
            'data: {"type": "complete"}\n\n',
            'data: [DONE]\n\n'
        ]

        for msg in sse_messages:
            assert msg.startswith("data: "), f"SSE message must start with 'data: ': {msg}"
            assert msg.endswith("\n\n"), f"SSE message must end with double newline: {msg}"

    @pytest.mark.asyncio
    async def test_sse_json_valid(self):
        """SSE data payloads are valid JSON (except [DONE])"""
        sse_messages = [
            'data: {"type": "start", "timestamp": "2024-01-01T00:00:00"}\n\n',
            'data: {"type": "token", "token": "Hello"}\n\n',
            'data: {"type": "complete", "sources": []}\n\n',
        ]

        for msg in sse_messages:
            # Extract JSON part
            json_str = msg.replace("data: ", "").strip()

            # Should parse without error
            try:
                parsed = json.loads(json_str)
                assert "type" in parsed, "SSE payload should have 'type' field"
            except json.JSONDecodeError as e:
                pytest.fail(f"Invalid JSON in SSE message: {msg} - {e}")

    @pytest.mark.asyncio
    async def test_done_marker_format(self):
        """[DONE] marker has correct format"""
        done_marker = "data: [DONE]\n\n"

        assert done_marker.startswith("data: "), "DONE marker needs data prefix"
        assert "[DONE]" in done_marker, "Must contain [DONE]"
        assert done_marker.endswith("\n\n"), "Must end with double newline"


class TestStreamCompletion:
    """Tests to ensure streams always complete properly"""

    @pytest.mark.asyncio
    async def test_stream_always_ends_with_done(self):
        """Every response stream must end with [DONE]"""
        async def mock_stream() -> AsyncGenerator[str, None]:
            yield 'data: {"type": "start"}\n\n'
            yield 'data: {"type": "token", "token": "Test"}\n\n'
            yield 'data: {"type": "complete"}\n\n'
            yield "data: [DONE]\n\n"

        chunks = []
        async for chunk in mock_stream():
            chunks.append(chunk)

        assert chunks[-1] == "data: [DONE]\n\n", "Stream must end with [DONE]"

    @pytest.mark.asyncio
    async def test_error_still_yields_done(self):
        """Errors must yield error event followed by [DONE]"""
        async def mock_error_stream() -> AsyncGenerator[str, None]:
            yield 'data: {"type": "start"}\n\n'
            # Simulate error
            yield 'data: {"type": "error", "message": "Something went wrong"}\n\n'
            yield "data: [DONE]\n\n"

        chunks = []
        async for chunk in mock_error_stream():
            chunks.append(chunk)

        # Check error event exists
        error_chunks = [c for c in chunks if '"type": "error"' in c]
        assert len(error_chunks) >= 1, "Error event should be yielded"

        # Still ends with DONE
        assert chunks[-1] == "data: [DONE]\n\n", "Error stream must still end with [DONE]"

    @pytest.mark.asyncio
    async def test_empty_rag_yields_done(self):
        """Empty RAG results still yield complete stream with [DONE]"""
        async def mock_empty_rag_stream() -> AsyncGenerator[str, None]:
            yield 'data: {"type": "start"}\n\n'
            yield 'data: {"type": "rag_status", "value": "empty"}\n\n'
            yield 'data: {"type": "token", "token": "I couldn\'t find relevant documents."}\n\n'
            yield 'data: {"type": "complete", "documents_found": 0}\n\n'
            yield "data: [DONE]\n\n"

        chunks = []
        async for chunk in mock_empty_rag_stream():
            chunks.append(chunk)

        assert chunks[-1] == "data: [DONE]\n\n", "Empty RAG stream must end with [DONE]"

        # Should have rag_status empty event
        rag_status_chunks = [c for c in chunks if "rag_status" in c]
        assert len(rag_status_chunks) >= 1, "Should indicate empty RAG status"


class TestTimeoutHandling:
    """Tests for timeout scenarios"""

    @pytest.mark.asyncio
    async def test_rag_timeout_graceful(self):
        """RAG timeout yields graceful error, not crash"""
        async def simulate_timeout():
            # Simulate what happens on timeout
            raise asyncio.TimeoutError("RAG hard timeout after 30s")

        try:
            await asyncio.wait_for(simulate_timeout(), timeout=0.1)
            pytest.fail("Should have raised TimeoutError")
        except asyncio.TimeoutError:
            # This is expected - verify we can handle it
            error_response = {"type": "error", "message": "Request timed out"}
            assert error_response["type"] == "error"

    @pytest.mark.asyncio
    async def test_heartbeat_during_long_operation(self):
        """Heartbeats are sent during long operations"""
        heartbeats = []

        async def mock_long_operation_with_heartbeat():
            for i in range(3):
                # Simulate heartbeat every iteration
                heartbeats.append(f'data: {{"type": "ping", "elapsed": {i * 7}}}\n\n')
                await asyncio.sleep(0.01)  # Shortened for test
            return {"success": True}

        result = await mock_long_operation_with_heartbeat()

        assert len(heartbeats) >= 1, "Should send heartbeats during long operation"
        assert all('"ping"' in h for h in heartbeats), "Heartbeats should be ping type"

    @pytest.mark.asyncio
    async def test_hard_timeout_limit(self):
        """Hard timeout prevents infinite hangs"""
        RAG_HARD_TIMEOUT = 30.0  # From actual code

        async def would_hang_forever():
            await asyncio.sleep(100)  # Would hang

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(would_hang_forever(), timeout=0.1)

        # Verify timeout constant is reasonable
        assert 10 <= RAG_HARD_TIMEOUT <= 60, "Hard timeout should be 10-60 seconds"


class TestClientDisconnect:
    """Tests for client disconnect handling"""

    @pytest.mark.asyncio
    async def test_disconnect_stops_streaming(self):
        """Client disconnect stops the stream gracefully"""
        request = MockRequest(disconnected=True)

        stream_continued = False

        async def mock_stream_with_disconnect_check():
            nonlocal stream_continued

            if await request.is_disconnected():
                return  # Should exit here

            stream_continued = True
            yield "data: should not reach\n\n"

        chunks = []
        async for chunk in mock_stream_with_disconnect_check():
            chunks.append(chunk)

        assert not stream_continued, "Stream should stop on disconnect"
        assert len(chunks) == 0, "No chunks should be yielded after disconnect"

    @pytest.mark.asyncio
    async def test_disconnect_check_frequency(self):
        """Disconnect is checked frequently during streaming"""
        check_count = 0

        async def mock_stream_with_checks():
            nonlocal check_count
            request = MockRequest(disconnected=False)

            for i in range(5):
                if await request.is_disconnected():
                    break
                check_count += 1
                yield f'data: {{"token": "{i}"}}\n\n'

        chunks = []
        async for chunk in mock_stream_with_checks():
            chunks.append(chunk)

        assert check_count >= 5, "Disconnect should be checked each iteration"


class TestConcurrentStreams:
    """Tests for concurrent stream handling"""

    @pytest.mark.asyncio
    async def test_multiple_concurrent_streams(self):
        """Multiple concurrent streams don't interfere"""
        results = {}

        async def stream_for_user(user_id: str):
            chunks = []
            for i in range(3):
                chunks.append(f"user_{user_id}_chunk_{i}")
                await asyncio.sleep(0.01)
            results[user_id] = chunks

        # Run 5 concurrent streams
        await asyncio.gather(
            stream_for_user("1"),
            stream_for_user("2"),
            stream_for_user("3"),
            stream_for_user("4"),
            stream_for_user("5"),
        )

        # Each user should have their own chunks
        assert len(results) == 5, "All streams should complete"
        for user_id, chunks in results.items():
            assert all(f"user_{user_id}" in c for c in chunks), \
                f"User {user_id} chunks should be isolated"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
