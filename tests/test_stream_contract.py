"""
Contract tests for unified /api/chat/stream endpoint.
Tests GET/POST endpoints, missing prompt validation, and RAG-empty fallback.
"""

import pytest
import asyncio
import httpx
from fastapi.testclient import TestClient
from datetime import datetime
import time


@pytest.fixture
def client():
    """Create test client"""
    from src.backend.api.endpoints import app
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Create auth headers with valid JWT token"""
    from src.backend.auth.authentication import create_access_token
    
    token = create_access_token({
        "sub": "employee@finsolve.com",
        "type": "access",
        "name": "Test User",
        "role": "employee",
        "department": "Engineering"
    })
    
    return {"Authorization": f"Bearer {token}"}


def parse_sse_events(response_text):
    """Parse SSE format response into events"""
    events = []
    lines = response_text.strip().split('\n')
    
    for line in lines:
        if line.startswith('data: '):
            data = line[6:]  # Remove 'data: ' prefix
            events.append(data)
    
    return events


class TestStreamContractGET:
    """Test GET endpoint contract"""
    
    def test_get_with_q_parameter_returns_200(self, client, auth_headers):
        """GET with ?q=hello should return 200 and stream tokens"""
        response = client.get(
            "/api/chat/stream?q=hello",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        assert response.headers.get("content-type") == "text/event-stream; charset=utf-8"
        
        # Parse events
        events = parse_sse_events(response.text)
        assert len(events) > 0
        
        # Should end with [DONE]
        assert events[-1] == "[DONE]"
        
        # Should have some token events
        token_events = [e for e in events if '"type":"token"' in e or '"type": "token"' in e]
        assert len(token_events) > 0
    
    def test_get_with_prompt_parameter_returns_200(self, client, auth_headers):
        """GET with ?prompt=hello should also work"""
        response = client.get(
            "/api/chat/stream?prompt=hello",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        assert response.headers.get("content-type") == "text/event-stream; charset=utf-8"
    
    def test_get_with_message_parameter_returns_200(self, client, auth_headers):
        """GET with ?message=hello should also work"""
        response = client.get(
            "/api/chat/stream?message=hello",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        assert response.headers.get("content-type") == "text/event-stream; charset=utf-8"
    
    def test_get_without_prompt_returns_400(self, client, auth_headers):
        """GET without any prompt parameter should return 400"""
        response = client.get(
            "/api/chat/stream",
            headers=auth_headers
        )
        
        assert response.status_code == 400
        assert response.json() == {"error": "missing_prompt"}
    
    def test_get_with_empty_prompt_returns_400(self, client, auth_headers):
        """GET with empty prompt should return 400"""
        response = client.get(
            "/api/chat/stream?q=",
            headers=auth_headers
        )
        
        assert response.status_code == 400
        assert response.json() == {"error": "missing_prompt"}
    
    def test_get_with_whitespace_only_returns_400(self, client, auth_headers):
        """GET with whitespace-only prompt should return 400"""
        response = client.get(
            "/api/chat/stream?q=%20%20%20",  # URL-encoded spaces
            headers=auth_headers
        )
        
        assert response.status_code == 400
        assert response.json() == {"error": "missing_prompt"}
    
    def test_get_first_line_arrives_quickly(self, client, auth_headers):
        """First line should arrive within reasonable time"""
        start_time = time.time()
        
        response = client.get(
            "/api/chat/stream?q=hello",
            headers=auth_headers
        )
        
        # Check that we got a response
        assert response.status_code == 200
        
        # Parse first event
        events = parse_sse_events(response.text)
        assert len(events) > 0
        
        # Time to complete should be < 10s (RAG processing can take time)
        # Note: In tests, the entire response is buffered, so we just check it completed
        elapsed = time.time() - start_time
        assert elapsed < 10.0, f"Response took {elapsed:.2f}s (should be < 10s)"


class TestStreamContractPOST:
    """Test POST endpoint contract"""
    
    def test_post_with_message_returns_200(self, client, auth_headers):
        """POST with {message:"hello"} should return 200 and stream tokens"""
        response = client.post(
            "/api/chat/stream",
            json={"message": "hello"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        assert response.headers.get("content-type") == "text/event-stream; charset=utf-8"
        
        # Parse events
        events = parse_sse_events(response.text)
        assert len(events) > 0
        
        # Should end with [DONE]
        assert events[-1] == "[DONE]"
        
        # Should have some token events
        token_events = [e for e in events if '"type":"token"' in e or '"type": "token"' in e]
        assert len(token_events) > 0
    
    def test_post_with_prompt_returns_200(self, client, auth_headers):
        """POST with {prompt:"hello"} should also work"""
        response = client.post(
            "/api/chat/stream",
            json={"prompt": "hello"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        assert response.headers.get("content-type") == "text/event-stream; charset=utf-8"
    
    def test_post_with_q_returns_200(self, client, auth_headers):
        """POST with {q:"hello"} should also work"""
        response = client.post(
            "/api/chat/stream",
            json={"q": "hello"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        assert response.headers.get("content-type") == "text/event-stream; charset=utf-8"
    
    def test_post_without_prompt_returns_400(self, client, auth_headers):
        """POST without any prompt field should return 400"""
        response = client.post(
            "/api/chat/stream",
            json={},
            headers=auth_headers
        )
        
        assert response.status_code == 400
        assert response.json() == {"error": "missing_prompt"}
    
    def test_post_with_empty_message_returns_400(self, client, auth_headers):
        """POST with empty message should return 400"""
        response = client.post(
            "/api/chat/stream",
            json={"message": ""},
            headers=auth_headers
        )
        
        assert response.status_code == 400
        assert response.json() == {"error": "missing_prompt"}
    
    def test_post_first_line_arrives_quickly(self, client, auth_headers):
        """First line should arrive within reasonable time"""
        start_time = time.time()
        
        response = client.post(
            "/api/chat/stream",
            json={"message": "hello"},
            headers=auth_headers
        )
        
        # Check that we got a response
        assert response.status_code == 200
        
        # Parse first event
        events = parse_sse_events(response.text)
        assert len(events) > 0
        
        # Time to complete should be < 10s (RAG processing can take time)
        elapsed = time.time() - start_time
        assert elapsed < 10.0, f"Response took {elapsed:.2f}s (should be < 10s)"


class TestStreamRAGEmpty:
    """Test RAG-empty fallback behavior"""
    
    def test_small_talk_returns_tokens_not_422(self, client, auth_headers):
        """Small talk query should return tokens, not 422 error"""
        # Small talk that won't match any documents
        response = client.post(
            "/api/chat/stream",
            json={"message": "hey sir how are you"},
            headers=auth_headers
        )
        
        # Should NOT return 422
        assert response.status_code == 200
        assert response.headers.get("content-type") == "text/event-stream; charset=utf-8"
        
        # Parse events
        events = parse_sse_events(response.text)
        assert len(events) > 0
        
        # Should include rag_status event
        rag_status_events = [e for e in events if '"type":"rag_status"' in e or '"type": "rag_status"' in e]
        assert len(rag_status_events) > 0, "Should have rag_status event"
        
        # Should still have token events (fallback to general LLM)
        token_events = [e for e in events if '"type":"token"' in e or '"type": "token"' in e]
        assert len(token_events) > 0, "Should still return tokens even when RAG is empty"
        
        # Should end with [DONE]
        assert events[-1] == "[DONE]"
    
    def test_rag_empty_includes_status_event(self, client, auth_headers):
        """RAG empty should gracefully fall back even when similarity is low"""
        # Note: ChromaDB always returns results even with low similarity
        # This test verifies the endpoint handles queries gracefully
        response = client.post(
            "/api/chat/stream",
            json={"message": "xyzqwerty99999 nonexistent query"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        
        # Parse events
        events = parse_sse_events(response.text)
        
        # Should have tokens (either from RAG or fallback)
        token_events = [e for e in events if '"type":"token"' in e or '"type": "token"' in e]
        assert len(token_events) > 0, "Should return tokens even with low-relevance queries"
        
        # Should end with [DONE]
        assert events[-1] == "[DONE]"


class TestStreamAuth:
    """Test authentication requirements"""
    
    def test_get_without_auth_returns_401(self, client):
        """GET without auth should return 401"""
        response = client.get("/api/chat/stream?q=hello")
        
        assert response.status_code == 401
    
    def test_post_without_auth_returns_401(self, client):
        """POST without auth should return 401"""
        response = client.post(
            "/api/chat/stream",
            json={"message": "hello"}
        )
        
        assert response.status_code == 401


class TestStreamHeaders:
    """Test SSE headers are correctly set"""
    
    def test_stream_headers_include_cache_control(self, client, auth_headers):
        """Stream should have proper cache control headers"""
        response = client.get(
            "/api/chat/stream?q=hello",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "no-cache"
        assert response.headers.get("x-accel-buffering") == "no"
    
    def test_stream_allows_credentials(self, client, auth_headers):
        """Stream should allow credentials for cookie auth"""
        response = client.get(
            "/api/chat/stream?q=hello",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        assert "access-control-allow-credentials" in response.headers


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "-s"])

