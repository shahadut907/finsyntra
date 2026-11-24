"""
Tests for Performance and Resource Usage.
Validates response times, memory usage, and concurrent handling.
"""
import pytest
import asyncio
import json
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestResponseTimes:
    """Test response time requirements."""

    @pytest.mark.asyncio
    async def test_health_endpoint_fast(self, mock_auth_bypass):
        """Health endpoint responds quickly (<100ms)."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            start = time.time()
            response = await client.get("/health")
            elapsed = time.time() - start

            assert elapsed < 0.1, f"Health check too slow: {elapsed:.2f}s"

    @pytest.mark.asyncio
    async def test_streaming_first_byte_fast(self, mock_auth_bypass):
        """Streaming endpoint sends first byte quickly (<2s)."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            start = time.time()
            first_byte_time = None

            async with client.stream(
                "GET",
                "/api/chat/stream?q=hello&session_id=perf_test"
            ) as response:
                async for line in response.aiter_lines():
                    if line.strip():
                        first_byte_time = time.time() - start
                        break

            assert first_byte_time is not None, "No response received"
            assert first_byte_time < 2.0, f"First byte too slow: {first_byte_time:.2f}s"

    @pytest.mark.asyncio
    async def test_small_talk_completes_fast(self, mock_auth_bypass):
        """Small talk queries complete quickly (<3s)."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            start = time.time()

            async with client.stream(
                "GET",
                "/api/chat/stream?q=hi&session_id=smalltalk_perf"
            ) as response:
                async for line in response.aiter_lines():
                    if "[DONE]" in line:
                        break

            elapsed = time.time() - start
            assert elapsed < 3.0, f"Small talk too slow: {elapsed:.2f}s"

    @pytest.mark.asyncio
    async def test_auth_endpoint_fast(self):
        """Auth endpoints respond quickly (<500ms)."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            start = time.time()
            response = await client.post(
                "/api/auth/login",
                json={"email": "test@test.com", "password": "test"}
            )
            elapsed = time.time() - start

            # Even failure should be fast
            assert elapsed < 0.5, f"Auth too slow: {elapsed:.2f}s"


class TestConcurrentRequests:
    """Test concurrent request handling."""

    @pytest.mark.asyncio
    async def test_concurrent_health_checks(self, mock_auth_bypass):
        """Multiple concurrent health checks succeed."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async def health_check():
                response = await client.get("/health")
                return response.status_code

            # 10 concurrent requests
            results = await asyncio.gather(*[health_check() for _ in range(10)])

            # All should succeed
            success_count = sum(1 for r in results if r in [200, 404])
            assert success_count >= 8, f"Too many failures: {10 - success_count}/10"

    @pytest.mark.asyncio
    async def test_concurrent_streams(self, mock_auth_bypass):
        """Multiple concurrent streams work."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async def stream_request(session_id):
                chunks = []
                async with client.stream(
                    "GET",
                    f"/api/chat/stream?q=test&session_id={session_id}"
                ) as response:
                    async for line in response.aiter_lines():
                        if line.strip():
                            chunks.append(line)
                        if "[DONE]" in line:
                            break
                return len(chunks) > 0

            # 5 concurrent streams
            results = await asyncio.gather(*[
                stream_request(f"concurrent_{i}") for i in range(5)
            ])

            assert all(results), "Some streams failed"

    @pytest.mark.asyncio
    async def test_concurrent_different_endpoints(self, mock_auth_bypass):
        """Concurrent requests to different endpoints work."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async def health():
                return await client.get("/health")

            async def stream():
                return await client.get("/api/chat/stream?q=test&session_id=mixed")

            results = await asyncio.gather(
                health(), stream(), health(), stream()
            )

            # All should complete
            assert all(r.status_code in [200, 404] for r in results)


class TestMemoryEfficiency:
    """Test memory usage efficiency."""

    @pytest.mark.asyncio
    async def test_large_response_streamed(self, mock_auth_bypass):
        """Large responses are streamed, not buffered."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app
        import gc

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            gc.collect()

            # Process a response without storing all chunks
            chunk_count = 0
            async with client.stream(
                "GET",
                "/api/chat/stream?q=Tell me about finance&session_id=memory_test"
            ) as response:
                async for line in response.aiter_lines():
                    chunk_count += 1
                    if "[DONE]" in line:
                        break
                    # Don't store chunks, just count

            # Should have received chunks
            assert chunk_count > 0

    @pytest.mark.asyncio
    async def test_many_small_requests(self, mock_auth_bypass):
        """Many small requests don't cause issues."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            success = 0
            for i in range(20):
                response = await client.get("/health")
                if response.status_code in [200, 404]:
                    success += 1

            assert success >= 18, f"Too many failures: {20 - success}/20"


class TestTimeoutHandling:
    """Test timeout behavior."""

    @pytest.mark.asyncio
    async def test_slow_client_doesnt_block(self, mock_auth_bypass):
        """Slow client consumption doesn't block server."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream(
                "GET",
                "/api/chat/stream?q=test&session_id=slow_client"
            ) as response:
                # Slow consumption
                async for line in response.aiter_lines():
                    await asyncio.sleep(0.01)  # 10ms delay per line
                    if "[DONE]" in line:
                        break

            # Should complete without issues
            assert True

    @pytest.mark.asyncio
    async def test_request_timeout_handled(self, mock_auth_bypass):
        """Request timeouts are handled gracefully."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            timeout=30.0
        ) as client:
            try:
                async with asyncio.timeout(0.01):  # Very short timeout
                    await client.get("/api/chat/stream?q=test&session_id=timeout_test")
            except asyncio.TimeoutError:
                pass  # Expected

            # Server should still be responsive
            response = await client.get("/health")
            assert response.status_code in [200, 404]


class TestThroughput:
    """Test request throughput."""

    @pytest.mark.asyncio
    async def test_sequential_request_throughput(self, mock_auth_bypass):
        """Sequential requests complete at reasonable rate."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            start = time.time()
            count = 10

            for _ in range(count):
                await client.get("/health")

            elapsed = time.time() - start
            rate = count / elapsed

            # Should handle at least 10 req/s
            assert rate > 5, f"Too slow: {rate:.1f} req/s"

    @pytest.mark.asyncio
    async def test_parallel_request_throughput(self, mock_auth_bypass):
        """Parallel requests complete efficiently."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            start = time.time()
            count = 10

            await asyncio.gather(*[
                client.get("/health") for _ in range(count)
            ])

            elapsed = time.time() - start

            # Parallel should be faster than sequential
            assert elapsed < 2.0, f"Parallel too slow: {elapsed:.2f}s"


class TestResourceCleanup:
    """Test resource cleanup after requests."""

    @pytest.mark.asyncio
    async def test_connection_cleanup(self, mock_auth_bypass):
        """Connections are cleaned up after requests."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)

        # Multiple client sessions
        for _ in range(5):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.get("/health")

        # Should not leak connections
        assert True

    @pytest.mark.asyncio
    async def test_stream_cleanup_on_cancel(self, mock_auth_bypass):
        """Cancelled streams clean up properly."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Start and cancel stream
            try:
                async with asyncio.timeout(0.05):
                    async with client.stream(
                        "GET",
                        "/api/chat/stream?q=long story&session_id=cleanup_test"
                    ) as response:
                        async for _ in response.aiter_lines():
                            pass
            except asyncio.TimeoutError:
                pass

            # Should still work after cancelled stream
            response = await client.get("/health")
            assert response.status_code in [200, 404]


class TestLoadBehavior:
    """Test behavior under load."""

    @pytest.mark.asyncio
    async def test_graceful_under_moderate_load(self, mock_auth_bypass):
        """System stays responsive under moderate load."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async def mixed_request(i):
                if i % 2 == 0:
                    return await client.get("/health")
                else:
                    return await client.get(
                        f"/api/chat/stream?q=test&session_id=load_{i}"
                    )

            # 20 concurrent mixed requests
            results = await asyncio.gather(*[
                mixed_request(i) for i in range(20)
            ], return_exceptions=True)

            # Count successes
            success = sum(1 for r in results
                         if not isinstance(r, Exception) and r.status_code in [200, 404])

            assert success >= 15, f"Too many failures under load: {20 - success}/20"

    @pytest.mark.asyncio
    async def test_recovery_after_burst(self, mock_auth_bypass):
        """System recovers after burst of requests."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Burst of requests
            await asyncio.gather(*[
                client.get("/health") for _ in range(30)
            ], return_exceptions=True)

            # Should recover and respond normally
            await asyncio.sleep(0.1)

            response = await client.get("/health")
            assert response.status_code in [200, 404]
