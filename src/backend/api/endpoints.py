"""
FastAPI Application Entry Point
FinSyntra AI - Enterprise RAG System
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

# Import routers
from src.backend.api.chat import router as chat_router
from src.backend.api.chat_stream import router as chat_stream_router
from src.backend.api.speech import router as speech_router
from src.backend.api.admin import router as admin_router
from src.backend.api.document_upload import router as document_upload_router
from src.backend.api.auth import router as auth_router
from src.backend.api.conversations import router as conversations_router
from src.backend.api.knowledge import router as knowledge_router
from src.backend.api.auth_deps import get_current_admin_user
from src.backend.middleware.security import setup_security_middleware
from src.config.settings import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler.

    Required-dependency startup failures (DB, RAG/vector store) are logged
    distinctly (sanitized: exception type only, no raw message that could
    carry a DSN or path) and then RE-RAISED. FastAPI/uvicorn treat a startup
    exception as a failed lifespan: the ASGI server never finishes starting
    and never accepts a request, so there is no window where the process is
    "up" but unusable — no reliance on Nginx or any external gate honoring
    /health/ready.

    Once startup has actually succeeded, /health/ready remains available to
    detect RUNTIME degradation (e.g. the database going away later); that is
    a live per-request check, not a re-run of this startup gate.
    """
    logger.info("🚀 FinSyntra AI starting up...")
    app.state.rag = None
    app.state.vector_store = None
    app.state.db_ready = False
    app.state.rag_ready = False

    try:
        from src.backend.database.database import create_tables
        create_tables()
        app.state.db_ready = True
    except Exception as e:
        logger.error(
            "STARTUP_DB_FAILURE: database initialization failed (%s); refusing to start",
            type(e).__name__, exc_info=True,
        )
        raise RuntimeError(
            "FATAL: database initialization failed at startup. Refusing to serve traffic."
        ) from e

    try:
        from src.backend.services.rag_service import RAGService
        app.state.rag = RAGService()
        app.state.vector_store = getattr(app.state.rag, "vector_store", None)
        if app.state.vector_store is None:
            raise RuntimeError("RAGService started without a usable vector_store")
        from src.backend.services.llm_provider import OllamaProvider
        provider = getattr(app.state.rag, "llm_provider", None)
        if isinstance(provider, OllamaProvider):
            await asyncio.to_thread(provider.warm_up)
        app.state.rag_ready = True
    except Exception as e:
        logger.error(
            "STARTUP_RAG_FAILURE: RAG service initialization failed (%s); refusing to start",
            type(e).__name__, exc_info=True,
        )
        app.state.rag = None
        app.state.vector_store = None
        raise RuntimeError(
            "FATAL: RAG service initialization failed at startup. Refusing to serve traffic."
        ) from e

    yield
    logger.info("🛑 FinSyntra AI shutting down...")
    # Release what this startup installed: after shutdown the app must not
    # report ready or keep handing requests a stale service instance.
    app.state.rag_ready = False
    app.state.rag = None
    app.state.vector_store = None


# Create FastAPI application
app = FastAPI(
    title="FinSyntra AI",
    description="Enterprise RAG System with Role-Based Access Control",
    version="2.0.0",
    lifespan=lifespan
)

setup_security_middleware(app)


@app.get("/health")
async def health_check():
    """Fast public liveness response: no external calls or internal topology."""
    return {"status": "ok", "service": "finsyntra-api"}


@app.get("/health/ready")
async def readiness_check():
    """Unauthenticated deployment readiness probe.

    Verifies only what's needed to serve real traffic: DB connectivity and
    RAG/vector-store initialization. No LLM calls, no embedding operations,
    and no secrets/URLs/stack traces in the response — safe for an external
    hosting/orchestration health checker to call directly.
    """
    db_ready = False
    try:
        from src.backend.database.database import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            db_ready = True
        finally:
            db.close()
    except Exception:
        db_ready = False

    rag_ready = bool(getattr(app.state, "rag_ready", False)) and \
        getattr(app.state, "vector_store", None) is not None

    ready = db_ready and rag_ready
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "checks": {
                "database": "ok" if db_ready else "unavailable",
                "rag": "ok" if rag_ready else "unavailable",
            },
        },
    )


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Welcome to FinSyntra AI API",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health/deep")
async def deep_health_check(current_user: Dict = Depends(get_current_admin_user)):
    """
    Deep health check — verifies all critical subsystems.
    Returns 200 if all are reachable, 503 if any are degraded.
    Used by Docker HEALTHCHECK.
    """
    checks = {}
    all_ok = True

    # 1. Active LLM provider (never expose URLs, keys, or raw exceptions)
    try:
        rag = getattr(app.state, "rag", None)
        provider = getattr(rag, "llm_provider", None)
        if provider is None:
            from src.backend.services.llm_provider import create_llm_provider
            provider = create_llm_provider()
        provider_ok = provider.healthcheck()
        checks["llm_provider"] = "ok" if provider_ok else "unavailable"
        if not provider_ok:
            all_ok = False
    except Exception:
        checks["llm_provider"] = "unavailable"
        all_ok = False

    # 2. ChromaDB / Vector store
    try:
        vs = getattr(app.state, "vector_store", None)
        if vs is None:
            from src.backend.services.vector_store import VectorStore
            vs = VectorStore()
        vs.get_collection_stats(tenant_id=current_user["tenant_id"])
        checks["vector_store"] = "ok"
    except Exception:
        checks["vector_store"] = "unavailable"
        all_ok = False

    # 3. Database connectivity
    try:
        from src.backend.database.database import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
        all_ok = False

    status_code = 200 if all_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if all_ok else "degraded",
            "checks": checks,
            "timestamp": datetime.now().isoformat(),
        }
    )


# Include routers
app.include_router(chat_router, prefix="/api", tags=["Chat"])
app.include_router(chat_stream_router, prefix="/api", tags=["Chat Stream"])
app.include_router(speech_router, prefix="/api", tags=["Speech"])
app.include_router(admin_router, prefix="/api", tags=["Admin"])
app.include_router(document_upload_router, prefix="/api", tags=["Documents"])
app.include_router(conversations_router, prefix="/api", tags=["Conversations"])
app.include_router(knowledge_router, prefix="/api", tags=["Knowledge"])
app.include_router(auth_router, tags=["Auth"])


# Re-export get_current_user for backward compatibility
from src.backend.api.auth_deps import get_current_user


# Error handlers
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402


@app.exception_handler(SQLAlchemyError)
async def database_exception_handler(request: Request, exc: SQLAlchemyError):
    """Database failures: actionable server log, opaque client response.

    SQLAlchemy/SQLite messages carry schema details and filesystem paths
    (e.g. "no such column: chat_sessions.tenant_id", "sqlite:///<path>/finsolve.db").
    Those belong in the log, never in an API payload.
    """
    logger.error(
        "DB_ERROR path=%s method=%s error_type=%s error=%s",
        request.url.path, request.method, type(exc).__name__, exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=503,
        content={"detail": {"code": "DATABASE_UNAVAILABLE",
                            "message": "A database error occurred. Please try again."}},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    logger.error(
        "UNHANDLED_ERROR path=%s method=%s error_type=%s error=%s",
        request.url.path, request.method, type(exc).__name__, exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred"}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8000, reload=True)
