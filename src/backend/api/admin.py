"""
Admin API Router - Dashboard metrics and management endpoints
RBAC: admin role required for all endpoints
"""
import asyncio
import time
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Depends, Request, status, UploadFile, File, Form, Body
from pydantic import BaseModel, Field
from pathlib import Path
import hashlib
import re

from src.config.roles import Role
from src.backend.services.rag_service import RAGService
from src.backend.auth.authentication import get_password_hash
from src.backend.api.auth_deps import get_current_admin_user, require_non_demo_mutation
from src.backend.database.database import (
    SessionLocal, ChatSession, ChatMessage, Document, RefreshToken, User,
)
from src.config.settings import get_demo_documents_path, get_raw_documents_path

logger = logging.getLogger(__name__)

# Create admin router
router = APIRouter(prefix="/admin", tags=["admin"])

# Track application start time for uptime
APP_START_TIME = time.time()

# Metrics counters (in-memory, will reset on restart)
METRICS = {
    "total_requests": 0,
    "successful_requests": 0,
    "failed_requests": 0,
    "active_sessions": 0,
    "messages_last_30m": 0,
    "last_sync": datetime.now().isoformat()
}

def increment_request_metric(success: bool = True):
    """Increment request counters"""
    METRICS["total_requests"] += 1
    if success:
        METRICS["successful_requests"] += 1
    else:
        METRICS["failed_requests"] += 1


def track_session(active: bool = True):
    """Track active session count"""
    if active:
        METRICS["active_sessions"] += 1
    else:
        METRICS["active_sessions"] = max(0, METRICS["active_sessions"] - 1)


def track_message():
    """Increment message counter"""
    METRICS["messages_last_30m"] += 1


# Response models
class AdminOverviewResponse(BaseModel):
    """Admin dashboard overview metrics"""
    users_total: int
    sessions_active: int
    documents_total: int
    msgs_last_30m: int
    uptime_seconds: float
    success_rate: float
    total_requests: int
    last_sync: str
    timestamp: str
    # NEW: Total cumulative counts from database
    total_sessions: int = 0
    total_messages: int = 0


class RecentActivityItem(BaseModel):
    """Recent activity log item"""
    id: str
    timestamp: str
    event_type: str
    user: Optional[str]
    details: str
    status: str


class RecentActivityResponse(BaseModel):
    """Recent activity list"""
    activities: List[RecentActivityItem]
    total: int


@router.get("/overview", response_model=AdminOverviewResponse)
async def get_admin_overview(
    current_user: Dict = Depends(get_current_admin_user)
):
    """
    GET /admin/overview
    
    Returns comprehensive dashboard metrics:
    - users_total: Total user count
    - sessions_active: Active session count
    - documents_total: Total documents in vector store
    - msgs_last_30m: Messages in last 30 minutes
    - uptime_seconds: Server uptime
    - success_rate: API success rate percentage
    - total_requests: Total API requests
    - last_sync: Last data sync timestamp
    
    RBAC: admin role required
    """
    trace_id = str(uuid.uuid4())
    user_role = current_user.get('role', 'unknown')
    user_email = current_user.get('email', 'unknown')
    
    # Log probe: /admin/* Auth status and role
    logger.info(f"[{trace_id}] Admin fetch Auth: Yes role={user_role} path=/admin/overview")
    
    try:
        # Calculate uptime
        uptime_seconds = time.time() - APP_START_TIME
        
        # Get document count from vector store
        documents_total = 0
        try:
            # Try to get RAG service and count documents
            # Import here to avoid circular dependency at module load time
            import sys
            if 'src.backend.api.endpoints' in sys.modules:
                endpoints_module = sys.modules['src.backend.api.endpoints']
                rag_service = getattr(endpoints_module, 'rag_service', None)
                
                if rag_service and hasattr(rag_service, 'vector_store'):
                    # Try to get collection stats
                    if hasattr(rag_service.vector_store, 'get_collection_stats'):
                        collection_stats = rag_service.vector_store.get_collection_stats(
                            tenant_id=current_user["tenant_id"]
                        )
                        if isinstance(collection_stats, dict):
                            documents_total = collection_stats.get('total_documents', 0)
        except Exception as e:
            logger.warning(f"[{trace_id}] Could not fetch document count: {e}")
            documents_total = 0
        
        # Calculate success rate
        success_rate = 0.0
        if METRICS["total_requests"] > 0:
            success_rate = (METRICS["successful_requests"] / METRICS["total_requests"]) * 100
        
        # === Query REAL data from database ===
        users_total = 0
        
        # Query actual database for session and message counts
        db = None
        try:
            db = SessionLocal()
            thirty_min_ago = datetime.utcnow() - timedelta(minutes=30)
            
            # Active sessions: sessions with updated_at in last 30 min
            sessions_active = db.query(ChatSession).filter(
                ChatSession.tenant_id == current_user["tenant_id"],
                ChatSession.updated_at >= thirty_min_ago
            ).count()
            
            # Fallback: if no updated_at matches, check created_at
            if sessions_active == 0:
                sessions_active = db.query(ChatSession).filter(
                    ChatSession.tenant_id == current_user["tenant_id"],
                    ChatSession.created_at >= thirty_min_ago
                ).count()
            
            # Messages in last 30 minutes
            msgs_last_30m = db.query(ChatMessage).join(
                ChatSession, ChatSession.id == ChatMessage.session_id
            ).filter(
                ChatSession.tenant_id == current_user["tenant_id"],
                ChatMessage.timestamp >= thirty_min_ago
            ).count()
            
            # Also add total counts for context
            total_sessions = db.query(ChatSession).filter(
                ChatSession.tenant_id == current_user["tenant_id"]
            ).count()
            total_messages = db.query(ChatMessage).join(
                ChatSession, ChatSession.id == ChatMessage.session_id
            ).filter(ChatSession.tenant_id == current_user["tenant_id"]).count()
            users_total = db.query(User).filter(
                User.tenant_id == current_user["tenant_id"]
            ).count()
            
            logger.info(f"[{trace_id}] DB stats: sessions_30m={sessions_active} msgs_30m={msgs_last_30m} total_sessions={total_sessions} total_msgs={total_messages}")
            
        except Exception as db_error:
            logger.warning(f"[{trace_id}] Database query failed, using fallback: {db_error}")
            sessions_active = METRICS.get("active_sessions", 0)
            msgs_last_30m = METRICS.get("messages_last_30m", 0)
            total_sessions = 0
            total_messages = 0
        finally:
            if db:
                db.close()
        
        if documents_total == 0:
            db = SessionLocal()
            try:
                documents_total = db.query(Document).filter(
                    Document.tenant_id == current_user["tenant_id"],
                    Document.is_active.is_(True),
                ).count()
            finally:
                db.close()
        
        response = AdminOverviewResponse(
            users_total=users_total,
            sessions_active=sessions_active,
            documents_total=documents_total,
            msgs_last_30m=msgs_last_30m,
            uptime_seconds=round(uptime_seconds, 2),
            success_rate=round(success_rate, 2),
            total_requests=METRICS["total_requests"],
            last_sync=METRICS["last_sync"],
            timestamp=datetime.now().isoformat(),
            total_sessions=total_sessions,
            total_messages=total_messages
        )
        
        increment_request_metric(success=True)
        
        logger.info(f"[{trace_id}] /admin/overview -> docs={documents_total} uptime={uptime_seconds:.0f}s")
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        increment_request_metric(success=False)
        logger.error(f"[{trace_id}] /admin/overview error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch admin overview"
        )


@router.get("/recent-activity", response_model=RecentActivityResponse)
async def get_recent_activity(
    limit: int = 20,
    current_user: Dict = Depends(get_current_admin_user)
):
    """
    GET /admin/recent-activity
    
    Returns recent system activity events (last 20 by default).
    
    RBAC: admin role required
    """
    trace_id = str(uuid.uuid4())
    user_role = current_user.get('role', 'unknown')
    
    # Log probe: /admin/* Auth status and role
    logger.info(f"[{trace_id}] Admin fetch Auth: Yes role={user_role} path=/admin/recent-activity")
    
    try:
        # Query REAL recent activity from database
        db = None
        activities = []
        
        try:
            db = SessionLocal()
            
            # Get recent chat messages as activity
            recent_messages = db.query(ChatMessage).join(
                ChatSession, ChatSession.id == ChatMessage.session_id
            ).filter(
                ChatSession.tenant_id == current_user["tenant_id"]
            ).order_by(
                ChatMessage.timestamp.desc()
            ).limit(limit).all()
            
            for msg in recent_messages:
                # Get user info from session if available
                user_email = msg.user_id if msg.user_id else "unknown"
                content_preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
                
                activities.append(
                    RecentActivityItem(
                        id=msg.id,
                        timestamp=msg.timestamp.isoformat() if msg.timestamp else datetime.now().isoformat(),
                        event_type="chat_message",
                        user=user_email,
                        details=f"[{msg.message_type}] {content_preview}",
                        status="success"
                    )
                )
            
            logger.info(f"[{trace_id}] Returning {len(activities)} recent activities from database")
            
        except Exception as db_error:
            logger.warning(f"[{trace_id}] Database query failed for recent activity: {db_error}")
            # Fallback to placeholder data
            now = datetime.now()
            activities = [
                RecentActivityItem(
                    id=str(uuid.uuid4()),
                    timestamp=(now - timedelta(minutes=i*5)).isoformat(),
                    event_type="system",
                    user="system",
                    details="Database query unavailable",
                    status="warning"
                )
                for i in range(min(limit, 5))
            ]
        finally:
            if db:
                db.close()
        
        increment_request_metric(success=True)
        
        return RecentActivityResponse(
            activities=activities,
            total=len(activities)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        increment_request_metric(success=False)
        logger.error(f"[{trace_id}] /admin/recent-activity error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch recent activity"
        )


@router.get("/health")
async def admin_health(current_user: Dict = Depends(get_current_admin_user)):
    """Authenticated admin API liveness check."""
    return {
        "status": "healthy",
        "service": "admin-api",
        "timestamp": datetime.now().isoformat()
    }


# ============== USERS ENDPOINT ==============
@router.get("/users")
async def get_admin_users(
    current_user: Dict = Depends(get_current_admin_user)
):
    """
    GET /admin/users
    Returns list of all users from DEMO_USERS config.
    RBAC: admin role required
    """
    trace_id = str(uuid.uuid4())
    logger.info(f"[{trace_id}] Admin fetch: /admin/users")
    
    try:
        users = []
        db = SessionLocal()
        records = db.query(User).filter(User.tenant_id == current_user["tenant_id"]).all()
        for record in records:
            users.append({
                "id": record.id,
                "email": record.email,
                "name": record.full_name or record.email.split("@")[0],
                "role": record.role,
                "department": record.department or "General",
                "is_active": record.is_active,
                "is_online": False,
                "total_messages": 0,
                "last_login": record.last_login.isoformat() if record.last_login else None,
            })
        db.close()
        
        increment_request_metric(success=True)
        return users
        
    except Exception as e:
        increment_request_metric(success=False)
        logger.error(f"[{trace_id}] /admin/users error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch users"
        )


# ============== USER CRUD ENDPOINTS ==============

class CreateUserRequest(BaseModel):
    email: str
    name: str
    role: str = "employee"
    department: str = "General"
    # Required: there is intentionally no default password.
    password: str = Field(..., min_length=10, max_length=128)

class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    is_active: Optional[bool] = None


@router.post("/users")
async def create_admin_user(
    payload: CreateUserRequest,
    current_user: Dict = Depends(get_current_admin_user)
):
    """
    POST /admin/users
    Create a new user in the runtime DEMO_USERS dict.
    RBAC: admin role required
    """
    require_non_demo_mutation(current_user)
    trace_id = str(uuid.uuid4())
    logger.info(f"[{trace_id}] Admin create user: {payload.email}")

    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email address")

    role = payload.role.lower()
    if role not in {item.value for item in Role}:
        raise HTTPException(status_code=400, detail="Invalid role")
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == email).first():
            raise HTTPException(status_code=409, detail="User already exists")
        db.add(User(
            id=email, username=email, email=email,
            hashed_password=get_password_hash(payload.password),
            full_name=payload.name.strip(), role=role,
            tenant_id=current_user["tenant_id"],
            department=payload.department or "General", is_active=True,
        ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    increment_request_metric(success=True)
    return {
        "success": True,
        "message": f"User {email} created",
        "user": {
            "id": email,
            "email": email,
            "name": payload.name.strip(),
            "role": payload.role,
            "department": payload.department or "General",
            "is_active": True,
        },
    }


@router.put("/users/{user_id}")
async def update_admin_user(
    user_id: str,
    payload: UpdateUserRequest,
    current_user: Dict = Depends(get_current_admin_user)
):
    """
    PUT /admin/users/{user_id}
    Update an existing user.  user_id is the email address.
    RBAC: admin role required
    """
    require_non_demo_mutation(current_user)
    trace_id = str(uuid.uuid4())
    logger.info(f"[{trace_id}] Admin update user: {user_id}")

    db = SessionLocal()
    try:
        user = db.query(User).filter(
            User.id == user_id, User.tenant_id == current_user["tenant_id"]
        ).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if payload.role is not None:
            role = payload.role.lower()
            if role not in {item.value for item in Role}:
                raise HTTPException(status_code=400, detail="Invalid role")
            user.role = role
        if payload.name is not None:
            user.full_name = payload.name.strip()
        if payload.department is not None:
            user.department = payload.department
        if payload.is_active is not None:
            user.is_active = payload.is_active
            if not user.is_active:
                db.query(RefreshToken).filter(
                    RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
                ).update({"revoked_at": datetime.utcnow()}, synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    increment_request_metric(success=True)
    return {
        "success": True,
        "message": f"User {user_id} updated",
    }


@router.delete("/users/{user_id}")
async def delete_admin_user(
    user_id: str,
    current_user: Dict = Depends(get_current_admin_user)
):
    """
    DELETE /admin/users/{user_id}
    Remove a user from the runtime DEMO_USERS dict.
    RBAC: admin role required
    """
    require_non_demo_mutation(current_user)
    trace_id = str(uuid.uuid4())
    logger.info(f"[{trace_id}] Admin delete user: {user_id}")

    # Prevent deleting yourself
    if user_id == current_user.get("email"):
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    db = SessionLocal()
    try:
        user = db.query(User).filter(
            User.id == user_id, User.tenant_id == current_user["tenant_id"]
        ).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        db.query(RefreshToken).filter(RefreshToken.user_id == user.id).delete(
            synchronize_session=False
        )
        db.delete(user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    increment_request_metric(success=True)
    return {"success": True, "message": f"User {user_id} deleted"}


@router.patch("/users/{user_id}/toggle-status")
async def toggle_user_status(
    user_id: str,
    body: dict = Body(...),
    current_user: Dict = Depends(get_current_admin_user)
):
    """
    PATCH /admin/users/{user_id}/toggle-status
    Toggle a user's active status.
    RBAC: admin role required
    """
    require_non_demo_mutation(current_user)
    trace_id = str(uuid.uuid4())
    logger.info(f"[{trace_id}] Admin toggle status: {user_id}")

    new_status = body.get("is_active", True)
    if not isinstance(new_status, bool):
        raise HTTPException(status_code=400, detail="is_active must be boolean")
    db = SessionLocal()
    try:
        user = db.query(User).filter(
            User.id == user_id, User.tenant_id == current_user["tenant_id"]
        ).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user.is_active = new_status
        if not new_status:
            db.query(RefreshToken).filter(
                RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
            ).update({"revoked_at": datetime.utcnow()}, synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    increment_request_metric(success=True)
    return {
        "success": True,
        "message": f"User {user_id} {'activated' if new_status else 'deactivated'}",
    }


# ============== DOCUMENTS ENDPOINT ==============
@router.get("/documents")
async def get_admin_documents(
    current_user: Dict = Depends(get_current_admin_user)
):
    """
    GET /admin/documents
    Returns list of uploaded documents and indexed document stats.
    RBAC: admin role required
    """
    db = SessionLocal()
    try:
        records = db.query(Document).filter(
            Document.tenant_id == current_user["tenant_id"],
            Document.is_active.is_(True),
        ).order_by(Document.uploaded_at.desc()).all()
        return [{
            "id": item.id,
            "filename": item.filename,
            "department": item.department,
            "file_type": Path(item.filename).suffix.lower().lstrip("."),
            "size_bytes": item.file_size or 0,
            "size_formatted": format_file_size(item.file_size or 0),
            "status": "indexed" if item.processed_at else "uploaded",
            "uploaded_at": item.uploaded_at.isoformat() if item.uploaded_at else None,
            "chunk_count": item.chunk_count or 0,
            "is_sample": bool(item.is_protected_demo),
        } for item in records]
    finally:
        db.close()


# ============== DOCUMENT CRUD ENDPOINTS ==============

def _owned_document(doc_id: str, tenant_id: str) -> tuple[Document, Path]:
    db = SessionLocal()
    try:
        record = db.query(Document).filter(
            Document.id == doc_id,
            Document.tenant_id == tenant_id,
            Document.is_active.is_(True),
        ).first()
        if not record or not record.storage_path:
            raise HTTPException(status_code=404, detail="Document not found")
        root = Path(
            get_demo_documents_path() if record.is_protected_demo else get_raw_documents_path()
        ).resolve()
        path = (root / record.storage_path).resolve()
        if path.parent != root or not path.is_file():
            raise HTTPException(status_code=404, detail="Document not found")
        db.expunge(record)
        return record, path
    finally:
        db.close()

@router.get("/documents/{doc_id}/content")
async def get_document_content(
    doc_id: str,
    current_user: Dict = Depends(get_current_admin_user)
):
    """
    GET /admin/documents/{doc_id}/content
    Return the text content of a document for the viewer modal.
    RBAC: admin role required
    """
    trace_id = str(uuid.uuid4())
    logger.info(f"[{trace_id}] Admin view document: {doc_id}")

    record, file_path = _owned_document(doc_id, current_user["tenant_id"])
    if file_path.suffix.lower() == ".pdf":
        # PDF bytes are not text; show what was actually indexed instead.
        from src.backend.api.document_upload import get_rag_service
        passages = get_rag_service().vector_store.get_source_passages(
            record.storage_path, current_user["tenant_id"], [record.department],
        )
        content = "\n\n".join(passages) or "No indexed text is available for this PDF."
    else:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    return {"content": content, "filename": record.filename,
            "size_bytes": file_path.stat().st_size}


@router.get("/documents/{doc_id}/download")
async def download_document(
    doc_id: str,
    current_user: Dict = Depends(get_current_admin_user)
):
    """
    GET /admin/documents/{doc_id}/download
    Return document as base64 for client-side download.
    RBAC: admin role required
    """
    import base64
    trace_id = str(uuid.uuid4())
    logger.info(f"[{trace_id}] Admin download document: {doc_id}")

    record, file_path = _owned_document(doc_id, current_user["tenant_id"])
    raw_bytes = file_path.read_bytes()
    return {"data": base64.b64encode(raw_bytes).decode("ascii"),
            "filename": record.filename, "content_type": record.content_type,
            "size_bytes": len(raw_bytes)}


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    current_user: Dict = Depends(get_current_admin_user)
):
    """
    DELETE /admin/documents/{doc_id}
    Delete a document file from disk.
    RBAC: admin role required
    """
    require_non_demo_mutation(current_user)
    trace_id = str(uuid.uuid4())
    logger.info(f"[{trace_id}] Admin delete document: {doc_id}")

    record, file_path = _owned_document(doc_id, current_user["tenant_id"])
    _require_document_manager(current_user, record)
    file_removed = _retire_document(record, file_path, current_user["tenant_id"], trace_id)
    return {"success": True, "message": f"Document {record.filename} deleted",
            "bundled_sample": bool(record.is_protected_demo), "file_removed": file_removed}


@router.post("/documents/{doc_id}/replace")
async def replace_document(
    doc_id: str,
    file: UploadFile = File(...),
    current_user: Dict = Depends(get_current_admin_user)
):
    """Replace a document with a new version in the same department.

    The new version is validated and indexed first, then the old one is
    retired. If retiring the old version fails, the new one is withdrawn so the
    two versions are never left searchable side by side.
    """
    require_non_demo_mutation(current_user)
    trace_id = str(uuid.uuid4())
    tenant_id = current_user["tenant_id"]
    logger.info(f"[{trace_id}] Admin replace document: {doc_id}")

    record, file_path = _owned_document(doc_id, tenant_id)
    _require_document_manager(current_user, record)

    from src.backend.api.document_upload import upload_document_realtime
    # Same department as the old version, so visibility does not change.
    result = await upload_document_realtime(
        file=file, department=record.department, force_refresh=False, current_user=current_user,
    )
    new_id = result["file_info"]["document_id"]

    try:
        file_removed = _retire_document(record, file_path, tenant_id, trace_id, replaced_by=new_id)
    except HTTPException:
        new_record, new_path = _owned_document(new_id, tenant_id)
        try:
            _retire_document(new_record, new_path, tenant_id, trace_id)
        except HTTPException:
            logger.error(f"[{trace_id}] Replace rollback failed; {doc_id} and {new_id} both active")
            raise HTTPException(
                status_code=503,
                detail="Replacement failed and the new version could not be withdrawn; "
                       "both versions are active, delete one of them",
            )
        raise HTTPException(status_code=503,
                            detail="Replacement failed; the original document is unchanged")

    db = SessionLocal()
    try:
        new_row = db.query(Document).filter(Document.id == new_id).first()
        if new_row:
            new_row.meta = {**(new_row.meta or {}), "replaces": record.id}
            db.commit()
    except Exception:
        db.rollback()
        logger.warning(f"[{trace_id}] Could not record replacement link for {new_id}", exc_info=True)
    finally:
        db.close()

    return {"success": True,
            "message": f"{record.filename} replaced by {result['file_info']['original_filename']}",
            "replaced_id": record.id, "document_id": new_id,
            "department": record.department,
            "chunks_created": result["processing_info"]["chunks_created"],
            "file_removed": file_removed}


@router.post("/documents/{doc_id}/reindex")
async def reindex_document(
    doc_id: str,
    current_user: Dict = Depends(get_current_admin_user)
):
    """Re-chunk an active document's stored file with the current processor.

    Needed once for files indexed before section-aware chunking (a PDF used
    to become a single chunk). Same tenant, department and storage name;
    new chunks are indexed before the old ones are removed.
    """
    require_non_demo_mutation(current_user)
    trace_id = str(uuid.uuid4())
    tenant_id = current_user["tenant_id"]
    record, file_path = _owned_document(doc_id, tenant_id)
    _require_document_manager(current_user, record)
    rag = RAGService()
    try:
        result = await asyncio.to_thread(rag.reindex_document, file_path, tenant_id, record.department)
    except Exception:
        logger.exception(f"[{trace_id}] Reindex failed for document {doc_id}")
        raise HTTPException(status_code=503, detail="Document could not be re-indexed; its previous index is unchanged")
    db = SessionLocal()
    try:
        owned = db.query(Document).filter(Document.id == record.id, Document.tenant_id == tenant_id).first()
        if owned:
            owned.chunk_count = result["chunks_after"]
            owned.processed_at = datetime.utcnow()
            db.commit()
    except Exception:
        db.rollback()
        logger.warning(f"[{trace_id}] Could not update chunk count for {doc_id}", exc_info=True)
    finally:
        db.close()
    logger.info(f"[{trace_id}] Reindexed document {doc_id}: {result}")
    return {"success": True, "document_id": record.id, **result}


def _require_document_manager(current_user: Dict, record: Document) -> None:
    """Bundled public-demo samples are managed only by the tenant administrator.

    Callers have already passed get_current_admin_user and
    require_non_demo_mutation (role and demo flag from the DB user row) and
    _owned_document (row scoped to the caller's tenant), so this only narrows
    the admin roles: c_level may manage uploads but not the bundled samples.
    """
    if record.is_protected_demo and current_user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only the tenant administrator can manage bundled demo samples",
        )


def _retire_document(record: Document, file_path: Path, tenant_id: str, trace_id: str,
                     replaced_by: Optional[str] = None) -> bool:
    """Make a document unretrievable, then inactive, then remove its file.

    Order matters: retrieval stops first (verified vector delete), then cached
    answers that may cite it, then the metadata row. Raises 503 on any step
    that would leave it retrievable or listed; returns whether the stored file
    was removed. Bundled samples are packaged source (src/data/demo_corpus),
    so their file stays: the inactive row is the tombstone that every read
    route, the demo seed and startup indexing honour.
    """
    rag = RAGService()
    try:
        rag.vector_store.delete_documents_by_sources(
            [record.storage_path], tenant_id=tenant_id, raise_on_error=True,
        )
    except Exception:
        logger.exception(f"[{trace_id}] Vector removal failed for document {record.id}")
        raise HTTPException(status_code=503,
                            detail="Document could not be removed from the search index; nothing was changed")
    rag._response_cache.clear()

    db = SessionLocal()
    try:
        owned = db.query(Document).filter(
            Document.id == record.id, Document.tenant_id == tenant_id
        ).first()
        if owned:
            owned.is_active = False
            owned.meta = {**(owned.meta or {}), "retired_at": datetime.utcnow().isoformat(),
                          **({"replaced_by": replaced_by} if replaced_by else {})}
            db.commit()
    except Exception:
        db.rollback()
        logger.exception(f"[{trace_id}] Metadata retirement failed for document {record.id}")
        raise HTTPException(status_code=503,
                            detail="Document was removed from search but its record could not be "
                                   "updated; retry the delete")
    finally:
        db.close()

    if record.is_protected_demo:
        return False
    try:
        file_path.unlink(missing_ok=True)
        return True
    except OSError:
        logger.warning(f"[{trace_id}] Stored file for {record.id} could not be removed", exc_info=True)
        return False


def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable form"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# ============== ANALYTICS ENDPOINT ==============
@router.get("/analytics")
async def get_admin_analytics(
    current_user: Dict = Depends(get_current_admin_user)
):
    """
    GET /admin/analytics
    Returns system analytics and metrics.
    RBAC: admin role required
    """
    trace_id = str(uuid.uuid4())
    logger.info(f"[{trace_id}] Admin fetch: /admin/analytics")
    
    try:
        uptime_seconds = time.time() - APP_START_TIME
        hours, remainder = divmod(int(uptime_seconds), 3600)
        minutes, _ = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m"
        
        # Calculate success rate
        success_rate = "100%"
        if METRICS["total_requests"] > 0:
            rate = (METRICS["successful_requests"] / METRICS["total_requests"]) * 100
            success_rate = f"{rate:.1f}%"
        
        # Get system metrics
        cpu_percent = 0
        memory_percent = 0
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory_percent = psutil.virtual_memory().percent
        except ImportError:
            logger.warning("psutil not available for system metrics")
        except Exception as e:
            logger.warning(f"Could not get system metrics: {e}")
        
        analytics = {
            "system_uptime": uptime_str,
            "uptime_seconds": int(uptime_seconds),
            "success_rate": success_rate,
            "avg_response_time": "< 1s",
            "total_requests": METRICS["total_requests"],
            "successful_requests": METRICS["successful_requests"],
            "failed_requests": METRICS["failed_requests"],
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "recent_activity": [],
            "timestamp": datetime.now().isoformat()
        }
        
        increment_request_metric(success=True)
        return analytics
        
    except Exception as e:
        increment_request_metric(success=False)
        logger.error(f"[{trace_id}] /admin/analytics error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch analytics"
        )


# ============== ORGANIZATIONS ENDPOINT ==============
@router.get("/organizations")
async def get_admin_organizations(
    current_user: Dict = Depends(get_current_admin_user)
):
    """
    GET /admin/organizations
    Returns list of organizations/tenants.
    RBAC: admin role required
    """
    trace_id = str(uuid.uuid4())
    logger.info(f"[{trace_id}] Admin fetch: /admin/organizations")
    
    try:
        db = SessionLocal()
        try:
            tenant_user_count = db.query(User).filter(
                User.tenant_id == current_user["tenant_id"]
            ).count()
        finally:
            db.close()
        organizations = [
            {
                "id": current_user["tenant_id"],
                "name": current_user["tenant_id"],
                "users_count": tenant_user_count,
                "status": "active",
            }
        ]
        
        increment_request_metric(success=True)
        return organizations
        
    except Exception as e:
        increment_request_metric(success=False)
        logger.error(f"[{trace_id}] /admin/organizations error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch organizations"
        )


# ============== AUDIT LOGS ENDPOINT ==============
@router.get("/audit-logs")
async def get_admin_audit_logs(
    limit: int = 50,
    current_user: Dict = Depends(get_current_admin_user)
):
    """
    GET /admin/audit-logs
    Returns recent audit log entries.
    RBAC: admin role required
    """
    trace_id = str(uuid.uuid4())
    logger.info(f"[{trace_id}] Admin fetch: /admin/audit-logs")
    
    try:
        # No persistent audit-log model exists yet. Returning fabricated global
        # identities would be both misleading and a tenant metadata leak.
        logs = []
        
        increment_request_metric(success=True)
        return {"logs": logs, "total": len(logs)}
        
    except Exception as e:
        increment_request_metric(success=False)
        logger.error(f"[{trace_id}] /admin/audit-logs error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch audit logs"
        )


# ============== DOCUMENT UPLOAD ENDPOINT ==============
@router.post("/upload-department-data")
async def upload_department_data(
    files: List[UploadFile] = File(...),
    department: str = Form(...),
    target_role: Optional[str] = Form(None),
    current_user: Dict = Depends(get_current_admin_user)
):
    """Use the same validated, tenant-owned pipeline as /api/documents/upload."""
    require_non_demo_mutation(current_user)
    from src.backend.api.document_upload import upload_document_realtime

    results = []
    errors = []
    for file in files:
        filename = Path(file.filename or "").name
        try:
            result = await upload_document_realtime(
                file=file, department=department, force_refresh=False,
                current_user=current_user,
            )
            chunks = result["processing_info"]["chunks_created"]
            results.append({**result, "filename": filename, "status": "success",
                            "chunks_created": chunks})
        except HTTPException as exc:
            # upload_document_realtime only raises curated, user-facing details
            # (type/size/duplicate/empty/malformed); internal errors are logged
            # there and surface here as a generic message.
            reason = exc.detail if isinstance(exc.detail, str) else "Upload rejected"
            errors.append({"filename": filename, "status": exc.status_code, "error": reason})
    total_chunks = sum(item["chunks_created"] for item in results)
    if results and errors:
        message = f"{len(results)} of {len(files)} file(s) indexed"
    elif results:
        message = f"{len(results)} file(s) indexed"
    else:
        message = "; ".join(f"{e['filename']}: {e['error']}" for e in errors) or "No files uploaded"
    return {"success": bool(results), "message": message, "total_chunks": total_chunks,
            "results": results, "errors": errors,
            "department": department.lower().strip(), "target_role": target_role}


async def _legacy_upload_department_data_unused(
    files: List[UploadFile] = File(...),
    department: str = Form(...),
    target_role: Optional[str] = Form(None),
    current_user: Dict = Depends(get_current_admin_user)
):
    """
    POST /admin/upload-department-data
    
    Upload documents to a specific department with optional role restriction.
    
    Args:
        files: One or more files (PDF, CSV, MD, TXT, XLSX)
        department: Target department (finance, hr, engineering, etc.)
        target_role: Optional role restriction (if None, all roles can access)
    
    RBAC: admin role required
    """
    trace_id = str(uuid.uuid4())
    user_email = current_user.get('email', 'unknown')
    
    logger.info(f"[{trace_id}] Admin upload: {len(files)} files to {department} by {user_email}")
    
    # Validate department
    allowed_departments = {'general', 'finance', 'hr', 'engineering', 'marketing', 'executive', 'it', 'legal', 'operations'}
    department_lower = department.lower().strip()
    if department_lower not in allowed_departments:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid department: {department}. Allowed: {', '.join(sorted(allowed_departments))}"
        )
    
    # Allowed file types
    allowed_extensions = {'.pdf', '.csv', '.md', '.txt', '.xlsx', '.xls', '.markdown', '.docx'}
    max_file_size = 50 * 1024 * 1024  # 50MB per file
    
    results = []
    total_chunks = 0
    errors = []
    
    try:
        # Get RAG service for indexing
        rag_service_instance = None
        try:
            import sys
            if 'src.backend.api.endpoints' in sys.modules:
                endpoints_module = sys.modules['src.backend.api.endpoints']
                rag_service_instance = getattr(endpoints_module, 'rag_service', None)
            
            if rag_service_instance is None:
                # Try to create new instance
                rag_service_instance = RAGService()
        except Exception as e:
            logger.warning(f"[{trace_id}] Could not get RAG service: {e}")
        
        # Process each file
        for file in files:
            file_result = {
                "filename": file.filename,
                "status": "pending",
                "chunks": 0,
                "error": None
            }
            
            try:
                # Validate filename
                if not file.filename:
                    file_result["status"] = "error: no filename"
                    errors.append(file_result)
                    continue
                
                # Sanitize filename
                safe_filename = re.sub(r'[^\w\s.-]', '', file.filename)
                safe_filename = safe_filename.replace('..', '').strip()
                
                if not safe_filename:
                    file_result["status"] = "error: invalid filename"
                    errors.append(file_result)
                    continue
                
                # Check extension
                ext = Path(safe_filename).suffix.lower()
                if ext not in allowed_extensions:
                    file_result["status"] = f"error: unsupported file type {ext}"
                    errors.append(file_result)
                    continue
                
                # Read file content
                content = await file.read()
                file_size = len(content)
                
                if file_size > max_file_size:
                    file_result["status"] = f"error: file too large ({file_size // (1024*1024)}MB > 50MB)"
                    errors.append(file_result)
                    continue
                
                if file_size == 0:
                    file_result["status"] = "error: empty file"
                    errors.append(file_result)
                    continue
                
                # Create data directory
                data_dir = Path("src/data/raw")
                data_dir.mkdir(parents=True, exist_ok=True)
                
                # Generate unique filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                original_stem = Path(safe_filename).stem
                unique_filename = f"{original_stem}_{timestamp}{ext}"
                file_path = data_dir / unique_filename
                
                # Save file
                with open(file_path, "wb") as f:
                    f.write(content)
                
                logger.info(f"[{trace_id}] Saved: {unique_filename} ({file_size} bytes)")
                
                # Calculate hash for tracking
                file_hash = hashlib.md5(content).hexdigest()
                
                # Process and index if RAG service available
                chunks_created = 0
                if rag_service_instance and hasattr(rag_service_instance, 'vector_store'):
                    try:
                        from src.backend.utils.document_processor import DocumentProcessor
                        processor = DocumentProcessor()
                        
                        # Process based on file type
                        if ext == '.pdf':
                            chunks = processor.process_pdf(str(file_path))
                        elif ext == '.csv':
                            chunks = processor.process_csv(str(file_path))
                        elif ext in ['.md', '.markdown', '.txt']:
                            chunks = processor.process_markdown(str(file_path))
                        else:
                            # Fallback for other types
                            chunks = processor.process_markdown(str(file_path))
                        
                        if chunks:
                            # Add metadata to chunks
                            for chunk in chunks:
                                chunk.metadata.update({
                                    'tenant_id': current_user["tenant_id"],
                                    'department': department_lower,  # CRITICAL: key used by vector_store.add_documents
                                    'uploaded_by': user_email,
                                    'uploaded_at': datetime.now().isoformat(),
                                    'upload_department': department_lower,
                                    'target_role': target_role or '',
                                    'file_hash': file_hash,
                                    'original_filename': file.filename,
                                    'indexed_at': datetime.now().isoformat()
                                })
                            
                            # Add to vector store
                            success = rag_service_instance.vector_store.add_documents(chunks)
                            if success:
                                chunks_created = len(chunks)
                                total_chunks += chunks_created
                                logger.info(f"[{trace_id}] Indexed {chunks_created} chunks from {unique_filename}")
                            else:
                                logger.warning(f"[{trace_id}] Failed to index chunks from {unique_filename}")
                        
                    except Exception as proc_error:
                        logger.warning(f"[{trace_id}] Processing error for {unique_filename}: {proc_error}")
                        # File is saved, just not indexed
                
                file_result.update({
                    "status": "success",
                    "chunks": chunks_created,
                    "saved_as": unique_filename,
                    "size_bytes": file_size,
                    "file_hash": file_hash
                })
                results.append(file_result)
                
            except Exception as file_error:
                logger.error(f"[{trace_id}] Error processing {file.filename}: {file_error}")
                file_result["status"] = f"error: {str(file_error)}"
                errors.append(file_result)
        
        increment_request_metric(success=True)
        
        # Build response
        success_count = len([r for r in results if r["status"] == "success"])
        
        return {
            "success": success_count > 0,
            "message": f"Uploaded {success_count}/{len(files)} file(s) to {department}",
            "department": department_lower,
            "target_role": target_role,
            "total_chunks": total_chunks,
            "results": results,
            "errors": errors,
            "uploaded_by": user_email,
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        increment_request_metric(success=False)
        logger.error(f"[{trace_id}] Upload endpoint error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )


# ============== VALIDATE SESSION ENDPOINT ==============
@router.get("/validate-session")
async def validate_admin_session(
    current_user: Dict = Depends(get_current_admin_user)
):
    """
    GET /admin/validate-session
    Validates admin session token.
    RBAC: admin role required
    """
    return {
        "valid": True,
        "user": current_user.get("email"),
        "role": current_user.get("role"),
        "timestamp": datetime.now().isoformat()
    }
