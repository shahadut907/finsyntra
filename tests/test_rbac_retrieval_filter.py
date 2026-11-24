"""
Tests for RBAC retrieval-layer filtering.
Validates that the access matrix defined in roles.py is correctly enforced
at the vector store and RAG service levels.
"""
import pytest
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.roles import (
    Role, Department, Permission,
    ROLE_PERMISSIONS, can_access_document, get_accessible_documents, has_access,
)


class TestAccessMatrix:
    """Verify the ROLE_PERMISSIONS access matrix returns correct departments."""

    def test_employee_only_general(self):
        perms = ROLE_PERMISSIONS[Role.EMPLOYEE]
        assert perms.allowed_departments == {Department.GENERAL}

    def test_finance_general_and_finance(self):
        perms = ROLE_PERMISSIONS[Role.FINANCE]
        assert perms.allowed_departments == {Department.GENERAL, Department.FINANCE}

    def test_hr_general_and_hr(self):
        perms = ROLE_PERMISSIONS[Role.HR]
        assert perms.allowed_departments == {Department.GENERAL, Department.HR}

    def test_engineering_general_and_engineering(self):
        perms = ROLE_PERMISSIONS[Role.ENGINEERING]
        assert perms.allowed_departments == {Department.GENERAL, Department.ENGINEERING}

    def test_marketing_general_and_marketing(self):
        perms = ROLE_PERMISSIONS[Role.MARKETING]
        assert perms.allowed_departments == {Department.GENERAL, Department.MARKETING}

    def test_c_level_all_except_it(self):
        perms = ROLE_PERMISSIONS[Role.C_LEVEL]
        expected = {
            Department.GENERAL, Department.ENGINEERING, Department.FINANCE,
            Department.MARKETING, Department.HR, Department.EXECUTIVE,
        }
        assert perms.allowed_departments == expected

    def test_admin_all_departments(self):
        perms = ROLE_PERMISSIONS[Role.ADMIN]
        expected = {
            Department.GENERAL, Department.ENGINEERING, Department.FINANCE,
            Department.MARKETING, Department.HR, Department.EXECUTIVE, Department.IT,
        }
        assert perms.allowed_departments == expected


class TestCanAccessDocument:
    """Validate can_access_document enforces the access matrix per document."""

    # === EMPLOYEE should NOT access department-specific docs ===
    def test_employee_blocked_from_finance(self):
        assert can_access_document(Role.EMPLOYEE, "financial_summary.md") is False

    def test_employee_blocked_from_hr(self):
        assert can_access_document(Role.EMPLOYEE, "sample_hr_data.csv") is False

    def test_employee_blocked_from_engineering(self):
        assert can_access_document(Role.EMPLOYEE, "engineering_projects.csv") is False

    def test_employee_blocked_from_executive(self):
        assert can_access_document(Role.EMPLOYEE, "strategic_plan_2025_2027.md") is False

    # === EMPLOYEE CAN access general docs ===
    def test_employee_can_access_handbook(self):
        assert can_access_document(Role.EMPLOYEE, "employee_handbook.md") is True

    def test_employee_can_access_policies(self):
        assert can_access_document(Role.EMPLOYEE, "company_policies.md") is True

    # === EMPLOYEE access to unknown docs (should default to general) ===
    def test_employee_can_access_unknown_doc(self):
        assert can_access_document(Role.EMPLOYEE, "random_unknown_file.md") is True

    # === FINANCE can access finance + general ===
    def test_finance_can_access_financial_summary(self):
        assert can_access_document(Role.FINANCE, "financial_summary.md") is True

    def test_finance_can_access_budget(self):
        assert can_access_document(Role.FINANCE, "budget_analysis.csv") is True

    def test_finance_can_access_handbook(self):
        assert can_access_document(Role.FINANCE, "employee_handbook.md") is True

    def test_finance_blocked_from_hr(self):
        assert can_access_document(Role.FINANCE, "sample_hr_data.csv") is False

    # === C_LEVEL can access everything except IT ===
    def test_c_level_can_access_finance(self):
        assert can_access_document(Role.C_LEVEL, "financial_summary.md") is True

    def test_c_level_can_access_hr(self):
        assert can_access_document(Role.C_LEVEL, "sample_hr_data.csv") is True

    def test_c_level_can_access_engineering(self):
        assert can_access_document(Role.C_LEVEL, "engineering_projects.csv") is True

    def test_c_level_can_access_executive(self):
        assert can_access_document(Role.C_LEVEL, "strategic_plan_2025_2027.md") is True

    # === ADMIN can access everything including IT ===
    def test_admin_can_access_system_config(self):
        assert can_access_document(Role.ADMIN, "system_config.md") is True

    def test_admin_can_access_finance(self):
        assert can_access_document(Role.ADMIN, "financial_summary.md") is True


class TestGetAccessibleDocuments:
    """Validate get_accessible_documents returns the right list per role."""

    def test_employee_gets_only_general_docs(self):
        docs = get_accessible_documents(Role.EMPLOYEE)
        for doc_name in docs:
            from src.config.roles import DOCUMENT_CATEGORIES
            doc_info = DOCUMENT_CATEGORIES.get(doc_name, {})
            dept = doc_info.get("department", Department.GENERAL)
            assert dept == Department.GENERAL, f"Employee should not see {doc_name} (dept={dept})"

    def test_finance_includes_finance_docs(self):
        docs = get_accessible_documents(Role.FINANCE)
        assert "financial_summary.md" in docs
        assert "budget_analysis.csv" in docs

    def test_c_level_includes_all_non_it(self):
        docs = get_accessible_documents(Role.C_LEVEL)
        assert "financial_summary.md" in docs
        assert "sample_hr_data.csv" in docs
        assert "strategic_plan_2025_2027.md" in docs

    def test_admin_includes_it_docs(self):
        docs = get_accessible_documents(Role.ADMIN)
        assert "system_config.md" in docs
        assert "admin_manual.pdf" in docs


class TestHasAccess:
    """Validate the has_access function for department-level checks."""

    def test_employee_no_finance_access(self):
        assert has_access(Role.EMPLOYEE, Department.FINANCE) is False

    def test_finance_has_finance_access(self):
        assert has_access(Role.FINANCE, Department.FINANCE) is True

    def test_c_level_has_executive_access(self):
        assert has_access(Role.C_LEVEL, Department.EXECUTIVE) is True

    def test_admin_has_it_access(self):
        assert has_access(Role.ADMIN, Department.IT) is True

    def test_employee_has_general_access(self):
        assert has_access(Role.EMPLOYEE, Department.GENERAL) is True


class TestVectorStoreAccessibleDepartments:
    """Validate VectorStore._get_accessible_departments returns correct values."""

    def test_employee_gets_general_only(self):
        from src.backend.services.vector_store import VectorStore
        # Use the static method without initializing the full store
        vs = object.__new__(VectorStore)
        result = vs._get_accessible_departments(Role.EMPLOYEE)
        assert result == ["general"]

    def test_finance_gets_general_and_finance(self):
        from src.backend.services.vector_store import VectorStore
        vs = object.__new__(VectorStore)
        result = vs._get_accessible_departments(Role.FINANCE)
        assert set(result) == {"general", "finance"}

    def test_c_level_gets_all_non_it(self):
        from src.backend.services.vector_store import VectorStore
        vs = object.__new__(VectorStore)
        result = vs._get_accessible_departments(Role.C_LEVEL)
        expected = {"general", "engineering", "finance", "marketing", "hr", "executive"}
        assert set(result) == expected

    def test_admin_gets_all(self):
        from src.backend.services.vector_store import VectorStore
        vs = object.__new__(VectorStore)
        result = vs._get_accessible_departments(Role.ADMIN)
        expected = {"general", "engineering", "finance", "marketing", "hr", "executive", "it"}
        assert set(result) == expected
