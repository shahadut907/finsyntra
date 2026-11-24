"""Wave 7 closure: /api/chat must not block the asyncio event loop.

Before this fix, `chat()` called `rag_service.text_generation(...)` directly
(a synchronous call, on the event loop) which in turn called
`translate_text()` -> `GoogleTranslator(...).translate()` with no bounded
timeout for any Bangla-language turn. A slow/stuck call there froze every
other request on the same server process — proven against the real dev
server (see docs of this closure pass): three English `/api/chat` calls each
completed in ~1s, then the first Bangla call hung past 60s and every request
afterward (including unrelated English/finance/tenant_beta ones) also timed
out on the same process.

The fix routes `/api/chat` through the same `rag_service.process_query`
pipeline the SSE endpoint already uses (deterministic offline Bangla
retrieval hinting, no external translation call), offloaded with
`asyncio.to_thread` and bounded by `RAG_HARD_TIMEOUT_SECONDS` via
`asyncio.wait_for`. These tests reproduce the failure mode with a
deliberately slow, genuinely blocking (`time.sleep`) mocked RAG call and
prove: (1) an unrelated concurrent request stays responsive, (2) a call that
exceeds the hard timeout fails safely without persisting a false success.
"""
import asyncio
import time
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.backend.api.endpoints import app
from src.backend.database.database import ChatMessage, SessionLocal, create_tables
from src.backend.middleware.security import rate_limiter
from src.config.settings import settings


def _message_count(session_id):
    db = SessionLocal()
    try:
        return db.query(ChatMessage).filter(ChatMessage.session_id == session_id).count()
    finally:
        db.close()


@pytest.fixture
async def demo_client(monkeypatch):
    create_tables()
    rate_limiter.reset()
    monkeypatch.setattr(settings, "public_demo_enabled", True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        await value.post("/auth/demo-login", json={"role": "employee"})
        value.headers["X-CSRF-Token"] = value.cookies.get("csrf_token")
        yield value
    rate_limiter.reset()


def _blocking_process_query(delay_seconds, **response_overrides):
    """A fake RAGService.process_query that genuinely blocks the calling
    thread for `delay_seconds` — reproducing a stuck synchronous network call
    (e.g. the old unbounded GoogleTranslator request), not merely a slow
    coroutine."""
    def _impl(*args, **kwargs):
        time.sleep(delay_seconds)
        base = {
            "success": True,
            "response": "slow answer",
            "sources": ["doc.md"],
            "documents_found": 1,
            "processing_time": f"{delay_seconds:.2f}s",
        }
        base.update(response_overrides)
        return base
    return _impl


@pytest.mark.asyncio
async def test_slow_rag_call_does_not_block_concurrent_health_request(demo_client):
    """The old implementation would fail this: a slow synchronous call inside
    the /api/chat handler ran directly on the event loop, so a concurrent
    /health request had to wait behind it."""
    with patch(
        "src.backend.api.chat.RAGService.process_query",
        new=_blocking_process_query(2.0),
    ):
        chat_task = asyncio.create_task(
            demo_client.post("/api/chat", json={"message": "trigger the slow path"})
        )
        await asyncio.sleep(0.05)  # let the chat request actually start

        t0 = time.monotonic()
        health_response = await demo_client.get("/health")
        health_latency = time.monotonic() - t0

        assert health_response.status_code == 200
        # A blocked event loop would make this wait ~2s behind the chat call.
        assert health_latency < 1.0, f"/health took {health_latency:.2f}s — event loop appears blocked"

        chat_response = await chat_task
        assert chat_response.status_code == 200
        assert chat_response.json()["response"] == "slow answer"


@pytest.mark.asyncio
async def test_hard_timeout_returns_controlled_failure_and_does_not_persist(demo_client, monkeypatch):
    monkeypatch.setattr(settings, "rag_hard_timeout_seconds", 0.3)
    with patch(
        "src.backend.api.chat.RAGService.process_query",
        new=_blocking_process_query(2.0),
    ):
        response = await demo_client.post(
            "/api/chat",
            json={"message": "this will exceed the hard timeout", "session_id": "wave7-timeout-probe"},
        )

    assert response.status_code == 503
    body = response.json()
    # No raw exception, traceback, or internal detail leaked to the client.
    detail = str(body.get("detail", ""))
    assert "Traceback" not in detail
    assert "asyncio" not in detail
    assert "Exception" not in detail

    assert _message_count("wave7-timeout-probe") == 0, (
        "a timed-out turn must not be persisted as a successful exchange"
    )


@pytest.mark.asyncio
async def test_successful_response_still_persists_normally(demo_client):
    with patch(
        "src.backend.api.chat.RAGService.process_query",
        new=_blocking_process_query(0.0, response="normal fast answer"),
    ):
        response = await demo_client.post(
            "/api/chat",
            json={"message": "a normal question", "session_id": "wave7-normal-probe"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["response"] == "normal fast answer"
    assert body["success"] is True
    assert _message_count("wave7-normal-probe") == 2  # user turn + assistant turn
