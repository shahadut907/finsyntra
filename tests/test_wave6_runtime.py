"""Focused Wave 6 memory, Bangla, SSE, and disconnect regressions."""
import asyncio
import time
import uuid

import pytest

from src.backend.api.chat_stream import generate_sse_response
from src.backend.database.database import create_tables, db_manager
from src.backend.services.language_utils import detect_language, prepare_retrieval_query
from src.config.roles import Role
from src.config.settings import settings

USER = "employee@finsolve.com"
TENANT = "tenant_acme"


@pytest.fixture(autouse=True)
def schema():
    create_tables()


def session_id():
    return f"wave6-{uuid.uuid4().hex}"


def persist(sid, query, answer):
    db_manager.persist_chat_exchange(
        session_id=sid, user_id=USER, tenant_id=TENANT,
        user_role="employee", query=query, response=answer, sources=[])


def test_bounded_context_is_recent_ordered_and_owned():
    sid = session_id()
    for index in range(8):
        persist(sid, f"question-{index}-" + "q" * 500, f"answer-{index}-" + "a" * 500)
    history = db_manager.get_bounded_conversation_context(
        sid, USER, TENANT, max_messages=10, max_chars=1200)
    assert len(history) <= 10
    assert sum(len(item["content"]) for item in history) <= 1200
    assert "answer-7" in history[-1]["content"]
    with pytest.raises(ValueError):
        db_manager.get_bounded_conversation_context(sid, "other@finsolve.com", TENANT)
    with pytest.raises(ValueError):
        db_manager.get_bounded_conversation_context(sid, USER, "tenant_beta")


def test_bangla_detection_and_offline_retrieval_hints_are_per_query():
    bangla = "কোম্পানির কাজের সময় কী?"
    assert detect_language(bangla)[0] == "bn"
    assert "work hours" in prepare_retrieval_query(bangla, "bn")
    assert "leave policy" in prepare_retrieval_query("আর ছুটির নীতি?", "bn")
    assert prepare_retrieval_query("What about leave?", "en") == "What about leave?"


class RequestState:
    def __init__(self, disconnect_after=999):
        self.calls = 0
        self.disconnect_after = disconnect_after
    async def is_disconnected(self):
        self.calls += 1
        return self.calls >= self.disconnect_after


class CapturingRag:
    def __init__(self, delay=0):
        self.delay = delay
        self.kwargs = None
    def process_query(self, **kwargs):
        self.kwargs = kwargs
        if self.delay:
            time.sleep(self.delay)
        return {
            "success": True, "retrieval_status": "hit", "generation_status": "ok",
            "response": "কাজের সময় সকাল ৯টা থেকে বিকেল ৫টা।",
            "sources": ["employee_handbook.md"], "documents_found": 1,
            "used_rag": True,
        }


@pytest.mark.asyncio
async def test_sse_passes_owned_history_and_persists_bangla(monkeypatch):
    sid = session_id()
    persist(sid, "কোম্পানির কাজের সময় কী?", "সকাল ৯টা থেকে বিকেল ৫টা।")
    rag = CapturingRag()
    events = []
    async for event in generate_sse_response(
        query="আর ছুটির নীতি?", user_role=Role.EMPLOYEE, user_name="Employee",
        user_email=USER, session_id=sid, rag_service=rag, request=RequestState(),
        user_id=USER, tenant_id=TENANT, topK=8):
        events.append(event)
    assert rag.kwargs["tenant_id"] == TENANT
    assert rag.kwargs["conversation_history"][-1]["role"] == "assistant"
    assert "সকাল ৯টা" in rag.kwargs["conversation_history"][-1]["content"]
    assert sum("[DONE]" in event for event in events) == 1
    history = db_manager.get_bounded_conversation_context(sid, USER, TENANT, 10, 4000)
    assert history[-2]["content"] == "আর ছুটির নীতি?"
    assert "কাজের সময়" in history[-1]["content"]


@pytest.mark.asyncio
async def test_disconnect_cancels_async_wrapper_without_persistence(monkeypatch):
    sid = session_id()
    db_manager.ensure_chat_session(USER, sid, {"tenant_id": TENANT, "user_role": "employee"})
    monkeypatch.setattr(settings, "sse_heartbeat_seconds", 0.01)
    monkeypatch.setattr(settings, "rag_hard_timeout_seconds", 1)
    rag = CapturingRag(delay=0.25)
    started = time.perf_counter()
    events = []
    async for event in generate_sse_response(
        query="What is the handbook policy?", user_role=Role.EMPLOYEE,
        user_name="Employee", user_email=USER, session_id=sid, rag_service=rag,
        request=RequestState(disconnect_after=2), user_id=USER, tenant_id=TENANT):
        events.append(event)
    assert time.perf_counter() - started < 0.2
    assert db_manager.get_bounded_conversation_context(sid, USER, TENANT) == []
    # requests.post inside the worker cannot be hard-killed; production bounds
    # that worker by OLLAMA_TIMEOUT_SECONDS while the asyncio wrapper is gone.
    await asyncio.sleep(0)
