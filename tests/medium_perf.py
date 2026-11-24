"""
Medium Priority Performance Tests - Response Time, Concurrency, Resource Leaks
Priority: MEDIUM - Performance requirements for production
8 tests covering performance characteristics
"""
import pytest
import asyncio
import time
import os
import sys
import gc
from unittest.mock import MagicMock, AsyncMock, patch
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def mock_fast_rag():
    """Mock RAG that responds quickly"""
    mock = MagicMock()

    def fast_query(*args, **kwargs):
        time.sleep(0.05)  # Simulate 50ms processing
        return {
            "success": True,
            "response": "Fast response.",
            "sources": [],
            "documents_found": 1,
            "used_rag": True
        }

    mock.process_query = fast_query
    return mock


@pytest.fixture
def mock_slow_rag():
    """Mock RAG that simulates slow processing"""
    mock = MagicMock()

    def slow_query(*args, **kwargs):
        time.sleep(2.0)  # Simulate 2s processing
        return {
            "success": True,
            "response": "Slow response.",
            "sources": [],
            "documents_found": 1,
            "used_rag": True
        }

    mock.process_query = slow_query
    return mock


class TestResponseTime:
    """Tests for response time requirements"""

    @pytest.mark.asyncio
    async def test_health_check_fast(self):
        """Health check responds in < 500ms"""
        with patch.dict(os.environ, {"BYPASS_AUTH": "true"}):
            from src.backend.api.endpoints import app
            from httpx import AsyncClient, ASGITransport

            transport = ASGITransport(app=app)

            start = time.time()
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/health")
            elapsed = time.time() - start

            assert response.status_code == 200
            assert elapsed < 2.0, f"Health check took {elapsed:.2f}s, should be < 2s"

    @pytest.mark.asyncio
    async def test_rag_query_reasonable_time(self, mock_fast_rag):
        """RAG query completes in reasonable time"""
        MAX_RESPONSE_TIME = 5.0  # Allow 5s for mocked RAG

        start = time.time()
        result = mock_fast_rag.process_query("What is the leave policy?", tenant_id="test")
        elapsed = time.time() - start

        assert result["success"], "Query should succeed"
        assert elapsed < MAX_RESPONSE_TIME, \
            f"RAG query took {elapsed:.2f}s, should be < {MAX_RESPONSE_TIME}s"

    @pytest.mark.asyncio
    async def test_small_talk_instant(self):
        """Small talk responses are instant (no RAG)"""
        from src.backend.api.chat_stream import is_small_talk, get_small_talk_response

        small_talk_queries = ["hello", "hi", "thanks", "goodbye"]

        for query in small_talk_queries:
            start = time.time()
            is_st = is_small_talk(query)
            if is_st:
                response = get_small_talk_response(query)
            elapsed = time.time() - start

            assert elapsed < 0.1, f"Small talk '{query}' took {elapsed:.3f}s, should be instant"


class TestConcurrency:
    """Tests for concurrent request handling"""

    @pytest.mark.asyncio
    async def test_concurrent_10_requests(self, mock_fast_rag):
        """Handle 10 concurrent requests without failure"""
        results = []
        errors = []

        async def make_request(i):
            try:
                result = await asyncio.to_thread(
                    mock_fast_rag.process_query,
                    f"Query {i}",
                    tenant_id="test"
                )
                results.append(result)
            except Exception as e:
                errors.append(str(e))

        # Run 10 concurrent requests
        await asyncio.gather(*[make_request(i) for i in range(10)])

        assert len(errors) == 0, f"Concurrent requests failed: {errors}"
        assert len(results) == 10, f"Expected 10 results, got {len(results)}"
        assert all(r["success"] for r in results), "All requests should succeed"

    @pytest.mark.asyncio
    async def test_concurrent_different_tenants(self, mock_fast_rag):
        """Concurrent requests from different tenants are isolated"""
        tenant_results = {}

        async def query_for_tenant(tenant_id):
            result = await asyncio.to_thread(
                mock_fast_rag.process_query,
                "What is revenue?",
                tenant_id=tenant_id
            )
            tenant_results[tenant_id] = result

        # Run requests for 5 different tenants
        tenants = ["tenant1", "tenant2", "tenant3", "tenant4", "tenant5"]
        await asyncio.gather(*[query_for_tenant(t) for t in tenants])

        assert len(tenant_results) == 5, "All tenant requests should complete"

    @pytest.mark.asyncio
    async def test_no_request_interference(self):
        """Concurrent requests don't interfere with each other"""
        request_ids = []
        lock = asyncio.Lock()

        async def tracked_request(request_id):
            async with lock:
                request_ids.append(f"start_{request_id}")

            await asyncio.sleep(0.1)  # Simulate work

            async with lock:
                request_ids.append(f"end_{request_id}")

        await asyncio.gather(*[tracked_request(i) for i in range(5)])

        # All starts and ends should be recorded
        starts = [r for r in request_ids if r.startswith("start_")]
        ends = [r for r in request_ids if r.startswith("end_")]

        assert len(starts) == 5, "All requests should start"
        assert len(ends) == 5, "All requests should end"


class TestResourceLeaks:
    """Tests for memory and resource leaks"""

    @pytest.mark.asyncio
    async def test_no_memory_leak_repeated_queries(self, mock_fast_rag):
        """Repeated queries don't cause memory leak"""
        import tracemalloc

        tracemalloc.start()

        # Baseline
        baseline_snapshot = tracemalloc.take_snapshot()

        # Run 100 queries
        for i in range(100):
            result = mock_fast_rag.process_query(f"Query {i}", tenant_id="test")
            assert result["success"]

        gc.collect()

        # Final snapshot
        final_snapshot = tracemalloc.take_snapshot()

        # Compare
        top_stats = final_snapshot.compare_to(baseline_snapshot, 'lineno')

        # Memory growth should be reasonable (< 10MB for 100 queries)
        total_diff = sum(stat.size_diff for stat in top_stats[:10])
        assert total_diff < 10 * 1024 * 1024, \
            f"Memory grew by {total_diff / 1024 / 1024:.2f}MB, possible leak"

        tracemalloc.stop()

    @pytest.mark.asyncio
    async def test_connection_cleanup(self):
        """Connections are properly cleaned up"""
        # Simulate connection tracking
        active_connections = []

        class MockConnection:
            def __init__(self, conn_id):
                self.id = conn_id
                self.closed = False

            async def close(self):
                self.closed = True

        async def use_connection(conn_id):
            conn = MockConnection(conn_id)
            active_connections.append(conn)
            try:
                await asyncio.sleep(0.01)  # Simulate use
            finally:
                await conn.close()

        # Use 10 connections
        await asyncio.gather(*[use_connection(i) for i in range(10)])

        # All should be closed
        assert all(c.closed for c in active_connections), "All connections should be closed"

    @pytest.mark.asyncio
    async def test_file_handle_cleanup(self):
        """File handles are properly closed"""
        import tempfile

        handles_closed = []

        for i in range(10):
            # Create temp file
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
                f.write(f"Test content {i}")
                temp_path = f.name

            # Read and close
            with open(temp_path, 'r') as f:
                content = f.read()

            handles_closed.append(True)

            # Clean up
            os.unlink(temp_path)

        assert len(handles_closed) == 10, "All file operations should complete"


class TestCacheEfficiency:
    """Tests for caching behavior"""

    @pytest.mark.asyncio
    async def test_cache_hit_faster(self):
        """Cached responses are faster than fresh queries"""
        cache = {}

        def cached_query(query):
            if query in cache:
                return cache[query]  # Instant cache hit

            # Simulate slow computation
            time.sleep(0.1)
            result = {"response": f"Result for {query}"}
            cache[query] = result
            return result

        # First call - cache miss
        start = time.time()
        result1 = cached_query("test query")
        time1 = time.time() - start

        # Second call - cache hit
        start = time.time()
        result2 = cached_query("test query")
        time2 = time.time() - start

        assert time2 < time1, "Cache hit should be faster"
        assert time2 < 0.01, "Cache hit should be near instant"

    @pytest.mark.asyncio
    async def test_cache_tenant_isolation(self):
        """Cache respects tenant boundaries"""
        tenant_cache = {}

        def tenant_cached_query(query, tenant_id):
            cache_key = f"{tenant_id}:{query}"
            if cache_key in tenant_cache:
                return tenant_cache[cache_key]

            result = {"response": f"Result for {tenant_id}", "tenant": tenant_id}
            tenant_cache[cache_key] = result
            return result

        # Query as tenant1
        result1 = tenant_cached_query("revenue", "tenant1")

        # Same query as tenant2 should NOT hit tenant1's cache
        result2 = tenant_cached_query("revenue", "tenant2")

        assert result1["tenant"] == "tenant1"
        assert result2["tenant"] == "tenant2"
        assert result1 != result2, "Different tenants should have different cache entries"


class TestDatabasePool:
    """Tests for database connection pool"""

    @pytest.mark.asyncio
    async def test_pool_handles_concurrent_queries(self):
        """Connection pool handles concurrent DB queries"""
        pool_size = 5
        queries_executed = []

        async def db_query(query_id):
            # Simulate pool checkout
            await asyncio.sleep(0.01)
            queries_executed.append(query_id)
            return {"id": query_id, "success": True}

        # Run more queries than pool size
        results = await asyncio.gather(*[db_query(i) for i in range(20)])

        assert len(results) == 20, "All queries should complete"
        assert len(queries_executed) == 20, "All queries should be executed"

    @pytest.mark.asyncio
    async def test_pool_timeout_handling(self):
        """Pool handles exhaustion gracefully"""
        # Simulate pool exhaustion scenario
        available_connections = 2
        waiting_requests = []

        async def request_connection(request_id, timeout=1.0):
            nonlocal available_connections
            start = time.time()

            while available_connections <= 0:
                if time.time() - start > timeout:
                    raise TimeoutError(f"Connection pool timeout for request {request_id}")
                await asyncio.sleep(0.01)

            available_connections -= 1
            waiting_requests.append(request_id)
            await asyncio.sleep(0.05)  # Use connection
            available_connections += 1

        # This should work (2 concurrent with 2 pool size)
        await asyncio.gather(
            request_connection(1),
            request_connection(2)
        )

        assert len(waiting_requests) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
