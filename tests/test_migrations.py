"""Wave 4: the migration chain must work on a fresh DB and on the legacy shape.

Every test here runs against a throwaway SQLite file under tmp_path. The Wave 1
guards additionally ensure nothing can reach the development database.
"""
import os
import subprocess
import sys
import sqlite3

import pytest

from conftest import DEV_DB_PATH, is_dev_path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HEAD_REVISION = "0005_visitor_session_isolation"


def alembic(db_path, *args):
    """Run alembic against an explicit throwaway database."""
    url = "sqlite:///%s" % str(db_path).replace("\\", "/")
    assert not is_dev_path(str(db_path), DEV_DB_PATH), "refusing to migrate the dev DB"
    env = dict(os.environ)
    env["DATABASE_URL"] = url
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "-x", "db_url=%s" % url, *args],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    return proc


def cols(db_path, table):
    con = sqlite3.connect(str(db_path))
    try:
        return {r[1] for r in con.execute("pragma table_info([%s])" % table)}
    finally:
        con.close()


def tables(db_path):
    con = sqlite3.connect(str(db_path))
    try:
        return {r[0] for r in con.execute(
            "select name from sqlite_master where type='table'")}
    finally:
        con.close()


def indexes(db_path, table):
    con = sqlite3.connect(str(db_path))
    try:
        return {r[1] for r in con.execute("pragma index_list([%s])" % table)}
    finally:
        con.close()


def version(db_path):
    con = sqlite3.connect(str(db_path))
    try:
        return [r[0] for r in con.execute("select version_num from alembic_version")]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def legacy_schema(db_path):
    """Recreate the pre-migration shape: real tables, no tenant_id, no version."""
    con = sqlite3.connect(str(db_path))
    con.executescript("""
        CREATE TABLE chat_sessions (
            id VARCHAR NOT NULL PRIMARY KEY, user_id VARCHAR NOT NULL,
            title VARCHAR, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME, is_active BOOLEAN, metadata JSON);
        CREATE TABLE chat_messages (
            id VARCHAR NOT NULL PRIMARY KEY, session_id VARCHAR NOT NULL,
            user_id VARCHAR NOT NULL, message_type VARCHAR NOT NULL,
            content TEXT NOT NULL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            sources JSON, metadata JSON);
    """)
    con.commit()
    con.close()


def seed_session(db_path, sid, user_id, metadata='{"tenant_id": "default"}'):
    con = sqlite3.connect(str(db_path))
    con.execute("insert into chat_sessions (id, user_id, metadata) values (?,?,?)",
                (sid, user_id, metadata))
    con.commit()
    con.close()


def tenant_of(db_path, sid):
    con = sqlite3.connect(str(db_path))
    try:
        row = con.execute("select tenant_id from chat_sessions where id=?", (sid,)).fetchone()
        return row[0] if row else None
    finally:
        con.close()


# ---------------------------------------------------------------------------
# CASE B — completely fresh database
# ---------------------------------------------------------------------------

class TestFreshDatabase:
    def test_upgrade_head_succeeds(self, tmp_path):
        db = tmp_path / "fresh.db"
        p = alembic(db, "upgrade", "head")
        assert p.returncode == 0, "alembic failed:\n%s\n%s" % (p.stdout, p.stderr)

    def test_expected_tables_exist(self, tmp_path):
        db = tmp_path / "fresh.db"
        assert alembic(db, "upgrade", "head").returncode == 0
        assert {"users", "chat_sessions", "chat_messages", "documents",
                "session_facts", "system_metrics"} <= tables(db)

    def test_tenant_id_column_created(self, tmp_path):
        db = tmp_path / "fresh.db"
        assert alembic(db, "upgrade", "head").returncode == 0
        assert "tenant_id" in cols(db, "chat_sessions")

    def test_alembic_version_is_head(self, tmp_path):
        db = tmp_path / "fresh.db"
        assert alembic(db, "upgrade", "head").returncode == 0
        assert version(db) == [HEAD_REVISION]

    def test_schema_matches_the_sqlalchemy_models(self, tmp_path):
        """Drift guard: migrations and models must not diverge again."""
        db = tmp_path / "fresh.db"
        assert alembic(db, "upgrade", "head").returncode == 0
        from src.backend.database.database import Base

        for table_name, table in Base.metadata.tables.items():
            declared = {c.name for c in table.columns}
            actual = cols(db, table_name)
            missing = declared - actual
            assert not missing, "%s: migration is missing %s" % (table_name, missing)

    def test_tenant_user_index_matches_the_model(self, tmp_path):
        db = tmp_path / "fresh.db"
        assert alembic(db, "upgrade", "head").returncode == 0
        assert "idx_chat_sessions_tenant_user" in indexes(db, "chat_sessions")
        from src.backend.database.database import ChatSession
        assert "idx_chat_sessions_tenant_user" in {
            index.name for index in ChatSession.__table__.indexes
        }

    def test_visitor_session_column_and_index_match_the_model(self, tmp_path):
        db = tmp_path / "fresh.db"
        assert alembic(db, "upgrade", "head").returncode == 0
        assert "visitor_session_id" in cols(db, "chat_sessions")
        assert "idx_chat_sessions_tenant_user_visitor" in indexes(db, "chat_sessions")
        from src.backend.database.database import ChatSession
        assert "idx_chat_sessions_tenant_user_visitor" in {
            index.name for index in ChatSession.__table__.indexes
        }


# ---------------------------------------------------------------------------
# CASE A — existing database created by create_all(), no version stamp
# ---------------------------------------------------------------------------

class TestExistingDatabase:
    def test_stamp_then_upgrade_adds_tenant_id(self, tmp_path):
        db = tmp_path / "legacy.db"
        legacy_schema(db)
        assert "tenant_id" not in cols(db, "chat_sessions")

        assert alembic(db, "stamp", "0001_baseline_schema").returncode == 0
        p = alembic(db, "upgrade", "head")
        assert p.returncode == 0, p.stderr
        assert "tenant_id" in cols(db, "chat_sessions")
        assert version(db) == [HEAD_REVISION]

    def test_upgrade_without_stamp_is_also_safe(self, tmp_path):
        """0001 is idempotent, so a forgotten stamp must not corrupt anything."""
        db = tmp_path / "legacy.db"
        legacy_schema(db)
        seed_session(db, "s1", "employee@finsolve.com")
        p = alembic(db, "upgrade", "head")
        assert p.returncode == 0, p.stderr
        assert "tenant_id" in cols(db, "chat_sessions")
        assert tenant_of(db, "s1") == "tenant_acme"

    def test_existing_rows_are_preserved(self, tmp_path):
        db = tmp_path / "legacy.db"
        legacy_schema(db)
        for i in range(25):
            seed_session(db, "s%d" % i, "employee@finsolve.com")
        assert alembic(db, "upgrade", "head").returncode == 0
        con = sqlite3.connect(str(db))
        assert con.execute("select count(*) from chat_sessions").fetchone()[0] == 25
        con.close()


# ---------------------------------------------------------------------------
# Backfill correctness — the heart of this wave
# ---------------------------------------------------------------------------

class TestTenantBackfill:
    @pytest.fixture
    def migrated(self, tmp_path):
        db = tmp_path / "backfill.db"
        legacy_schema(db)
        seed_session(db, "acme-1", "employee@finsolve.com")
        seed_session(db, "acme-2", "finance.lead@finsolve.com")
        seed_session(db, "acme-3", "  TONY.SHARMA@finsolve.com  ")   # case/space
        seed_session(db, "beta-1", "beta.employee@finsolve.com")
        seed_session(db, "beta-2", "beta.admin@finsolve.com")
        seed_session(db, "unknown-1", "emp@test.com")                # pytest fixture user
        seed_session(db, "unknown-2", "dev_user")                    # BYPASS_AUTH synthetic
        seed_session(db, "unknown-3", "someone@nowhere.example")
        assert alembic(db, "upgrade", "head").returncode == 0
        return db

    def test_acme_sessions_backfilled(self, migrated):
        assert tenant_of(migrated, "acme-1") == "tenant_acme"
        assert tenant_of(migrated, "acme-2") == "tenant_acme"

    def test_backfill_normalises_case_and_whitespace(self, migrated):
        assert tenant_of(migrated, "acme-3") == "tenant_acme"

    def test_beta_sessions_backfilled(self, migrated):
        assert tenant_of(migrated, "beta-1") == "tenant_beta"
        assert tenant_of(migrated, "beta-2") == "tenant_beta"

    @pytest.mark.parametrize("sid", ["unknown-1", "unknown-2", "unknown-3"])
    def test_unknown_users_are_never_assigned_a_tenant(self, migrated, sid):
        """The critical rule: no blanket tenant_acme."""
        assert tenant_of(migrated, sid) is None

    def test_phantom_default_tenant_is_never_written(self, migrated):
        con = sqlite3.connect(str(migrated))
        try:
            n = con.execute(
                "select count(*) from chat_sessions where tenant_id = 'default'").fetchone()[0]
        finally:
            con.close()
        assert n == 0, "the superseded migration's metadata backfill reappeared"

    def test_metadata_blob_is_not_used_as_evidence(self, tmp_path):
        """A row whose metadata claims a tenant, but whose user is unknown."""
        db = tmp_path / "meta.db"
        legacy_schema(db)
        seed_session(db, "x1", "ghost@nowhere.example", '{"tenant_id": "tenant_acme"}')
        assert alembic(db, "upgrade", "head").returncode == 0
        assert tenant_of(db, "x1") is None, "metadata blob was trusted as ownership evidence"


# ---------------------------------------------------------------------------
# Idempotency and downgrade
# ---------------------------------------------------------------------------

class TestIdempotencyAndDowngrade:
    def test_running_upgrade_twice_is_a_noop(self, tmp_path):
        db = tmp_path / "twice.db"
        assert alembic(db, "upgrade", "head").returncode == 0
        p = alembic(db, "upgrade", "head")
        assert p.returncode == 0, p.stderr
        assert version(db) == [HEAD_REVISION]

    def test_reapplying_0002_over_existing_column_does_not_fail(self, tmp_path):
        """Simulates a partially applied run: column present, version behind."""
        db = tmp_path / "partial.db"
        legacy_schema(db)
        con = sqlite3.connect(str(db))
        con.execute("alter table chat_sessions add column tenant_id VARCHAR")
        con.commit()
        con.close()
        p = alembic(db, "upgrade", "head")
        assert p.returncode == 0, "duplicate-column disaster:\n%s" % p.stderr
        assert "tenant_id" in cols(db, "chat_sessions")

    def test_downgrade_one_removes_tenant_id(self, tmp_path):
        db = tmp_path / "down.db"
        assert alembic(db, "upgrade", "head").returncode == 0
        assert "tenant_id" in cols(db, "chat_sessions")
        p = alembic(db, "downgrade", "0001_baseline_schema")
        assert p.returncode == 0, p.stderr
        assert "tenant_id" not in cols(db, "chat_sessions")

    def test_downgrade_then_upgrade_round_trips(self, tmp_path):
        db = tmp_path / "round.db"
        assert alembic(db, "upgrade", "head").returncode == 0
        assert alembic(db, "downgrade", "0001_baseline_schema").returncode == 0
        p = alembic(db, "upgrade", "head")
        assert p.returncode == 0, p.stderr
        assert version(db) == [HEAD_REVISION]


class TestRevisionChain:
    def test_history_is_linear_and_reaches_head(self):
        p = subprocess.run([sys.executable, "-m", "alembic", "history"],
                           cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120)
        assert p.returncode == 0, p.stderr
        assert "0001_baseline_schema" in p.stdout
        assert HEAD_REVISION in p.stdout

    def test_legacy_migrations_are_not_in_the_active_chain(self):
        p = subprocess.run([sys.executable, "-m", "alembic", "history"],
                           cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120)
        assert "001_lifecycle" not in p.stdout
        assert "002_tenant_id" not in p.stdout


class TestDevDatabaseProtection:
    def test_pytest_never_targets_the_development_database(self):
        from src.backend.database.database import engine
        assert not is_dev_path(str(engine.url).replace("sqlite:///", ""), DEV_DB_PATH)
