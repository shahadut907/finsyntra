"""Phase 2: public-demo identities (Admin/Finance/HR/Engineering/General) and
demo-corpus completeness.

Covers:
  A. demo-login identifier -> exactly one dedicated public-demo identity;
     an invalid identifier is rejected.
  B. every public-demo identity carries is_public_demo=True, the correct
     role, department, and tenant.
  C. cross-department RBAC denial (Finance/HR/Engineering can't reach each
     other's departments), and server-side read-only enforcement for both
     the demo Admin and demo employee identities.
  D. Engineering demo document is classified Department.ENGINEERING;
     Finance/HR/General demo sources remain correctly classified; an
     unclassified filename still fails closed (returns None).
  E. demo login for every identity uses the normal JWT/cookie/CSRF path and
     never returns a plaintext password.

No heavy embedding model, no Chroma ingestion, no Docker, no installs.
RBAC/security assertions use the authoritative ROLE_PERMISSIONS table
directly (the same table vector_store._get_accessible_departments reads)
rather than constructing a VectorStore, which would eagerly load
SentenceTransformer.
"""
import pytest
from httpx import AsyncClient, ASGITransport

from src.backend.api.endpoints import app
from src.backend.database.database import create_tables
from src.backend.middleware.security import rate_limiter
from src.config.roles import (
    Department, Role, ROLE_PERMISSIONS, get_bootstrap_department,
    is_bootstrap_classified, has_access,
)
from src.config.settings import settings


# ---------------------------------------------------------------------------
# A. Identity mapping
# ---------------------------------------------------------------------------

class TestIdentityMapping:
    def test_each_identifier_maps_to_exactly_one_dedicated_identity(self):
        from src.backend.api.auth import PUBLIC_DEMO_IDENTITIES

        assert PUBLIC_DEMO_IDENTITIES["admin"]["email"] == "portfolio.admin@finsolve.demo"
        assert PUBLIC_DEMO_IDENTITIES["general"]["email"] == "portfolio.employee@finsolve.demo"
        assert PUBLIC_DEMO_IDENTITIES["finance"]["email"] == "portfolio.finance@finsolve.demo"
        assert PUBLIC_DEMO_IDENTITIES["hr"]["email"] == "portfolio.hr@finsolve.demo"
        assert PUBLIC_DEMO_IDENTITIES["engineering"]["email"] == "portfolio.engineering@finsolve.demo"

    def test_employee_alias_resolves_to_the_same_identity_as_general(self):
        from src.backend.api.auth import PUBLIC_DEMO_IDENTITIES

        assert PUBLIC_DEMO_IDENTITIES["employee"] == PUBLIC_DEMO_IDENTITIES["general"]

    def test_no_two_identifiers_share_an_identity_except_the_general_alias(self):
        from src.backend.api.auth import PUBLIC_DEMO_IDENTITIES

        emails_by_identifier = {k: v["email"] for k, v in PUBLIC_DEMO_IDENTITIES.items()}
        distinct_emails = set(emails_by_identifier.values())
        # 7 identifiers, 6 distinct identities (employee is an alias of general;
        # ceo maps to the dedicated c_level identity).
        assert len(emails_by_identifier) == 7
        assert len(distinct_emails) == 6

    def test_invalid_demo_identity_is_rejected_by_the_request_model(self):
        from pydantic import ValidationError
        from src.backend.api.auth import DemoLoginRequest

        with pytest.raises(ValidationError):
            DemoLoginRequest(role="superadmin")


# ---------------------------------------------------------------------------
# B. Attributes of every public-demo identity
# ---------------------------------------------------------------------------

class TestPublicDemoIdentityAttributes:
    @pytest.fixture(autouse=True)
    def _schema(self):
        create_tables()

    @pytest.mark.parametrize("email,expected_role,expected_department", [
        ("portfolio.admin@finsolve.demo", "admin", "Administration"),
        ("portfolio.employee@finsolve.demo", "employee", "General"),
        ("portfolio.finance@finsolve.demo", "finance", "Finance"),
        ("portfolio.hr@finsolve.demo", "hr", "Human Resources"),
        ("portfolio.engineering@finsolve.demo", "engineering", "Engineering"),
    ])
    def test_identity_attributes(self, email, expected_role, expected_department):
        from src.backend.api.auth_deps import resolve_active_user

        user = resolve_active_user(email)
        assert user["is_public_demo"] is True
        assert user["role"] == expected_role
        assert user["department"] == expected_department
        assert user["tenant_id"] == settings.demo_tenant_id

    def test_employee_accounts_are_not_admins(self):
        from src.backend.api.auth_deps import resolve_active_user

        for email in (
            "portfolio.employee@finsolve.demo",
            "portfolio.finance@finsolve.demo",
            "portfolio.hr@finsolve.demo",
            "portfolio.engineering@finsolve.demo",
        ):
            user = resolve_active_user(email)
            assert user["is_admin"] is False
            assert user["role"] not in {"admin", "c_level"}

    def test_demo_admin_remains_admin(self):
        from src.backend.api.auth_deps import resolve_active_user

        user = resolve_active_user("portfolio.admin@finsolve.demo")
        assert user["is_admin"] is True
        assert user["role"] == "admin"

    def test_internal_credentialed_department_leads_were_not_converted(self):
        """finance.lead@/hr.lead@/peter.pandey@ must remain ordinary
        tenant_acme accounts — Phase 2 must not repurpose them."""
        from src.backend.api.auth_deps import resolve_active_user

        for email, expected_role in (
            ("finance.lead@finsolve.com", "finance"),
            ("hr.lead@finsolve.com", "hr"),
            ("peter.pandey@finsolve.com", "engineering"),
        ):
            user = resolve_active_user(email)
            assert user["is_public_demo"] is False
            assert user["tenant_id"] == "tenant_acme"
            assert user["role"] == expected_role


# ---------------------------------------------------------------------------
# C. Cross-department RBAC and server-side read-only enforcement
# ---------------------------------------------------------------------------

class TestCrossDepartmentRbac:
    """Uses the authoritative ROLE_PERMISSIONS table directly — the same
    table vector_store._get_accessible_departments(user_role) reads — so
    this proves the real filtering rule without constructing a VectorStore
    (which would eagerly load SentenceTransformer)."""

    def test_finance_cannot_reach_hr_or_engineering(self):
        assert has_access(Role.FINANCE, Department.HR) is False
        assert has_access(Role.FINANCE, Department.ENGINEERING) is False
        assert has_access(Role.FINANCE, Department.FINANCE) is True
        assert has_access(Role.FINANCE, Department.GENERAL) is True

    def test_hr_cannot_reach_finance_or_engineering(self):
        assert has_access(Role.HR, Department.FINANCE) is False
        assert has_access(Role.HR, Department.ENGINEERING) is False
        assert has_access(Role.HR, Department.HR) is True
        assert has_access(Role.HR, Department.GENERAL) is True

    def test_engineering_cannot_reach_finance_or_hr(self):
        assert has_access(Role.ENGINEERING, Department.FINANCE) is False
        assert has_access(Role.ENGINEERING, Department.HR) is False
        assert has_access(Role.ENGINEERING, Department.ENGINEERING) is True
        assert has_access(Role.ENGINEERING, Department.GENERAL) is True

    def test_general_employee_only_reaches_general(self):
        """Current intended general-access policy: Role.EMPLOYEE is scoped
        to Department.GENERAL only."""
        perms = ROLE_PERMISSIONS[Role.EMPLOYEE]
        assert perms.allowed_departments == {Department.GENERAL}


@pytest.fixture
async def client(monkeypatch):
    create_tables()
    rate_limiter.reset()
    monkeypatch.setattr(settings, "public_demo_enabled", True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        yield value
    rate_limiter.reset()


async def _demo_login(client, identity):
    response = await client.post("/auth/demo-login", json={"role": identity})
    assert response.status_code == 200, response.text
    return response


class TestServerSideReadOnlyEnforcement:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("identity", ["finance", "hr", "engineering", "general"])
    async def test_public_demo_employee_cannot_reach_admin_endpoints(self, client, identity):
        await _demo_login(client, identity)
        response = await client.get("/api/admin/users")
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "ADMIN_REQUIRED"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("identity", ["finance", "hr", "engineering", "general"])
    async def test_public_demo_employee_upload_is_blocked(self, client, identity):
        await _demo_login(client, identity)
        csrf = client.cookies.get("csrf_token")
        response = await client.post(
            "/api/documents/upload", headers={"X-CSRF-Token": csrf},
            data={"department": "general"},
            files={"file": ("demo.md", b"# Mutation\n" + b"safe text " * 10, "text/markdown")},
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "PUBLIC_DEMO_READ_ONLY"

    @pytest.mark.asyncio
    async def test_public_demo_admin_cannot_refresh_the_document_index(self, client):
        """/documents/refresh only clears a process-local cache and reads
        stats (no Chroma/SQL/disk write) but is blocked for public-demo
        accounts anyway — see document_upload.py's updated docstring."""
        await _demo_login(client, "admin")
        csrf = client.cookies.get("csrf_token")
        response = await client.post("/api/documents/refresh", headers={"X-CSRF-Token": csrf})
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "PUBLIC_DEMO_READ_ONLY"

    @pytest.mark.asyncio
    async def test_public_demo_admin_still_blocked_from_destructive_document_ops(self, client):
        await _demo_login(client, "admin")
        csrf = client.cookies.get("csrf_token")
        headers = {"X-CSRF-Token": csrf}
        blocked = [
            await client.delete("/api/documents/clear", headers=headers),
            await client.post("/api/admin/users", headers=headers, json={
                "email": "new@finsolve.demo", "name": "New", "role": "employee",
                "department": "General", "password": "not-a-real-secret",
            }),
        ]
        assert {r.status_code for r in blocked} == {403}
        assert all(r.json()["detail"]["code"] == "PUBLIC_DEMO_READ_ONLY" for r in blocked)


# ---------------------------------------------------------------------------
# D. Demo document classification
# ---------------------------------------------------------------------------

class TestDemoDocumentClassification:
    def test_engineering_demo_document_is_classified_engineering(self):
        assert get_bootstrap_department("demo_engineering_platform.md") == Department.ENGINEERING
        assert is_bootstrap_classified("demo_engineering_platform.md") is True

    def test_finance_hr_general_demo_sources_remain_correctly_classified(self):
        assert get_bootstrap_department("demo_financial_summary.md") == Department.FINANCE
        assert get_bootstrap_department("demo_hr_sample.csv") == Department.HR
        assert get_bootstrap_department("demo_company_policies.md") == Department.GENERAL
        assert get_bootstrap_department("demo_employee_handbook.md") == Department.GENERAL

    def test_unclassified_demo_filename_still_fails_closed(self):
        assert get_bootstrap_department("totally_unknown_demo_file.md") is None
        assert is_bootstrap_classified("totally_unknown_demo_file.md") is False

    def test_engineering_demo_file_exists_on_disk(self):
        from src.config.settings import get_demo_documents_path
        import os

        path = os.path.join(get_demo_documents_path(), "demo_engineering_platform.md")
        assert os.path.isfile(path)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        # No secrets, no PII markers, and a handful of concrete retrievable facts.
        assert "password" not in content.lower()
        assert "api_key" not in content.lower()
        assert "99.9 percent" in content
        assert "Sev1" in content

    def test_engineering_demo_document_gets_registered_as_a_document_row(self):
        """seed_public_demo_documents() (called by create_tables()) must
        register the new file as a Document row — metadata only, no Chroma
        ingestion, no embedding call."""
        from src.backend.database.database import Document, SessionLocal

        create_tables()
        db = SessionLocal()
        try:
            row = db.query(Document).filter(
                Document.tenant_id == settings.demo_tenant_id,
                Document.storage_path == "demo_engineering_platform.md",
            ).first()
        finally:
            db.close()
        assert row is not None
        assert row.department == "engineering"
        assert row.is_active is True


# ---------------------------------------------------------------------------
# E. Authentication path
# ---------------------------------------------------------------------------

class TestDemoLoginAuthenticationPath:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("identity,expected_email,expected_role", [
        ("admin", "portfolio.admin@finsolve.demo", "admin"),
        ("general", "portfolio.employee@finsolve.demo", "employee"),
        ("finance", "portfolio.finance@finsolve.demo", "finance"),
        ("hr", "portfolio.hr@finsolve.demo", "hr"),
        ("engineering", "portfolio.engineering@finsolve.demo", "engineering"),
    ])
    async def test_demo_login_issues_normal_secure_session(
        self, client, identity, expected_email, expected_role
    ):
        response = await _demo_login(client, identity)
        body = response.json()
        assert body["user"]["email"] == expected_email
        assert body["user"]["role"] == expected_role
        assert body["user"]["is_public_demo"] is True
        assert client.cookies.get("session_token")
        assert client.cookies.get("refresh_token")
        assert client.cookies.get("csrf_token")

        me = await client.get("/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == expected_email

    @pytest.mark.asyncio
    @pytest.mark.parametrize("identity", ["admin", "general", "finance", "hr", "engineering"])
    async def test_demo_login_response_never_contains_a_plaintext_password(self, client, identity):
        response = await _demo_login(client, identity)
        text = response.text.lower()
        assert "password123" not in text
        assert "admin123" not in text
        assert "demo123" not in text
        assert "hashed_password" not in text
        assert "$2b$" not in text
