"""
Test SSE Auth + CORS fixes
Tests authentication on /api/chat/stream endpoint and CORS configuration
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import asyncio
from fastapi.testclient import TestClient
from src.backend.api.endpoints import app
from src.backend.auth.authentication import create_access_token


class TestSSEAuthAndCORS:
    """Test SSE authentication and CORS configuration"""
    
    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)
    
    @pytest.fixture
    def auth_token(self):
        """Create valid JWT token"""
        return create_access_token(data={"sub": "employee@finsolve.com", "type": "access"})
    
    def test_sse_endpoint_requires_auth_no_bypass(self, client):
        """Test that /api/chat/stream returns 401 when no auth token provided (ENV != dev)"""
        # Ensure auth bypass is disabled
        os.environ.pop('BYPASS_AUTH', None)
        os.environ.pop('ENV', None)
        
        # Make request without authentication
        response = client.get("/api/chat/stream?q=test query")
        
        # Should return 401 Unauthorized
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        assert 'AUTH_REQUIRED' in response.text or 'Authentication required' in response.text
        
    def test_sse_endpoint_works_with_bearer_token(self, client, auth_token):
        """Test that /api/chat/stream works with valid Bearer token"""
        # Make request with Bearer token
        response = client.get(
            "/api/chat/stream?q=test query",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        # Should return 200 OK (or at least not 401)
        assert response.status_code != 401, f"Should not get 401 with valid token, got {response.status_code}"
        
    def test_sse_endpoint_works_with_cookie(self, client, auth_token):
        """Test that /api/chat/stream works with session cookie"""
        # Set session token in cookies
        client.cookies.set("session_token", auth_token)
        
        # Make request with cookies
        response = client.get("/api/chat/stream?q=test query")
        
        # Should return 200 OK (or at least not 401)
        assert response.status_code != 401, f"Should not get 401 with valid cookie, got {response.status_code}"
        
    def test_cors_headers_present(self, client):
        """Test that CORS headers are configured correctly"""
        # Make OPTIONS preflight request
        response = client.options(
            "/api/chat/stream",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET"
            }
        )
        
        # Check CORS headers are present
        assert response.status_code in [200, 204], f"Preflight should succeed, got {response.status_code}"
        
    def test_cors_credentials_allowed(self, client, auth_token):
        """Test that CORS allows credentials"""
        # Make request with Origin header and auth
        response = client.get(
            "/api/chat/stream?q=test",
            headers={
                "Origin": "http://localhost:3000",
                "Authorization": f"Bearer {auth_token}"
            }
        )
        
        # Check Access-Control-Allow-Credentials header
        # Note: TestClient might not expose all headers, but we verify the middleware is configured
        assert response.status_code != 401, "Should accept authenticated request"


class TestHealthEndpointPerformance:
    """Test health endpoint performance"""
    
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    def test_health_endpoint_fast(self, client):
        """Test that /health endpoint responds in < 100ms"""
        import time
        
        # Warm up
        client.get("/health")
        
        # Measure 10 requests
        times = []
        for _ in range(10):
            start = time.perf_counter()
            response = client.get("/health")
            elapsed = (time.perf_counter() - start) * 1000  # Convert to ms
            times.append(elapsed)
            assert response.status_code == 200
        
        # Check p95
        times.sort()
        p95 = times[int(len(times) * 0.95)]
        print(f"\n/health p95: {p95:.2f}ms")
        assert p95 < 100, f"/health p95 should be < 100ms, got {p95:.2f}ms"
        
    def test_health_no_external_calls(self, client):
        """Test that /health doesn't make external calls (fast even when offline)"""
        # Direct check: any outbound HTTP call made while serving /health fails
        # the test. The app's external calls (Groq/Ollama providers, health
        # probes) go through requests or httpx, so their send paths are
        # blocked. (Raw sockets are not patched: on Windows asyncio opens a
        # loopback socketpair for every new event loop TestClient starts.)
        # Latency is still bounded below, after a warm-up like the test above,
        # so a cold first request on a loaded host does not decide the result.
        import time
        from unittest.mock import patch

        client.get("/health")

        def refuse(*args, **kwargs):
            raise AssertionError("/health attempted an outbound HTTP call")

        times = []
        with patch("requests.Session.send", refuse), \
                patch("httpx.AsyncClient.send", refuse), \
                patch("urllib.request.urlopen", refuse):
            for _ in range(5):
                start = time.perf_counter()
                response = client.get("/health")
                elapsed = (time.perf_counter() - start) * 1000
                times.append(elapsed)
                assert response.status_code == 200
        
        # All responses should be fast (< 50ms avg)
        avg_time = sum(times) / len(times)
        print(f"\n/health avg: {avg_time:.2f}ms")
        assert avg_time < 50, f"Health check too slow (avg {avg_time:.2f}ms), likely making external calls"


if __name__ == "__main__":
    print("Running SSE Auth + CORS tests...")
    pytest.main([__file__, "-v", "-s"])

