"""
Security regression tests v2 — FinSyntra hardening.
Run: python -m pytest tests/test_security_hardening_v2.py -v

Covers:
  - DEMO_USERS tenant_id presence (no "default")
  - JWT tenant_id propagation
  - Refresh token → access token tenant_id propagation
  - Session ownership with tenant context
  - Token type enforcement (access vs refresh)
  - Vector store tenant isolation
  - ChatSession model tenant_id column
  - deps.py production guard
  - tenant_beta users existence
  - ensure_chat_session tenant mismatch rejection
  - Alembic migration chain
  - Frontend cookie-only auth (no Bearer header)
  - Tracked secrets cleaned from git
  - Admin document tenant scoping
"""
import pytest
import inspect
import re
import importlib.util
import os
import subprocess
from unittest.mock import MagicMock
from datetime import timedelta


# ═══════════════════════════════════════════════
# 1. DEMO_USERS tenant_id
# ═══════════════════════════════════════════════

class TestDemoUsersTenant:
    """All demo users must have explicit tenant_id — never fall back to 'default'."""

    def test_every_demo_user_has_tenant_id(self):
        from src.config.roles import DEMO_USERS
        for email, data in DEMO_USERS.items():
            assert "tenant_id" in data, (
                f"DEMO_USERS['{email}'] missing tenant_id"
            )
            assert data["tenant_id"] != "default", (
                f"DEMO_USERS['{email}'] still uses tenant_id='default'"
            )

    def test_tenant_id_not_empty(self):
        from src.config.roles import DEMO_USERS
        for email, data in DEMO_USERS.items():
            tid = data.get("tenant_id", "")
            assert tid and isinstance(tid, str) and len(tid.strip()) > 0, (
                f"DEMO_USERS['{email}'] has empty tenant_id"
            )


# ═══════════════════════════════════════════════
# 2. JWT tenant_id propagation
# ═══════════════════════════════════════════════

class TestJWTTenantPropagation:
    """JWT tokens must contain tenant_id claim."""

    def test_access_token_has_tenant_id(self):
        from src.backend.auth.authentication import create_access_token, verify_token
        token = create_access_token({
            "sub": "test@finsolve.com",
            "role": "finance",
            "name": "Test",
            "tenant_id": "tenant_acme",
            "type": "access"
        })
        payload = verify_token(token)
        assert payload.get("tenant_id") == "tenant_acme"

    def test_refresh_token_has_tenant_id(self):
        from src.backend.auth.authentication import create_access_token, verify_token
        token = create_access_token(
            {
                "sub": "test@finsolve.com",
                "role": "finance",
                "tenant_id": "tenant_beta",
                "type": "refresh"
            },
            expires_delta=timedelta(days=7)
        )
        payload = verify_token(token)
        assert payload.get("tenant_id") == "tenant_beta"


# ═══════════════════════════════════════════════
# 3. _build_user includes tenant_id
# ═══════════════════════════════════════════════

class TestBuildUserTenant:
    """Identity, role and tenant come from the authoritative User row
    (resolve_active_user); the former _build_user helper no longer exists. A
    user without a tenant must be rejected, never given a 'default' tenant."""

    @staticmethod
    def _user(email, tenant_id):
        from src.backend.database.database import SessionLocal, User, create_tables
        create_tables()
        db = SessionLocal()
        try:
            db.query(User).filter(User.email == email).delete()
            db.add(User(id=email, username=email, email=email, hashed_password="x",
                        role="finance", tenant_id=tenant_id, is_active=True))
            db.commit()
        finally:
            db.close()

    def test_build_user_with_tenant_id(self):
        from src.backend.api.auth_deps import resolve_active_user
        self._user("tenant.check@finsolve.test", "tenant_acme")
        user = resolve_active_user("tenant.check@finsolve.test")
        assert user["tenant_id"] == "tenant_acme"

    def test_build_user_without_tenant_id_returns_none(self):
        """A user row with no tenant is rejected (401), never mapped to 'default'."""
        from fastapi import HTTPException
        from src.backend.api.auth_deps import resolve_active_user
        self._user("no.tenant@finsolve.test", None)
        with pytest.raises(HTTPException) as exc:
            resolve_active_user("no.tenant@finsolve.test")
        assert exc.value.status_code == 401


# ═══════════════════════════════════════════════
# 4. ChatSession model has tenant_id column
# ═══════════════════════════════════════════════

class TestChatSessionModel:
    """ChatSession ORM model must have a discrete tenant_id column."""

    def test_chat_session_has_tenant_id_column(self):
        from src.backend.database.database import ChatSession
        assert hasattr(ChatSession, "tenant_id"), (
            "ChatSession model missing tenant_id column"
        )

    def test_chat_session_tenant_id_is_indexed(self):
        from src.backend.database.database import ChatSession
        # Check column properties via SQLAlchemy column
        col = ChatSession.__table__.columns.get("tenant_id")
        assert col is not None, "tenant_id column not found in table definition"
        assert col.index is True or any(
            "tenant_id" in str(idx.columns)
            for idx in ChatSession.__table__.indexes
        ), "tenant_id column should be indexed"


# ═══════════════════════════════════════════════
# 5. Session ownership + tenant
# ═══════════════════════════════════════════════

class TestSessionOwnershipWithTenant:
    """ensure_chat_session must set tenant_id on creation and verify ownership."""

    @pytest.fixture(autouse=True)
    def _schema(self):
        from src.backend.database.database import create_tables
        create_tables()

    def test_new_session_gets_tenant_id(self):
        from src.backend.database.database import db_manager
        try:
            session = db_manager.ensure_chat_session(
                user_id="tenant_test_user@test.com",
                session_id="tenant_test_session_001",
                metadata={"tenant_id": "tenant_acme"}
            )
            assert session is not None
            assert session.tenant_id == "tenant_acme"
        except Exception as e:
            if "no such column" in str(e):
                pytest.skip("Migration 002 not yet applied to dev DB — run 'alembic upgrade head'")
            raise

    def test_existing_unresolved_session_cannot_be_claimed(self):
        """NULL historical ownership requires explicit offline triage."""
        from src.backend.database.database import db_manager, ChatSession
        try:
            db = db_manager.get_db()
            try:
                db.add(ChatSession(
                    id="backfill_test_session_001",
                    user_id="backfill_user@test.com",
                    tenant_id=None,
                    meta={},
                ))
                db.commit()
            finally:
                db_manager.close_db(db)

            with pytest.raises(ValueError, match="unresolved ownership"):
                db_manager.ensure_chat_session(
                    user_id="backfill_user@test.com",
                    session_id="backfill_test_session_001",
                    metadata={"tenant_id": "tenant_backfill"},
                )
        except Exception as e:
            if "no such column" in str(e):
                pytest.skip("Migration 002 not yet applied to dev DB — run 'alembic upgrade head'")
            raise

    def test_tenant_mismatch_rejected(self):
        """Same user, same session, different tenant → ValueError."""
        from src.backend.database.database import db_manager
        try:
            # Create session with tenant_acme
            db_manager.ensure_chat_session(
                user_id="mismatch_user@test.com",
                session_id="mismatch_test_session_001",
                metadata={"tenant_id": "tenant_acme"}
            )
            # Try again with different tenant — must raise ValueError
            with pytest.raises(ValueError, match="Conversation not found"):
                db_manager.ensure_chat_session(
                    user_id="mismatch_user@test.com",
                    session_id="mismatch_test_session_001",
                    metadata={"tenant_id": "tenant_beta"}
                )
        except Exception as e:
            if "no such column" in str(e):
                pytest.skip("Migration 002 not yet applied to dev DB — run 'alembic upgrade head'")
            raise


# ═══════════════════════════════════════════════
# 6. Token type enforcement (re-verify)
# ═══════════════════════════════════════════════

class TestTokenTypeEnforcementV2:
    """Verify access/refresh token semantics are enforced."""

    def test_extract_access_token_skips_refresh_cookie(self):
        """_extract_access_token must NOT fall back to refresh_token cookie."""
        from src.backend.api.auth import _extract_access_token

        from src.backend.api.auth_deps import _extract_access_credential
        mock_request = MagicMock()
        # Starlette's headers.get(name, default) returns the default when absent.
        mock_request.headers.get = lambda name, default=None: default
        mock_request.cookies.get = lambda name: "fake_refresh" if name == "refresh_token" else None
        token = _extract_access_token(mock_request)
        assert token is None, "Must NOT extract refresh_token cookie for normal auth"
        assert _extract_access_credential(mock_request) is None, (
            "The authoritative dependency must not accept the refresh cookie either"
        )


# ═══════════════════════════════════════════════
# 7. Vector store tenant isolation
# ═══════════════════════════════════════════════

class TestVectorStoreTenantIsolation:
    """Verify vector store functions accept tenant_id parameter."""

    def test_search_documents_accepts_tenant_id(self):
        from src.backend.services.vector_store import VectorStore
        sig = inspect.signature(VectorStore.search_documents)
        assert "tenant_id" in sig.parameters, \
            "search_documents must accept tenant_id parameter"

    def test_add_documents_accepts_tenant_id(self):
        from src.backend.services.vector_store import VectorStore
        sig = inspect.signature(VectorStore.add_documents)
        assert "tenant_id" in sig.parameters, \
            "add_documents must accept tenant_id parameter"

    def test_delete_documents_by_sources_accepts_tenant_id(self):
        from src.backend.services.vector_store import VectorStore
        sig = inspect.signature(VectorStore.delete_documents_by_sources)
        assert "tenant_id" in sig.parameters, \
            "delete_documents_by_sources must accept tenant_id parameter"

    def test_keyword_search_accepts_tenant_id(self):
        from src.backend.services.vector_store import VectorStore
        sig = inspect.signature(VectorStore.keyword_search)
        assert "tenant_id" in sig.parameters, \
            "keyword_search must accept tenant_id parameter"


# ═══════════════════════════════════════════════
# 8. deps.py production guard
# ═══════════════════════════════════════════════

class TestDepsProductionGuard:
    """deps.py must not provide any hardcoded/fallback user in any mode: it only
    re-exports the authoritative, DB-backed dependencies."""

    def test_deps_user_has_non_default_tenant(self):
        import src.backend.api.auth_deps as auth_deps
        import src.backend.api.deps as deps_module
        assert deps_module.get_current_user is auth_deps.get_current_user
        assert deps_module.get_current_admin_user is auth_deps.get_current_admin_user
        assert deps_module.get_current_user_optional is auth_deps.get_current_user_optional
        source = inspect.getsource(deps_module)
        for forbidden in ('"default"', "'default'", "tenant_dev", "bypass_auth", "BYPASS_AUTH"):
            assert forbidden not in source, f"deps.py must not contain {forbidden}"


# ═══════════════════════════════════════════════
# 9. Upload RBAC department restrictions
# ═══════════════════════════════════════════════

class TestUploadRBACv2:
    """Verify upload department restrictions by role."""

    def test_finance_cannot_upload_to_hr(self):
        from src.config.roles import Role, ROLE_PERMISSIONS
        perms = ROLE_PERMISSIONS.get(Role.FINANCE)
        allowed = {d.value for d in perms.allowed_departments}
        assert "hr" not in allowed, "Finance role must NOT upload to HR"

    def test_employee_cannot_upload_to_executive(self):
        from src.config.roles import Role, ROLE_PERMISSIONS
        perms = ROLE_PERMISSIONS.get(Role.EMPLOYEE)
        allowed = {d.value for d in perms.allowed_departments}
        assert "executive" not in allowed, "Employee must NOT upload to executive"

    def test_c_level_can_access_all_departments(self):
        from src.config.roles import Role, ROLE_PERMISSIONS
        perms = ROLE_PERMISSIONS.get(Role.C_LEVEL)
        allowed = {d.value for d in perms.allowed_departments}
        for dept in ["finance", "hr", "engineering"]:
            assert dept in allowed, f"C-level should have access to {dept}"


# ═══════════════════════════════════════════════
# 10. Alembic migration chain
# ═══════════════════════════════════════════════

class TestAlembicMigrationChain:
    """Verify the active tenant migration follows the baseline schema."""

    def _load_migration(self):
        migration_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "alembic", "versions", "0002_chat_session_tenant_id.py"
        )
        spec = importlib.util.spec_from_file_location("migration_002", migration_path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_migration_002_depends_on_001(self):
        m = self._load_migration()
        assert m.down_revision == "0001_baseline_schema", (
            "Tenant migration must depend on the runnable baseline"
        )
        assert m.revision == "0002_chat_session_tenant_id"

    def test_migration_002_has_upgrade_and_downgrade(self):
        m = self._load_migration()
        assert hasattr(m, "upgrade") and callable(m.upgrade)
        assert hasattr(m, "downgrade") and callable(m.downgrade)


# ═══════════════════════════════════════════════
# 11. Refresh token tenant propagation
# ═══════════════════════════════════════════════

class TestRefreshTokenTenantPropagation:
    """Verify that refresh-created access tokens include tenant_id."""

    def test_refresh_flow_includes_tenant_id_in_new_access(self):
        """Simulates: create refresh token with tenant → verify it propagates."""
        from src.backend.auth.authentication import create_access_token, verify_token
        # Create a "refresh" token with tenant_id
        refresh_token = create_access_token(
            {
                "sub": "admin@finsolve.com",
                "role": "admin",
                "tenant_id": "tenant_acme",
                "type": "refresh"
            },
            expires_delta=timedelta(days=7)
        )
        # Decode it — the tenant_id must be present
        payload = verify_token(refresh_token)
        assert payload.get("tenant_id") == "tenant_acme", (
            "Refresh token must carry tenant_id claim"
        )

    def test_auth_refresh_handler_source_includes_tenant_id(self):
        """Tenant claims are not trusted: /auth/refresh re-resolves the user (and
        therefore the tenant) from the authoritative DB row on every rotation."""
        import src.backend.api.auth as auth_module
        source = inspect.getsource(auth_module.refresh)
        assert "resolve_active_user(" in source, (
            "/auth/refresh must re-resolve tenant/role from the DB, not from token claims"
        )


# ═══════════════════════════════════════════════
# 12. tenant_beta users
# ═══════════════════════════════════════════════

class TestTenantBetaUsers:
    """Verify tenant_beta demo users exist for cross-tenant isolation testing."""

    def test_beta_employee_exists(self):
        from src.config.roles import DEMO_USERS
        assert "beta.employee@finsolve.com" in DEMO_USERS, (
            "beta.employee@finsolve.com must exist in DEMO_USERS"
        )
        user = DEMO_USERS["beta.employee@finsolve.com"]
        assert user["tenant_id"] == "tenant_beta"
        assert user["role"] == "employee"

    def test_beta_admin_exists(self):
        from src.config.roles import DEMO_USERS
        assert "beta.admin@finsolve.com" in DEMO_USERS, (
            "beta.admin@finsolve.com must exist in DEMO_USERS"
        )
        user = DEMO_USERS["beta.admin@finsolve.com"]
        assert user["tenant_id"] == "tenant_beta"
        assert user["role"] == "admin"
        assert user.get("is_admin") is True

    def test_at_least_two_distinct_tenants(self):
        """There must be at least 2 distinct tenant_ids across DEMO_USERS."""
        from src.config.roles import DEMO_USERS
        tenants = {d.get("tenant_id") for d in DEMO_USERS.values() if d.get("tenant_id")}
        assert len(tenants) >= 2, (
            f"Expected at least 2 tenants, found: {tenants}"
        )


# ═══════════════════════════════════════════════
# 13. No tenant_id="default" in backend API code
# ═══════════════════════════════════════════════

class TestNoDefaultTenantFallback:
    """Backend API modules must NOT fall back to tenant_id='default'."""

    def _check_module_no_default_tenant(self, module):
        source = inspect.getsource(module)
        # Match patterns like: "default" in get("tenant_id", ...) or = "default"
        # Exclude comments and docstrings
        lines = source.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Skip comments and docstrings
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            # Check for tenant_id = "default" or .get("tenant_id", "default")
            if 'tenant_id' in stripped and '"default"' in stripped:
                # Allow generate_general_response default param which is now ""
                if "def generate_general_response" in stripped:
                    continue
                pytest.fail(
                    f"tenant_id='default' found in {module.__name__} "
                    f"at line {i}: {stripped}"
                )

    def test_auth_deps_no_default(self):
        import src.backend.api.auth_deps as m
        self._check_module_no_default_tenant(m)

    def test_auth_no_default(self):
        import src.backend.api.auth as m
        self._check_module_no_default_tenant(m)

    def test_chat_no_default(self):
        import src.backend.api.chat as m
        self._check_module_no_default_tenant(m)

    def test_document_upload_no_default(self):
        import src.backend.api.document_upload as m
        self._check_module_no_default_tenant(m)


# ═══════════════════════════════════════════════
# 14. Frontend cookie-only auth
# ═══════════════════════════════════════════════

class TestFrontendCookieOnlyAuth:
    """Frontend must NOT send Authorization: Bearer header after login."""

    def test_authcontext_no_bearer_after_login(self):
        """AuthContext.js login() must not send Authorization: Bearer to /auth/me."""
        auth_context_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "frontend", "src", "contexts", "AuthContext.js"
        )
        with open(auth_context_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Skip comments
            if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
                continue
            # Fail on active code that sets Authorization: Bearer header
            if "Authorization" in stripped and "Bearer" in stripped:
                pytest.fail(
                    f"AuthContext.js line {i} sends Bearer header in active code: {stripped}"
                )

    def test_api_client_no_bearer(self):
        """apiClient.js must NOT attach Bearer token from localStorage."""
        api_client_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "frontend", "src", "lib", "apiClient.js"
        )
        with open(api_client_path, "r") as f:
            content = f.read()

        # Check that no active code sets Authorization header
        for i, line in enumerate(content.split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            if "Authorization" in stripped and "Bearer" in stripped:
                pytest.fail(
                    f"apiClient.js line {i} sets Bearer header: {stripped}"
                )


# ═══════════════════════════════════════════════
# 15. Tracked secrets cleaned
# ═══════════════════════════════════════════════

class TestTrackedSecretsClean:
    """Sensitive files must NOT be tracked in git."""

    def test_no_tracked_secrets(self):
        """Verify .env, secret_key.txt, etc. are not tracked by git."""
        sensitive_files = [".env", "secret_key.txt", "jwt_key.txt", "cookies.txt", "data/finsolve.db"]
        try:
            result = subprocess.run(
                ["git", "ls-files"] + sensitive_files,
                capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            tracked = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
            assert len(tracked) == 0, (
                f"Sensitive files still tracked by git: {tracked}"
            )
        except FileNotFoundError:
            pytest.skip("git not available")

    def test_gitignore_covers_secrets(self):
        gitignore_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".gitignore"
        )
        with open(gitignore_path, "r") as f:
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


# ═══════════════════════════════════════════════
# 16. Railway env no real password
# ═══════════════════════════════════════════════

class TestRailwayEnvClean:
    """railway.env.example must NOT contain real passwords."""

    def test_no_hardcoded_password(self):
        railway_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "railway.env.example"
        )
        with open(railway_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "demo_admin_2024" not in content, (
            "railway.env.example still contains hardcoded password"
        )
        # Secret-bearing settings must be empty or the repository-wide
        # placeholder (the convention .env.example also follows).
        for line in content.splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            if re.search(r"SECRET|PASSWORD|API_KEY|TOKEN", key) and "EXPIRE" not in key:
                assert value.strip() in ("", "MUST_BE_SET_VIA_ENV"), (
                    f"railway.env.example sets a value for {key}"
                )


# ═══════════════════════════════════════════════
# 17. SSE persistence deferral verification
# ═══════════════════════════════════════════════

class TestSSEPersistenceDeferral:
    """SSE must acknowledge completion only after durable persistence."""

    def test_small_talk_persists_before_done_ack(self):
        """The complete/DONE acknowledgement must mean the exchange committed."""
        import src.backend.api.chat_stream as cs_module
        source = inspect.getsource(cs_module.generate_sse_response)
        # Find the small-talk block
        small_talk_idx = source.index("INTENT: small_talk")
        # Find [DONE] after small talk
        done_idx = source.index('[DONE]', small_talk_idx)
        # Find _persist_conversation after small talk
        persist_idx = source.index('_persist_conversation', small_talk_idx)
        assert persist_idx < done_idx, (
            "Small-talk persistence must commit before [DONE] acknowledges durability"
        )

    def test_cancelled_error_handler_exists(self):
        """generate_sse_response must handle asyncio.CancelledError."""
        import src.backend.api.chat_stream as cs_module
        source = inspect.getsource(cs_module.generate_sse_response)
        assert "CancelledError" in source, (
            "generate_sse_response must handle asyncio.CancelledError"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
