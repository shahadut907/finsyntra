"""Model selection, thinking effort and voice dictation.

Everything provider-facing is mocked: no network calls and no quota use.
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.services import model_catalog as mc
from src.backend.services.llm_provider import GroqProvider, LLMGenerationError, _strip_private_reasoning

SERVED = {"openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b", "whisper-large-v3"}


@pytest.fixture
def groq(monkeypatch):
    """Groq provider active, model listing mocked."""
    monkeypatch.setattr(mc.settings, "llm_provider", "groq")
    monkeypatch.setattr(mc.settings, "groq_api_key", "test-key")
    monkeypatch.setattr(mc.settings, "groq_model", "openai/gpt-oss-20b")
    monkeypatch.setattr(mc.settings, "chat_default_model", "prism")
    served = set(SERVED)
    monkeypatch.setattr(mc.availability, "served_models", lambda: served)
    return served


# --------------------------------------------------------------- catalog ---

def test_catalog_lists_aliases_without_provider_details(groq):
    catalog = mc.get_catalog()
    assert [m["id"] for m in catalog["models"]] == ["prism", "atlas", "axiom"]
    assert catalog["default_model"] == "prism"
    raw = json.dumps(catalog)
    assert "gpt-oss" not in raw and "qwen" not in raw and "http" not in raw
    axiom = next(m for m in catalog["models"] if m["id"] == "axiom")
    assert axiom["preview"] is True
    assert [e["id"] for e in axiom["efforts"]] == ["low", "medium", "high"]


def test_unserved_model_is_shown_unavailable_and_rejected(groq):
    groq.discard("qwen/qwen3.8-27b")
    axiom = next(m for m in mc.get_catalog()["models"] if m["id"] == "axiom")
    assert axiom["available"] is False and axiom["unavailable_reason"]
    with pytest.raises(mc.ModelSelectionError) as exc:
        mc.resolve_selection("axiom", "high")
    assert exc.value.code == "model_unavailable"


def test_listing_failure_only_trusts_startup_validated_model(groq, monkeypatch):
    monkeypatch.setattr(mc.availability, "served_models", lambda: None)
    available = {m["id"]: m["available"] for m in mc.get_catalog()["models"]}
    assert available == {"prism": True, "atlas": False, "axiom": False}


def test_ollama_offers_only_its_configured_model_without_effort(monkeypatch):
    monkeypatch.setattr(mc.settings, "llm_provider", "ollama")
    catalog = mc.get_catalog()
    assert [m["id"] for m in catalog["models"]] == ["prism"]
    assert catalog["models"][0]["efforts"] == []
    with pytest.raises(mc.ModelSelectionError):
        mc.resolve_selection("atlas", None)
    with pytest.raises(mc.ModelSelectionError) as exc:
        mc.resolve_selection("prism", "high")
    assert exc.value.code == "invalid_effort"


# ------------------------------------------------------------- resolution ---

@pytest.mark.parametrize("alias,model,control", [
    ("prism", "openai/gpt-oss-20b", {"include_reasoning": False}),
    ("atlas", "openai/gpt-oss-120b", {"include_reasoning": False}),
    ("axiom", "qwen/qwen3.8-27b", {"reasoning_format": "hidden"}),
])
@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_every_mapping_and_effort_resolves(groq, alias, model, control, effort):
    sel = mc.resolve_selection(alias, effort)
    assert sel.provider_model == model
    assert sel.reasoning_effort == effort
    assert sel.reasoning_controls == control
    assert sel.timeout_seconds < mc.settings.rag_hard_timeout_seconds
    assert sel.public_dict() == {"alias": alias, "label": alias.title(), "reasoning_effort": effort}


@pytest.mark.parametrize("alias,effort,code", [
    ("gpt-4o", None, "invalid_model"),
    ("openai/gpt-oss-120b", None, "invalid_model"),
    ("http://attacker.example/v1", None, "invalid_model"),
    ("prism", "ultra", "invalid_effort"),
    ("atlas", "none", "invalid_effort"),
    ("axiom", "xhigh", "invalid_effort"),
])
def test_tampered_selection_is_rejected_not_replaced(groq, alias, effort, code):
    with pytest.raises(mc.ModelSelectionError) as exc:
        mc.resolve_selection(alias, effort)
    assert exc.value.code == code


def test_defaults(groq):
    assert mc.resolve_selection(None, None).cache_token == "prism:openai/gpt-oss-20b:low"
    assert mc.resolve_selection("atlas", None).reasoning_effort == "medium"
    assert mc.resolve_selection(" AXIOM ", "HIGH").reasoning_effort == "high"


def test_effort_budget_grows(groq):
    budgets = [mc.resolve_selection("atlas", e).max_completion_tokens for e in ("low", "medium", "high")]
    assert budgets == sorted(budgets) and budgets[0] < budgets[-1]


# ------------------------------------------------------- provider request ---

def _groq_response(content="12:15", status=200):
    response = MagicMock(status_code=status, headers={})
    response.json.return_value = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}], "usage": {}}
    return response


def _provider():
    return GroqProvider(api_key="k", base_url="https://api.groq.com/openai/v1", model="openai/gpt-oss-20b",
                        timeout_seconds=20, reasoning_effort="auto")


def test_selection_drives_request_body(groq, monkeypatch):
    post = MagicMock(return_value=_groq_response())
    monkeypatch.setattr("src.backend.services.llm_provider.requests.post", post)
    _provider().generate("q", system="s", options=mc.resolve_selection("axiom", "high"))
    body = post.call_args.kwargs["json"]
    assert body["model"] == "qwen/qwen3.8-27b"
    assert body["reasoning_effort"] == "high"
    assert body["reasoning_format"] == "hidden"
    assert "include_reasoning" not in body          # mutually exclusive per Groq docs
    assert body["max_completion_tokens"] == 4096
    assert post.call_args.kwargs["timeout"] == mc.resolve_selection("axiom", "high").timeout_seconds

    _provider().generate("q", options=mc.resolve_selection("atlas", "low"))
    body = post.call_args.kwargs["json"]
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["include_reasoning"] is False and "reasoning_format" not in body


def test_no_selection_keeps_previous_behaviour(monkeypatch):
    post = MagicMock(return_value=_groq_response())
    monkeypatch.setattr("src.backend.services.llm_provider.requests.post", post)
    _provider().generate("q")
    body = post.call_args.kwargs["json"]
    assert body["model"] == "openai/gpt-oss-20b" and body["reasoning_effort"] == "low"
    assert "include_reasoning" not in body


def test_provider_failure_is_raised_not_rerouted(groq, monkeypatch):
    post = MagicMock(return_value=_groq_response(status=503))
    monkeypatch.setattr("src.backend.services.llm_provider.requests.post", post)
    with pytest.raises(LLMGenerationError) as exc:
        _provider().generate("q", options=mc.resolve_selection("atlas", "high"))
    assert exc.value.reason == "unavailable"
    assert post.call_count == 1
    assert post.call_args.kwargs["json"]["model"] == "openai/gpt-oss-120b"


@pytest.mark.parametrize("raw,clean", [
    ("<think>private</think>Answer", "Answer"),
    ("Answer", "Answer"),
    ("Answer <think>unterminated", "Answer"),
])
def test_private_reasoning_never_reaches_answer(raw, clean):
    assert _strip_private_reasoning(raw) == clean


# ------------------------------------------------------------ SSE wiring ---

class _Request:
    async def is_disconnected(self):
        return False


def _run_stream(monkeypatch, result, generation):
    from src.backend.api import chat_stream
    from src.config.roles import Role

    persisted = []
    monkeypatch.setattr(chat_stream.db_manager, "get_bounded_conversation_context", lambda **_: [])
    monkeypatch.setattr(chat_stream.db_manager, "persist_chat_exchange", lambda **kw: persisted.append(kw))
    calls = []

    def process_query(**kwargs):
        calls.append(kwargs)
        return result

    rag = SimpleNamespace(process_query=process_query)

    async def collect():
        events = []
        async for chunk in chat_stream.generate_sse_response(
            query="What is the leave policy for full-time staff?", user_role=Role.EMPLOYEE, user_name="T",
            user_email="t@x", session_id="s1", rag_service=rag, request=_Request(),
            user_id="u1", tenant_id="t1", generation=generation,
        ):
            data = chunk[len("data: "):].strip()
            if data and data != "[DONE]":
                events.append(json.loads(data))
        return events

    return asyncio.run(collect()), calls, persisted


def test_stream_passes_selection_records_and_reports_it(groq, monkeypatch):
    sel = mc.resolve_selection("atlas", "high")
    result = {"success": True, "documents_found": 2, "sources": ["handbook.md"], "response": "20 days.",
              "generation_status": "ok", "retrieval_status": "hit",
              "model": sel.public_dict(), "model_record": sel.record_dict()}
    events, calls, persisted = _run_stream(monkeypatch, result, sel)
    assert calls[0]["generation"] is sel                    # retrieval/RBAC path unchanged, model chosen
    complete = next(e for e in events if e["type"] == "complete")
    assert complete["model"] == {"alias": "atlas", "label": "Atlas", "reasoning_effort": "high"}
    assert complete["sources"] == ["handbook.md"]
    assert persisted[0]["assistant_meta"] == {"model": sel.record_dict()}


def test_failed_generation_names_model_and_is_not_persisted(groq, monkeypatch):
    sel = mc.resolve_selection("axiom", "medium")
    result = {"success": False, "documents_found": 2, "sources": [], "response": "The language model is busy.",
              "generation_status": "rate_limited", "retrieval_status": "hit", "model": sel.public_dict()}
    events, _, persisted = _run_stream(monkeypatch, result, sel)
    complete = next(e for e in events if e["type"] == "complete")
    assert complete["success"] is False
    assert complete["model"]["alias"] == "axiom"            # no silent switch to another model
    assert persisted == []


# --------------------------------------------------------------- speech ---

@pytest.fixture
def speech_client(groq, monkeypatch):
    from src.backend.api import speech
    from src.backend.middleware.security import rate_limiter

    rate_limiter.reset()

    async def user(_request):
        return {"id": "u1", "tenant_id": "t1", "role": "employee"}

    monkeypatch.setattr(speech, "get_current_user", user)
    monkeypatch.setattr(speech.settings, "speech_enabled", True)
    app = FastAPI()
    app.include_router(speech.router, prefix="/api")
    return TestClient(app), speech


WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 2048


def _whisper(monkeypatch, speech, payload, status=200):
    response = MagicMock(status_code=status, headers={})
    response.json.return_value = payload
    post = MagicMock(return_value=response)
    monkeypatch.setattr(speech.requests, "post", post)
    return post


def test_transcribe_returns_text_and_uses_language(speech_client, monkeypatch):
    client, speech = speech_client
    post = _whisper(monkeypatch, speech, {"text": "ছুটির নীতি", "language": "bengali", "duration": 3.0,
                                          "segments": [{"text": "ছুটির নীতি", "no_speech_prob": 0.01}]})
    r = client.post("/api/speech/transcribe", files={"audio": ("a.webm", WEBM, "audio/webm;codecs=opus")},
                    data={"language": "bn"})
    assert r.status_code == 200 and r.json()["text"] == "ছুটির নীতি"
    sent = post.call_args.kwargs
    assert sent["data"]["language"] == "bn" and sent["data"]["model"] == "whisper-large-v3"
    assert post.call_args.args[0].endswith("/audio/transcriptions")


def test_silence_hallucination_is_dropped(speech_client, monkeypatch):
    client, speech = speech_client
    _whisper(monkeypatch, speech, {"text": "Thank you.", "duration": 2.0,
                                   "segments": [{"text": "Thank you.", "no_speech_prob": 0.92}]})
    r = client.post("/api/speech/transcribe", files={"audio": ("a.webm", WEBM, "audio/webm")})
    assert r.status_code == 422 and r.json()["error"] == "no_speech"


@pytest.mark.parametrize("files,data,status,code", [
    ({"audio": ("a.txt", b"hello", "text/plain")}, {}, 415, "unsupported_audio"),
    ({"audio": ("a.webm", b"not audio at all" * 100, "audio/webm")}, {}, 422, "empty_audio"),
    ({"audio": ("a.webm", WEBM, "audio/webm")}, {"language": "fr"}, 400, "invalid_language"),
])
def test_bad_uploads_never_reach_provider(speech_client, monkeypatch, files, data, status, code):
    client, speech = speech_client
    post = _whisper(monkeypatch, speech, {})
    r = client.post("/api/speech/transcribe", files=files, data=data)
    assert r.status_code == status and r.json()["error"] == code
    post.assert_not_called()


def test_oversize_rejected_before_provider(speech_client, monkeypatch):
    client, speech = speech_client
    monkeypatch.setattr(speech.settings, "speech_max_bytes", 4096)
    post = _whisper(monkeypatch, speech, {})
    r = client.post("/api/speech/transcribe", files={"audio": ("a.webm", WEBM + b"\x00" * 5000, "audio/webm")})
    assert r.status_code == 413
    post.assert_not_called()


def test_overlong_audio_rejected(speech_client, monkeypatch):
    client, speech = speech_client
    _whisper(monkeypatch, speech, {"text": "long", "duration": 600.0})
    r = client.post("/api/speech/transcribe", files={"audio": ("a.webm", WEBM, "audio/webm")})
    assert r.status_code == 413


def test_provider_busy_and_failure_are_reported(speech_client, monkeypatch):
    client, speech = speech_client
    _whisper(monkeypatch, speech, {}, status=429)
    r = client.post("/api/speech/transcribe", files={"audio": ("a.webm", WEBM, "audio/webm")})
    assert r.status_code == 503 and r.json()["error"] == "provider_busy"
    _whisper(monkeypatch, speech, {}, status=500)
    r = client.post("/api/speech/transcribe", files={"audio": ("a.webm", WEBM, "audio/webm")})
    assert r.status_code == 502 and r.json()["error"] == "transcription_failed"


def test_per_user_rate_limit(speech_client, monkeypatch):
    client, speech = speech_client
    monkeypatch.setattr(speech.settings, "speech_rate_limit_per_minute", 2)
    _whisper(monkeypatch, speech, {"text": "ok", "duration": 1.0})
    codes = [client.post("/api/speech/transcribe", files={"audio": ("a.webm", WEBM, "audio/webm")}).status_code
             for _ in range(3)]
    assert codes == [200, 200, 429]


def test_dictation_unavailable_without_credentials(speech_client, monkeypatch):
    client, speech = speech_client
    monkeypatch.setattr(speech.settings, "groq_api_key", "")
    assert speech.dictation_capability()["available"] is False
    r = client.post("/api/speech/transcribe", files={"audio": ("a.webm", WEBM, "audio/webm")})
    assert r.status_code == 503
