"""
Chat API endpoint handling all conversational requests.
This module implements the chat functionality with language detection and translation.
"""

import asyncio
import logging
import uuid
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from src.backend.services.rag_service import RAGService
from src.backend.database.database import (
    db_manager,
    ChatMessage,
    ConversationForbiddenError,
    ConversationNotFoundError,
)
from src.backend.services.language_utils import detect_language
from src.config.roles import Role
from src.backend.api.auth_deps import get_current_user, require_visitor_session_for_demo
from src.config.settings import settings

# Initialize router
router = APIRouter()
logger = logging.getLogger(__name__)

# Define models using Pydantic for validation
class ChatRequest(BaseModel):
    """Chat request model"""
    message: str
    # SECURITY: role removed - always derived from JWT/auth context
    user_name: Optional[str] = None
    session_id: Optional[str] = None
    conversation_history: Optional[List[Dict[str, str]]] = None

class User(BaseModel):
    """Simple user model"""
    id: str
    role: Role
    
    class Config:
        arbitrary_types_allowed = True


@router.get("/chat/conversations/{session_id}")
async def get_chat_conversation(
    session_id: str, http_request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Return stored chat messages for a session (for history/export)."""
    visitor_session_id = require_visitor_session_for_demo(user, http_request)
    db = db_manager.get_db()
    try:
        # Single authoritative access rule, shared with /api/conversations:
        # user AND tenant must both match (plus vsid for public demo).
        # Messages are reached only through their owning session, so
        # ChatMessage needs no tenant column.
        from src.backend.api.conversations import load_owned_session
        session = load_owned_session(db, session_id, user, visitor_session_id)

        messages = db.query(ChatMessage)\
            .filter(ChatMessage.session_id == session_id)\
            .order_by(ChatMessage.timestamp.asc())\
            .all()

        return {
            "session_id": session_id,
            "messages": [
                {
                    "id": m.id,
                    "message_type": m.message_type,
                    "content": m.content,
                    "timestamp": m.timestamp.isoformat() if m.timestamp else None,
                    "sources": m.sources or [],
                    "metadata": m.meta or {}
                }
                for m in messages
            ]
        }
    finally:
        db_manager.close_db(db)

@router.post("/chat")
async def chat(request: ChatRequest, user: Dict[str, Any] = Depends(get_current_user), http_request: Request = None):
    """Process a chat request and return a response with language support"""
    
    # Initialize or get RAG service
    rag_service = None
    if http_request is not None:
        rag_service = getattr(http_request.app.state, "rag", None)
    if rag_service is None:
        rag_service = RAGService()
    
    # Process the request
    try:
        visitor_session_id = require_visitor_session_for_demo(user, http_request)

        # SECURITY: Role derived ONLY from authenticated user, never request body
        try:
            user_role = Role(user["role"])
        except ValueError:
            user_role = Role.EMPLOYEE

        tenant_id = (user.get("tenant_id") or "").strip()
        if not tenant_id:
            raise HTTPException(status_code=403, detail="Tenant context missing")
        session_id = request.session_id or str(uuid.uuid4())

        # Reserve/authorize the session before invoking RAG. This prevents a
        # caller-controlled session id from becoming an ownership probe after
        # expensive generation has already happened.
        try:
            db_manager.ensure_chat_session(
                user_id=user["id"],
                session_id=session_id,
                metadata={"tenant_id": tenant_id, "user_role": user_role.value},
                visitor_session_id=visitor_session_id,
            )
        except ConversationNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Conversation not found") from exc
        except ConversationForbiddenError as exc:
            raise HTTPException(status_code=403, detail="Forbidden") from exc

        # Context is always loaded from the owned server-side session. Any
        # client-supplied history is deliberately ignored.
        conversation_history = db_manager.get_bounded_conversation_context(
            session_id=session_id,
            user_id=user["id"],
            tenant_id=tenant_id,
            visitor_session_id=visitor_session_id,
        )

        # Process the message via the same RAG pipeline the SSE endpoint uses
        # (deterministic offline Bangla retrieval hinting — no external
        # translation call). The blocking pipeline runs off the event loop via
        # asyncio.to_thread and is bounded by RAG_HARD_TIMEOUT_SECONDS, so a
        # slow/stuck call here cannot freeze other requests on this process.
        rag_hard_timeout = float(settings.rag_hard_timeout_seconds)
        rag_task = asyncio.create_task(asyncio.to_thread(
            rag_service.process_query,
            query=request.message,
            user_id=user["id"],
            tenant_id=tenant_id,
            top_k=8,
            departments=[user_role.value],
            conversation_id=session_id,
            include_citations=True,
            user_role=user_role,
            user_name=user.get("full_name") or user.get("email", "User"),
            conversation_history=conversation_history,
        ))
        try:
            response = await asyncio.wait_for(rag_task, timeout=rag_hard_timeout)
        except asyncio.TimeoutError:
            rag_task.cancel()
            logger.error(
                "RAG_HARD_TIMEOUT_EXCEEDED session_id=%s tenant_id=%s timeout=%ss",
                session_id, tenant_id, rag_hard_timeout,
            )
            # Nothing was generated within the bound — do not persist a
            # falsely successful exchange for this turn.
            raise HTTPException(
                status_code=503,
                detail="The assistant took too long to respond. Please try again.",
            )

        if not isinstance(response, dict):
            logger.error("RAG service returned invalid type: %s", type(response))
            raise HTTPException(status_code=500, detail="An error occurred while processing your request")

        response_text = response.get("response") or ""
        sources = response.get("sources") or []
        documents_found = response.get("documents_found", 0)

        # Persist both sides in one transaction. A successful API response is a
        # durability acknowledgement, so persistence failures are never hidden.
        try:
            db_manager.persist_chat_exchange(
                session_id=session_id,
                user_id=user["id"],
                tenant_id=tenant_id,
                user_role=user_role.value,
                query=request.message,
                response=response_text,
                sources=sources,
                visitor_session_id=visitor_session_id,
            )
        except Exception as persist_err:
            logger.error("Failed to persist chat exchange", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail="Conversation could not be saved; please retry",
            ) from persist_err

        # Return the response
        return {
            "response": response_text,
            "session_id": session_id,
            "sources": sources,
            "documents_found": documents_found,
            "processing_time": response.get("processing_time", "0s"),
            "success": response.get("success", True),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing chat request: {e}")
        raise HTTPException(
            status_code=500,
            detail="An error occurred while processing your request"
        )
