"""
Conversation history and export endpoints.
"""
from typing import Dict, Any, List, Optional
import json
import os
import tempfile
import textwrap
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Query
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy import func
from pydantic import BaseModel

from src.backend.api.auth_deps import get_current_user, require_visitor_session_for_demo
from src.backend.database.database import db_manager, ChatSession, ChatMessage
from src.backend.services.pdf_export import pdf_exporter

router = APIRouter()


class ConversationCreateRequest(BaseModel):
    title: Optional[str] = None
    conversation_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


async def get_current_user_strict(request: Request) -> Dict[str, Any]:
    """Backward-compatible alias for the authoritative shared dependency."""
    return await get_current_user(request)


def load_owned_session(
    db, conversation_id: str, current_user: Dict[str, Any],
    visitor_session_id: Optional[str] = None,
) -> ChatSession:
    """Fetch a conversation the caller is allowed to read, or raise.

    Single authoritative access rule for every conversation read path:
        session.user_id   == authenticated user      AND
        session.tenant_id == authenticated tenant    AND
        (public-demo only) session.visitor_session_id == caller's vsid

    Status codes deliberately differ by dimension:
      * absent, or owned by ANOTHER TENANT -> 404. A 403 would confirm that a
        conversation id exists in someone else's tenant, so cross-tenant probes
        are answered exactly like a miss.
      * present in the SAME tenant but owned by a different user -> 403, which
        preserves the pre-existing intra-tenant contract.
      * (public-demo only) same tenant AND same shared user_id but a
        different (or legacy NULL) visitor_session_id -> 404, never 403.
        Every demo visitor shares the exact same user_id, so a 403 here would
        confirm "this id exists under my shared account" to anyone who can
        log in with that same public identity — an enumeration oracle a
        normal multi-employee tenant doesn't have. 404 avoids it and never
        exposes legacy shared history either.

    Sessions with a NULL tenant_id are unreachable by design: Wave 4 leaves
    historical rows of unproven ownership unassigned rather than guessing.
    ``visitor_session_id`` is None for non-demo callers, which is a strict
    no-op here — non-demo ownership semantics are unchanged.
    """
    caller_tenant = (current_user.get("tenant_id") or "").strip()
    if not caller_tenant:
        raise HTTPException(status_code=403, detail="Tenant context missing")

    session = db.query(ChatSession).filter(ChatSession.id == conversation_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if (session.tenant_id or "") != caller_tenant:
        # Includes NULL tenant_id (unresolved historical rows).
        raise HTTPException(status_code=404, detail="Conversation not found")
    if session.user_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if visitor_session_id is not None and (session.visitor_session_id or "") != visitor_session_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return session


@router.get("/conversations")
async def list_conversations(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_strict),
):
    """List conversation sessions for the current user."""
    visitor_session_id = require_visitor_session_for_demo(current_user, request)
    db = db_manager.get_db()
    try:
        # SECURITY: scope by user AND tenant. tenant_id is mandatory — an absent
        # tenant must not silently widen the query to every tenant's sessions.
        tenant_id = (current_user.get("tenant_id") or "").strip()
        if not tenant_id:
            raise HTTPException(status_code=403, detail="Tenant context missing")
        query = db.query(ChatSession)\
            .filter(ChatSession.user_id == current_user["id"])\
            .filter(ChatSession.tenant_id == tenant_id)
        if visitor_session_id is not None:
            # Public-demo caller: the vsid partition is a hard requirement,
            # not a relaxable filter — legacy/NULL and other-visitor rows
            # must never appear in this list.
            query = query.filter(ChatSession.visitor_session_id == visitor_session_id)
        sessions = query\
            .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())\
            .all()

        counts = dict(
            db.query(ChatMessage.session_id, func.count(ChatMessage.id))\
              .filter(ChatMessage.user_id == current_user["id"])\
              .group_by(ChatMessage.session_id)\
              .all()
        )

        results = []
        for s in sessions:
            results.append({
                "id": s.id,
                "user_id": s.user_id,
                # Operator-precedence fix: Python parses "A or B if C else D" as
                # "(A or B) if C else D", so a falsy s.meta (e.g. {}) previously
                # discarded a real s.title and returned None. Parenthesizing the
                # fallback restores the intended "title, else meta title" order.
                "session_name": s.title or (s.meta.get("title") if s.meta else None),
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                "message_count": counts.get(s.id, 0),
                "metadata": s.meta or {}
            })
        return {"sessions": results}
    finally:
        db_manager.close_db(db)


@router.post("/conversations")
async def create_conversation(
    payload: ConversationCreateRequest,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_strict)
):
    """Create a new conversation for the current user."""
    visitor_session_id = require_visitor_session_for_demo(current_user, request)
    db = db_manager.get_db()
    try:
        # SECURITY: tenant is mandatory and comes only from authenticated
        # identity — never from the request body.
        tenant_id = (current_user.get("tenant_id") or "").strip()
        if not tenant_id:
            raise HTTPException(status_code=403, detail="Tenant context missing")

        conversation_id = payload.conversation_id or str(uuid.uuid4())
        existing = db.query(ChatSession).filter(ChatSession.id == conversation_id).first()
        if existing:
            # The id is client-supplied, so this doubles as a probe surface.
            # Cross-tenant collisions answer like a miss; same-tenant collisions
            # with another user keep the existing 403 contract. A same-tenant,
            # same-user, wrong-vsid collision (public demo only) also answers
            # like a miss — see load_owned_session's docstring for why.
            if (existing.tenant_id or "") != tenant_id:
                raise HTTPException(status_code=404, detail="Conversation not found")
            if existing.user_id != current_user["id"]:
                raise HTTPException(status_code=403, detail="Forbidden")
            if visitor_session_id is not None and (existing.visitor_session_id or "") != visitor_session_id:
                raise HTTPException(status_code=404, detail="Conversation not found")
            return {
                "id": existing.id,
                "user_id": existing.user_id,
                "title": existing.title,
                "created_at": existing.created_at.isoformat() if existing.created_at else None,
                "updated_at": existing.updated_at.isoformat() if existing.updated_at else None,
                "metadata": existing.meta or {}
            }

        session = ChatSession(
            id=conversation_id,
            user_id=current_user["id"],
            tenant_id=tenant_id,
            visitor_session_id=visitor_session_id,
            title=payload.title,
            meta={**(payload.metadata or {}), "tenant_id": tenant_id}
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return {
            "id": session.id,
            "user_id": session.user_id,
            "title": session.title,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
            "metadata": session.meta or {}
        }
    finally:
        db_manager.close_db(db)


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    request: Request,
    limit: int = Query(1000, ge=1, le=20000),
    current_user: Dict[str, Any] = Depends(get_current_user_strict)
):
    """Get messages for a single conversation."""
    visitor_session_id = require_visitor_session_for_demo(current_user, request)
    db = db_manager.get_db()
    try:
        session = load_owned_session(db, conversation_id, current_user, visitor_session_id)

        messages = db.query(ChatMessage)\
            .filter(ChatMessage.session_id == conversation_id)\
            .order_by(ChatMessage.timestamp.asc())\
            .limit(limit)\
            .all()

        message_list = [
            {
                "id": m.id,
                "session_id": m.session_id,
                "user_id": m.user_id,
                "message_type": m.message_type,
                "content": m.content,
                "timestamp": m.timestamp.isoformat() if m.timestamp else None,
                "sources": m.sources or [],
                "metadata": m.meta or {}
            }
            for m in messages
        ]

        return {
            "session": {
                "id": session.id,
                "user_id": session.user_id,
                "created_at": session.created_at.isoformat() if session.created_at else None,
                "updated_at": session.updated_at.isoformat() if session.updated_at else None,
                "metadata": session.meta or {}
            },
            "messages": message_list
        }
    finally:
        db_manager.close_db(db)


def _format_markdown(conversation_id: str, messages: List[Dict[str, Any]]) -> str:
    lines = [f"# Conversation {conversation_id}", ""]
    for msg in messages:
        ts = msg.get("timestamp") or ""
        role = msg.get("message_type", "unknown")
        content = msg.get("content", "")
        lines.append(f"## {role} ({ts})")
        lines.append(content)
        lines.append("")
    return "\n".join(lines)


def _sanitize_filename(value: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in value)


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_simple_pdf(lines: List[str]) -> bytes:
    # Basic PDF generator without external dependencies.
    if not lines:
        lines = ["(No content)"]

    lines_per_page = 45
    pages = [lines[i:i + lines_per_page] for i in range(0, len(lines), lines_per_page)]
    num_pages = max(1, len(pages))

    objects = {}

    # Catalog and Pages
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = []
    for i in range(num_pages):
        page_id = 3 + (i * 2)
        kids.append(f"{page_id} 0 R")
    kids_str = " ".join(kids).encode("ascii")
    objects[2] = b"<< /Type /Pages /Kids [" + kids_str + b"] /Count " + str(num_pages).encode("ascii") + b" >>"

    # Font object id
    font_id = 3 + (num_pages * 2)

    # Pages and content streams
    for i, page_lines in enumerate(pages):
        page_id = 3 + (i * 2)
        content_id = page_id + 1

        content_lines = [b"BT", b"/F1 11 Tf", b"72 750 Td"]
        for idx, line in enumerate(page_lines):
            if idx > 0:
                content_lines.append(b"0 -14 Td")
            escaped = _escape_pdf_text(line)
            content_lines.append(f"({escaped}) Tj".encode("latin-1", "replace"))
        content_lines.append(b"ET")
        stream = b"\n".join(content_lines)
        objects[content_id] = b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"

        page_obj = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents " + str(content_id).encode("ascii") + b" 0 R "
            b"/Resources << /Font << /F1 " + str(font_id).encode("ascii") + b" 0 R >> >> >>"
        )
        objects[page_id] = page_obj

    # Font
    objects[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    # Build PDF
    output = b"%PDF-1.4\n"
    offsets = {0: 0}
    for obj_id in sorted(objects.keys()):
        offsets[obj_id] = len(output)
        output += f"{obj_id} 0 obj\n".encode("ascii") + objects[obj_id] + b"\nendobj\n"

    max_id = max(objects.keys())
    xref_start = len(output)
    output += f"xref\n0 {max_id + 1}\n".encode("ascii")
    output += b"0000000000 65535 f \n"
    for obj_id in range(1, max_id + 1):
        output += f"{offsets[obj_id]:010d} 00000 n \n".encode("ascii")
    output += b"trailer\n<< /Size " + str(max_id + 1).encode("ascii") + b" /Root 1 0 R >>\nstartxref\n"
    output += f"{xref_start}\n%%EOF\n".encode("ascii")
    return output


def _format_pdf(conversation_id: str, messages: List[Dict[str, Any]]) -> bytes:
    lines = [f"Conversation {conversation_id}", ""]
    for msg in messages:
        ts = msg.get("timestamp") or ""
        role = msg.get("message_type", "unknown")
        lines.append(f"{role} ({ts})")
        content = msg.get("content", "")
        if content:
            lines.extend(textwrap.wrap(content, width=90))
        lines.append("")
    return _build_simple_pdf(lines)


@router.get("/conversations/export")
async def export_conversation_missing_id():
    """Reject export requests missing a conversation id."""
    raise HTTPException(status_code=400, detail="conversation_id is required")


@router.get("/conversations/{conversation_id}/export")
async def export_conversation(
    conversation_id: str,
    request: Request,
    format: str = Query("json"),
    current_user: Dict[str, Any] = Depends(get_current_user_strict),
    background_tasks: BackgroundTasks = None
):
    """Export a conversation as JSON, Markdown, or PDF."""
    visitor_session_id = require_visitor_session_for_demo(current_user, request)
    db = db_manager.get_db()
    try:
        session = load_owned_session(db, conversation_id, current_user, visitor_session_id)

        messages = db.query(ChatMessage)\
            .filter(ChatMessage.session_id == conversation_id)\
            .order_by(ChatMessage.timestamp.asc())\
            .all()

        export_payload = {
            "conversation_id": conversation_id,
            "user_id": session.user_id,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
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
            ],
        }

        if format not in ("json", "md", "pdf"):
            raise HTTPException(status_code=400, detail="Unsupported export format")

        if format == "md":
            md_content = _format_markdown(conversation_id, export_payload["messages"])
            filename = f"conversation_{_sanitize_filename(conversation_id)}.md"
            return StreamingResponse(
                iter([md_content]),
                media_type="text/markdown",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'}
            )

        if format == "pdf":
            # Use professional PDF exporter with branding
            pdf_bytes = pdf_exporter.export_chat(
                messages=export_payload["messages"],
                session_title=session.title or f"Conversation {conversation_id[:8]}",
                session_id=conversation_id,
                user_email=current_user.get("email", ""),
                user_role=current_user.get("role", ""),
                tenant_name=current_user.get("organization_name", "FinSyntra")
            )
            safe_id = _sanitize_filename(conversation_id)
            filename = f"finsyntra_chat_{safe_id}.pdf"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            try:
                tmp.write(pdf_bytes)
                tmp.close()
                if background_tasks is None:
                    background_tasks = BackgroundTasks()
                background_tasks.add_task(os.unlink, tmp.name)
                return FileResponse(
                    tmp.name,
                    media_type="application/pdf",
                    filename=filename,
                    background=background_tasks
                )
            except Exception:
                try:
                    tmp.close()
                except Exception:
                    pass
                try:
                    os.unlink(tmp.name)
                except Exception:
                    pass
                raise

        json_content = json.dumps(export_payload, ensure_ascii=False, indent=2)
        filename = f"conversation_{_sanitize_filename(conversation_id)}.json"
        return StreamingResponse(
            iter([json_content]),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    finally:
        db_manager.close_db(db)
