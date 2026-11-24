"""Wave 7 provider, public-demo, and production validation regressions."""
from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import patch

import pytest
import requests
from httpx import ASGITransport, AsyncClient

from src.backend.api.endpoints import app
from src.backend.database.database import SessionLocal, User, create_tables
from src.backend.middleware.security import rate_limiter
from src.backend.services.llm_provider import (
    GroqProvider, LLMGenerationError, OllamaProvider, create_llm_provider,
)
from src.backend.services.rag_service import RAGService
from src.config.roles import Role
from src.config.settings import settings


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, json_error=False):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("raw-provider-payload /private/path")
        return self._payload


def groq() -> GroqProvider:
    return GroqProvider("super-secret-key", "https://api.groq.test/openai/v1", "model-from-env", 9)


def test_provider_selection_is_environment_driven(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    assert isinstance(create_llm_provider(), OllamaProvider)
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", "key")
    monkeypatch.setattr(settings, "groq_model", "chosen-at-runtime")
    provider = create_llm_provider()
    assert isinstance(provider, GroqProvider)
    assert provider.model == "chosen-at-runtime"


def test_ollama_preload_is_bounded_and_uses_generation_model_options():
    provider = OllamaProvider("http://127.0.0.1:11434", "local-model", 30)
    with patch("requests.post", side_effect=[
        FakeResponse(200), FakeResponse(200, {"response": "answer"})
    ]) as post:
        provider.warm_up()
        assert provider.generate("question") == "answer"
    preload, generation = [call.kwargs for call in post.call_args_list]
    assert preload["timeout"] == (2, 15)
    assert "prompt" not in preload["json"]
    assert preload["json"]["keep_alive"] == generation["json"]["keep_alive"] == "10m"
    assert preload["json"]["options"].items() <= generation["json"]["options"].items()
    assert generation["timeout"] == 30


def test_ollama_preload_failure_is_nonfatal_and_generation_errors_are_safe(caplog):
    provider = OllamaProvider("http://127.0.0.1:11434", "local-model", 30)
    with patch("requests.post", side_effect=requests.exceptions.Timeout("raw private payload")) as post:
        provider.warm_up()
        assert post.call_count == 1
        with pytest.raises(LLMGenerationError) as caught:
            provider.generate("question")
        assert post.call_count == 2
    assert caught.value.reason == "timeout"
    assert "raw private payload" not in caplog.text


def test_groq_success_uses_openai_compatible_contract():
    captured = {}

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return FakeResponse(200, {"choices": [{"message": {"content": " grounded answer "}}]})

    with patch("requests.post", side_effect=fake_post):
        assert groq().generate("authorized context") == "grounded answer"
    assert captured["url"].endswith("/chat/completions")
    assert captured["json"]["model"] == "model-from-env"
    assert captured["json"]["messages"] == [{"role": "user", "content": "authorized context"}]
    assert captured["timeout"] == 9
    assert captured["headers"]["Authorization"] == "Bearer super-secret-key"


@pytest.mark.parametrize("failure,reason", [
    (requests.exceptions.Timeout("secret /private/path"), "timeout"),
    (requests.exceptions.ConnectionError("secret https://internal"), "unavailable"),
])
def test_groq_transport_failures_are_safe(failure, reason):
    with patch("requests.post", side_effect=failure):
        with pytest.raises(LLMGenerationError) as caught:
            groq().generate("p")
    assert caught.value.reason == reason
    assert "secret" not in caught.value.user_message
    assert "/private" not in caught.value.user_message


def test_groq_rate_limit_is_explicit_and_not_retried():
    with patch("requests.post", return_value=FakeResponse(429, {}, {"Retry-After": "7"})) as post:
        with pytest.raises(LLMGenerationError) as caught:
            groq().generate("p")
    assert caught.value.reason == "rate_limited"
    assert caught.value.retry_after_seconds == 7
    assert post.call_count == 1


@pytest.mark.parametrize("response,reason", [
    (FakeResponse(401, {"error": "bad key super-secret-key"}), "unavailable"),
    (FakeResponse(503, {"error": "upstream internal"}), "unavailable"),
    (FakeResponse(200, json_error=True), "malformed"),
    (FakeResponse(200, {"choices": []}), "malformed"),
])
def test_groq_http_and_malformed_failures_are_normalized(response, reason):
    with patch("requests.post", return_value=response):
        with pytest.raises(LLMGenerationError) as caught:
            groq().generate("p")
    assert caught.value.reason == reason
    assert "super-secret-key" not in caught.value.user_message
    assert "internal" not in caught.value.user_message


def test_rate_limited_generation_envelope_is_truthful():
    svc = object.__new__(RAGService)
    svc.cuda_available = False
    result = svc._create_generation_failure_response(
        "rate_limited", "The language model is temporarily busy.",
        Role.EMPLOYEE, 2, 0.2,
    )
    assert result["success"] is False
    assert result["retrieval_status"] == "hit"
    assert result["generation_status"] == "rate_limited"
    assert result["documents_found"] == 2
    assert result["sources"] == []


@pytest.fixture
async def client(monkeypatch):
    create_tables()
    rate_limiter.reset()
    monkeypatch.setattr(settings, "public_demo_enabled", True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        yield value
    rate_limiter.reset()


@pytest.mark.asyncio
async def test_demo_login_is_allowlisted_normal_session(client):
    response = await client.post("/auth/demo-login", json={"role": "admin"})
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["tenant_id"] == "tenant_demo"
    assert body["user"]["role"] == "admin"
    assert body["user"]["is_public_demo"] is True
    assert client.cookies.get("session_token")
    assert client.cookies.get("refresh_token")
    assert client.cookies.get("csrf_token")
    me = await client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "portfolio.admin@finsolve.demo"


@pytest.mark.asyncio
async def test_demo_login_rejects_arbitrary_identity_and_disabled_mode(client, monkeypatch):
    assert (await client.post("/auth/demo-login", json={"role": "superadmin"})).status_code == 422
    monkeypatch.setattr(settings, "public_demo_enabled", False)
    assert (await client.post("/auth/demo-login", json={"role": "employee"})).status_code == 404


@pytest.mark.asyncio
async def test_public_demo_admin_is_read_only_backend_enforced(client):
    assert (await client.post("/auth/demo-login", json={"role": "admin"})).status_code == 200
    csrf = client.cookies.get("csrf_token")
    headers = {"X-CSRF-Token": csrf}
    users = await client.get("/api/admin/users")
    assert users.status_code == 200
    assert {u["email"] for u in users.json()} == {
        "portfolio.admin@finsolve.demo", "portfolio.employee@finsolve.demo",
        "portfolio.finance@finsolve.demo", "portfolio.hr@finsolve.demo",
        "portfolio.engineering@finsolve.demo", "portfolio.ceo@finsolve.demo",
    }
    documents = await client.get("/api/admin/documents")
    assert documents.status_code == 200
    assert documents.json()
    protected_doc_id = documents.json()[0]["id"]
    blocked = [
        await client.post("/api/admin/users", headers=headers, json={
            "email": "new@finsolve.demo", "name": "New", "role": "employee",
            "department": "General", "password": "not-a-real-secret",
        }),
        await client.patch(
            "/api/admin/users/portfolio.employee@finsolve.demo/toggle-status",
            headers=headers, json={"is_active": False},
        ),
        await client.delete("/api/admin/users/portfolio.employee@finsolve.demo", headers=headers),
        await client.delete("/api/documents/clear", headers=headers),
        await client.delete(f"/api/admin/documents/{protected_doc_id}", headers=headers),
        await client.post(
            "/api/documents/upload", headers=headers,
            data={"department": "general"},
            files={"file": ("demo.md", b"# Mutation\n" + b"safe text " * 10, "text/markdown")},
        ),
    ]
    assert {response.status_code for response in blocked} == {403}
    assert all(response.json()["detail"]["code"] == "PUBLIC_DEMO_READ_ONLY" for response in blocked)


@pytest.mark.asyncio
async def test_private_admin_mutation_capability_remains(client):
    login = await client.post("/auth/login", json={
        "email": "admin@finsolve.com", "password": "admin123",
    })
    assert login.status_code == 200
    headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}
    email = "wave7-private-capability@finsolve.test"
    created = await client.post("/api/admin/users", headers=headers, json={
        "email": email, "name": "Wave 7 Private", "role": "employee",
        "department": "General", "password": "temporary-test-password",
    })
    assert created.status_code == 200
    deleted = await client.delete(f"/api/admin/users/{email}", headers=headers)
    assert deleted.status_code == 200


def _settings_import(env_overrides, tmp_path, command="from src.config.settings import settings; print(settings.llm_provider)"):
    env = dict(os.environ)
    env.update({
        "ENV": "production",
        "DEBUG": "false",
        "LLM_PROVIDER": "groq",
        "SECRET_KEY": "x" * 64,
        "GROQ_API_KEY": "test-only-key",
        "GROQ_MODEL": "openai/gpt-oss-20b",
        "ALLOWED_ORIGINS": '["https://demo.example"]',
        "VECTOR_DB_PATH": str(tmp_path / "chroma"),
    })
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", command],
        cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        env=env, capture_output=True, text=True, timeout=30,
    )


@pytest.mark.parametrize("overrides,expected", [
    ({"GROQ_API_KEY": ""}, "GROQ_API_KEY"),
    ({"GROQ_MODEL": ""}, "GROQ_MODEL"),
    ({"SECRET_KEY": "secret"}, "SECRET_KEY"),
    ({"SECRET_KEY": "short-not-a-known-weak-value"}, "SECRET_KEY"),
    ({"ALLOWED_ORIGINS": '["http://demo.example"]'}, "ALLOWED_ORIGINS"),
    ({"ALLOWED_ORIGINS": '["*"]'}, "ALLOWED_ORIGINS"),
    ({"GROQ_BASE_URL": "http://api.groq.test/v1"}, "GROQ_BASE_URL"),
    ({"DEBUG": "true"}, "DEBUG"),
])
def test_invalid_production_configuration_fails_startup(overrides, expected, tmp_path):
    result = _settings_import(overrides, tmp_path)
    assert result.returncode != 0
    assert expected in result.stderr
    assert "test-only-key" not in result.stdout + result.stderr


def test_valid_groq_production_configuration_imports_without_secret_logging(tmp_path):
    result = _settings_import({}, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "groq" in result.stdout
    assert "test-only-key" not in result.stdout + result.stderr


def test_production_cors_preflight_only_allows_the_configured_https_origin(tmp_path):
    result = _settings_import({}, tmp_path, command="""
from fastapi.testclient import TestClient
from src.backend.api.endpoints import app
client = TestClient(app)
for origin in ("https://demo.example", "https://untrusted.example", "http://demo.example"):
    response = client.options("/api/chat/stream", headers={
        "Origin": origin, "Access-Control-Request-Method": "GET",
    })
    if origin == "https://demo.example":
        assert response.status_code == 200
        assert response.headers["Access-Control-Allow-Origin"] == origin
        assert response.headers["Access-Control-Allow-Credentials"] == "true"
    else:
        assert response.status_code == 400
        assert "Access-Control-Allow-Origin" not in response.headers
""")
    assert result.returncode == 0, result.stderr


def test_production_with_debug_false_is_allowed(tmp_path):
    """Explicit companion to the DEBUG=true failure case above: the same
    production config with DEBUG left at its template default must still
    import cleanly."""
    result = _settings_import({"DEBUG": "false"}, tmp_path)
    assert result.returncode == 0, result.stderr


def test_development_with_debug_true_is_still_allowed(tmp_path):
    """DEBUG=true must remain usable for local/dev — only ENV=production
    fails closed on it."""
    env = dict(os.environ)
    env.update({
        "ENV": "dev",
        "DEBUG": "true",
        "LLM_PROVIDER": "ollama",
        "VECTOR_DB_PATH": str(tmp_path / "chroma"),
    })
    result = subprocess.run(
        [sys.executable, "-c", "from src.config.settings import settings; print(settings.debug)"],
        cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "True" in result.stdout
