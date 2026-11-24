"""RBAC module — re-exports from roles config for convenience."""
from src.config.roles import (
    Role,
    Department,
    Permission,
    ROLE_PERMISSIONS,
    DOCUMENT_CATEGORIES,
    can_access_document,
    get_accessible_documents,
    has_access,
    get_access_denied_message,
    is_admin_user,
    get_admin_level,
)

__all__ = [
    "Role",
    "Department",
    "Permission",
    "ROLE_PERMISSIONS",
    "DOCUMENT_CATEGORIES",
    "can_access_document",
    "get_accessible_documents",
    "has_access",
    "get_access_denied_message",
    "is_admin_user",
    "get_admin_level",
]
