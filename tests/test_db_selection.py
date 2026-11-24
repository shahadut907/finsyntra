"""Deterministic database selection: PostgreSQL-or-fail, never a silent
SQLite downgrade.

Covers:
  - build_database_engine() in src/backend/database/database.py
  - is_postgres_url()/require_postgres_driver() now live in the neutral,
    side-effect-free src/config/database_url.py (re-exported from
    database.py for backward compatibility) so that importing them does not
    require constructing the application's runtime database engine
  - the mirrored guard in alembic/env.py (via real `alembic -x db_url=...`
    subprocess calls, same pattern as tests/test_migrations.py), including
    the x-arg > DATABASE_URL env var precedence it has always documented

No real PostgreSQL server, Docker, or new package install is required:
psycopg2 is genuinely absent from this environment, so the "missing driver"
path is exercised for real rather than mocked. The "driver present" path is
verified at the create_engine() call boundary via mocking, since installing
psycopg2 to prove that branch is out of scope for this pass.
"""
import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from conftest import DEV_DB_PATH, is_dev_path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

POSTGRES_URL_WITH_SECRET = "postgresql://demo_user:sup3rsecret@127.0.0.1:59999/finsolve"


class TestBuildDatabaseEngine:
    def test_no_url_uses_local_sqlite_default(self):
        from src.backend.database.database import build_database_engine

        engine = build_database_engine(None, debug=False)
        assert str(engine.url).startswith("sqlite:///")
        assert str(engine.url).replace("\\", "/").endswith("data/finsolve.db")

    def test_explicit_sqlite_url_is_used_as_given(self, tmp_path):
        from src.backend.database.database import build_database_engine

        target = tmp_path / "explicit.db"
        url = "sqlite:///%s" % str(target).replace("\\", "/")
        engine = build_database_engine(url, debug=False)
        assert str(engine.url) == url

    def test_explicit_postgres_without_driver_fails_loudly_not_silently(self):
        """The core regression guard: psycopg2 really is absent in this
        environment, so this proves the fail-closed path for real."""
        from src.backend.database.database import build_database_engine

        with pytest.raises(RuntimeError) as exc_info:
            build_database_engine(POSTGRES_URL_WITH_SECRET, debug=False)

        message = str(exc_info.value)
        assert "fatal" in message.lower() or "refus" in message.lower(), (
            "error should clearly state this is a hard failure, not a substitution"
        )

    def test_postgres_failure_message_never_leaks_credentials(self):
        from src.backend.database.database import build_database_engine

        with pytest.raises(RuntimeError) as exc_info:
            build_database_engine(POSTGRES_URL_WITH_SECRET, debug=False)

        message = str(exc_info.value)
        assert "sup3rsecret" not in message
        assert "demo_user" not in message
        assert POSTGRES_URL_WITH_SECRET not in message

    def test_postgres_failure_does_not_fall_back_to_a_working_sqlite_engine(self):
        """No engine is silently returned at all — the call must raise."""
        from src.backend.database.database import build_database_engine

        try:
            build_database_engine(POSTGRES_URL_WITH_SECRET, debug=False)
            pytest.fail("expected RuntimeError, got a return value instead")
        except RuntimeError:
            pass

    def test_explicit_postgres_with_driver_available_uses_postgres_not_sqlite(self):
        """Simulate the driver being installed: require_postgres_driver() is a
        no-op, and create_engine() must be invoked with the Postgres URL
        (verified at the call boundary, without needing a real server)."""
        from src.backend.database import database as db_module

        with patch.object(db_module, "require_postgres_driver", return_value=None), \
             patch.object(db_module, "create_engine") as mock_create_engine:
            mock_create_engine.return_value = "FAKE_ENGINE"
            result = db_module.build_database_engine(POSTGRES_URL_WITH_SECRET, debug=False)

        assert result == "FAKE_ENGINE"
        mock_create_engine.assert_called_once()
        called_url = mock_create_engine.call_args.args[0]
        assert called_url == POSTGRES_URL_WITH_SECRET
        called_kwargs = mock_create_engine.call_args.kwargs
        assert called_kwargs.get("pool_pre_ping") is True


class TestRequirePostgresDriver:
    def test_raises_clear_error_when_psycopg2_missing(self):
        from src.backend.database.database import require_postgres_driver

        with pytest.raises(RuntimeError, match="psycopg2"):
            require_postgres_driver()


class TestIsPostgresUrl:
    @pytest.mark.parametrize("url", [
        "postgresql://user@host/db",
        "postgres://user@host/db",
        "postgresql+psycopg2://user@host/db",
        "PostgreSQL://user@host/db",
    ])
    def test_recognizes_postgres_schemes(self, url):
        from src.backend.database.database import is_postgres_url
        assert is_postgres_url(url) is True

    @pytest.mark.parametrize("url", [
        "sqlite:///data/finsolve.db",
        "sqlite+pysqlite:///data/finsolve.db",
    ])
    def test_does_not_flag_sqlite(self, url):
        from src.backend.database.database import is_postgres_url
        assert is_postgres_url(url) is False


# ---------------------------------------------------------------------------
# Alembic: same deterministic rule, proven end-to-end via the real CLI.
# ---------------------------------------------------------------------------

def run_alembic_with_url(url, *args, timeout=60):
    assert not is_dev_path(url.split("sqlite:///")[-1], DEV_DB_PATH), (
        "refusing to point this test's alembic invocation at the dev DB"
    )
    env = dict(os.environ)
    env["DATABASE_URL"] = url
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-x", "db_url=%s" % url, *args],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=timeout,
    )


class TestAlembicDeterministicSelection:
    def test_explicit_postgres_without_driver_fails_the_alembic_command(self):
        p = run_alembic_with_url(POSTGRES_URL_WITH_SECRET, "current")
        assert p.returncode != 0

    def test_explicit_postgres_failure_message_does_not_leak_credentials(self):
        p = run_alembic_with_url(POSTGRES_URL_WITH_SECRET, "current")
        combined = p.stdout + p.stderr
        assert "sup3rsecret" not in combined

    def test_explicit_postgres_failure_does_not_touch_the_dev_sqlite_file(self):
        before = os.path.getmtime(DEV_DB_PATH) if os.path.exists(DEV_DB_PATH) else None
        run_alembic_with_url(POSTGRES_URL_WITH_SECRET, "current")
        after = os.path.getmtime(DEV_DB_PATH) if os.path.exists(DEV_DB_PATH) else None
        assert before == after, "the dev SQLite file must never be touched by a failed Postgres request"

    def test_explicit_sqlite_still_works_via_alembic(self, tmp_path):
        db = tmp_path / "alembic_sqlite_ok.db"
        url = "sqlite:///%s" % str(db).replace("\\", "/")
        p = run_alembic_with_url(url, "upgrade", "head")
        assert p.returncode == 0, p.stderr

    def test_x_arg_url_takes_precedence_over_database_url_env_var(self, tmp_path):
        """get_url() checks -x db_url before the DATABASE_URL env var — prove
        it with two DIFFERENT targets so a same-value test couldn't hide a
        precedence bug."""
        x_arg_db = tmp_path / "xarg_wins.db"
        env_var_db = tmp_path / "env_var_loses.db"
        x_arg_url = "sqlite:///%s" % str(x_arg_db).replace("\\", "/")
        env_var_url = "sqlite:///%s" % str(env_var_db).replace("\\", "/")

        env = dict(os.environ)
        env["DATABASE_URL"] = env_var_url
        p = subprocess.run(
            [sys.executable, "-m", "alembic", "-x", "db_url=%s" % x_arg_url,
             "upgrade", "head"],
            cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=60,
        )

        assert p.returncode == 0, p.stderr
        assert x_arg_db.exists(), "the -x db_url target must be the one alembic wrote to"
        assert not env_var_db.exists(), "DATABASE_URL env var must not win over -x db_url"


class TestNeutralUrlHelperModuleHasNoSideEffects:
    """src/config/database_url.py must be importable on its own, without
    pulling in SQLAlchemy or constructing the application's runtime engine —
    that coupling was the Issue 2 regression this module exists to remove."""

    def test_importing_the_helper_module_in_isolation_never_touches_sqlalchemy(self):
        code = (
            "import sys, json\n"
            "import src.config.database_url\n"
            "print(json.dumps({\n"
            "    'sqlalchemy_imported': 'sqlalchemy' in sys.modules,\n"
            "    'runtime_db_module_imported': 'src.backend.database.database' in sys.modules,\n"
            "}))\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0, proc.stderr
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        assert result["sqlalchemy_imported"] is False, (
            "importing src.config.database_url must not import sqlalchemy"
        )
        assert result["runtime_db_module_imported"] is False, (
            "importing src.config.database_url must not import (and thus "
            "construct the engine inside) src.backend.database.database"
        )

    def test_module_source_has_no_engine_or_settings_dependency(self):
        """Belt-and-braces static check alongside the isolated-process proof
        above: the module text itself must not reference sqlalchemy,
        create_engine, or the settings object."""
        path = os.path.join(PROJECT_ROOT, "src", "config", "database_url.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        assert "import sqlalchemy" not in source.lower()
        assert "create_engine" not in source
        assert "import settings" not in source

    def test_database_module_still_re_exports_the_same_helpers(self):
        """Backward compatibility: existing call sites (and this test file)
        import is_postgres_url/require_postgres_driver from database.py too."""
        from src.config.database_url import is_postgres_url as canonical_is_pg
        from src.config.database_url import require_postgres_driver as canonical_require
        from src.backend.database.database import is_postgres_url as reexported_is_pg
        from src.backend.database.database import require_postgres_driver as reexported_require

        assert reexported_is_pg is canonical_is_pg
        assert reexported_require is canonical_require

    def test_alembic_env_imports_helpers_from_the_neutral_module_not_database_py(self):
        path = os.path.join(PROJECT_ROOT, "alembic", "env.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        assert "from src.config.database_url import is_postgres_url, require_postgres_driver" in source
        # The only thing still imported from database.py should be `Base`.
        db_py_import_line = next(
            line for line in source.splitlines()
            if "from src.backend.database.database import" in line
        )
        assert "is_postgres_url" not in db_py_import_line
        assert "require_postgres_driver" not in db_py_import_line
        assert "Base" in db_py_import_line
