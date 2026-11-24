"""Root pytest configuration — FinSyntra test data isolation.

THIS FILE MUST STAY AT THE REPOSITORY ROOT.

pytest imports the rootdir conftest.py before `tests/conftest.py` and before any
test module. That ordering is the only reason this works: several application
modules build global state at *import* time —

    src/config/settings.py        settings = Settings()          (reads .env)
    src/backend/database/database.py
                                  engine = create_engine(...)    (module level)
                                  SessionLocal = sessionmaker(...)
                                  db_manager = DatabaseManager()
    src/backend/services/vector_store.py
                                  VectorStore is a process-wide singleton whose
                                  first construction fixes the Chroma path

— so redirecting paths from inside a fixture would be too late. Everything here
runs at module import, before `src.*` is importable state.

Isolation strategy:
  * DATABASE_URL   -> temporary SQLite file  (env var beats .env in
                      pydantic-settings, so this wins over data/finsolve.db)
  * VECTOR_DB_PATH -> temporary directory    (consumed by
                      vector_store.resolve_persist_directory)
  * VECTOR_COLLECTION_NAME -> run-unique name, so a leaked handle to the real
                      store still cannot touch the `company_docs` collection.

Plus a fail-closed guard (see `_install_dev_path_guards`): if isolation ever
breaks, tests raise instead of destroying development data.
"""

import atexit
import os
import secrets
import shutil
import sys
import tempfile
import uuid

# --------------------------------------------------------------------------
# 0. Guard: nothing may have imported application settings before we get here.
# --------------------------------------------------------------------------
_PRELOADED = [m for m in ("src.config.settings",
                          "src.backend.database.database",
                          "src.backend.services.vector_store") if m in sys.modules]
if _PRELOADED:
    raise RuntimeError(
        "FinSyntra test isolation failed: %s already imported before the root "
        "conftest.py ran. Test data isolation cannot be guaranteed; aborting "
        "rather than risking development data." % ", ".join(_PRELOADED)
    )

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

# --------------------------------------------------------------------------
# 1. Development paths that tests must never touch.
# --------------------------------------------------------------------------
DEV_DB_PATH = os.path.abspath(os.path.join(PROJECT_ROOT, "data", "finsolve.db"))
DEV_CHROMA_PATH = os.path.abspath(
    os.path.join(PROJECT_ROOT, "src", "data", "embeddings", "chroma_db"))
DEV_RAW_PATH = os.path.abspath(os.path.join(PROJECT_ROOT, "src", "data", "raw"))


def _norm(p):
    """Absolute, symlink-resolved, case-normalised path for comparison."""
    try:
        return os.path.normcase(os.path.realpath(os.path.abspath(str(p))))
    except Exception:
        return os.path.normcase(os.path.abspath(str(p)))


def is_dev_path(candidate, dev_path):
    """True if `candidate` is `dev_path` or lives underneath it."""
    c, d = _norm(candidate), _norm(dev_path)
    return c == d or c.startswith(d + os.sep)


# --------------------------------------------------------------------------
# 2. Allocate the throwaway test sandbox.
# --------------------------------------------------------------------------
TEST_SANDBOX = tempfile.mkdtemp(prefix="finsolve-tests-")
TEST_DB_PATH = os.path.join(TEST_SANDBOX, "test_finsolve.db")
TEST_CHROMA_PATH = os.path.join(TEST_SANDBOX, "chroma_db")
TEST_RAW_PATH = os.path.join(TEST_SANDBOX, "raw_docs")
TEST_COLLECTION = "test_docs_%s" % uuid.uuid4().hex[:8]

os.makedirs(TEST_CHROMA_PATH, exist_ok=True)
os.makedirs(TEST_RAW_PATH, exist_ok=True)

# sqlite URL needs forward slashes on Windows
os.environ["DATABASE_URL"] = "sqlite:///%s" % TEST_DB_PATH.replace("\\", "/")
os.environ["VECTOR_DB_PATH"] = TEST_CHROMA_PATH
os.environ["VECTOR_COLLECTION_NAME"] = TEST_COLLECTION
os.environ["RAW_DOCUMENTS_PATH"] = TEST_RAW_PATH
os.environ["FINSOLVE_TEST_SANDBOX"] = TEST_SANDBOX
os.environ["FINSOLVE_TEST_RAW_PATH"] = TEST_RAW_PATH
# Match the test clients' explicit origin, independent of the developer dotenv.
os.environ["ALLOWED_ORIGINS"] = '["http://localhost:3000"]'
# A clean checkout has no .env, and settings deliberately never default the
# signing key (fail closed: the sentinel MUST_BE_SET_VIA_ENV is refused in
# production). Use a random per-run key so the suite does not depend on a
# developer's dotenv; an explicitly exported SECRET_KEY is still honoured.
os.environ.setdefault("SECRET_KEY", secrets.token_urlsafe(48))
# Keep tests deterministic and off the developer's runtime config.
#
# ENV must stay "dev" here. It is NOT cosmetic: chat_stream's auth bypass is
# gated on `os.getenv("ENV", "dev").lower() == "dev"`, so setting ENV="test"
# silently disables the `mock_auth_bypass` fixture and turns several streaming
# tests into 401s. Changing that gate belongs to the auth wave, not to Wave 1 —
# isolation must not alter application semantics.
os.environ.setdefault("ENV", "dev")
os.environ.setdefault("BYPASS_AUTH", "false")
os.environ.setdefault("ENABLE_METRICS", "false")
os.environ.setdefault("REDIS_URL", "")


@atexit.register
def _cleanup_sandbox():
    """Remove only the temporary sandbox. Never touches development paths.

    Chroma can still hold the sqlite handle open on Windows, so a first pass may
    leave a few .bin files behind. That residue lives in %TEMP%, never in the
    repository, and each run allocates a fresh sandbox.
    """
    if is_dev_path(TEST_SANDBOX, DEV_CHROMA_PATH) or is_dev_path(TEST_SANDBOX, DEV_RAW_PATH):
        return  # paranoia: refuse to delete anything near dev data
    for _ in range(2):
        shutil.rmtree(TEST_SANDBOX, ignore_errors=True)
        if not os.path.exists(TEST_SANDBOX):
            break
        import gc
        gc.collect()


# --------------------------------------------------------------------------
# 3. Fail-closed guards.
#
# Fixtures alone are not enough: a future test could construct a VectorStore
# directly, or a settings change could silently reintroduce the dev path. These
# guards wrap the *destructive* entry points so that broken isolation produces a
# test failure instead of data loss. They are installed only from conftest, so
# application runtime is unaffected.
# --------------------------------------------------------------------------
class DevDataProtectionError(RuntimeError):
    """Raised when a test tries to operate on real development data."""


def assert_not_dev_chroma(path, action="operate on"):
    if is_dev_path(path, DEV_CHROMA_PATH):
        raise DevDataProtectionError(
            "BLOCKED: test attempted to %s the DEVELOPMENT Chroma store.\n"
            "  resolved path : %s\n"
            "  dev path      : %s\n"
            "Test isolation has broken. Fix the fixture rather than removing "
            "this guard." % (action, _norm(path), _norm(DEV_CHROMA_PATH))
        )


def assert_not_dev_db(url_or_path, action="operate on"):
    raw = str(url_or_path)
    path = raw.split("sqlite:///")[-1] if "sqlite" in raw else raw
    if is_dev_path(path, DEV_DB_PATH):
        raise DevDataProtectionError(
            "BLOCKED: test attempted to %s the DEVELOPMENT SQLite database.\n"
            "  resolved : %s\n"
            "  dev db   : %s\n"
            "Test isolation has broken." % (action, _norm(path), _norm(DEV_DB_PATH))
        )


def assert_not_dev_raw(path, action="write to"):
    if is_dev_path(path, DEV_RAW_PATH):
        raise DevDataProtectionError(
            "BLOCKED: test attempted to %s the DEVELOPMENT document directory.\n"
            "  resolved : %s\n"
            "  dev raw  : %s" % (action, _norm(path), _norm(DEV_RAW_PATH))
        )


_GUARDS_INSTALLED = False


def _install_dev_path_guards():
    """Wrap VectorStore construction/destruction with dev-path assertions."""
    global _GUARDS_INSTALLED
    if _GUARDS_INSTALLED:
        return
    from src.backend.services import vector_store as vs_mod

    _orig_init = vs_mod.VectorStore.__init__
    _orig_clear = vs_mod.VectorStore.clear_collection

    def guarded_init(self, collection_name=None, persist_directory=None):
        resolved = vs_mod.resolve_persist_directory(persist_directory)
        assert_not_dev_chroma(resolved, "construct a VectorStore against")
        return _orig_init(self, collection_name=collection_name,
                          persist_directory=persist_directory)

    def guarded_clear(self, *a, **kw):
        assert_not_dev_chroma(getattr(self, "persist_directory", ""),
                              "clear_collection() on")
        return _orig_clear(self, *a, **kw)

    vs_mod.VectorStore.__init__ = guarded_init
    vs_mod.VectorStore.clear_collection = guarded_clear
    _GUARDS_INSTALLED = True


def pytest_configure(config):
    """Verify isolation actually took effect, then arm the guards."""
    from src.config.settings import settings, get_raw_documents_path
    from src.backend.services.vector_store import resolve_persist_directory

    resolved_chroma = resolve_persist_directory()
    assert_not_dev_chroma(resolved_chroma, "configure the test session against")
    assert_not_dev_db(settings.database_url or DEV_DB_PATH,
                      "configure the test session against")

    resolved_raw = get_raw_documents_path()
    assert_not_dev_raw(resolved_raw, "configure the test session against")

    from src.backend.database.database import engine
    assert_not_dev_db(str(engine.url), "bind the SQLAlchemy engine to")

    _install_dev_path_guards()

    config._finsolve_isolation = {
        "sandbox": TEST_SANDBOX,
        "db": str(engine.url),
        "chroma": resolved_chroma,
        "collection": TEST_COLLECTION,
        "raw": resolved_raw,
    }


def pytest_report_header(config):
    info = getattr(config, "_finsolve_isolation", None)
    if not info:
        return None
    return [
        "FinSyntra test isolation ACTIVE",
        "  sqlite     : %s" % info["db"],
        "  chroma     : %s" % info["chroma"],
        "  collection : %s" % info["collection"],
        "  raw docs   : %s" % info["raw"],
        "  dev data   : PROTECTED (fail-closed guards armed)",
    ]
