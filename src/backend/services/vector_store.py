"""
ENHANCED Vector Store with Improved GPU Detection and CPU Optimization
"""
import os
import chromadb
from chromadb.config import Settings
from typing import List, Dict, Any, Optional
import uuid
import json
import hashlib
import time
import threading
import requests
from functools import lru_cache
import gc
from src.config.settings import settings
from src.config.roles import Role, Department, ROLE_PERMISSIONS
from src.backend.utils.document_processor import DocumentChunk
import re
import logging
import numpy as np

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Create a logger for this module
logger = logging.getLogger(__name__)

# Project root: src/backend/services/vector_store.py -> up three levels
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# Chroma signals "no such collection" differently across versions: 0.4.x raises a
# plain ValueError, later versions an InvalidCollectionException / NotFoundError.
try:  # pragma: no cover - import shape varies by chromadb version
    from chromadb.errors import InvalidCollectionException as _InvalidCollectionException
except Exception:  # pragma: no cover
    _InvalidCollectionException = None


class VectorStoreUnavailableError(RuntimeError):
    """The vector store could not be opened and MUST NOT be auto-recovered.

    Raised for transient faults, schema incompatibilities and corrupted
    storage. Recovery (deleting or rebuilding a collection) is an explicit
    operator action, never an automatic side effect of start-up.
    """


def _is_missing_collection_error(exc: BaseException) -> bool:
    """True only when Chroma is telling us the collection does not exist.

    Anything else — locks, permissions, schema drift, corruption — returns
    False so the caller fails closed instead of destroying data.
    """
    if _InvalidCollectionException is not None and isinstance(exc, _InvalidCollectionException):
        return True
    if type(exc).__name__ in ("NotFoundError", "InvalidCollectionException"):
        return True
    if isinstance(exc, ValueError):
        msg = str(exc).lower()
        return "does not exist" in msg or "not found" in msg
    return False


def resolve_persist_directory(persist_directory: Optional[str] = None) -> str:
    """Resolve the Chroma persistence directory to an absolute path.

    Precedence: explicit argument -> settings.vector_db_path -> legacy default.
    Relative paths are resolved against the project root (not the process CWD)
    so that behaviour does not change with the working directory.
    """
    configured = persist_directory or getattr(settings, "vector_db_path", None)
    if not configured:
        configured = os.path.join("src", "data", "embeddings", "chroma_db")
    if os.path.isabs(configured):
        return os.path.abspath(configured)
    return os.path.abspath(os.path.join(_PROJECT_ROOT, configured))


def resolve_collection_name(collection_name: Optional[str] = None,
                             embeddings_provider: Optional[str] = None) -> str:
    """Resolve the Chroma collection name.

    Explicit argument always wins. Otherwise the default depends on the
    active embeddings provider: different providers produce vectors of
    different dimensionality and semantics (local MiniLM is 384-dim,
    Cloudflare BGE-M3 is 1024-dim), so they must never share a collection —
    querying one provider's vectors with the other's embedding would return
    meaningless distances, not an error.
    """
    if collection_name:
        return collection_name
    provider = (embeddings_provider or getattr(settings, "embeddings_provider", "local") or "local").strip().lower()
    if provider == "cloudflare":
        return getattr(settings, "cloudflare_vector_collection_name", None) or "company_docs_cloudflare_bgem3"
    return getattr(settings, "vector_collection_name", None) or "company_docs"


class CloudflareEmbeddingsError(RuntimeError):
    """A Cloudflare Workers AI embeddings call failed.

    There is deliberately no local fallback for this: silently substituting
    a different model's vectors would desynchronise a query embedding from
    its collection's embedding space (wrong dimensionality / semantics)
    without ever raising, which is worse than a visible failure.
    """


class CloudflareEmbeddingsClient:
    """Embeds text via Cloudflare Workers AI (default model: BGE-M3).

    Batches requests, retries transient failures briefly, and raises
    CloudflareEmbeddingsError (never falls back to a local model) on any
    unrecoverable failure. Also directly usable as a Chroma
    EmbeddingFunction via __call__, so a Cloudflare-backed collection is
    never wired to a SentenceTransformerEmbeddingFunction.
    """

    _RUN_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"

    def __init__(self, account_id: str, api_token: str, model: str,
                 timeout_seconds: int = 30, batch_size: int = 20, max_retries: int = 2):
        if not account_id or not api_token:
            # Never echo the token (or the exception payload) anywhere a log
            # might capture it: this message intentionally names only the
            # missing field.
            raise CloudflareEmbeddingsError(
                "Cloudflare embeddings require both an account id and an API token."
            )
        self._url = self._RUN_URL.format(account_id=account_id, model=model)
        self._headers = {"Authorization": f"Bearer {api_token}"}
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.batch_size = max(1, batch_size)
        self.max_retries = max(0, max_retries)

    def __call__(self, input):  # Chroma EmbeddingFunction protocol
        return self.embed(list(input))

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed every text, batched. Raises CloudflareEmbeddingsError on
        any failure — callers must not treat a partial result as success."""
        if not texts:
            return []
        vectors: List[List[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed_batch(texts[start:start + self.batch_size]))
        return vectors

    def _embed_batch(self, batch: List[str]) -> List[List[float]]:
        last_error: Optional[BaseException] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = requests.post(
                    self._url,
                    headers=self._headers,
                    json={"text": batch},
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 5))
                    continue
                raise CloudflareEmbeddingsError(
                    f"Cloudflare Workers AI embeddings request failed: {exc}"
                ) from exc

            if response.status_code >= 500 and attempt < self.max_retries:
                last_error = RuntimeError(f"HTTP {response.status_code}")
                time.sleep(min(2 ** attempt, 5))
                continue

            if response.status_code != 200:
                raise CloudflareEmbeddingsError(
                    f"Cloudflare Workers AI embeddings returned HTTP {response.status_code}: "
                    f"{response.text[:300]}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise CloudflareEmbeddingsError(
                    "Cloudflare Workers AI embeddings returned a non-JSON response"
                ) from exc

            if not payload.get("success", False):
                raise CloudflareEmbeddingsError(
                    f"Cloudflare Workers AI embeddings call was not successful: {payload.get('errors')}"
                )

            data = (payload.get("result") or {}).get("data")
            if not isinstance(data, list) or len(data) != len(batch):
                got = len(data) if isinstance(data, list) else type(data).__name__
                raise CloudflareEmbeddingsError(
                    "Cloudflare Workers AI embeddings returned an unexpected shape "
                    f"(expected {len(batch)} vectors, got {got})"
                )
            return data

        raise CloudflareEmbeddingsError(
            f"Cloudflare Workers AI embeddings failed after {self.max_retries + 1} attempts: {last_error}"
        )


class VectorStore:
    """Enhanced AI Memory System with Better GPU/CPU Handling"""

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        # NOTE: *args/**kwargs are accepted and ignored here so that the
        # documented __init__ parameters are actually usable. Without this,
        # VectorStore(collection_name=..., persist_directory=...) raised
        # TypeError and every caller silently fell back to the default store.
        if cls._instance is None:
            cls._instance = super(VectorStore, cls).__new__(cls)
        return cls._instance

    def __init__(self, collection_name: str = None, persist_directory: str = None):
        """
        Initialize the vector store with specified collection and persistence settings

        Args:
            collection_name: Name of the collection to use.
                Defaults to settings.vector_collection_name ("company_docs").
            persist_directory: Directory for persistence.
                Defaults to settings.vector_db_path, resolved against the
                project root.
        """
        if self._initialized:
            return

        self.embeddings_provider = (getattr(settings, "embeddings_provider", "local") or "local").strip().lower()
        if self.embeddings_provider not in ("local", "cloudflare"):
            raise ValueError(
                f"Unknown embeddings_provider {self.embeddings_provider!r}; expected 'local' or 'cloudflare'"
            )

        collection_name = resolve_collection_name(collection_name, self.embeddings_provider)
        persist_directory = resolve_persist_directory(persist_directory)

        # BLOCK_BACKUP_FOLDERS (default on): never open a backup copy as the
        # live store — Chroma writes on open, which would silently mutate the
        # backup that restore.sh relies on.
        if settings.BLOCK_BACKUP_FOLDERS and any(
            "backup" in part.lower() for part in os.path.normpath(persist_directory).split(os.sep)
        ):
            raise ValueError(
                "Backup folder detected in vector store path; refusing to open it as the live store"
            )

        self.collection_name = collection_name
        self.persist_directory = persist_directory

        # ── Build the embedding backend FIRST for Cloudflare ────────────────
        # Fail closed on a bad/missing credential or an unreachable API
        # before Chroma is ever touched, and never fall back to loading
        # MiniLM. For "local" this is a no-op here — the heavy model load
        # happens later, after the collection is open (unchanged behaviour).
        self._cloudflare_client = None
        self._cloudflare_embedding_dim = None
        if self.embeddings_provider == "cloudflare":
            self._cloudflare_client = self._build_cloudflare_client()
            try:
                probe = self._cloudflare_client.embed(["connectivity check"])
            except CloudflareEmbeddingsError as exc:
                raise VectorStoreUnavailableError(
                    f"Cloudflare Workers AI embeddings are unreachable at startup: {exc}. "
                    "No local fallback is used — fix the credentials/connectivity and retry."
                ) from exc
            self._cloudflare_embedding_dim = len(probe[0]) if probe and probe[0] else None
            self.device = "cloudflare-api"
            self.cuda_available = False
            logger.info(
                "VECTOR_STORE_CLOUDFLARE_EMBEDDINGS_READY model=%s dim=%s",
                self._cloudflare_client.model, self._cloudflare_embedding_dim,
            )

        # ── Open the Chroma client ──────────────────────────────────────────
        # NOTE: initialisation NEVER deletes data. See _is_missing_collection_error.
        try:
            self.client = chromadb.PersistentClient(path=persist_directory)
        except Exception as exc:
            logger.error(
                "VECTOR_STORE_CLIENT_OPEN_FAILED path=%s error_type=%s error=%s",
                persist_directory, type(exc).__name__, exc,
            )
            raise VectorStoreUnavailableError(
                "Could not open the Chroma persistence directory %r (%s: %s). "
                "No data was modified. Check the path, permissions, and whether "
                "another process holds the store open."
                % (persist_directory, type(exc).__name__, exc)
            ) from exc

        # ── Open or create the collection ───────────────────────────────────
        try:
            # Case B: collection exists and opens cleanly.
            self.collection = self.client.get_collection(name=collection_name)
            logger.info(
                "VECTOR_STORE_COLLECTION_OPENED name=%s path=%s",
                collection_name, persist_directory,
            )
        except Exception as exc:
            if not _is_missing_collection_error(exc):
                # Cases C / D / E: transient fault, schema incompatibility, or
                # corrupted storage. Historically this branch deleted the
                # collection, which silently destroyed the whole corpus on any
                # unexpected error. Deletion is now an explicit operator action
                # only (clear_collection / rebuild script) — never automatic.
                logger.error(
                    "VECTOR_STORE_COLLECTION_OPEN_FAILED name=%s path=%s "
                    "error_type=%s error=%s destructive_recovery=disabled",
                    collection_name, persist_directory, type(exc).__name__, exc,
                )
                raise VectorStoreUnavailableError(
                    "Chroma collection %r at %r could not be opened (%s: %s).\n"
                    "The collection was NOT deleted and no data was modified.\n"
                    "This usually means a transient lock/permission fault, a "
                    "Chroma schema incompatibility, or corrupted storage.\n"
                    "Resolve it explicitly — inspect the store, restore a "
                    "backup, or run a deliberate rebuild. Automatic deletion is "
                    "disabled by design."
                    % (collection_name, persist_directory,
                       type(exc).__name__, exc)
                ) from exc

            # Case A: the collection genuinely does not exist yet — create it.
            logger.info(
                "VECTOR_STORE_COLLECTION_MISSING name=%s path=%s — creating",
                collection_name, persist_directory,
            )
            try:
                self.collection = self.client.create_collection(
                    name=collection_name,
                    embedding_function=self._get_embedding_function()
                )
                logger.info("VECTOR_STORE_COLLECTION_CREATED name=%s", collection_name)
            except Exception as create_error:
                # Benign race: another process created it between get and create.
                try:
                    self.collection = self.client.get_collection(name=collection_name)
                    logger.info(
                        "VECTOR_STORE_COLLECTION_CREATED_CONCURRENTLY name=%s — reusing",
                        collection_name,
                    )
                except Exception:
                    logger.error(
                        "VECTOR_STORE_COLLECTION_CREATE_FAILED name=%s path=%s "
                        "error_type=%s error=%s",
                        collection_name, persist_directory,
                        type(create_error).__name__, create_error,
                    )
                    raise VectorStoreUnavailableError(
                        "Could not create Chroma collection %r at %r (%s: %s). "
                        "No data was modified."
                        % (collection_name, persist_directory,
                           type(create_error).__name__, create_error)
                    ) from create_error


        if self._initialized:
            return
            
        print("[*] Initializing Enhanced AI Memory System...")
        
        # Performance tracking
        self._embedding_cache = {}
        self._max_cache_size = 1000
        self._cache_stats = {"hits": 0, "misses": 0}
        self._performance_stats = {
            "total_embeddings": 0,
            "avg_embedding_time": 0,
            "cache_hit_rate": 0
        }
        
        # Setup embedding model with enhanced GPU/CPU detection. Cloudflare
        # already finished its own setup above (before Chroma was touched) —
        # torch and sentence_transformers must never be imported in that mode.
        if self.embeddings_provider == "local":
            self._setup_embedding_model()

        self._initialized = True
        print("[+] Enhanced AI Memory System ready")

    def _build_cloudflare_client(self) -> "CloudflareEmbeddingsClient":
        """Construct the Cloudflare Workers AI embeddings client.

        Credentials are read from the environment first (the documented,
        non-committed path for CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN),
        falling back to settings. Never logs or returns the token itself.
        """
        account_id = (os.environ.get("CLOUDFLARE_ACCOUNT_ID") or getattr(settings, "cloudflare_account_id", "") or "").strip()
        api_token = (os.environ.get("CLOUDFLARE_API_TOKEN") or getattr(settings, "cloudflare_api_token", "") or "").strip()
        if not account_id or not api_token:
            raise VectorStoreUnavailableError(
                "EMBEDDINGS_PROVIDER=cloudflare requires both CLOUDFLARE_ACCOUNT_ID and "
                "CLOUDFLARE_API_TOKEN (environment variable or settings). There is no "
                "local fallback."
            )
        model = getattr(settings, "cloudflare_embeddings_model", None) or "@cf/baai/bge-m3"
        try:
            return CloudflareEmbeddingsClient(
                account_id=account_id,
                api_token=api_token,
                model=model,
                timeout_seconds=getattr(settings, "cloudflare_embeddings_timeout_seconds", 30),
                batch_size=getattr(settings, "cloudflare_embeddings_batch_size", 20),
            )
        except CloudflareEmbeddingsError as exc:
            raise VectorStoreUnavailableError(str(exc)) from exc

    def _setup_embedding_model(self):
        """Enhanced embedding model setup with better GPU/CPU handling (local provider only)."""
        from sentence_transformers import SentenceTransformer

        print(f"[*] Loading Enhanced Embeddings Model: {settings.local_embeddings_model}")

        # Detailed device detection
        self._detect_compute_device()

        # Load model with device-specific optimizations
        try:
            self.embeddings_model = SentenceTransformer(
                settings.local_embeddings_model,
                device=self.device
            )

            # Apply device-specific optimizations
            self._optimize_model_for_device()

            # Warm up the model
            self._warmup_embedding_model()

            print(f"[+] Embeddings model loaded on {self.device}")

        except Exception as e:
            print(f"[-] Model loading failed: {e}")
            raise e

    def _detect_compute_device(self):
        """Enhanced device detection with detailed diagnostics (local provider only)."""
        import torch
        print("[*] Detecting optimal compute device...")
        
        try:
            if torch.cuda.is_available():
                self.device = "cuda"
                self.cuda_available = True
                
                # Detailed GPU info
                gpu_name = torch.cuda.get_device_name()
                gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1e9
                gpu_count = torch.cuda.device_count()
                
                print(f"[+] CUDA GPU detected: {gpu_name}")
                print(f"[*] GPU Memory: {gpu_memory:.1f} GB")
                print(f"[*] GPU Count: {gpu_count}")
                print(f"[*] CUDA Version: {torch.version.cuda}")
                
                # Check available memory
                torch.cuda.empty_cache()
                allocated = torch.cuda.memory_allocated() / 1e9
                reserved = torch.cuda.memory_reserved() / 1e9
                print(f"[*] GPU Memory - Allocated: {allocated:.2f} GB, Reserved: {reserved:.2f} GB")
                
            else:
                self.device = "cpu"
                self.cuda_available = False
                
                print("[!] CUDA not available - using optimized CPU")
                print("[*] CPU Info:")
                print(f"   Threads available: {torch.get_num_threads()}")
                print(f"   MKL available: {torch.backends.mkl.is_available()}")
                print(f"   OpenMP available: {torch.backends.openmp.is_available()}")
                
                # CPU optimizations
                self._apply_cpu_optimizations()
                
        except Exception as e:
            print(f"[-] Device detection error: {e}")
            self.device = "cpu"
            self.cuda_available = False
    
    def _apply_cpu_optimizations(self):
        """Apply aggressive CPU optimizations when GPU is not available (local provider only)."""
        import os
        import torch


        # Set environment variables for optimal CPU performance
        optimizations = {
            "OMP_NUM_THREADS": "8",
            "MKL_NUM_THREADS": "8", 
            "OPENBLAS_NUM_THREADS": "8",
            "VECLIB_MAXIMUM_THREADS": "8",
            "NUMEXPR_NUM_THREADS": "8"
        }
        
        for var, value in optimizations.items():
            os.environ[var] = value
            
        # PyTorch specific optimizations
        torch.set_num_threads(8)
        torch.set_num_interop_threads(4)
        
        print("[*] Applied aggressive CPU optimizations")
    
    def _optimize_model_for_device(self):
        """Apply device-specific model optimizations (local provider only)."""
        import torch

        if self.cuda_available:
            print("[*] Applying GPU optimizations...")
            
            # Set model to eval mode
            self.embeddings_model.eval()
            
            # Try half precision if supported
            try:
                self.embeddings_model.half()
                self._use_half_precision = True
                print("[+] Enabled half-precision (FP16) inference")
            except Exception as e:
                self._use_half_precision = False
                print(f"[!] Half-precision not supported: {e}")
            
            # CUDA optimizations
            torch.backends.cudnn.benchmark = True
            torch.backends.cuda.matmul.allow_tf32 = True
            
        else:
            print("[*] Applying CPU optimizations...")
            self._use_half_precision = False
            
            # CPU-specific optimizations
            self.embeddings_model.eval()
    
    def _warmup_embedding_model(self):
        """Comprehensive model warmup"""
        print("[*] Warming up embedding model...")
        
        warmup_texts = [
            "financial report analysis",
            "engineering documentation query", 
            "hr policy information",
            "marketing campaign data",
            "executive summary report"
        ]
        
        start_time = time.perf_counter()
        
        try:
            # Single embedding warmup
            for text in warmup_texts:
                _ = self.embeddings_model.encode(
                    text,
                    convert_to_tensor=False,
                    show_progress_bar=False,
                    batch_size=1,
                    device=self.device
                )
            
            # Batch embedding warmup
            _ = self.embeddings_model.encode(
                warmup_texts,
                convert_to_tensor=False,
                show_progress_bar=False,
                batch_size=len(warmup_texts),
                device=self.device
            )
            
            warmup_time = time.perf_counter() - start_time
            print(f"[+] Model warmed up in {warmup_time:.2f}s")
            
        except Exception as e:
            print(f"[!] Warmup failed: {e}")
    
    def _generate_batch_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Optimized batch embedding generation"""
        if not texts:
            return []

        batch_start = time.perf_counter()

        if self.embeddings_provider == "cloudflare":
            # No try/except here: a Cloudflare failure must propagate (raise
            # CloudflareEmbeddingsError) rather than silently fall back to a
            # local model or a wrong-dimension zero vector. Callers
            # (add_documents / search_documents) decide how to degrade.
            embeddings = self._cloudflare_client.embed(texts)
            batch_time = time.perf_counter() - batch_start
            self._performance_stats["total_embeddings"] += len(texts)
            avg_time = batch_time / len(texts)
            if self._performance_stats["avg_embedding_time"] == 0:
                self._performance_stats["avg_embedding_time"] = avg_time
            else:
                self._performance_stats["avg_embedding_time"] = (
                    0.9 * self._performance_stats["avg_embedding_time"] + 0.1 * avg_time
                )
            if settings.debug:
                print(f"[*] Cloudflare batch embedding: {len(texts)} texts in {batch_time:.3f}s ({avg_time*1000:.1f}ms/text)")
            return embeddings

        try:
            # Determine optimal batch size based on device
            if self.cuda_available:
                batch_size = min(64, len(texts))  # Larger batches for GPU
            else:
                batch_size = min(16, len(texts))  # Smaller batches for CPU
            
            # Generate embeddings with optimizations
            embeddings = self.embeddings_model.encode(
                texts,
                batch_size=batch_size,
                show_progress_bar=False,
                convert_to_tensor=False,
                normalize_embeddings=True,
                device=self.device
            )
            
            batch_time = time.perf_counter() - batch_start
            
            # Update performance stats
            self._performance_stats["total_embeddings"] += len(texts)
            avg_time = batch_time / len(texts)
            
            if self._performance_stats["avg_embedding_time"] == 0:
                self._performance_stats["avg_embedding_time"] = avg_time
            else:
                # Exponential moving average
                self._performance_stats["avg_embedding_time"] = (
                    0.9 * self._performance_stats["avg_embedding_time"] + 0.1 * avg_time
                )
            
            if settings.debug:
                print(f"[*] Batch embedding: {len(texts)} texts in {batch_time:.3f}s ({avg_time*1000:.1f}ms/text)")
            
            return embeddings.tolist()
            
        except Exception as e:
            print(f"[-] Batch embedding error: {e}")
            # Fallback to individual embeddings
            return [self._get_single_embedding(text) for text in texts]
    
    @lru_cache(maxsize=2000)
    def _get_cached_embedding(self, query: str) -> List[float]:
        """Enhanced embedding caching with performance tracking"""
        # Check manual cache first
        query_hash = hashlib.md5(query.encode()).hexdigest()
        
        if query_hash in self._embedding_cache:
            self._cache_stats["hits"] += 1
            return self._embedding_cache[query_hash]
        
        self._cache_stats["misses"] += 1
        
        # Generate new embedding
        embedding = self._get_single_embedding(query)
        
        # Manage cache size
        if len(self._embedding_cache) >= self._max_cache_size:
            # Remove oldest 20% of entries
            remove_count = self._max_cache_size // 5
            oldest_keys = list(self._embedding_cache.keys())[:remove_count]
            for key in oldest_keys:
                del self._embedding_cache[key]
        
        self._embedding_cache[query_hash] = embedding
        return embedding
    
    def _get_single_embedding(self, text: str) -> List[float]:
        """Optimized single embedding generation"""
        embed_start = time.perf_counter()

        if self.embeddings_provider == "cloudflare":
            # No local fallback: propagate CloudflareEmbeddingsError on failure
            # rather than returning a wrong-dimension zero vector.
            vectors = self._cloudflare_client.embed([text])
            embed_time = time.perf_counter() - embed_start
            if settings.debug and embed_time > 0.5:
                print(f"[!] Slow Cloudflare embedding: {embed_time:.3f}s for text length {len(text)}")
            return vectors[0]

        try:
            embedding = self.embeddings_model.encode(
                text,
                batch_size=1,
                show_progress_bar=False,
                convert_to_tensor=False,
                normalize_embeddings=True,
                device=self.device
            )
            
            embed_time = time.perf_counter() - embed_start
            
            if settings.debug and embed_time > 0.5:
                print(f"[!] Slow embedding: {embed_time:.3f}s for text length {len(text)}")
            
            return embedding.tolist()
            
        except Exception as e:
            print(f"[-] Single embedding error: {e}")
            # Return zero vector as fallback
            return [0.0] * 384

    def search_documents(self, query: str, user_role: Role = Role.EMPLOYEE, tenant_id: str = "default", limit: int = 3, min_similarity: float = 0.15, min_results: int = 2, exclude_sources: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Search documents based on query with RBAC and tenant isolation.

        Args:
            query: The search query
            user_role: User role for RBAC
            tenant_id: Tenant identifier for multi-tenancy isolation
            limit: Maximum number of results to return
            min_similarity: Minimum similarity threshold (default 0.15)
            min_results: Minimum results to return even with low confidence (default 2)

        Returns:
            List of document dictionaries with content and metadata
        """
        try:
            logger.info(f"AUDIT: Vector search requested with limit={limit} tenant_id={tenant_id} role={user_role.value}")

            # Get departments accessible to the user role
            accessible_departments = self._get_accessible_departments(user_role)

            # Generate embedding for query
            query_embedding = self._get_cached_embedding(query)
            if query_embedding is None:
                logger.warning("Failed to generate query embedding")
                return []

            # Build where clause with tenant isolation AND department filtering
            where_clause = {
                "$and": [
                    {"tenant_id": {"$eq": tenant_id}},
                    {"department": {"$in": accessible_departments}}
                ]
            }
            if exclude_sources:
                # Retired (deleted/replaced) documents of this tenant.
                where_clause["$and"].append({"source": {"$nin": list(exclude_sources)}})

            # Search with tenant and department filtering
            search_kwargs = {
                "n_results": min(limit * 3, 20),  # Get more than needed for filtering
                "where": where_clause,
                "include": ["metadatas", "documents", "distances"]
            }

            logger.debug(f"Chroma query: where={where_clause} n_results={search_kwargs['n_results']}")

            results = self.collection.query(
                query_embeddings=[query_embedding],
                **search_kwargs
            )

            # Process results
            documents = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            logger.info(f"Chroma returned {len(documents)} documents for tenant_id={tenant_id}")

            # Build result list with all candidates
            all_candidates = []
            for i, (doc, meta, dist) in enumerate(zip(documents, metadatas, distances)):
                # AUDIT: Chroma returns DISTANCE (0=exact, 2=opposite)
                # Convert distance to similarity: similarity = 1 - (distance / 2)
                similarity = 1.0 - min(dist, 2.0) / 2.0

                # Log each score for audit
                logger.info(f"Doc {i}: distance={dist:.4f} similarity={similarity:.4f} source={meta.get('source', 'unknown')[:50]}")

                all_candidates.append({
                    "content": doc,
                    "metadata": meta,
                    "similarity": similarity,
                    "source": meta.get("source", "unknown")
                })

            # Sort by similarity (highest first)
            all_candidates.sort(key=lambda x: x["similarity"], reverse=True)

            # One absolute floor, then the best `limit` candidates. The former
            # two-tier rule dropped every 0.15-0.20 candidate whenever two
            # others cleared 0.20 - for a misspelled question that discarded
            # the section that answers it. Weak padding is still removed by
            # the prompt builder's floor relative to the best match.
            document_list = [d for d in all_candidates if d["similarity"] >= min_similarity][:limit]
            logger.info(f"Returning {len(document_list)} documents (similarity >= {min_similarity})")
            return document_list

        except Exception as e:
            logger.error(f"Error in search_documents: {e}", exc_info=True)
            return []

    def _get_accessible_departments(self, user_role: Role) -> List[str]:
        """Get accessible departments for role"""
        user_permissions = ROLE_PERMISSIONS.get(user_role)
        if not user_permissions:
            return ["general"]
        
        return [dept.value for dept in user_permissions.allowed_departments]

    def _get_cache_hit_rate(self) -> float:
        """Calculate cache hit rate"""
        total = self._cache_stats["hits"] + self._cache_stats["misses"]
        return self._cache_stats["hits"] / max(total, 1)

    def get_performance_stats(self) -> Dict[str, Any]:
        """Enhanced performance statistics"""
        if self.embeddings_provider == "cloudflare":
            model_name = self._cloudflare_client.model if self._cloudflare_client else settings.cloudflare_embeddings_model
        else:
            model_name = settings.local_embeddings_model
        return {
            "device": self.device,
            "cuda_available": self.cuda_available,
            "embeddings_provider": self.embeddings_provider,
            "half_precision": getattr(self, '_use_half_precision', False),
            "cache_hit_rate": f"{self._get_cache_hit_rate():.2%}",
            "cache_size": len(self._embedding_cache),
            "cache_hits": self._cache_stats["hits"],
            "cache_misses": self._cache_stats["misses"],
            "total_embeddings": self._performance_stats["total_embeddings"],
            "avg_embedding_time": f"{self._performance_stats['avg_embedding_time']*1000:.1f}ms",
            "model_name": model_name
        }

    # ... (rest of the methods remain the same: add_documents, similarity_search, etc.)
    @staticmethod
    def _validate_chunk_tenancy(chunks: List[DocumentChunk], tenant_id: Optional[str]) -> None:
        """Enforce the single tenant-ownership contract before any write.

        Invariant: for every persisted chunk,
            chunk.metadata["tenant_id"] == indexing tenant == owner's tenant.

        Fails loudly rather than silently normalising a mismatch or inventing a
        fallback tenant.
        """
        param_tenant = (tenant_id or "").strip() or None

        for idx, chunk in enumerate(chunks):
            meta = getattr(chunk, "metadata", None) or {}
            chunk_tenant = meta.get("tenant_id")
            chunk_tenant = (chunk_tenant or "").strip() or None
            source = meta.get("source", "<unknown source>")

            if chunk_tenant and param_tenant and chunk_tenant != param_tenant:
                raise ValueError(
                    "Tenant ownership conflict for chunk %d of %r: chunk metadata "
                    "says tenant_id=%r but add_documents() was called with "
                    "tenant_id=%r. Refusing to index — resolve the ownership "
                    "mismatch at the call site rather than normalising it here."
                    % (idx, source, chunk_tenant, param_tenant)
                )

            if not (chunk_tenant or param_tenant):
                raise ValueError(
                    "Missing tenant ownership for chunk %d of %r. Every indexed "
                    "chunk must have an explicit tenant: pass tenant_id= to "
                    "add_documents() or set chunk.metadata['tenant_id']. "
                    "There is no implicit 'default' tenant."
                    % (idx, source)
                )

    @staticmethod
    def chunk_record_id(chunk: DocumentChunk, tenant_id: str) -> str:
        """Stable Chroma id: tenant, source, chunk position and content hash."""
        doc_hash = hashlib.md5(chunk.content.encode()).hexdigest()[:8]
        return f"{tenant_id}_{chunk.metadata['source']}_{chunk.metadata['chunk_id']}_{doc_hash}"

    def source_record_ids(self, source: str, tenant_id: str) -> List[str]:
        """Ids of every indexed chunk of one source within one tenant."""
        result = self.collection.get(
            where={"$and": [{"tenant_id": tenant_id}, {"source": source}]}, include=[])
        return list(result.get("ids") or [])

    def add_documents(self, chunks: List[DocumentChunk], tenant_id: str = None) -> bool:
        """Add document chunks with tenant tagging and performance tracking.

        Tenant ownership is MANDATORY and must be unambiguous. It may be supplied
        via the `tenant_id` argument, via `chunk.metadata["tenant_id"]`, or both
        — but if both are present they must agree.

        Args:
            chunks: Document chunks to index.
            tenant_id: Owning tenant. Required unless every chunk already carries
                `metadata["tenant_id"]`.

        Raises:
            ValueError: if a chunk has no resolvable tenant, or if the chunk's
                metadata tenant conflicts with the `tenant_id` argument.

        Note:
            The previous signature defaulted to ``tenant_id="default"``. That
            silently filed every bootstrap chunk under a phantom "default"
            tenant that no authenticated user can ever query. There is no
            implicit tenant any more — callers must decide ownership.
        """
        self._validate_chunk_tenancy(chunks, tenant_id)
        print(f"[*] Adding {len(chunks)} document chunks with tenant_id={tenant_id}...")

        add_start = time.perf_counter()

        try:
            batch_size = 100 if self.cuda_available else 50
            total_batches = (len(chunks) + batch_size - 1) // batch_size
            
            for batch_idx in range(total_batches):
                batch_start = time.perf_counter()
                
                start_idx = batch_idx * batch_size
                end_idx = min(start_idx + batch_size, len(chunks))
                batch_chunks = chunks[start_idx:end_idx]
                
                # Prepare data
                documents = []
                embeddings = []
                metadatas = []
                ids = []
                
                texts = [chunk.content for chunk in batch_chunks]
                
                # Generate embeddings in batch
                batch_embeddings = self._generate_batch_embeddings(texts)
                
                # Process chunks
                for i, chunk in enumerate(batch_chunks):
                    # Tenancy was validated up-front by _validate_chunk_tenancy,
                    # so this resolution can no longer fall back to "default".
                    chunk_tenant_id = chunk.metadata.get("tenant_id") or tenant_id

                    # Generate unique ID with tenant_id to ensure uniqueness across tenants
                    chunk_id = self.chunk_record_id(chunk, chunk_tenant_id)
                    
                    dept = chunk.metadata["department"]
                    dept_value = dept.value if hasattr(dept, 'value') else str(dept)
                    
                    metadata = {
                        "tenant_id": chunk_tenant_id,  # CRITICAL: Add tenant_id to metadata
                        "source": chunk.metadata["source"],
                        "department": dept_value,
                        "department_enum": dept_value,
                        "doc_type": chunk.metadata.get("doc_type", "unknown"),
                        "content_type": chunk.metadata.get("content_type", "text"),
                        "chunk_id": str(chunk.metadata["chunk_id"])
                    }
                    
                    documents.append(chunk.content)
                    embeddings.append(batch_embeddings[i])
                    metadatas.append(metadata)
                    ids.append(chunk_id)
                
                # Add to ChromaDB (idempotent)
                if hasattr(self.collection, "upsert"):
                    self.collection.upsert(
                        documents=documents,
                        embeddings=embeddings,
                        metadatas=metadatas,
                        ids=ids
                    )
                else:
                    try:
                        existing = self.collection.get(ids=ids, include=[])
                        existing_ids = set(existing.get("ids", []))
                    except Exception:
                        existing_ids = set()
                    if existing_ids:
                        filtered = [
                            (d, e, m, i)
                            for d, e, m, i in zip(documents, embeddings, metadatas, ids)
                            if i not in existing_ids
                        ]
                        if not filtered:
                            continue
                        documents, embeddings, metadatas, ids = zip(*filtered)
                        documents, embeddings, metadatas, ids = list(documents), list(embeddings), list(metadatas), list(ids)
                    if documents:
                        self.collection.add(
                            documents=documents,
                            embeddings=embeddings,
                            metadatas=metadatas,
                            ids=ids
                        )
                
                batch_time = time.perf_counter() - batch_start
                print(f"   Batch {batch_idx + 1}/{total_batches}: {len(batch_chunks)} chunks in {batch_time:.2f}s")
            
            total_time = time.perf_counter() - add_start
            print(f"[+] Enhanced processing: {len(chunks)} chunks in {total_time:.2f}s")
            
            return True
            
        except Exception as e:
            print(f"[-] Enhanced document adding error: {e}")
            return False

    def get_collection_stats(self, tenant_id: str = None,
                             departments: Optional[List[str]] = None) -> Dict[str, Any]:
        """Enhanced collection statistics, optionally scoped to a tenant and,
        for callers whose role cannot read every department, to the
        departments retrieval would allow them to see."""
        try:
            if tenant_id:
                # SECURITY: Tenant-scoped stats
                where = {"tenant_id": tenant_id}
                if departments is not None:
                    where = {"$and": [where, {"department": {"$in": list(departments) or [""]}}]}
                sample_results = self.collection.get(
                    where=where,
                    include=["metadatas"]
                )
                collection_count = len(sample_results.get("metadatas", []))
                sample_size = collection_count
            else:
                collection_count = self.collection.count()
                sample_size = min(100, collection_count)
                sample_results = self.collection.get(limit=sample_size, include=["metadatas"])
            
            departments = {}
            doc_types = {}
            sources = {}
            
            for metadata in sample_results["metadatas"]:
                dept = metadata.get("department", "unknown")
                doc_type = metadata.get("doc_type", "unknown")
                source = metadata.get("source", "unknown")
                
                departments[dept] = departments.get(dept, 0) + 1
                doc_types[doc_type] = doc_types.get(doc_type, 0) + 1
                sources[source] = sources.get(source, 0) + 1
            
            return {
                "total_documents": collection_count,
                "departments": departments,
                "document_types": doc_types,
                "sources": sources,
                "performance": self.get_performance_stats(),
                "sample_size": sample_size
            }
            
        except Exception as e:
            return {"error": str(e), "total_documents": 0}

    def get_source_passages(self, source: str, tenant_id: str,
                            departments: List[str]) -> List[str]:
        """Indexed text of one source, in chunk order, under the same tenant +
        department filter retrieval applies. Empty when the caller could not
        retrieve it, so callers cannot tell "hidden" from "absent"."""
        if not source or not tenant_id or not departments:
            return []
        result = self.collection.get(
            where={"$and": [
                {"tenant_id": tenant_id},
                {"source": source},
                {"department": {"$in": list(departments)}},
            ]},
            include=["documents", "metadatas"],
        )
        pairs = sorted(
            zip(result.get("metadatas") or [], result.get("documents") or []),
            key=lambda pair: int((pair[0] or {}).get("chunk_id") or 0),
        )
        return [text for _, text in pairs if text]

    def similarity_search(self, query: str, k: int = 5) -> List[Any]:
        """Standard similarity search with enhanced performance"""
        try:
            query_embedding = self._get_cached_embedding(query)
            
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=k,
                include=["documents", "metadatas", "distances"]
            )
            
            docs = []
            if results["documents"] and len(results["documents"]) > 0:
                for i in range(len(results["documents"][0])):
                    class MockDocument:
                        def __init__(self, content, metadata):
                            self.page_content = content
                            self.metadata = metadata
                    
                    doc = MockDocument(
                        content=results["documents"][0][i],
                        metadata=results["metadatas"][0][i]
                    )
                    docs.append(doc)
            
            return docs
            
        except Exception as e:
            print(f"[-] Similarity search error: {e}")
            return []

    def clear_collection(self):
        """Clear collection with cache cleanup"""
        try:
            self.client.delete_collection(self.collection_name)
            self.collection = self.client.create_collection(
                name=self.collection_name,
                embedding_function=self._get_embedding_function()
            )
            
            # Clear all caches
            self._embedding_cache.clear()
            self._cache_stats = {"hits": 0, "misses": 0}
            self._performance_stats = {
                "total_embeddings": 0,
                "avg_embedding_time": 0,
                "cache_hit_rate": 0
            }
            
            print("[*] Collection and caches cleared successfully")
            
        except Exception as e:
            print(f"[-] Error clearing collection: {e}")

    def get_unique_sources(self, tenant_id: str = None) -> List[str]:
        """Return a list of unique source filenames, optionally filtered by tenant_id."""
        try:
            if tenant_id:
                # SECURITY: Filter by tenant
                results = self.collection.get(
                    where={"tenant_id": tenant_id},
                    include=["metadatas"]
                )
            else:
                total_docs = self.collection.count()
                if total_docs == 0:
                    return []
                results = self.collection.get(limit=total_docs, include=["metadatas"])

            sources = set()
            for meta in results.get("metadatas", []):
                source = meta.get("source")
                if source:
                    sources.add(source)
            return list(sources)
        except Exception as e:
            print(f"[!] Unable to fetch unique sources: {e}")
            return []

    def delete_documents_by_sources(self, sources: List[str], tenant_id: str = None,
                                    raise_on_error: bool = False) -> int:
        """Delete all document chunks whose metadata.source is in the provided list.
        SECURITY: If tenant_id is provided, only delete within that tenant's scope.
        Returns number of deleted chunks (best-effort).

        With raise_on_error=True the deletion is verified (no matching chunk may
        remain) and any failure raises instead of returning 0, so callers that
        must not report success while content is still retrievable can tell
        "nothing to delete" apart from "delete failed"."""
        if not sources:
            return 0
        if tenant_id:
            # SECURITY: Scope deletion to tenant
            where = {"$and": [{"source": {"$in": sources}}, {"tenant_id": tenant_id}]}
        else:
            where = {"source": {"$in": sources}}
        try:
            self.collection.delete(where=where)
            if raise_on_error and self.collection.get(where=where, limit=1).get("ids"):
                raise RuntimeError("vector chunks still present after delete")
            # Best-effort count removal stats – may require another count
            print(f"[*] Removed vectors for {len(sources)} stale sources: {sources}")

            # Clean internal caches because underlying data changed
            self._embedding_cache.clear()
            self._cache_stats = {"hits": 0, "misses": 0}
            return len(sources)
        except Exception as e:
            if raise_on_error:
                raise
            print(f"[-] Error deleting documents for sources {sources}: {e}")
            return 0

    def keyword_search(self, query: str, user_role: Role, limit: int = 5, tenant_id: str = "default") -> List[Dict[str, Any]]:
        """Enhanced keyword search as fallback when semantic search fails"""
        print(f"\n[*] DEBUG: Running enhanced keyword search for: '{query}'")
        
        try:
            # Get departments accessible to the user role
            accessible_departments = self._get_accessible_departments(user_role)
            
            # Extract important terms for search
            search_terms = self._extract_search_terms(query)
            if not search_terms:
                print(f"[*] No valid search terms extracted from query")
                return []
            
            print(f"[*] Using search terms: {search_terms}")
            
            # Get all documents filtered by tenant AND department
            where_filter = {
                "$and": [
                    {"tenant_id": tenant_id},
                    {"department": {"$in": accessible_departments}}
                ]
            }
            all_docs = self.collection.get(
                where=where_filter,
                include=["metadatas", "documents"]
            )
            
            # collection.get() returns flat lists (not nested like .query())
            documents = all_docs.get("documents", [])
            metadatas = all_docs.get("metadatas", [])
            
            if not documents:
                return []
            
            # Score documents based on term frequency
            scored_docs = []
            for i, (doc, meta) in enumerate(zip(documents, metadatas)):
                if not doc or not isinstance(doc, str):
                    continue
                
                # Calculate document score based on term matches
                score = 0
                doc_lower = doc.lower()
                
                # Score exact matches more highly
                for term in search_terms:
                    if term.lower() in doc_lower:
                        # Count occurrences (with diminishing returns)
                        count = doc_lower.count(term.lower())
                        score += min(count * 0.2, 1.0)
                        
                        # Boost score for exact matches
                        if re.search(r'\b' + re.escape(term.lower()) + r'\b', doc_lower):
                            score += 0.5
                
                # Only include documents with at least one matching term
                if score > 0:
                    scored_docs.append({
                        "content": doc,
                        "metadata": meta,
                        "similarity": score,
                        "source": meta.get("source", "unknown")
                    })
            
            # Sort by score and limit results
            scored_docs.sort(key=lambda x: x["similarity"], reverse=True)
            results = scored_docs[:limit]
            
            print(f"[*] Keyword search found {len(results)} relevant documents")
            return results
            
        except Exception as e:
            print(f"[*] ERROR in keyword search: {e}")
            return []
            
    def _extract_search_terms(self, query: str) -> List[str]:
        """Extract meaningful search terms from a query"""
        # Remove common stopwords for better keyword matching
        stopwords = {'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'with',
                   'by', 'about', 'as', 'into', 'like', 'through', 'after', 'over', 'between',
                   'out', 'of', 'from', 'up', 'about', 'is', 'are', 'was', 'were', 'be', 'been',
                   'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'shall',
                   'should', 'may', 'might', 'must', 'can', 'could'}
        
        # Split query and filter out stopwords
        words = query.split()
        filtered_words = [word.strip('.,?!()[]{}":;') for word in words 
                         if word.lower() not in stopwords and len(word) > 2]
        
        # Extract named entities or special terms
        special_terms = []
        
        # Look for terms in quotes
        quoted_terms = re.findall(r'"([^"]+)"', query)
        if quoted_terms:
            special_terms.extend(quoted_terms)
        
        # Look for potential named entities (capitalized terms)
        for i, word in enumerate(words):
            if i > 0 and word[0].isupper() and len(word) > 1:
                special_terms.append(word.strip('.,?!()[]{}":;'))
        
        # Look for numbers and dates
        numbers = re.findall(r'\b\d+(?:\.\d+)?\b', query)
        special_terms.extend(numbers)
        
        # Add any special terms that weren't already included
        for term in special_terms:
            if term.lower() not in [w.lower() for w in filtered_words]:
                filtered_words.append(term)
        
        return filtered_words

    def _preprocess_query(self, query: str) -> str:
        """
        Preprocess the query to improve search quality
        
        Args:
            query: The original query
            
        Returns:
            Processed query
        """
        # Simple preprocessing - trim whitespace, lowercase
        processed = query.strip().lower()
        
        # Remove excessive punctuation but preserve important characters
        processed = re.sub(r'[^\w\s\?\.\,\-]', ' ', processed)
        
        # Remove extra spaces
        processed = re.sub(r'\s+', ' ', processed)
        
        return processed
        
    def get_accessible_roles_for_user(self, user_role: Role) -> List[str]:
        """
        Get the roles that this user can access based on their own role
        
        Args:
            user_role: The user's role
            
        Returns:
            List of role names accessible to this user
        """
        # Role hierarchy - higher roles can access lower roles' content
        role_hierarchy = {
            Role.C_LEVEL: ["C_LEVEL", "FINANCE", "HR", "ENGINEERING", "MARKETING", "EMPLOYEE"],
            Role.FINANCE: ["FINANCE", "EMPLOYEE"],
            Role.HR: ["HR", "EMPLOYEE"],
            Role.ENGINEERING: ["ENGINEERING", "EMPLOYEE"],
            Role.MARKETING: ["MARKETING", "EMPLOYEE"],
            Role.EMPLOYEE: ["EMPLOYEE"]
        }
        
        # Handle string role values
        if isinstance(user_role, str):
            try:
                user_role = Role[user_role.upper()]
            except (KeyError, AttributeError):
                return ["EMPLOYEE"]  # Default to employee access
        
        # Return accessible roles based on user's role
        return role_hierarchy.get(user_role, ["EMPLOYEE"])

    def _get_embedding_function(self):
        """
        Get the Chroma-compatible embedding function for the active provider.

        This is only ever used so a newly-created Chroma collection has a
        callable registered against it — every add/query in this module
        always supplies embeddings explicitly, so Chroma never actually
        invokes this for encoding. It still must match the active provider
        so a Cloudflare collection is never wired to a
        SentenceTransformerEmbeddingFunction (which would import torch), and
        local mode never builds a Cloudflare client it has no credentials
        for.

        Returns:
            Embedding function to use with ChromaDB
        """
        if self.embeddings_provider == "cloudflare":
            return self._cloudflare_client
        try:
            from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
            return SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        except Exception as e:
            logger.error(f"Error creating embedding function: {e}")
            return None
