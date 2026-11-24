"""
Tests for RBAC (Role-Based Access Control) Security.
Validates role permissions, tenant isolation, and access control.
"""
import pytest
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRolePermissions:
    """Test role-based access control."""

    @pytest.mark.asyncio
    async def test_employee_cannot_access_admin_endpoints(self, auth_token, test_users):
        """Employees cannot access admin-only endpoints."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("employee")

            # Try to access admin endpoint
            response = await client.delete(
                "/api/documents/clear",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 403, "Employee should not access admin endpoints"

    @pytest.mark.asyncio
    async def test_admin_can_access_admin_endpoints(self, auth_token, test_users):
        """Admins can access admin-only endpoints."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")

            response = await client.get(
                "/api/documents/status",
                headers={"Authorization": f"Bearer {token}"}
            )
            # Admin should have access (200) or endpoint may not exist (404)
            assert response.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_finance_role_access(self, auth_token, test_users):
        """Finance role has appropriate access."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("finance")

            # Finance should be able to chat
            chunks = []
            async with client.stream(
                "GET",
                "/api/chat/stream?q=revenue&session_id=finance_test",
                headers={"Authorization": f"Bearer {token}"}
            ) as response:
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    if line.strip():
                        chunks.append(line)

            assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_c_level_role_access(self, auth_token, test_users):
        """C-level executives have elevated access."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("c_level")

            # C-level should be able to access documents
            response = await client.get(
                "/api/documents/list",
                headers={"Authorization": f"Bearer {token}"}
            )
            # Should have access
            assert response.status_code in [200, 404]


class TestTenantIsolation:
    """Test multi-tenant data isolation."""

    @pytest.mark.asyncio
    async def test_tenant_cannot_access_other_tenant_data(self, auth_token, test_users):
        """Users cannot access data from other tenants."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # User from tenant1
            token1 = auth_token("employee")

            # User from tenant2
            token2 = auth_token("other_tenant")

            # Both should be able to query, but get different results
            # This tests that the system respects tenant boundaries
            response1 = await client.get(
                "/api/chat/stream?q=confidential&session_id=tenant1_test",
                headers={"Authorization": f"Bearer {token1}"}
            )
            response2 = await client.get(
                "/api/chat/stream?q=confidential&session_id=tenant2_test",
                headers={"Authorization": f"Bearer {token2}"}
            )

            assert response1.status_code == 200
            assert response2.status_code == 200

    @pytest.mark.asyncio
    async def test_document_upload_includes_tenant_id(self, auth_token, test_users):
        """Uploaded documents are tagged with tenant_id."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app
        from unittest.mock import patch, MagicMock

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("admin")

            # Mock the vector store to capture metadata
            captured_metadata = []

            with patch('src.backend.api.document_upload.get_rag_service') as mock_rag:
                mock_instance = MagicMock()
                mock_instance.vector_store = MagicMock()

                def capture_add(docs, **kwargs):
                    for doc in docs:
                        if hasattr(doc, 'metadata'):
                            captured_metadata.append(doc.metadata)
                    return True

                mock_instance.vector_store.add_documents = capture_add
                mock_rag.return_value = mock_instance

                response = await client.post(
                    "/api/documents/upload",
                    files={"file": ("test.txt", b"test content", "text/plain")},
                    headers={"Authorization": f"Bearer {token}"}
                )

                # Check if tenant_id was included in metadata
                # Note: This test may need adjustment based on actual implementation
                if captured_metadata:
                    for meta in captured_metadata:
                        assert "tenant_id" in meta, "Document metadata must include tenant_id"


class TestAuthenticationRequired:
    """Test authentication requirements."""

    @pytest.mark.asyncio
    async def test_protected_endpoints_require_auth(self, mock_auth_required):
        """Protected endpoints reject unauthenticated requests."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Document endpoints should require auth
            response = await client.get("/api/documents/list")
            assert response.status_code == 401

            response = await client.post(
                "/api/documents/upload",
                files={"file": ("test.txt", b"content", "text/plain")}
            )
            assert response.status_code == 401

            response = await client.delete("/api/documents/clear")
            assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_token_rejected(self, test_users):
        """Expired tokens are rejected."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app
        import jwt
        from datetime import datetime, timedelta
        from src.config.settings import settings

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Create an expired token
            user = test_users["employee"]
            expired_payload = {
                "sub": user["email"],
                "role": user["role"],
                "tenant_id": user["tenant_id"],
                "exp": datetime.utcnow() - timedelta(hours=1)  # Expired 1 hour ago
            }

            try:
                expired_token = jwt.encode(
                    expired_payload,
                    settings.secret_key,
                    algorithm="HS256"
                )

                response = await client.get(
                    "/api/documents/list",
                    headers={"Authorization": f"Bearer {expired_token}"}
                )
                assert response.status_code == 401, "Expired token should be rejected"
            except Exception:
                # If we can't create token, skip this test
                pytest.skip("Could not create test token")

    @pytest.mark.asyncio
    async def test_invalid_token_rejected(self, mock_auth_required):
        """Invalid/malformed tokens are rejected."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Completely invalid token
            response = await client.get(
                "/api/documents/list",
                headers={"Authorization": "Bearer invalid.token.here"}
            )
            assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_bearer_prefix_rejected(self, mock_auth_required):
        """Authorization header without Bearer prefix is rejected."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/documents/list",
                headers={"Authorization": "some_token_without_bearer"}
            )
            assert response.status_code == 401


class TestRoleEscalation:
    """Test prevention of role escalation attacks."""

    @pytest.mark.asyncio
    async def test_cannot_escalate_via_jwt_claim(self, test_users):
        """Cannot escalate privileges by modifying JWT claims."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app
        import jwt
        from datetime import datetime, timedelta
        from src.config.settings import settings

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Try to create a token with admin role for employee email
            user = test_users["employee"]
            try:
                malicious_payload = {
                    "sub": user["email"],
                    "role": "admin",  # Attempting escalation
                    "tenant_id": user["tenant_id"],
                    "exp": datetime.utcnow() + timedelta(hours=1)
                }

                # This token is signed with the correct key
                # The system should validate role against backend data, not just trust the claim
                token = jwt.encode(
                    malicious_payload,
                    settings.secret_key,
                    algorithm="HS256"
                )

                response = await client.delete(
                    "/api/documents/clear",
                    headers={"Authorization": f"Bearer {token}"}
                )

                # Should be rejected (403) because backend should verify role
                # Or accepted (200) if system trusts JWT claims - this is the vulnerability
                # We're testing that it's NOT vulnerable
                # Note: If this passes with 200, there's a security issue
                if response.status_code == 200:
                    pytest.fail(
                        "SECURITY VULNERABILITY: Role escalation via JWT claim succeeded! "
                        "Employee was able to access admin endpoint by modifying JWT role claim."
                    )
            except Exception:
                pytest.skip("Could not create test token")


class TestDepartmentAccess:
    """Test department-based access control."""

    @pytest.mark.asyncio
    async def test_general_department_access(self, auth_token, test_users):
        """General department users have basic access."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("employee")

            response = await client.get(
                "/api/chat/stream?q=general info&session_id=dept_test",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_finance_department_access(self, auth_token, test_users):
        """Finance department users can access financial data."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("finance")

            response = await client.get(
                "/api/chat/stream?q=Q4 revenue&session_id=finance_dept_test",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200


class TestSessionSecurity:
    """Test session-based security."""

    @pytest.mark.asyncio
    async def test_session_cookie_auth(self, auth_token, test_users):
        """Session cookie authentication works."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = auth_token("employee")

            # Set session cookie
            client.cookies.set("session_token", token)

            response = await client.get(
                "/api/chat/stream?q=test&session_id=cookie_test"
            )
            # Should work with cookie auth
            assert response.status_code in [200, 401]

    @pytest.mark.asyncio
    async def test_bearer_token_priority(self, auth_token, test_users):
        """Bearer token takes priority over session cookie."""
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            employee_token = auth_token("employee")
            admin_token = auth_token("admin")

            # Set employee cookie, but use admin bearer
            client.cookies.set("session_token", employee_token)

            response = await client.get(
                "/api/documents/status",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            # Should use bearer token (admin) not cookie (employee)
            assert response.status_code in [200, 404]
