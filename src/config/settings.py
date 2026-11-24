"""
Application configuration settings for Ollama (Local LLM)
"""
import os
import sys
from typing import List
from pydantic_settings import BaseSettings

# Fix Windows console encoding issues
if sys.platform == 'win32':
    try:
        import io
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    except Exception:
        pass  # Silently fail if we can't fix encoding


# Well-known weak keys that must never be used in production
_WEAK_KEYS = frozenset({
    "finsolve_super_secret_key_12345",
    "finsolve_super_secret_key_12345_change_later",
    "your-secret-key",
    "secret",
    "changeme",
})


# SHA-256 fingerprints of signing-key values that were committed to this
# repository's Git history (found by a full-history scan; values are never
# stored here). They are compromised: anyone with a clone can mint tokens.
_COMPROMISED_KEY_SHA256 = frozenset({
    "1d859a2ef1bac22f112b89515e492c07bd56b8d7f31afd8ef5b1fa4d6e64d39b",
    "3c2dbbc14e591149e9e24bc61d587a572510050395b68f4cd184ee4dfbb2b879",
    "4625cfb92782acbfee6b97de0be22175a553a4f06e59265ed68e91137ba72e7c",
    "8552693516f79256b5bbab5b76fabbdf40ebcb27763062de5205219c6b4b181d",
    "8b6bec0d70e926c2d36b57d7062f193dfc45e278434e7009213229a87c30c5f3",
    "9486e95f4479c88bdc9cb7b5a6a32e0852a1215ea5034c1ad322e56a5af19561",
    "a42adcb93303c4df2fbbba985076c4ca9bfa59357a8d15c7d0b2476288674b18",
    "a4d98a29aa894d150af16a8a7d8da50ba7fe567e500a95038728276fd644bf43",
    "c5756336f362d76cd0ed05a1275a30e453b1e6ea5cc1cfa81e9b850faa0241d9",
    "ee98de762e47f02f2e4b0a833503cf3fe6bf2cdbf89957aeda500059fa4e87ba",
})


def is_compromised_secret_key(value: str) -> bool:
    """True if the key's SHA-256 is a known-compromised fingerprint.

    FINSOLVE_COMPROMISED_KEY_SHA256 (comma-separated hex digests) extends the
    built-in set, so a key that leaks later can be blocked without a release.
    """
    import hashlib
    extra = {f.strip().lower() for f in os.environ.get("FINSOLVE_COMPROMISED_KEY_SHA256", "").split(",") if f.strip()}
    digest = hashlib.sha256((value or "").encode("utf-8")).hexdigest()
    return digest in _COMPROMISED_KEY_SHA256 or digest in extra


class Settings(BaseSettings):
    # LLM inference. Retrieval and local embeddings remain provider-independent.
    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"  # Good balance of speed and quality
    groq_api_key: str = ""
    groq_model: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_timeout_seconds: int = 20
    # Reasoning models (openai/gpt-oss-*) spend completion tokens on hidden
    # reasoning before any answer text; 320 tokens was observed to be consumed
    # entirely by reasoning (finish_reason=length, empty content).
    groq_max_completion_tokens: int = 1024
    # "auto": send reasoning_effort=low for gpt-oss models only (Groq rejects
    # the parameter for non-reasoning models). Explicit low/medium/high is sent
    # as-is; "none" never sends it.
    groq_reasoning_effort: str = "auto"
    # User-selectable chat model alias used when the client sends none
    # (see src/backend/services/model_catalog.py for the allowlist).
    chat_default_model: str = "prism"

    # Voice dictation (speech -> editable composer text). Audio is forwarded
    # to the Groq transcription API and never written to disk or the DB.
    speech_enabled: bool = True
    speech_model: str = "whisper-large-v3"
    speech_max_bytes: int = 4_000_000       # ~60 s of browser Opus is < 1 MB
    speech_max_seconds: int = 60            # enforced client-side and via provider duration
    speech_rate_limit_per_minute: int = 8
    speech_timeout_seconds: int = 30
    local_embeddings_model: str = "all-MiniLM-L6-v2"  # Fast local embeddings

    # ── Embeddings provider ─────────────────────────────────────────────────
    # "local": sentence-transformers/torch, in-process (default, unchanged).
    # "cloudflare": Cloudflare Workers AI (BGE-M3, 1024-dim), remote HTTP calls.
    # No local fallback on a Cloudflare failure — see vector_store.py.
    embeddings_provider: str = "local"
    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""
    cloudflare_embeddings_model: str = "@cf/baai/bge-m3"
    cloudflare_embeddings_timeout_seconds: int = 30
    cloudflare_embeddings_batch_size: int = 20
    # Separate collection: BGE-M3 (1024-dim) vectors must never share a Chroma
    # collection with MiniLM (384-dim) vectors.
    cloudflare_vector_collection_name: str = "company_docs_cloudflare_bgem3"

    # Security Settings
    # NOTE: No default — the value MUST come from .env or environment variable.
    secret_key: str = "MUST_BE_SET_VIA_ENV"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # Environment mode (dev | staging | production)
    env: str = "dev"
    
    # Application Info
    app_name: str = "FinSyntra RAG Chatbot (Local)"
    app_version: str = "1.0.0"
    debug: bool = True

    # Database / cache
    database_url: str | None = None
    redis_url: str | None = None
    enable_metrics: bool = False
    
    # Server Configuration
    host: str = "localhost"
    port: int = 8000
    frontend_port: int = 8501
    
    # Vector Database
    vector_db_path: str = "./src/data/embeddings/chroma_db"
    vector_collection_name: str = "company_docs"
    # Filesystem location of uploaded/source documents
    raw_documents_path: str = "./src/data/raw"
    # Tenant that owns the bundled/sample corpus in raw_documents_path.
    # Bootstrap indexing is explicit: there is no implicit "default" tenant.
    # Shared/global document visibility is deliberately NOT modelled — it would
    # need its own authorization design.
    bootstrap_tenant_id: str = "tenant_acme"
    chunk_size: int = 800  # Smaller chunks for local LLM
    chunk_overlap: int = 100
    max_tokens: int = 2048  # Conservative for local models

    # CORS Settings
    allowed_origins: List[str] = [
        "http://localhost:8501",
        "http://localhost:3000",
        "http://127.0.0.1:8501"
    ]
    
    # Performance Settings
    max_concurrent_requests: int = 1  # Conservative for local processing
    # NOTE: timeout_seconds is a generic app-level knob with no single owner —
    # it is currently unreferenced in code. It is deliberately NOT reused as the
    # Ollama or RAG timeout; those have explicit settings below.
    timeout_seconds: int = 30
    rate_limit_per_minute: int = 60
    login_rate_limit_per_minute: int = 5
    refresh_rate_limit_per_minute: int = 10
    public_demo_chat_rate_limit_per_minute: int = 10
    # Demo-login is credentialless (no brute-force surface) but recruiters
    # switch personas repeatedly during a demo; the strict /auth/login limit
    # must not apply to it. Separate bucket so it never consumes the real
    # login budget either.
    public_demo_login_rate_limit_per_minute: int = 30

    # Public portfolio demonstration. Authentication still uses normal JWT,
    # cookies, CSRF, refresh rotation, and the authoritative User table.
    public_demo_enabled: bool = False
    demo_tenant_id: str = "tenant_demo"
    demo_documents_path: str = "./src/data/demo_corpus"

    # ── Timeout hierarchy ───────────────────────────────────────────────────
    # Must satisfy: ollama_timeout_seconds < rag_hard_timeout_seconds
    # Measured on llama3.2:3b with the cleaned corpus (Wave 3 benchmark):
    #   cold model load 0.2s | typical RAG generation 2.8-5.8s | worst case 7.3s
    # 30s gives ~4x headroom on the worst observed case; 45s bounds the whole
    # retrieval + generation operation with room for retrieval (~0.5s).
    ollama_timeout_seconds: int = 30      # HTTP timeout for a single Ollama generate
    rag_hard_timeout_seconds: int = 45    # outer bound on the whole RAG operation
    sse_heartbeat_seconds: int = 15       # ping cadence while RAG is in flight
    
    # Admin Users (for dev/test - comma-separated emails)
    admin_users: str = ""  # e.g., "admin@test.com,dev@test.com"
    
    # Auth bypass (development only)
    bypass_auth: bool = False

    # ── Enterprise RAG feature flags ────────────────────────────────────────
    # Declared here so that modules and scripts which already read them
    # (services/cache_manager.py, workers/vector_deletion_worker.py,
    # scripts/check_flags.py, scripts/validate_flags.py,
    # scripts/reconcile_vectors.py) resolve instead of raising AttributeError.
    # Defaults match README_FLAGS.md and scripts/check_flags.py: all OFF,
    # except BLOCK_BACKUP_FOLDERS which defaults ON.
    # Field names are intentionally upper-case to match existing call sites.
    STRICT_MODE: bool = False
    TENANT_SCOPING_ON: bool = False
    ENABLE_DELETION_WORKER: bool = False
    ENABLE_RECONCILIATION: bool = False
    BLOCK_BACKUP_FOLDERS: bool = True
    CANONICAL_COLLECTION_ENFORCED: bool = False
    ENABLE_CROSS_PROCESS_CACHE_SYNC: bool = False
    ENABLE_UPLOAD_LOGGING: bool = False
    REDIS_CACHE_INVALIDATION_CHANNEL: str = "finsolve:cache:invalidation"
    DELETION_WORKER_BATCH_SIZE: int = 10

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.env.lower() in ("production", "prod")

    @property
    def cors_origins(self) -> List[str]:
        """Return allowed CORS origins."""
        return self.allowed_origins

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


# Create global settings instance
settings = Settings()


# ── Path helpers ────────────────────────────────────────────────────────────
# src/config/settings.py -> up two levels is the project root.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def resolve_project_path(configured: str, default: str) -> str:
    """Resolve a configured path to an absolute one.

    Relative values resolve against the project root rather than the process
    CWD, so behaviour does not depend on where the server was started from.
    """
    value = configured or default
    if os.path.isabs(value):
        return os.path.abspath(value)
    return os.path.abspath(os.path.join(PROJECT_ROOT, value))


def get_raw_documents_path() -> str:
    """Absolute path of the uploaded/source document directory."""
    return resolve_project_path(
        getattr(settings, "raw_documents_path", None),
        os.path.join("src", "data", "raw"),
    )


def get_demo_documents_path() -> str:
    """Absolute path of the immutable synthetic public-demo corpus."""
    return resolve_project_path(
        getattr(settings, "demo_documents_path", None),
        os.path.join("src", "data", "demo_corpus"),
    )


# ── Startup validation ──────────────────────────────────────────────────────
if settings.secret_key in _WEAK_KEYS or settings.secret_key == "MUST_BE_SET_VIA_ENV":
    if settings.is_production:
        raise RuntimeError(
            "FATAL: SECRET_KEY is a well-known weak value. "
            "Set a cryptographically random key before running in production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    else:
        print("[!] WARNING: SECRET_KEY is a weak default — acceptable for local dev only.")

if is_compromised_secret_key(settings.secret_key):
    if settings.is_production:
        raise RuntimeError(
            "FATAL: SECRET_KEY is a value that was committed to the repository and is "
            "compromised. Generate and install a new one with scripts/rotate_secret_key.py."
        )
    print("[!] WARNING: SECRET_KEY was committed to the repository; never use it outside local dev.")

if settings.is_production and len(settings.secret_key) < 32:
    raise RuntimeError(
        "FATAL: SECRET_KEY must be at least 32 characters in production. "
        "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
    )

if settings.is_production and settings.debug:
    # DEBUG also controls SQLAlchemy's create_engine(echo=...), which logs
    # every bound parameter value for every query — including
    # visitor_session_id (Phase 3) and other sensitive values. A warning was
    # not enough: fail closed instead.
    raise RuntimeError(
        "FATAL: DEBUG=true is not allowed in production mode. It enables "
        "SQLAlchemy SQL echo, which can log sensitive bound values."
    )

if settings.is_production and settings.bypass_auth:
    raise RuntimeError("FATAL: BYPASS_AUTH=true is not allowed in production mode.")

if settings.is_production:
    from urllib.parse import urlparse
    if not settings.allowed_origins:
        raise RuntimeError("FATAL: ALLOWED_ORIGINS must contain a production HTTPS origin.")
    for configured_origin in settings.allowed_origins:
        parsed_origin = urlparse(configured_origin)
        if configured_origin == "*" or parsed_origin.scheme != "https" or not parsed_origin.netloc:
            raise RuntimeError(
                "FATAL: production ALLOWED_ORIGINS entries must be explicit HTTPS origins."
            )

embeddings_provider_name = settings.embeddings_provider.strip().lower()
if embeddings_provider_name not in {"local", "cloudflare"}:
    raise RuntimeError("FATAL: EMBEDDINGS_PROVIDER must be either 'local' or 'cloudflare'.")
if embeddings_provider_name == "cloudflare":
    # Checked against the environment directly (not just settings) because
    # CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN are meant to be injected as
    # process env vars (never committed to .env), same pattern as GROQ_API_KEY.
    if not (os.environ.get("CLOUDFLARE_ACCOUNT_ID") or settings.cloudflare_account_id).strip():
        raise RuntimeError("FATAL: CLOUDFLARE_ACCOUNT_ID is required when EMBEDDINGS_PROVIDER=cloudflare.")
    if not (os.environ.get("CLOUDFLARE_API_TOKEN") or settings.cloudflare_api_token).strip():
        raise RuntimeError("FATAL: CLOUDFLARE_API_TOKEN is required when EMBEDDINGS_PROVIDER=cloudflare.")

provider_name = settings.llm_provider.strip().lower()
if provider_name not in {"ollama", "groq"}:
    raise RuntimeError("FATAL: LLM_PROVIDER must be either 'ollama' or 'groq'.")
if provider_name == "groq":
    if not settings.groq_api_key.strip():
        raise RuntimeError("FATAL: GROQ_API_KEY is required when LLM_PROVIDER=groq.")
    if not settings.groq_model.strip():
        raise RuntimeError("FATAL: GROQ_MODEL is required when LLM_PROVIDER=groq.")
    if not settings.groq_base_url.startswith("https://"):
        from urllib.parse import urlparse as _urlparse
        parsed_groq = _urlparse(settings.groq_base_url)
        loopback_dev = (
            not settings.is_production
            and parsed_groq.scheme == "http"
            and parsed_groq.hostname in {"127.0.0.1", "localhost"}
        )
        if not loopback_dev:
            raise RuntimeError("FATAL: GROQ_BASE_URL must use HTTPS.")

# Timeout hierarchy must be coherent: a request timeout longer than the outer
# bound that wraps it is meaningless.
active_provider_timeout = (
    settings.ollama_timeout_seconds if provider_name == "ollama"
    else settings.groq_timeout_seconds
)
if active_provider_timeout >= settings.rag_hard_timeout_seconds:
    raise RuntimeError(
        "FATAL: incoherent timeout hierarchy — provider timeout (%ss) must be "
        "strictly less than RAG_HARD_TIMEOUT_SECONDS (%ss); otherwise the outer RAG "
        "bound cancels the request before its own timeout can ever fire."
        % (active_provider_timeout, settings.rag_hard_timeout_seconds)
    )
if settings.sse_heartbeat_seconds >= settings.rag_hard_timeout_seconds:
    print("[!] WARNING: SSE_HEARTBEAT_SECONDS >= RAG_HARD_TIMEOUT_SECONDS; "
          "clients may see no keep-alive ping before the RAG timeout fires.")

# Create necessary directories
os.makedirs(os.path.dirname(settings.vector_db_path), exist_ok=True)
if not settings.is_production:
    # Nothing in this codebase currently writes into "logs/" (audit/log.py's
    # AuditLogger is constructed with log_file=None and ENABLE_AUDIT_LOGGING
    # defaults to False, so its FileHandler is never created), but local dev
    # tooling/expectations may still assume the directory exists. Production
    # logs exclusively through journald (StandardOutput=journal in
    # finsolve.service) and runs under systemd's ProtectSystem=strict, which
    # makes the application directory read-only outside
    # /var/lib/finsolve — so this must not run there.
    os.makedirs("logs", exist_ok=True)

print(f"[+] FinSyntra settings loaded successfully!")
print(f"[*] Environment: {settings.env} (production={settings.is_production})")
print(f"[*] LLM provider: {provider_name}")
print(f"[*] LLM model: {settings.ollama_model if provider_name == 'ollama' else settings.groq_model}")
if embeddings_provider_name == "cloudflare":
    print(f"[*] Embeddings provider: cloudflare ({settings.cloudflare_embeddings_model})")
else:
    print(f"[*] Using Local Embeddings: {settings.local_embeddings_model}")
print(f"[*] Vector DB path: {settings.vector_db_path}")
if provider_name == "ollama":
    print(f"[*] Ollama URL: {settings.ollama_base_url}")
