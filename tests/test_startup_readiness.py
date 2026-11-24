"""Startup fail-closed behaviour and the /health/ready deployment probe.

Covers:
  - lifespan() RE-RAISES (and logs a sanitized, type-only failure) when
    create_tables() or RAGService() raise, instead of swallowing the error
    and continuing to `yield`. A required-dependency startup failure must
    prevent the ASGI app from ever finishing startup — there must be no
    window where the process is "up" but unusable, since nothing downstream
    (Nginx, an orchestrator) is proven to gate traffic on /health/ready alone.
  - GET /health/ready remains available AFTER a successful startup to detect
    runtime (not startup) degradation: it returns 200 only when both
    dependencies are ready, 503 otherwise, requires no authentication, and
    never calls the LLM provider or runs an embedding operation.

ASGITransport does not run FastAPI lifespan events, so the readiness tests
set `app.state` directly before hitting the route — the same pattern already
used by tests/test_api_endpoints.py's `isolated_schema` fixture. The lifespan
tests invoke `lifespan()` directly against a throwaway FastAPI app.
"""
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI


@pytest.fixture(autouse=True)
def _restore_shared_app_state():
    """These tests write readiness fields on the shared `app` singleton (and
    one runs the real lifespan against it with a mocked RAGService). Restore
    them so a MagicMock RAG never leaks into later tests, e.g. the SSE
    contract, which serves requests from app.state.rag."""
    from src.backend.api.endpoints import app

    fields = ("rag", "rag_ready", "vector_store", "db_ready")
    missing = object()
    saved = {name: getattr(app.state, name, missing) for name in fields}
    yield
    for name, value in saved.items():
        if value is missing:
            if hasattr(app.state, name):
                delattr(app.state, name)
        else:
            setattr(app.state, name, value)


class TestLifespanFailClosed:
    @pytest.mark.asyncio
    async def test_db_failure_prevents_startup_before_yield(self):
        from src.backend.api.endpoints import lifespan

        app = FastAPI()
        entered_body = False
        with patch("src.backend.database.database.create_tables",
                   side_effect=RuntimeError("boom: db unreachable")):
            with pytest.raises(Exception):
                async with lifespan(app):
                    entered_body = True  # must never execute

        assert entered_body is False, "lifespan reached yield despite a DB startup failure"
        assert app.state.db_ready is False

    @pytest.mark.asyncio
    async def test_db_failure_error_does_not_leak_the_raw_exception_string(self):
        """The re-raised error must be a sanitized RuntimeError, not a bare
        re-raise of whatever the DB driver said (which can carry a DSN)."""
        from src.backend.api.endpoints import lifespan

        app = FastAPI()
        with patch("src.backend.database.database.create_tables",
                   side_effect=RuntimeError("connect failed: postgresql://u:p@host/db")):
            with pytest.raises(RuntimeError) as exc_info:
                async with lifespan(app):
                    pass

        assert "u:p@host" not in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_rag_failure_prevents_startup_before_yield(self):
        from src.backend.api.endpoints import lifespan

        app = FastAPI()
        entered_body = False
        with patch("src.backend.database.database.create_tables", return_value=None), \
             patch("src.backend.services.rag_service.RAGService",
                   side_effect=RuntimeError("boom: embedding model failed to load")):
            with pytest.raises(Exception):
                async with lifespan(app):
                    entered_body = True  # must never execute

        assert entered_body is False, "lifespan reached yield despite a RAG startup failure"
        assert app.state.db_ready is True, "DB had already succeeded before RAG failed"
        assert app.state.rag_ready is False
        assert app.state.rag is None
        assert app.state.vector_store is None

    @pytest.mark.asyncio
    async def test_rag_failure_when_vector_store_is_none_also_prevents_startup(self):
        """RAGService() can return successfully with no vector_store attached
        — that must be treated as a startup failure too, not silent success."""
        from src.backend.api.endpoints import lifespan

        app = FastAPI()
        with patch("src.backend.database.database.create_tables", return_value=None), \
             patch("src.backend.services.rag_service.RAGService") as MockRAG:
            MockRAG.return_value = MagicMock(vector_store=None)
            with pytest.raises(Exception):
                async with lifespan(app):
                    pytest.fail("must not reach yield when vector_store is None")

        assert app.state.rag_ready is False
        assert app.state.vector_store is None

    @pytest.mark.asyncio
    async def test_successful_startup_reaches_yield_and_marks_both_ready(self):
        from src.backend.api.endpoints import lifespan

        app = FastAPI()
        with patch("src.backend.database.database.create_tables", return_value=None), \
             patch("src.backend.services.rag_service.RAGService") as MockRAG:
            MockRAG.return_value = MagicMock(vector_store=MagicMock())
            entered_body = False
            async with lifespan(app):
                entered_body = True
                assert app.state.db_ready is True
                assert app.state.rag_ready is True
            assert entered_body is True

    @pytest.mark.asyncio
    async def test_successful_startup_then_health_ready_reports_200(self):
        """End-to-end: run the real lifespan (real create_tables against the
        isolated test DB, RAG mocked), then hit /health/ready through the
        actual ASGI app and confirm it reports ready."""
        from src.backend.api.endpoints import app, lifespan
        from httpx import AsyncClient, ASGITransport

        with patch("src.backend.services.rag_service.RAGService") as MockRAG:
            MockRAG.return_value = MagicMock(vector_store=MagicMock())
            async with lifespan(app):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.get("/health/ready")

        assert response.status_code == 200
        assert response.json()["status"] == "ready"


class TestReadinessEndpoint:
    @pytest.fixture(autouse=True)
    def _schema(self):
        """ASGITransport skips lifespan; create the isolated test schema
        directly so the DB half of the readiness check has something to hit."""
        from src.backend.database.database import create_tables
        create_tables()

    async def _get(self, path="/health/ready"):
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)

    @pytest.mark.asyncio
    async def test_ready_when_db_ok_and_rag_ready_flag_set(self):
        from src.backend.api.endpoints import app

        app.state.rag_ready = True
        app.state.vector_store = MagicMock()
        response = await self._get()
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["checks"]["database"] == "ok"
        assert body["checks"]["rag"] == "ok"

    @pytest.mark.asyncio
    async def test_not_ready_when_rag_never_initialized(self):
        from src.backend.api.endpoints import app

        app.state.rag_ready = False
        app.state.vector_store = None
        response = await self._get()
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["rag"] == "unavailable"
        assert body["checks"]["database"] == "ok"

    @pytest.mark.asyncio
    async def test_not_ready_when_vector_store_missing_despite_flag(self):
        """rag_ready=True but vector_store somehow None must still fail closed."""
        from src.backend.api.endpoints import app

        app.state.rag_ready = True
        app.state.vector_store = None
        response = await self._get()
        assert response.status_code == 503
        assert response.json()["checks"]["rag"] == "unavailable"

    @pytest.mark.asyncio
    async def test_not_ready_when_database_check_fails(self):
        from src.backend.api.endpoints import app

        app.state.rag_ready = True
        app.state.vector_store = MagicMock()

        with patch("src.backend.database.database.SessionLocal",
                   side_effect=RuntimeError("db down")):
            response = await self._get()

        assert response.status_code == 503
        body = response.json()
        assert body["checks"]["database"] == "unavailable"

    @pytest.mark.asyncio
    async def test_readiness_requires_no_authentication(self):
        """No Authorization header, no cookies — must not 401/403."""
        from src.backend.api.endpoints import app

        app.state.rag_ready = True
        app.state.vector_store = MagicMock()
        response = await self._get()
        assert response.status_code in (200, 503)

    @pytest.mark.asyncio
    async def test_readiness_never_touches_llm_provider(self):
        """Unlike /health/deep, /health/ready must not construct or call an
        LLM provider — no Groq/Ollama request per probe."""
        from src.backend.api.endpoints import app

        app.state.rag_ready = True
        app.state.vector_store = MagicMock()

        with patch("src.backend.services.llm_provider.create_llm_provider") as mock_create:
            await self._get()
            mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_readiness_response_has_no_secrets_or_internal_paths(self):
        from src.backend.api.endpoints import app

        app.state.rag_ready = False
        app.state.vector_store = None
        response = await self._get()
        text = response.text.lower()
        for leak in ("secret", "database_url", "postgresql://", "sqlite:///",
                     "traceback", "site-packages"):
            assert leak not in text
