"""
Knowledge Base Statistics API
FinSyntra AI - Provides document/knowledge statistics for the chat welcome UI
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime

from src.backend.api.auth_deps import get_current_user
from src.config.roles import ROLE_PERMISSIONS, Role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["Knowledge"])


def _user_field(user, name):
    """Read a field from the authenticated user (a dict from get_current_user)."""
    return user.get(name) if isinstance(user, dict) else getattr(user, name, None)


@router.get("/stats")
async def get_knowledge_stats(current_user = Depends(get_current_user)):
    """
    Get knowledge base statistics for the current user's tenant.
    Returns document counts, type breakdown, and last updated timestamp.
    """
    try:
        # Import here to avoid circular imports
        from src.backend.services.vector_store import VectorStore
        
        vector_store = VectorStore()
        # SECURITY: Scope stats to caller's tenant AND to the departments the
        # caller's role may read, mirroring retrieval-time RBAC.
        caller_tenant = _user_field(current_user, "tenant_id")
        try:
            caller_role = Role(_user_field(current_user, "role") or Role.EMPLOYEE.value)
        except ValueError:
            caller_role = Role.EMPLOYEE
        permissions = ROLE_PERMISSIONS.get(caller_role)
        allowed_departments = (
            {d.value for d in permissions.allowed_departments} if permissions else set()
        )

        documents: dict = {}
        if caller_tenant:
            records = vector_store.collection.get(
                where={"tenant_id": caller_tenant}, include=["metadatas"]
            )
            for metadata in records.get("metadatas") or []:
                department = (metadata or {}).get("department")
                source = (metadata or {}).get("source")
                if source and department in allowed_departments:
                    documents[source] = department

        # Count distinct documents (not chunks), bucketed by file type and department.
        document_types = {"pdf": 0, "csv": 0, "md": 0, "other": 0}
        departments: dict = {}
        for source, department in documents.items():
            extension = source.rsplit(".", 1)[-1].lower() if "." in source else ""
            if extension == "markdown":
                extension = "md"
            document_types[extension if extension in ("pdf", "csv", "md") else "other"] += 1
            departments[department] = departments.get(department, 0) + 1

        return {
            "total_documents": len(documents),
            "document_types": document_types,
            "departments": departments,
            "last_updated": datetime.now().isoformat(),
            "user_role": caller_role.value,
            "tenant_id": caller_tenant,
        }

    except Exception as e:
        logger.error(f"Failed to get knowledge stats: {e}")
        # Return graceful fallback
        return {
            "total_documents": 0,
            "document_types": {"pdf": 0, "csv": 0, "md": 0, "other": 0},
            "departments": {},
            "last_updated": None,
            "error": "Could not retrieve knowledge stats"
        }
