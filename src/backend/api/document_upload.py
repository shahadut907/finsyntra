"""
Real-time Document Upload and Processing API
Handles immediate document indexing for real-time RAG updates

SECURITY: All endpoints require authentication (BUG-001 fix)
- upload, refresh, status, list: require authenticated user
- clear: requires admin role
"""
import asyncio
import os
import shutil
import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from fastapi.responses import JSONResponse
import logging

from src.config.settings import settings, get_raw_documents_path
from src.backend.services.rag_service import RAGService
from src.backend.utils.document_processor import DocumentProcessor
from src.backend.api.auth_deps import (
    get_current_user, get_current_admin_user, require_non_demo_mutation,
)
from src.backend.database.database import Document, SessionLocal

logger = logging.getLogger(__name__)

# Create router for document operations
router = APIRouter(prefix="/documents", tags=["documents"])

# Initialize services
rag_service = None
document_processor = DocumentProcessor()

def _readable_departments(current_user: Dict[str, Any]) -> Optional[set]:
    """Departments the caller may read, or None when the role reads all.

    Mirrors retrieval-time RBAC (and /api/knowledge/stats) so listing
    endpoints never disclose filenames retrieval would refuse to return.
    """
    from src.config.roles import Role, ROLE_PERMISSIONS
    role = (current_user.get("role") or "employee").lower()
    if role in ("admin", "c_level"):
        return None
    try:
        permissions = ROLE_PERMISSIONS.get(Role(role))
    except ValueError:
        permissions = ROLE_PERMISSIONS.get(Role.EMPLOYEE)
    return {d.value for d in permissions.allowed_departments} if permissions else {"general"}


def _retrieval_departments(current_user: Dict[str, Any]) -> List[str]:
    """Exactly the departments retrieval searches for this role.

    Unlike _readable_departments there is no admin/c_level shortcut, so the
    source viewer can never show a passage chat retrieval would withhold.
    """
    from src.config.roles import Role, ROLE_PERMISSIONS
    try:
        role = Role((current_user.get("role") or "").lower())
    except ValueError:
        role = Role.EMPLOYEE
    permissions = ROLE_PERMISSIONS.get(role)
    return sorted(d.value for d in permissions.allowed_departments) if permissions else ["general"]


def get_rag_service():
    """Get RAG service instance"""
    global rag_service
    if rag_service is None:
        try:
            rag_service = RAGService()
        except Exception as e:
            logger.error(f"Failed to initialize RAG service: {e}")
            raise HTTPException(status_code=503, detail="RAG service unavailable")
    return rag_service

@router.post("/upload")
async def upload_document_realtime(
    file: UploadFile = File(...),
    department: str = Form("general"),
    force_refresh: bool = Form(True),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Upload and immediately process a document for real-time RAG updates
    
    Args:
        file: The uploaded file
        department: Department category for RBAC
        force_refresh: Whether to force immediate refresh of the RAG system
    """
    require_non_demo_mutation(current_user)
    try:
        # Input validation and sanitization
        if not file.filename:
            raise HTTPException(status_code=400, detail="Filename is required")
        
        # Sanitize filename to prevent path traversal attacks
        import re
        if "/" in file.filename or "\\" in file.filename:
            raise HTTPException(status_code=400, detail="Invalid filename")
        supplied_name = Path(file.filename).name
        if supplied_name != file.filename.replace("\\", "/").split("/")[-1]:
            raise HTTPException(status_code=400, detail="Invalid filename")
        safe_filename = re.sub(r'[^\w\s.-]', '', supplied_name)
        safe_filename = safe_filename.replace('..', '').strip()
        
        if not safe_filename:
            raise HTTPException(status_code=400, detail="Invalid filename")
        windows_reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                            *(f"LPT{i}" for i in range(1, 10))}
        if Path(safe_filename).stem.upper() in windows_reserved:
            raise HTTPException(status_code=400, detail="Invalid filename")
        
        # Validate department parameter
        allowed_departments = {'general', 'finance', 'hr', 'engineering', 'marketing', 'executive', 'it'}
        department = department.lower().strip()
        if department not in allowed_departments:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid department: {department}. Allowed: {', '.join(allowed_departments)}"
            )
        
        # SECURITY: Upload RBAC — non-admin users can only upload to their allowed departments
        user_role_str = (current_user.get("role") or "employee").lower()
        if user_role_str not in ("admin", "c_level"):
            from src.config.roles import Role, ROLE_PERMISSIONS
            try:
                caller_role = Role(user_role_str)
            except ValueError:
                caller_role = Role.EMPLOYEE
            caller_perms = ROLE_PERMISSIONS.get(caller_role)
            caller_depts = {d.value for d in caller_perms.allowed_departments} if caller_perms else {"general"}
            if department not in caller_depts:
                raise HTTPException(
                    status_code=403,
                    detail=f"You do not have permission to upload to department '{department}'. "
                           f"Your allowed departments: {', '.join(sorted(caller_depts))}"
                )
        
        # Validate file type
        allowed_extensions = {'.md', '.csv', '.pdf', '.txt'}
        file_extension = Path(safe_filename).suffix.lower()
        
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {file_extension}. Allowed: {', '.join(allowed_extensions)}"
            )
        
        # Validate file size (10MB limit)
        max_size = 10 * 1024 * 1024  # 10MB
        file_content = await file.read(max_size + 1)
        
        if len(file_content) > max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File too large: {len(file_content)} bytes. Maximum: {max_size} bytes"
            )
        if not file_content:
            raise HTTPException(status_code=400, detail="File is empty")
        if file_extension == ".pdf" and not file_content.startswith(b"%PDF-"):
            raise HTTPException(status_code=400, detail="File content does not match PDF type")
        if file_extension in {".md", ".csv", ".txt"}:
            try:
                file_content.decode("utf-8")
            except UnicodeDecodeError:
                raise HTTPException(status_code=400, detail="Text uploads must be valid UTF-8")
            if b"\x00" in file_content:
                raise HTTPException(status_code=400, detail="Binary content is not a text document")

        # Identical content already active in this tenant would be indexed a
        # second time and surface as duplicate chunks and citations.
        content_sha256 = hashlib.sha256(file_content).hexdigest()
        db = SessionLocal()
        try:
            duplicate = next((
                item.filename for item in db.query(Document).filter(
                    Document.tenant_id == current_user["tenant_id"],
                    Document.is_active.is_(True),
                ).all()
                if (item.meta or {}).get("sha256") == content_sha256
            ), None)
        finally:
            db.close()
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=f"This file's content is already uploaded as '{duplicate}'",
            )

        # Create data directory if it doesn't exist
        data_dir = Path(get_raw_documents_path())
        data_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate unique filename to avoid conflicts using sanitized name
        original_name = Path(safe_filename).stem
        file_extension = Path(safe_filename).suffix
        unique_filename = f"{original_name}_{uuid.uuid4().hex}{file_extension}"
        
        file_path = data_dir / unique_filename
        
        # Save file to disk
        with open(file_path, "wb") as f:
            f.write(file_content)
        
        logger.info(f"[*] Saved uploaded file: {unique_filename} ({len(file_content)} bytes)")
        
        # Calculate file hash for tracking
        file_hash = hashlib.md5(file_content).hexdigest()
        
        # Get RAG service and process immediately
        rag = get_rag_service()
        
        # Process the document immediately. Parsing and embedding are CPU-bound
        # and take seconds for a PDF; they run in a worker thread so the event
        # loop keeps serving other requests (including live SSE streams).
        chunks_created = 0
        try:
            # Process based on file type
            if file_extension == '.md':
                parse = document_processor.process_markdown
            elif file_extension == '.csv':
                parse = document_processor.process_csv
            elif file_extension == '.pdf':
                parse = document_processor.process_pdf
            elif file_extension == '.txt':
                parse = document_processor.process_markdown
            else:
                parse = None
            chunks = await asyncio.to_thread(parse, str(file_path)) if parse else []

            if chunks:
                # Get tenant_id from authenticated user (BUG-009 fix)
                tenant_id = current_user["tenant_id"]

                # Add upload metadata to chunks including tenant_id for isolation
                for chunk in chunks:
                    chunk.metadata.update({
                        'tenant_id': tenant_id,  # CRITICAL: Tenant isolation
                        'department': department,  # CRITICAL: RBAC filtering key
                        'uploaded_by': current_user.get("email", "unknown"),
                        'uploaded_at': datetime.now().isoformat(),
                        'upload_department': department,
                        'file_hash': file_hash,
                        'original_filename': file.filename,
                        # Ensure recency fields for ranking immediately after upload
                        'indexed_at': datetime.now().isoformat(),
                        'file_modified': datetime.now().isoformat()
                    })
                
                # Add to vector store immediately.
                # tenant_id is passed EXPLICITLY as well as being set on each
                # chunk's metadata: add_documents cross-checks the two and
                # raises on any mismatch, so the authenticated user's tenant is
                # the single source of truth for ownership.
                success = await asyncio.to_thread(
                    rag.vector_store.add_documents, chunks, tenant_id=tenant_id
                )
                
                if success:
                    chunks_created = len(chunks)
                    logger.info(f"[+] Immediately indexed {chunks_created} chunks from {unique_filename}")
                    try:
                        # Clear caches to avoid stale retrieval and force fresh search
                        rag._response_cache.clear()
                        if hasattr(rag, '_query_embedding_cache'):
                            rag._query_embedding_cache.clear()
                    except Exception:
                        pass
                else:
                    logger.error(f"[-] Failed to index chunks from {unique_filename}")
                    raise HTTPException(status_code=500, detail="Failed to index document")
            else:
                logger.warning(f"[!] No chunks generated from {unique_filename}")
                raise HTTPException(
                    status_code=400,
                    detail="Document contained no indexable content",
                )
        
        except HTTPException:
            if file_path.exists():
                file_path.unlink()
            raise
        except Exception:
            logger.exception("Document processing failed")
            # Clean up file if processing failed
            if file_path.exists():
                file_path.unlink()
            raise HTTPException(status_code=400, detail="Document is malformed or could not be processed")

        document_id = str(uuid.uuid4())
        db = SessionLocal()
        try:
            db.add(Document(
                id=document_id,
                filename=safe_filename,
                tenant_id=current_user["tenant_id"],
                storage_path=unique_filename,
                content_type=file.content_type or "application/octet-stream",
                file_size=len(file_content),
                department=department,
                uploaded_by=current_user["id"],
                processed_at=datetime.utcnow(),
                chunk_count=chunks_created,
                is_active=True,
                meta={"sha256": content_sha256},
            ))
            db.commit()
        except Exception:
            db.rollback()
            rag.vector_store.delete_documents_by_sources(
                [unique_filename], tenant_id=current_user["tenant_id"]
            )
            if file_path.exists():
                file_path.unlink()
            logger.exception("Document metadata persistence failed")
            raise HTTPException(status_code=503, detail="Document could not be committed")
        finally:
            db.close()
        
        # Force refresh RAG system if requested
        if force_refresh:
            try:
                rag._response_cache.clear()
            except Exception:
                logger.warning("RAG cache refresh failed", exc_info=True)
        
        # Get updated system stats
        stats = rag.vector_store.get_collection_stats(tenant_id=current_user["tenant_id"])
        
        return {
            "success": True,
            "message": f"Document uploaded and processed successfully",
            "file_info": {
                "original_filename": file.filename,
                "saved_filename": unique_filename,
                "file_size": len(file_content),
                "file_hash": file_hash,
                "file_type": file_extension,
                "department": department
                ,"document_id": document_id
            },
            "processing_info": {
                "chunks_created": chunks_created,
                "indexed_immediately": True,
                "processing_time": "< 1s"
            },
            "system_stats": {
                "total_documents": stats.get("total_documents", 0),
                "departments": stats.get("departments", {}),
                "sources": list(stats.get("sources", {}).keys())[:10]  # Show first 10 sources
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception:
        logger.exception("Upload endpoint error")
        raise HTTPException(status_code=500, detail="Upload failed")

@router.post("/refresh")
async def force_document_refresh(
    current_user: Dict[str, Any] = Depends(get_current_admin_user)
):
    """
    Force immediate refresh of the document index
    Useful after manual file uploads or modifications

    Requires: Authentication

    Only clears process-local retrieval caches (rag._response_cache) and
    reads stats — it writes nothing to Chroma, SQL, or disk. There is no
    legitimate reason for a public-demo account to call it, so it is blocked
    for them too (defense-in-depth), even though it is not itself a
    shared-state mutation.
    """
    require_non_demo_mutation(current_user)
    logger.info(f"Document refresh requested by {current_user.get('email')}")
    try:
        rag = get_rag_service()

        rag._response_cache.clear()
        stats = rag.vector_store.get_collection_stats(tenant_id=current_user["tenant_id"])
        return {
            "success": True,
            "message": "Tenant retrieval caches refreshed",
            "total_documents": stats.get("total_documents", 0),
            "system_stats": stats,
            "timestamp": datetime.now().isoformat(),
        }
            
    except HTTPException:
        raise
    except Exception:
        logger.exception("Refresh endpoint error")
        raise HTTPException(status_code=500, detail="Refresh failed")

@router.get("/status")
async def get_document_status(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get current document index status and statistics

    Requires: Authentication (prevents info leakage)
    """
    try:
        rag = get_rag_service()
        
        # SECURITY: Get stats scoped to tenant and readable departments
        tenant_id = current_user["tenant_id"]
        readable = _readable_departments(current_user)
        stats = rag.vector_store.get_collection_stats(tenant_id=tenant_id, departments=readable)
        performance = rag.vector_store.get_performance_stats()

        db = SessionLocal()
        try:
            query = db.query(Document).filter(
                Document.tenant_id == tenant_id, Document.is_active.is_(True)
            )
            if readable is not None:
                query = query.filter(Document.department.in_(readable))
            recent = query.order_by(Document.uploaded_at.desc()).limit(20).all()
            recent_files = [{"id": item.id, "filename": item.filename,
                             "modified": item.uploaded_at.isoformat() if item.uploaded_at else None,
                             "size": item.file_size or 0} for item in recent]
        finally:
            db.close()
        
        return {
            "success": True,
            "system_status": {
                "total_documents": stats.get("total_documents", 0),
                "departments": stats.get("departments", {}),
                "document_types": stats.get("document_types", {}),
                "sources": stats.get("sources", {}),
                "recent_uploads": recent_files
            },
            "performance_stats": performance,
            "last_refresh": datetime.now().isoformat(),
            "real_time_monitoring": True
        }
        
    except Exception:
        logger.exception("Status endpoint error")
        raise HTTPException(status_code=500, detail="Status check failed")

@router.delete("/clear")
async def clear_document_index(
    current_user: Dict[str, Any] = Depends(get_current_admin_user)
):
    """
    Clear the entire document index (admin only)
    WARNING: This will remove all indexed documents

    Requires: Admin role (CRITICAL - destructive operation)
    """
    require_non_demo_mutation(current_user)
    logger.warning(f"ADMIN ACTION: Document index clear requested by {current_user.get('email')}")
    try:
        rag = get_rag_service()
        
        tenant_id = current_user["tenant_id"]
        sources = rag.vector_store.get_unique_sources(tenant_id=tenant_id)
        if sources:
            rag.vector_store.delete_documents_by_sources(sources, tenant_id=tenant_id)
        
        # Clear caches
        rag._response_cache.clear()
        if hasattr(rag.vector_store, '_embedding_cache'):
            rag.vector_store._embedding_cache.clear()
        
        logger.info("[*] Document index cleared by admin")
        
        return {
            "success": True,
            "message": "Document index cleared successfully",
            "warning": "All indexed documents for this tenant have been removed",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception:
        logger.exception("Clear endpoint error")
        raise HTTPException(status_code=500, detail="Clear failed")

@router.get("/list")
async def list_documents(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    List all currently indexed documents with metadata

    Requires: Authentication (prevents document inventory leakage)
    """
    try:
        rag = get_rag_service()
        
        tenant_id = current_user["tenant_id"]
        readable = _readable_departments(current_user)
        if readable is None:
            sources = rag.vector_store.get_unique_sources(tenant_id=tenant_id)
        else:
            sources = list(rag.vector_store.get_collection_stats(
                tenant_id=tenant_id, departments=readable).get("sources", {}))
        db = SessionLocal()
        try:
            query = db.query(Document).filter(
                Document.tenant_id == tenant_id, Document.is_active.is_(True)
            )
            if readable is not None:
                query = query.filter(Document.department.in_(readable))
            records = query.order_by(Document.uploaded_at.desc()).all()
            document_list = [{
                "id": item.id,
                "filename": item.filename,
                "indexed": item.storage_path in sources or item.filename in sources,
                "file_size": item.file_size or 0,
                "modified": item.uploaded_at.isoformat() if item.uploaded_at else None,
                "file_type": Path(item.filename).suffix.lower(),
            } for item in records]
        finally:
            db.close()
        
        return {
            "success": True,
            "documents": document_list,
            "total_indexed": len(sources),
            "total_files": len(document_list),
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception:
        logger.exception("List endpoint error")
        raise HTTPException(status_code=500, detail="List failed")


@router.get("/source/{source}")
async def get_cited_source(
    source: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Indexed passages of one cited source, for the chat citation viewer.

    Visibility is exactly retrieval's: the caller's own tenant and the
    departments their DB role may search. Missing, deleted, other-tenant and
    other-department sources all return the same 404. Raw file bytes are not
    served here; only admin routes download originals.
    """
    not_found = HTTPException(status_code=404, detail="Source not found")
    if not source or len(source) > 255 or "/" in source or "\\" in source:
        raise not_found
    tenant_id = current_user["tenant_id"]
    departments = _retrieval_departments(current_user)
    db = SessionLocal()
    try:
        record = db.query(Document).filter(
            Document.tenant_id == tenant_id, Document.storage_path == source,
        ).order_by(Document.is_active.desc()).first()
        if record is not None and (
            not record.is_active or record.department not in departments
        ):
            raise not_found
        filename = record.filename if record else source
        department = record.department if record else None
    finally:
        db.close()
    rag = get_rag_service()
    passages = await asyncio.to_thread(
        rag.vector_store.get_source_passages, source, tenant_id, departments
    )
    if not passages:
        raise not_found
    return {"source": source, "filename": filename,
            "department": department, "passages": passages}
