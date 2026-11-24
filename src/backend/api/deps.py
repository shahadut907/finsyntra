"""Backward-compatible imports for the authoritative API dependencies."""
from src.backend.api.auth_deps import (
    get_current_admin_user,
    get_current_user,
    get_current_user_optional,
)

__all__ = ["get_current_user", "get_current_user_optional", "get_current_admin_user"]
