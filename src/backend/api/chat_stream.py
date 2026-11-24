"""
Streaming chat API endpoint with Server-Sent Events (SSE) support.
Provides real-time, token-by-token streaming responses for a ChatGPT-like experience.

UNIFIED ENDPOINT: Both GET and POST supported with RAG-empty fallback to general LLM.
"""

import asyncio
import hashlib
import json
import logging
import time
import httpx
from typing import AsyncGenerator, Dict, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from datetime import datetime

from src.backend.services.rag_service import RAGService
from src.backend.services.language_utils import detect_language
from src.backend.services import demo_usage
from src.config.roles import Role
from src.config.settings import settings
from src.backend.database.database import (
    db_manager,
    ConversationForbiddenError,
    ConversationNotFoundError,
)
from src.backend.api.auth_deps import get_current_user, require_visitor_session_for_demo
from src.backend.services.model_catalog import (
    ModelSelection,
    ModelSelectionError,
    get_catalog,
    resolve_selection,
)

# Initialize router
router = APIRouter()


def _demo_refusal(request: Request, exc: "demo_usage.DemoLimitError", usage: Optional[dict] = None):
    """Friendly refusal of a public-demo message.

    EventSource (the UI's transport) cannot read HTTP status codes, so a GET
    stream is answered with a normal SSE stream carrying one ``error`` event the
    UI already renders. API clients (POST) get a conventional 429.
    """
    payload = {"code": exc.code.upper(), "message": exc.message, "retry_after": exc.retry_after}
    if request.method == "GET":
        event = json.dumps({'type': 'error', 'code': payload['code'], 'message': exc.message})
        body = "data: " + event + "\n\n" + "data: [DONE]\n\n"
        return StreamingResponse(iter([body]), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    return JSONResponse(status_code=429, content={"detail": payload}, headers=headers)


async def _leased_stream(inner, lease):
    """Hold the demo lease for the life of the stream; always release it."""
    lease.activate()  # provider tokens are charged to the public or admin pool
    try:
        async for chunk in inner:
            if isinstance(chunk, str) and chunk.startswith('data: {"type": "complete"'):
                try:
                    done = json.loads(chunk[6:])
                    if not done.get("success") and done.get("generation_status") != "ok":
                        # The visitor got no answer (model busy/unavailable):
                        # do not charge the failed attempt to their allowance.
                        await asyncio.to_thread(lease.refund_once)
                except ValueError:
                    pass
            yield chunk
    finally:
        lease.release()
logger = logging.getLogger(__name__)


def _derive_public_demo_session_id(user_id: str, visitor_session_id: str) -> str:
    """Deterministic, non-reversible default SSE session id for a public-demo
    visitor who omitted session_id.

    session_id is returned to the client via ordinary conversation-listing
    API responses, so it must never let the raw httpOnly vsid (or the
    account's public email/user_id) be recovered from it. SHA-256 with an
    explicit domain-separation prefix is one-way: same (user_id, vsid) always
    reproduces the same digest (so a visitor's own follow-up messages land in
    the same conversation), but the digest cannot be inverted back to either
    input. This value is only ever used as a conversation-partition label —
    the actual ownership boundary (tenant_id + user_id + raw server-side
    vsid, enforced by _assert_session_owner) is completely independent of it
    and is not weakened by this change in any way.
    """
    material = f"finsolve-demo-session-v1:{user_id}:{visitor_session_id}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"demo_{digest}"

# Process-wide httpx client for LLM calls
_http_client: Optional[httpx.AsyncClient] = None

async def get_http_client() -> httpx.AsyncClient:
    """Get or create the process-wide async HTTP client"""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=60.0)  # Increased for Ollama LLM calls
    return _http_client


class ChatStreamRequest(BaseModel):
    """Streaming chat request model"""
    message: Optional[str] = None
    prompt: Optional[str] = None
    q: Optional[str] = None
    session_id: Optional[str] = None
    # User-selectable model alias and thinking effort. Validated against the
    # server allowlist (model_catalog); provider ids are never accepted.
    model: Optional[str] = None
    effort: Optional[str] = None
    stream: Optional[bool] = True
    rag: Optional[bool] = True
    topK: Optional[int] = 8
    namespace: Optional[str] = None
    roles: Optional[list] = []


def is_small_talk(query: str) -> bool:
    """
    Detect small-talk/pleasantries that should not hit RAG.
    TIGHT rules: exact match on short phrases (≤3 words) only.
    Domain terms force RAG. "do not skip rag" forces RAG.
    Returns True if the query is small-talk.
    """
    query_lower = query.lower().strip()
    
    # Force RAG if user explicitly requests it
    if "do not skip rag" in query_lower or "don't skip rag" in query_lower:
        return False
    
    # Domain terms whitelist - if any of these appear, force RAG
    domain_terms = [
        'policy', 'policies', 'leave', 'vacation', 'pto', 'sick',
        'revenue', 'profit', 'financial', 'salary', 'expense',
        'employee', 'handbook', 'hr', 'benefit', 'insurance',
        'document', 'file', 'data', 'report', 'summary',
        'company', 'department', 'manager', 'team',
        'work', 'project', 'task', 'deadline', 'meeting'
    ]
    if any(term in query_lower for term in domain_terms):
        return False
    
    # Word count check: queries > 3 words are likely content queries
    word_count = len(query_lower.split())
    if word_count > 3:
        return False
    
    # Exact match small-talk set (≤3 words each)
    small_talk_exact = {
        # Greetings (1-2 words)
        'hi', 'hello', 'hey', 'hey sir', 'hey there',
        'good morning', 'good afternoon', 'good evening',
        'morning', 'afternoon', 'evening',
        # Status (2-3 words)
        'how are you', 'what\'s up', 'whats up', 'sup',
        'how\'s it going', 'hows it going',
        # Identity (2-3 words)
        'who are you', 'what are you', 'your name',
        # Thanks (1-2 words)
        'thanks', 'thank you', 'thx',
        # Goodbye (1-2 words)
        'bye', 'goodbye', 'see you', 'see ya', 'later',
        'good night', 'goodnight',
        # Bangla
        'হ্যালো', 'হাই', 'কেমন আছেন', 'কেমন আছো', 'ধন্যবাদ', 'বিদায়'
    }
    
    return query_lower in small_talk_exact


def get_small_talk_response(query: str) -> str:
    """Generate neutral small-talk response."""
    query_lower = query.lower().strip()
    if query_lower in {'হ্যালো', 'হাই'}:
        return "হ্যালো! আমি আপনার নথিভিত্তিক প্রশ্নে সাহায্য করতে প্রস্তুত। কী জানতে চান?"
    if query_lower in {'কেমন আছেন', 'কেমন আছো'}:
        return "আমি ভালো আছি, ধন্যবাদ! কী তথ্য খুঁজে দিতে পারি?"
    if query_lower == 'ধন্যবাদ':
        return "স্বাগতম! আরও কোনো তথ্য প্রয়োজন হলে বলুন।"
    if query_lower == 'বিদায়':
        return "বিদায়! প্রয়োজন হলে আবার আসবেন।"
    if any(word in query_lower for word in ['hello', 'hi', 'hey', 'morning', 'afternoon', 'evening']):
        return "Hello! I'm here to help you find information. What would you like to know?"
    elif any(word in query_lower for word in ['how are you', 'what\'s up', 'whats up']):
        return "I'm doing well, thank you! I'm ready to help you with any questions you have."
    elif any(word in query_lower for word in ['who are you', 'what are you']):
        return "I'm an AI assistant here to help you find information and answer your questions. How can I assist you today?"
    elif any(word in query_lower for word in ['thank', 'thanks']):
        return "You're welcome! Let me know if there's anything else I can help with."
    elif any(word in query_lower for word in ['bye', 'goodbye', 'see you', 'see ya']):
        return "Goodbye! Feel free to come back anytime you need assistance."
    else:
        return "I'm here to help! What would you like to know?"


def _persist_conversation(
    session_id: str, user_id: str, user_role: Role, tenant_id: str, query: str,
    response: str, sources: Optional[list] = None,
    visitor_session_id: Optional[str] = None,
    model_record: Optional[dict] = None,
) -> None:
    """Persist a delivered exchange atomically or raise.

    The caller emits ``complete`` only after this succeeds, so that event is a
    truthful durability acknowledgement rather than merely a generation ack.
    """
    db_manager.persist_chat_exchange(
        session_id=session_id,
        user_id=user_id,
        tenant_id=tenant_id,
        user_role=user_role.value,
        query=query,
        response=response,
        sources=sources or [],
        visitor_session_id=visitor_session_id,
        # Record which model/effort actually produced the answer. Canned
        # replies (small talk, inventory, empty retrieval) record none.
        assistant_meta={"model": model_record} if model_record else None,
    )


def is_inventory_query(query: str) -> bool:
    """
    Detect document inventory queries like "which documents", "list sources", "what docs".
    Returns True if the query is asking for document inventory.
    """
    query_lower = query.lower().strip()
    inventory_keywords = [
        'which document', 'what document', 'list document', 'show document',
        'which file', 'what file', 'list file', 'show file',
        'types of doc', 'kind of doc', 'what sources', 'list sources',
        'available document', 'have document', 'document inventory'
        , 'কোন নথি', 'নথির তালিকা', 'কোন ডকুমেন্ট', 'ফাইলের তালিকা'
    ]
    return any(keyword in query_lower for keyword in inventory_keywords)


async def generate_sse_response(
    query: str,
    user_role: Role,
    user_name: str,
    user_email: str,
    session_id: str,
    rag_service: RAGService,
    request: Request,
    user_id: str,
    tenant_id: str,
    topK: int = 8,
    namespace: str = 'company_docs',
    visitor_session_id: Optional[str] = None,
    generation: Optional[ModelSelection] = None,
) -> AsyncGenerator[str, None]:
    """
    ChatGPT-style streaming with RAG-empty fallback to general LLM.
    Checks client disconnects each loop iteration.

    CRITICAL: Every code path MUST yield "data: [DONE]\\n\\n" to complete the SSE stream.
    Uses try/finally to guarantee completion.
    """
    import uuid

    # Generate trace_id for request tracking
    trace_id = str(uuid.uuid4())

    # Timeout hierarchy (see settings.py):
    #   ollama_timeout_seconds  <  rag_hard_timeout_seconds
    # Heartbeats only control ping cadence, never the deadline.
    heartbeat_interval = settings.sse_heartbeat_seconds
    stream_completed = False
    exchange_failed = False

    try:
        # [*] AUDIT: Log successful authentication
        logger.info(f"[{trace_id}] STEP 0: Auth passed - user_id={user_id} email={user_email} tenant_id={tenant_id}")
        
        # [*] IMMEDIATE START - Send start signal instantly
        yield f"data: {json.dumps({'type': 'start', 'timestamp': datetime.now().isoformat()})}\n\n"
        # Status hint to avoid frozen UI
        yield f"data: {json.dumps({'type': 'status', 'text': 'Thinking...'})}\n\n"
        await asyncio.sleep(0)
        
        # Check for disconnect
        if await request.is_disconnected():
            logger.info("Client disconnected before processing")
            stream_completed = True
            return
        
        # [A] EARLY SMALL-TALK ROUTER - Detect before RAG
        if is_small_talk(query):
            logger.info(f"[{trace_id}] INTENT: small_talk - skipping RAG")
            response_text = get_small_talk_response(query)
            
            # Stream the response character by character
            for char in response_text:
                if await request.is_disconnected():
                    stream_completed = True
                    return
                yield f"data: {json.dumps({'type': 'token', 'token': char})}\n\n"
                await asyncio.sleep(0.01)
            
            # Tokens have been delivered; persist before acknowledging complete.
            _persist_conversation(
                session_id=session_id,
                user_id=user_id,
                user_role=user_role,
                tenant_id=tenant_id,
                query=query,
                response=response_text,
                sources=[],
                visitor_session_id=visitor_session_id,
            )

            # Send completion
            yield f"data: {json.dumps({'type': 'complete', 'sources': [], 'documents_found': 0, 'streaming_mode': 'small_talk'})}\n\n"
            yield "data: [DONE]\n\n"
            stream_completed = True
            return
        
        # [C] DOCUMENT INVENTORY INTENT - Query metadata directly
        if is_inventory_query(query):
            logger.info(f"[{trace_id}] INTENT: inventory - querying metadata")
            try:
                inventory_response = rag_service.get_document_inventory(tenant_id, user_role)
            except Exception as inv_err:
                logger.error(f"[{trace_id}] Inventory query error: {inv_err}")
                # Fall through to normal RAG
            else:
                # Stream the inventory response. Persistence errors below are
                # intentionally not treated as retrieval errors and must reach
                # the outer SSE error handler.
                for char in inventory_response:
                    if await request.is_disconnected():
                        return
                    yield f"data: {json.dumps({'type': 'token', 'token': char})}\n\n"
                    await asyncio.sleep(0.01)

                _persist_conversation(
                    session_id=session_id,
                    user_id=user_id,
                    user_role=user_role,
                    tenant_id=tenant_id,
                    query=query,
                    response=inventory_response,
                    sources=[],
                    visitor_session_id=visitor_session_id,
                )

                yield f"data: {json.dumps({'type': 'complete', 'sources': [], 'documents_found': 0, 'streaming_mode': 'inventory'})}\n\n"
                yield "data: [DONE]\n\n"
                stream_completed = True
                return
        
        # Try RAG retrieval for content queries
        logger.info(f"[{trace_id}] STEP 1: Starting RAG retrieval - topK={topK} ns={namespace}")

        # Conversation context is authoritative server state. The session was
        # ownership-checked before response headers were sent.
        conversation_history = db_manager.get_bounded_conversation_context(
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            visitor_session_id=visitor_session_id,
        )
        
        # Log content intent (default path)
        logger.info(f"[{trace_id}] INTENT: content - querying RAG")
        
        try:
            # ═══════════════════════════════════════════════════════════════════════
            # HARD TIMEOUT WRAPPER — outer bound on the whole RAG operation.
            # Configured via RAG_HARD_TIMEOUT_SECONDS and validated at startup to
            # be strictly greater than the Ollama request timeout.
            # ═══════════════════════════════════════════════════════════════════════
            RAG_HARD_TIMEOUT = float(settings.rag_hard_timeout_seconds)
            rag_start_time = time.time()

            logger.info(f"[{trace_id}] DBG-PRE: Creating RAG task with hard timeout={RAG_HARD_TIMEOUT}s")

            # Call RAG with correct signature including tenant_id
            rag_task = asyncio.create_task(asyncio.to_thread(
                rag_service.process_query,
                query=query,
                user_id=user_id,
                tenant_id=tenant_id,
                top_k=topK or 8,
                departments=[user_role.value] if user_role else ["general"],
                conversation_id=session_id,
                include_citations=True,
                user_role=user_role,
                user_name=user_name,
                trace_id=trace_id,
                conversation_history=conversation_history,
                generation=generation,
            ))

            # Heartbeat loop with HARD TIMEOUT check
            # FIX: Don't use is_disconnected() during RAG wait - it's unreliable with asyncio.to_thread
            # See: https://github.com/encode/starlette/issues/1012
            result = None
            heartbeat_count = 0

            while True:
                elapsed = time.time() - rag_start_time
                remaining = RAG_HARD_TIMEOUT - elapsed
                if remaining <= 0:
                    logger.error(f"[{trace_id}] DBG-TIMEOUT: RAG exceeded hard timeout ({elapsed:.1f}s > {RAG_HARD_TIMEOUT}s)")
                    rag_task.cancel()
                    raise asyncio.TimeoutError(f"RAG hard timeout after {elapsed:.1f}s")

                # Wait at most until the deadline, so the effective bound equals
                # the configured one. Previously this always waited a full
                # heartbeat, overshooting the hard timeout by up to one interval.
                wait_for = min(heartbeat_interval, remaining)

                try:
                    # SECURITY FIX: Use asyncio.shield to prevent heartbeat timeout
                    # from cancelling the RAG task. Without shield, wait_for cancels
                    # the wrapped coroutine on timeout, killing slow Ollama calls.
                    result = await asyncio.wait_for(asyncio.shield(rag_task), timeout=wait_for)
                    elapsed = time.time() - rag_start_time  # Recalculate after completion
                    logger.info(f"[{trace_id}] DBG-COMPLETE: RAG returned in {elapsed:.2f}s")
                    logger.info(f"[{trace_id}] DBG-BREAK: About to break from while loop")
                    break
                except asyncio.TimeoutError:
                    elapsed = time.time() - rag_start_time  # Recalculate after timeout
                    heartbeat_count += 1
                    if await request.is_disconnected():
                        logger.info(f"[{trace_id}] Client disconnected during RAG wait")
                        rag_task.cancel()
                        await asyncio.gather(rag_task, return_exceptions=True)
                        stream_completed = True
                        return
                    logger.info(f"[{trace_id}] DBG-HEARTBEAT: Sending ping #{heartbeat_count} at {elapsed:.1f}s")
                    yield f"data: {json.dumps({'type': 'ping', 'elapsed': round(elapsed, 1)})}\n\n"
                    await asyncio.sleep(0.1)  # Small delay to prevent tight loop
                    # The loop deadline above is the single authority on when to
                    # give up. A separate heartbeat-count limit was a second,
                    # inconsistent deadline (its comment claimed 5 x 7s = 35s while
                    # the interval was actually 15s), so it has been removed.

            # Validate RAG result
            if result is None:
                logger.error(f"[{trace_id}] RAG returned None")
                raise ValueError("RAG service returned None result")
            
            if not isinstance(result, dict):
                logger.error(f"[{trace_id}] RAG returned non-dict: {type(result)}")
                raise ValueError(f"RAG service returned invalid type: {type(result)}")
            
            # Extract fields safely
            docs_found = result.get('documents_found', 0)
            used_rag = result.get('used_rag', docs_found > 0)
            sources = result.get('sources', [])
            if not isinstance(sources, list):
                sources = list(sources) if sources else []
            
            logger.info(f"[{trace_id}] STEP 2: RAG complete — docs={docs_found} sources={len(sources)}")

            if result.get('success') is False:
                # Pipeline or generation failure. The service already returns a
                # curated user_message and no sources; surface it as a failure
                # (complete.success=false) rather than as a "no documents" answer.
                logger.warning(
                    f"[{trace_id}] RAG_FAILED generation_status={result.get('generation_status')} docs={docs_found}"
                )
                exchange_failed = True
                full_response = result.get('response') or "The request could not be completed. Please try again."
            elif docs_found == 0:
                # RAG_EMPTY: Send status event, then fall back to general LLM
                logger.info(f"[{trace_id}] RAG_EMPTY: falling back to general LLM")
                yield f"data: {json.dumps({'type': 'rag_status', 'value': 'empty'})}\n\n"
                await asyncio.sleep(0.01)
                
                # Check for disconnect
                if await request.is_disconnected():
                    logger.info("Client disconnected during RAG check")
                    stream_completed = True
                    return
                
                # Fall back to general LLM generation with context
                general_task = asyncio.create_task(generate_general_response(query, tenant_id, user_role.value))
                while True:
                    try:
                        full_response = await asyncio.wait_for(asyncio.shield(general_task), timeout=heartbeat_interval)
                        break
                    except asyncio.TimeoutError:
                        if await request.is_disconnected():
                            stream_completed = True
                            return
                        yield f"data: {json.dumps({'type': 'ping'})}\n\n"
            else:
                # RAG succeeded
                logger.info(f"[{trace_id}] RAG retrieved={docs_found} model=llama3.2 user_id={user_id} tenant_id={tenant_id}")
                # Safe response extraction
                raw_response = result.get('response', '')
                if raw_response is None:
                    full_response = ""
                elif not isinstance(raw_response, str):
                    logger.warning(f"[{trace_id}] Response was {type(raw_response)}, converting to str")
                    full_response = str(raw_response)
                else:
                    full_response = raw_response
            
            # NOTE: Persistence deferred until after stream completes successfully.
            # See post-stream persistence block below.
            _deferred_response = full_response
            _deferred_sources = sources if docs_found > 0 else []
            
        except Exception as e:
            # A timeout or pipeline crash is a failure, not an empty retrieval:
            # answering "I couldn't find documents" here would misstate what
            # happened, and persisting it would replay that into later context.
            timed_out = isinstance(e, asyncio.TimeoutError)
            logger.error(f"[{trace_id}] RAG {'timeout' if timed_out else 'error'}: {type(e).__name__}", exc_info=not timed_out)
            exchange_failed = True
            result = {
                'success': False,
                'retrieval_status': 'unknown',
                'generation_status': 'timeout' if timed_out else 'error',
                'sources': [],
            }
            docs_found = 0
            full_response = (
                "The request took too long to complete. Please try again."
                if timed_out else
                "The request could not be completed. Please try again."
            )
            _deferred_sources = []
        
        # Stream the response
        logger.info(f"[{trace_id}] STEP 3: Streaming response, len={len(full_response) if full_response else 0}")

        # Guard against empty response
        if not full_response:
            full_response = "I'm sorry, I couldn't generate a response. Please try again."
        _deferred_response = full_response
        if '_deferred_sources' not in locals():
            _deferred_sources = []

        yield f"data: {json.dumps({'type': 'response_start'})}\n\n"
        await asyncio.sleep(0.01)

        # Stream in word-sized chunks for a fast, GPT-like experience
        words = full_response.split(' ')
        chunk_count = 0
        WORDS_PER_CHUNK = 3
        for i in range(0, len(words), WORDS_PER_CHUNK):
            chunk = ' '.join(words[i:i + WORDS_PER_CHUNK])
            # Add leading space for all chunks after the first
            if i > 0:
                chunk = ' ' + chunk
            chunk_count += 1

            # Check for disconnect every 10 chunks (not every iteration)
            if chunk_count % 10 == 0 and await request.is_disconnected():
                logger.info("Client disconnected during streaming")
                stream_completed = True
                return

            yield f"data: {json.dumps({'type': 'token', 'token': chunk})}\n\n"
            await asyncio.sleep(0.03)
        
        # All response tokens were delivered. Persist before emitting complete;
        # a disconnect above leaves no false history, while a complete event now
        # guarantees that both messages committed together. Failed exchanges
        # (complete.success=false) are shown live but never persisted, so a
        # reload cannot present a failure as an answered question.
        if not exchange_failed and '_deferred_response' in locals() and _deferred_response:
            _persist_conversation(
                session_id=session_id,
                user_id=user_id,
                user_role=user_role,
                tenant_id=tenant_id,
                query=query,
                response=_deferred_response,
                sources=_deferred_sources if '_deferred_sources' in locals() else [],
                visitor_session_id=visitor_session_id,
                model_record=(result or {}).get('model_record') if isinstance(locals().get('result'), dict) else None,
            )

        # Send completion event.
        # `result` is initialised to None before the RAG wait, so guard on the
        # value rather than merely on the name being bound.
        _res = result if isinstance(locals().get('result'), dict) else {}
        completion_data = {
            'type': 'complete',
            # Citation invariant: sources come only from what RAG actually
            # retrieved and answered from. On a miss or a generation failure the
            # service already returns [].
            'sources': _res.get('sources', []),
            'retrieval_status': _res.get('retrieval_status', 'unknown'),
            'generation_status': _res.get('generation_status', 'unknown'),
            'retry_after_seconds': _res.get('retry_after_seconds'),
            'success': bool(_res.get('success', False)),
            'documents_found': docs_found if 'docs_found' in locals() else 0,
            # Model that wrote (or failed to write) this answer; absent when no
            # model ran (empty retrieval, canned replies).
            'model': _res.get('model'),
            'streaming_mode': 'real_time'
        }
        yield f"data: {json.dumps(completion_data)}\n\n"
        
        # Send final done event
        logger.info(f"[{trace_id}] STEP 4: Yielding [DONE] - stream complete")
        yield "data: [DONE]\n\n"
        stream_completed = True

    except asyncio.CancelledError:
        logger.info(f"[{trace_id}] Client disconnected (CancelledError) — no persistence")
        if not stream_completed:
            yield "data: [DONE]\n\n"
        return

    except Exception as e:
        logger.error(f"[{trace_id}] Error in SSE generation: {e}", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'message': 'Streaming response failed'})}\n\n"
        yield "data: [DONE]\n\n"
        stream_completed = True

    finally:
        for task_name in ("rag_task", "general_task"):
            task = locals().get(task_name)
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        # CRITICAL: Ensure [DONE] is always sent to complete ASGI response
        if not stream_completed:
            logger.warning(f"[{trace_id}] Stream did not complete normally, sending [DONE]")
            yield "data: [DONE]\n\n"


async def generate_general_response(query: str, tenant_id: str = "", user_role: str = "employee") -> str:
    """
    Generate a professional assistant response when RAG returns no results.
    Provides helpful suggestions instead of generic disclaimers.
    """
    # Detect small-talk patterns (greetings, casual questions, etc.)
    query_lower = query.lower().strip()
    query_language, _ = detect_language(query)
    small_talk_keywords = [
        'hello', 'hi', 'hey', 'good morning', 'good afternoon', 'good evening',
        'how are you', 'what\'s up', 'whats up', 'sup',
        'who are you', 'what are you', 'your name',
        'thank', 'thanks', 'bye', 'goodbye', 'see you'
    ]

    is_small_talk_query = any(keyword in query_lower for keyword in small_talk_keywords)

    if is_small_talk_query:
        # Neutral small-talk response without corporate disclaimer
        if any(word in query_lower for word in ['hello', 'hi', 'hey', 'morning', 'afternoon', 'evening']):
            return "Hello! I'm here to help you find information. What would you like to know?"
        elif any(word in query_lower for word in ['how are you', 'what\'s up', 'whats up']):
            return "I'm doing well, thank you! I'm ready to help you with any questions you have."
        elif any(word in query_lower for word in ['who are you', 'what are you']):
            return "I'm an AI assistant here to help you find information and answer your questions. How can I assist you today?"
        elif any(word in query_lower for word in ['thank', 'thanks']):
            return "You're welcome! Let me know if there's anything else I can help with."
        elif any(word in query_lower for word in ['bye', 'goodbye', 'see you']):
            return "Goodbye! Feel free to come back anytime you need assistance."
        else:
            return "I'm here to help! What would you like to know?"
    else:
        if query_language == 'bn':
            return (
                "আপনার অনুমোদিত নথিতে এই প্রশ্নের সঙ্গে মিলে এমন তথ্য পাওয়া যায়নি। "
                "আরও সাধারণ শব্দ ব্যবহার করে প্রশ্নটি আবার করতে পারেন বা সংশ্লিষ্ট নথি আপলোড হয়েছে কি না যাচাই করুন।"
            )
        # Professional empty-RAG response with helpful suggestions. The user's
        # text is deliberately not quoted back: this reply is streamed,
        # persisted and exported as assistant content, and echoing raw input
        # (e.g. markup or "os.environ['SECRET_KEY']") into it is avoidable.
        suggestions = [
            "company policies or employee handbook",
            "financial reports and summaries",
            "HR information and benefits",
            "department-specific documents"
        ]

        return (
            "I couldn't find documents matching your question in the knowledge base.\n\n"
            f"💡 **Suggestions:**\n"
            f"• Try broader keywords (e.g., 'leave policy' instead of specific dates)\n"
            f"• Ask about: {', '.join(suggestions[:2])}\n"
            f"• Check if the document has been uploaded to your department\n\n"
            f"How else can I help you?"
        )


async def unified_chat_stream_handler(
    query: str,
    session_id: Optional[str],
    request: Request,
    current_user: Dict,
    model: Optional[str] = None,
    effort: Optional[str] = None,
) -> StreamingResponse:
    """
    Unified handler for both GET and POST chat stream requests.
    """
    # Validate prompt
    if not query or not query.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "missing_prompt"}
        )

    # Validate the model choice before any work or response headers. An
    # unknown/unavailable alias or unsupported effort is refused, never
    # silently replaced with another model.
    try:
        generation = resolve_selection(model, effort)
    except ModelSelectionError as exc:
        return JSONResponse(status_code=400, content={"error": exc.code, "message": exc.message})
    
    visitor_session_id = require_visitor_session_for_demo(current_user, request)

    # Get RAG service from app state (singleton)
    # An attribute that exists but is None (e.g. a cleared slot) must fall back
    # too; hasattr() alone would hand None to the stream and crash it.
    rag_service = getattr(request.app.state, 'rag', None) or RAGService()

    # Get user details
    user_role_str = current_user.get('role', 'employee')
    try:
        user_role = Role(user_role_str) if isinstance(user_role_str, str) else user_role_str
    except ValueError:
        user_role = Role.EMPLOYEE
    
    user_name = current_user.get('name', 'User')
    user_email = current_user.get('email', 'unknown')
    user_id = (current_user.get('id') or '').strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Authenticated user id missing")
    
    # Tenant is mandatory and comes only from authenticated identity.
    tenant_id = (current_user.get('tenant_id') or current_user.get('organization_id') or '').strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="Tenant context missing")
    
    if not session_id:
        # Public-demo accounts share one physical user_id across every
        # anonymous visitor, so the plain "user_{user_id}" default would have
        # every such visitor collide on the exact same conversation id.
        # SECURITY: the default must NOT embed the raw vsid (or user_id)
        # directly — this id is returned to the client via conversation-list/
        # get responses, and a raw vsid there would let frontend JS recover
        # the httpOnly cookie value. _derive_public_demo_session_id() gives a
        # deterministic but one-way replacement instead. Non-demo default is
        # unchanged.
        session_id = (
            _derive_public_demo_session_id(user_id, visitor_session_id) if visitor_session_id
            else f"user_{user_id}"
        )

    # Public-demo daily/concurrency protection: charged once per accepted
    # message, before any retrieval or model call.
    lease = None
    if (current_user.get("is_public_demo") or demo_usage.is_super_admin(current_user)) and settings.public_demo_enabled:
        try:
            lease = await asyncio.to_thread(demo_usage.admit, request, visitor_session_id, current_user)
        except demo_usage.DemoLimitError as exc:
            logger.info("DEMO_LIMIT_REFUSED code=%s", exc.code)
            return _demo_refusal(request, exc)

    # Reserve/authorize before response headers are sent. Any cross-tenant or
    # same-tenant collision is rejected before RAG and before the SSE stream.
    try:
        db_manager.ensure_chat_session(
            user_id=user_id,
            session_id=session_id,
            metadata={"tenant_id": tenant_id, "user_role": user_role.value},
            visitor_session_id=visitor_session_id,
        )
    except ConversationNotFoundError as exc:
        if lease:
            await asyncio.to_thread(lease.refund_once)
            lease.release()
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    except ConversationForbiddenError as exc:
        if lease:
            await asyncio.to_thread(lease.refund_once)
            lease.release()
        raise HTTPException(status_code=403, detail="Forbidden") from exc
    except BaseException:
        if lease:
            lease.release()
        raise

    stream = generate_sse_response(
            query=query.strip(),
            user_role=user_role,
            user_name=user_name,
            user_email=user_email,
            session_id=session_id,
            rag_service=rag_service,
            request=request,
            user_id=user_id,
            tenant_id=tenant_id,
            topK=8,
            namespace='company_docs',
            visitor_session_id=visitor_session_id,
            generation=generation,
    )
    return StreamingResponse(
        _leased_stream(stream, lease) if lease else stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Access-Control-Allow-Credentials": "true",
        }
    )


@router.post("/chat/stream")
async def chat_stream_post(
    request: Request,
    body: ChatStreamRequest
):
    """
    POST endpoint for streaming chat.
    Accepts JSON body with any of {message, prompt, q}.
    """
    # Get current user (POST doesn't use URL token)
    current_user = await get_current_user_from_request(request, url_token=None)
    
    # Extract query from any of the possible fields
    query = body.message or body.prompt or body.q
    
    return await unified_chat_stream_handler(
        query=query,
        session_id=body.session_id,
        request=request,
        current_user=current_user,
        model=body.model,
        effort=body.effort,
    )


@router.get("/chat/stream")
async def chat_stream_get(
    request: Request,
    q: Optional[str] = None,
    prompt: Optional[str] = None,
    message: Optional[str] = None,
    session_id: Optional[str] = None,
    model: Optional[str] = None,
    effort: Optional[str] = None,
):
    """
    GET endpoint for streaming chat.
    Accepts query param: ?q= or ?prompt= or ?message=
    Auth via cookies only (EventSource with withCredentials)
    """
    # This GET mutates state (persists the exchange, spends LLM quota) under
    # cookie auth, so the CSRF middleware's unsafe-method check does not cover
    # it, and SameSite=Lax cookies DO accompany a cross-site top-level
    # navigation. Refuse requests the browser marks as cross-site, and any
    # Origin outside the allowlist. Same-origin/same-site EventSource and
    # non-browser clients (no Sec-Fetch-Site) are unaffected.
    origin = request.headers.get("Origin")
    if (request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site"
            or (origin and origin not in settings.cors_origins)):
        return JSONResponse(status_code=403, content={"detail": "Cross-site request rejected"})

    # Get current user from cookies only
    current_user = await get_current_user_from_request(request, url_token=None)

    # Extract query from any of the possible parameters
    query = q or prompt or message
    
    return await unified_chat_stream_handler(
        query=query,
        session_id=session_id,
        request=request,
        current_user=current_user,
        model=model,
        effort=effort,
    )


@router.get("/chat/models")
async def chat_models(request: Request):
    """Safe catalog of selectable chat models (aliases only, no provider
    ids or URLs) plus voice-dictation availability. Authenticated."""
    await get_current_user_from_request(request, url_token=None)
    from src.backend.api.speech import dictation_capability
    catalog = await asyncio.to_thread(get_catalog)
    return {**catalog, "dictation": dictation_capability()}


async def get_current_user_from_request(request: Request, url_token: Optional[str] = None) -> Dict:
    """Delegate every SSE authentication decision to the shared dependency."""
    return await get_current_user(request)


# Health check for streaming endpoint
@router.get("/chat/stream/health")
async def stream_health():
    """Check if streaming endpoint is healthy"""
    return {"status": "healthy", "streaming": True}
