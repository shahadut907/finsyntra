"""
Security regression tests for FinSyntra hardening.
Run: python -m pytest tests/test_security_hardening.py -v
"""
import pytest
import json
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import timedelta


# ═══════════════════════════════════════════════
# Issue 1: Role injection via ChatRequest
# ═══════════════════════════════════════════════

class TestRoleInjectionBlocked:
    """Verify that ChatRequest no longer accepts client-provided role."""

    def test_chat_request_has_no_role_field(self):
        from src.backend.api.chat import ChatRequest
        fields = ChatRequest.model_fields
        assert "role" not in fields, "ChatRequest must NOT have a 'role' field"

    def test_chat_request_accepts_message_only(self):
        from src.backend.api.chat import ChatRequest
        req = ChatRequest(message="What is the leave policy?")
        assert req.message == "What is the leave policy?"
        assert not hasattr(req, "role") or "role" not in req.model_fields


# ═══════════════════════════════════════════════
# Issue 2: Session ownership
# ═══════════════════════════════════════════════

class TestSessionOwnership:
    """Verify ensure_chat_session checks user ownership."""

    @pytest.fixture(autouse=True)
    def _schema(self):
        from src.backend.database.database import create_tables
        create_tables()

    def test_ensure_chat_session_rejects_wrong_user(self):
        """If session belongs to user A, user B calling ensure_chat_session must raise."""
        from src.backend.database.database import db_manager, ChatSession

        try:
            # Create a session as user_a
            session = db_manager.ensure_chat_session(
                user_id="user_a@test.com",
                session_id="ownership_test_session_1",
                metadata={"tenant_id": "test"}
            )
            assert session is not None

            # Attempt to access as user_b — must raise ValueError
            with pytest.raises(ValueError, match="belongs to another user"):
                db_manager.ensure_chat_session(
                    user_id="user_b@test.com",
                    session_id="ownership_test_session_1",
                    metadata={"tenant_id": "test"}
                )
        except Exception as e:
            if "no such column" in str(e):
                pytest.skip("Migration 002 not yet applied — run 'alembic upgrade head'")
            raise


# ═══════════════════════════════════════════════
# Issue 5: Token type enforcement
# ═══════════════════════════════════════════════

class TestTokenTypeEnforcement:
    """Verify access/refresh token semantics are enforced."""

    def test_access_token_includes_type(self):
        from src.backend.auth.authentication import create_access_token, verify_token
        token = create_access_token({"sub": "test@test.com", "role": "employee", "type": "access"})
        payload = verify_token(token)
        assert payload["type"] == "access"

    def test_refresh_token_includes_type(self):
        from src.backend.auth.authentication import create_access_token, verify_token
        token = create_access_token(
            {"sub": "test@test.com", "role": "employee", "type": "refresh"},
            expires_delta=timedelta(days=7)
        )
        payload = verify_token(token)
        assert payload["type"] == "refresh"

    def test_extract_access_token_skips_refresh_cookie(self):
        """_extract_access_token must NOT fall back to refresh_token cookie."""
        from src.backend.api.auth import _extract_access_token

        # Mock request with only refresh cookie
        mock_request = MagicMock()
        mock_request.headers.get = lambda name, default=None: default  # No Authorization header
        mock_request.cookies.get = lambda name: "fake_refresh" if name == "refresh_token" else None

        token = _extract_access_token(mock_request)
        assert token is None, "Must NOT extract refresh_token cookie for normal auth"


# ═══════════════════════════════════════════════
# Issue 7: Upload RBAC
# ═══════════════════════════════════════════════

class TestUploadRBAC:
    """Verify upload department restrictions."""

    def test_employee_cannot_upload_to_finance(self):
        """Employee role should not be able to upload to finance department."""
        from src.config.roles import Role, ROLE_PERMISSIONS
        caller_role = Role.EMPLOYEE
        perms = ROLE_PERMISSIONS.get(caller_role)
        allowed_depts = {d.value for d in perms.allowed_departments}
        assert "finance" not in allowed_depts, "Employee must NOT have access to finance department"

    def test_admin_can_upload_to_any_department(self):
        """Admin role should be able to upload to any department."""
        from src.config.roles import Role, ROLE_PERMISSIONS
        caller_role = Role.ADMIN
        perms = ROLE_PERMISSIONS.get(caller_role)
        allowed_depts = {d.value for d in perms.allowed_departments}
        assert "finance" in allowed_depts
        assert "hr" in allowed_depts
        assert "engineering" in allowed_depts


# ═══════════════════════════════════════════════
# Issue 11: Vector deletion tenant scope
# ═══════════════════════════════════════════════

class TestVectorDeletionTenantScope:
    """Verify delete_documents_by_sources accepts tenant_id parameter."""

    def test_delete_signature_accepts_tenant_id(self):
        import inspect
        from src.backend.services.vector_store import VectorStore
        sig = inspect.signature(VectorStore.delete_documents_by_sources)
        assert "tenant_id" in sig.parameters, \
            "delete_documents_by_sources must accept tenant_id parameter"

    def test_get_unique_sources_accepts_tenant_id(self):
        import inspect
        from src.backend.services.vector_store import VectorStore
        sig = inspect.signature(VectorStore.get_unique_sources)
        assert "tenant_id" in sig.parameters, \
            "get_unique_sources must accept tenant_id parameter"

    def test_get_collection_stats_accepts_tenant_id(self):
        import inspect
        from src.backend.services.vector_store import VectorStore
        sig = inspect.signature(VectorStore.get_collection_stats)
        assert "tenant_id" in sig.parameters, \
            "get_collection_stats must accept tenant_id parameter"


# ═══════════════════════════════════════════════
# Issue 12: Gitignore coverage
# ═══════════════════════════════════════════════

class TestGitignore:
    """Verify .gitignore covers sensitive files."""

    def test_gitignore_covers_secrets(self):
        with open(".gitignore", "r") as f:
            content = f.read()
        
        required_patterns = [
            ".env",
            "secret_key.txt",
            "jwt_key.txt",
            "cookies.txt",
            "*.db",
            "__pycache__",
            "venv/",
        ]
        for pattern in required_patterns:
            assert pattern in content, f".gitignore must contain '{pattern}'"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
