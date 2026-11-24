"""Wave 3: a generation failure must never look like a successful answer.

Before this wave an Ollama timeout produced:

    {"success": true, "response": "Response timeout. Please try again."}

i.e. a failure wearing a success badge, with a canned apology in the answer
field. These tests pin honest status reporting.

All Ollama interaction is mocked — nothing here touches the real dev server.
"""
import json
from unittest.mock import patch

import pytest
import requests

from src.backend.services.rag_service import LLMGenerationError, RAGService
from src.config.roles import Role


def bare_service(cuda=False, model="llama3.2:3b", url="http://localhost:11434"):
    """A RAGService shell without the heavy __init__ (no GPU, no Chroma, no Ollama)."""
    svc = object.__new__(RAGService)
    svc.cuda_available = cuda
    svc.model_name = model
    svc.ollama_url = url
    return svc


class FakeResponse:
    def __init__(self, status_code=200, payload=None, raise_json=False):
        self.status_code = status_code
        self._payload = payload
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


# ---------------------------------------------------------------------------
# Ollama call outcomes
# ---------------------------------------------------------------------------

class TestOllamaCallOutcomes:
    def test_success_returns_text(self):
        svc = bare_service()
        with patch("requests.post", return_value=FakeResponse(200, {"response": "  Revenue was $12.5M.  "})):
            assert svc._call_ollama_gpu_optimized("p") == "Revenue was $12.5M."

    def test_timeout_raises_with_reason_timeout(self):
        svc = bare_service()
        with patch("requests.post", side_effect=requests.exceptions.Timeout("timed out")):
            with pytest.raises(LLMGenerationError) as e:
                svc._call_ollama_gpu_optimized("p")
        assert e.value.reason == "timeout"

    def test_connection_refused_raises_reason_unavailable(self):
        svc = bare_service()
        with patch("requests.post", side_effect=requests.exceptions.ConnectionError("refused")):
            with pytest.raises(LLMGenerationError) as e:
                svc._call_ollama_gpu_optimized("p")
        assert e.value.reason == "unavailable"

    def test_http_error_status_raises_reason_error(self):
        svc = bare_service()
        with patch("requests.post", return_value=FakeResponse(500, None)):
            with pytest.raises(LLMGenerationError) as e:
                svc._call_ollama_gpu_optimized("p")
        assert e.value.reason == "error"

    def test_malformed_json_raises_reason_malformed(self):
        svc = bare_service()
        with patch("requests.post", return_value=FakeResponse(200, None, raise_json=True)):
            with pytest.raises(LLMGenerationError) as e:
                svc._call_ollama_gpu_optimized("p")
        assert e.value.reason == "malformed"

    def test_empty_response_raises_reason_malformed(self):
        svc = bare_service()
        with patch("requests.post", return_value=FakeResponse(200, {"response": "   "})):
            with pytest.raises(LLMGenerationError) as e:
                svc._call_ollama_gpu_optimized("p")
        assert e.value.reason == "malformed"

    def test_uses_configured_timeout_not_a_hardcoded_15(self):
        from src.config.settings import settings
        svc = bare_service()
        captured = {}

        def fake_post(url, **kw):
            captured.update(kw)
            return FakeResponse(200, {"response": "ok"})

        with patch("requests.post", side_effect=fake_post):
            svc._call_ollama_gpu_optimized("p")
        assert captured["timeout"] == settings.ollama_timeout_seconds
        assert captured["timeout"] != 15 or settings.ollama_timeout_seconds == 15


class TestNoRawExceptionLeakage:
    @pytest.mark.parametrize("exc,secret", [
        (requests.exceptions.ConnectionError(
            "HTTPConnectionPool(host='localhost', port=11434): /home/svc/secret.key"), "secret.key"),
        (requests.exceptions.Timeout("timed out at /internal/path/x"), "/internal/path"),
    ])
    def test_user_message_hides_internals(self, exc, secret):
        svc = bare_service()
        with patch("requests.post", side_effect=exc):
            with pytest.raises(LLMGenerationError) as e:
                svc._call_ollama_gpu_optimized("p")
        assert secret not in e.value.user_message
        assert "HTTPConnectionPool" not in e.value.user_message


# ---------------------------------------------------------------------------
# Result-envelope truthfulness
# ---------------------------------------------------------------------------

class TestGenerationFailureEnvelope:
    @pytest.mark.parametrize("reason", ["timeout", "unavailable", "malformed", "error"])
    def test_failure_is_not_success(self, reason):
        svc = bare_service()
        resp = svc._create_generation_failure_response(
            reason=reason, user_message="The language model did not respond.",
            user_role=Role.FINANCE, documents_found=4, total_time=31.2)
        assert resp["success"] is False, "a %s must not report success" % reason
        assert resp["generation_status"] == reason

    def test_retrieval_success_is_preserved(self):
        """A generation failure must not hide that retrieval worked."""
        svc = bare_service()
        resp = svc._create_generation_failure_response(
            reason="timeout", user_message="msg", user_role=Role.FINANCE,
            documents_found=4, total_time=31.2)
        assert resp["retrieval_status"] == "hit"
        assert resp["documents_found"] == 4

    def test_no_citations_on_generation_failure(self):
        """Nothing was answered, so nothing may be cited."""
        svc = bare_service()
        resp = svc._create_generation_failure_response(
            reason="timeout", user_message="msg", user_role=Role.FINANCE,
            documents_found=4, total_time=31.2)
        assert resp["sources"] == []

    def test_failure_envelope_is_json_serialisable(self):
        svc = bare_service()
        resp = svc._create_generation_failure_response(
            reason="unavailable", user_message="msg", user_role=Role.HR,
            documents_found=2, total_time=1.0)
        json.dumps(resp)

    def test_retrieval_miss_is_labelled_and_uncited(self):
        svc = bare_service()
        resp = svc._create_no_results_response(
            query="q", user_role=Role.FINANCE, user_name="n",
            accessible_docs=["financial_summary.md", "employee_handbook.md"])
        assert resp["retrieval_status"] == "miss"
        assert resp["generation_status"] == "skipped"
        assert resp["documents_found"] == 0
        assert resp["sources"] == []


class TestStatusesAreDistinguishable:
    def test_the_four_states_differ(self):
        """success / miss / timeout / unavailable must be tellable apart."""
        svc = bare_service()
        miss = svc._create_no_results_response("q", Role.FINANCE, "n", ["a.md"])
        timeout = svc._create_generation_failure_response(
            "timeout", "m", Role.FINANCE, 4, 31.0)
        unavailable = svc._create_generation_failure_response(
            "unavailable", "m", Role.FINANCE, 4, 0.2)
        ok = {"success": True, "retrieval_status": "hit", "generation_status": "ok"}

        seen = {
            (r["success"], r["retrieval_status"], r["generation_status"])
            for r in (miss, timeout, unavailable, ok)
        }
        assert len(seen) == 4, "states are not distinguishable: %r" % seen


class TestTimeoutHierarchy:
    def test_ollama_timeout_is_strictly_below_rag_hard_timeout(self):
        from src.config.settings import settings
        assert settings.ollama_timeout_seconds < settings.rag_hard_timeout_seconds

    def test_heartbeat_is_below_the_hard_timeout(self):
        from src.config.settings import settings
        assert settings.sse_heartbeat_seconds < settings.rag_hard_timeout_seconds

    def test_configured_model_is_the_benchmarked_one(self):
        from src.config.settings import settings
        assert settings.ollama_model == "llama3.2:3b"
