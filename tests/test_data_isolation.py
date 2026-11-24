"""Wave 1 guard rail: prove pytest cannot reach FinSyntra development data.

These tests are the executable contract for the isolation described in the root
conftest.py. If any of them fail, STOP — the suite is unsafe to run.
"""
import os

import pytest

from conftest import (
    DEV_CHROMA_PATH,
    DEV_DB_PATH,
    DEV_RAW_PATH,
    TEST_SANDBOX,
    DevDataProtectionError,
    assert_not_dev_chroma,
    assert_not_dev_db,
    assert_not_dev_raw,
    is_dev_path,
)


class TestConfiguredPathsAreTemporary:
    """The resolved runtime configuration must point into the sandbox."""

    def test_database_url_is_not_development_db(self):
        from src.config.settings import settings
        assert settings.database_url, "DATABASE_URL must be set for tests"
        assert not is_dev_path(
            settings.database_url.replace("sqlite:///", ""), DEV_DB_PATH
        ), "tests are configured against the DEVELOPMENT database"
        assert TEST_SANDBOX.replace("\\", "/") in settings.database_url.replace("\\", "/")

    def test_sqlalchemy_engine_is_bound_to_temp_db(self):
        from src.backend.database.database import engine
        url = str(engine.url)
        assert not is_dev_path(url.replace("sqlite:///", ""), DEV_DB_PATH)
        assert "test_finsolve.db" in url

    def test_chroma_path_is_not_development_store(self):
        from src.backend.services.vector_store import resolve_persist_directory
        resolved = resolve_persist_directory()
        assert not is_dev_path(resolved, DEV_CHROMA_PATH)
        assert is_dev_path(resolved, TEST_SANDBOX)

    def test_collection_name_is_not_the_development_collection(self):
        from src.config.settings import settings
        assert settings.vector_collection_name != "company_docs"
        assert settings.vector_collection_name.startswith("test_docs_")

    def test_raw_documents_path_is_not_development_directory(self):
        from src.config.settings import get_raw_documents_path
        resolved = get_raw_documents_path()
        assert not is_dev_path(resolved, DEV_RAW_PATH)
        assert is_dev_path(resolved, TEST_SANDBOX)


class TestFailClosedGuards:
    """The guards must refuse development paths, not just warn about them."""

    def test_guard_rejects_dev_chroma_directory(self):
        with pytest.raises(DevDataProtectionError):
            assert_not_dev_chroma(DEV_CHROMA_PATH)

    def test_guard_rejects_path_inside_dev_chroma(self):
        with pytest.raises(DevDataProtectionError):
            assert_not_dev_chroma(os.path.join(DEV_CHROMA_PATH, "nested", "seg"))

    def test_guard_rejects_dev_database(self):
        with pytest.raises(DevDataProtectionError):
            assert_not_dev_db(DEV_DB_PATH)

    def test_guard_rejects_dev_database_url_form(self):
        with pytest.raises(DevDataProtectionError):
            assert_not_dev_db("sqlite:///" + DEV_DB_PATH.replace("\\", "/"))

    def test_guard_rejects_dev_raw_directory(self):
        with pytest.raises(DevDataProtectionError):
            assert_not_dev_raw(os.path.join(DEV_RAW_PATH, "anything.md"))

    def test_guard_allows_sandbox_paths(self):
        assert_not_dev_chroma(os.path.join(TEST_SANDBOX, "chroma_db"))
        assert_not_dev_db(os.path.join(TEST_SANDBOX, "test_finsolve.db"))
        assert_not_dev_raw(os.path.join(TEST_SANDBOX, "raw_docs"))

    def test_vector_store_construction_against_dev_path_is_blocked(self):
        """The wrapped VectorStore.__init__ must reject the dev directory."""
        from src.backend.services.vector_store import VectorStore
        from tests.conftest import reset_vector_store_singleton

        reset_vector_store_singleton()
        try:
            with pytest.raises(DevDataProtectionError):
                VectorStore(collection_name="company_docs",
                            persist_directory=DEV_CHROMA_PATH)
        finally:
            reset_vector_store_singleton()


class TestIsolatedFixtures:
    """The provided fixtures must hand back genuinely temporary resources."""

    def test_isolated_vector_store_is_temporary(self, isolated_vector_store):
        store = isolated_vector_store
        assert not is_dev_path(store.persist_directory, DEV_CHROMA_PATH)
        assert store.collection_name.startswith("test_")

    def test_clear_collection_is_safe_on_isolated_store(self, isolated_vector_store):
        """This is the exact call that destroyed the dev collection."""
        isolated_vector_store.clear_collection()
        assert not is_dev_path(isolated_vector_store.persist_directory, DEV_CHROMA_PATH)

    def test_isolated_raw_docs_is_temporary(self, isolated_raw_docs):
        assert not is_dev_path(isolated_raw_docs, DEV_RAW_PATH)
        (isolated_raw_docs / "sample.md").write_text("# test", encoding="utf-8")
        assert (isolated_raw_docs / "sample.md").exists()


class TestDevelopmentDataUntouched:
    """Writing through the app must land in the sandbox, never in dev data."""

    def test_db_writes_go_to_temp_database(self):
        from src.backend.database.database import create_tables, db_manager, ChatSession
        create_tables()
        db_manager.create_chat_session(
            user_id="isolation-probe@test.local",
            session_id="isolation-probe-session",
            metadata={"tenant_id": "tenant_probe"},
        )
        db = db_manager.get_db()
        try:
            row = db.query(ChatSession).filter(
                ChatSession.id == "isolation-probe-session").first()
            assert row is not None, "write did not land in the temp DB"
        finally:
            db_manager.close_db(db)

        # And the development DB must not contain it.
        import sqlite3
        if os.path.exists(DEV_DB_PATH):
            con = sqlite3.connect("file:%s?mode=ro" % DEV_DB_PATH.replace("\\", "/"),
                                  uri=True)
            try:
                n = con.execute(
                    "select count(*) from chat_sessions where id=?",
                    ("isolation-probe-session",)).fetchone()[0]
                assert n == 0, "test data leaked into the DEVELOPMENT database"
            finally:
                con.close()

    @pytest.mark.asyncio
    async def test_api_upload_lands_in_sandbox_not_dev_raw(self):
        """Uploading through the real API must not write into src/data/raw.

        Prior test runs left artefacts such as `test_20260203_200413.txt` and
        `scriptalert1script_20260203_200309.txt` in the development document
        directory. This asserts that can no longer happen.
        """
        from httpx import AsyncClient, ASGITransport
        from src.backend.api.endpoints import app
        from src.config.settings import get_raw_documents_path
        from src.backend.auth.authentication import create_access_token
        from src.backend.database.database import create_tables

        create_tables()
        admin_token = create_access_token({
            "sub": "admin@finsolve.com", "type": "access"
        })

        sandbox_raw = get_raw_documents_path()
        assert not is_dev_path(sandbox_raw, DEV_RAW_PATH)

        dev_before = (sorted(os.listdir(DEV_RAW_PATH))
                      if os.path.isdir(DEV_RAW_PATH) else [])

        marker = "isolation_probe_upload"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/documents/upload",
                files={"file": ("%s.md" % marker,
                                b"# Isolation probe\n\nThis valid markdown document contains enough sandbox-only content to produce an indexable chunk safely.\n",
                                "text/markdown")},
                data={"department": "general", "force_refresh": "false"},
                headers={"Authorization": "Bearer %s" % admin_token},
            )

        dev_after = (sorted(os.listdir(DEV_RAW_PATH))
                     if os.path.isdir(DEV_RAW_PATH) else [])
        assert dev_after == dev_before, (
            "upload leaked into the DEVELOPMENT document directory: %s"
            % sorted(set(dev_after) - set(dev_before))
        )
        assert not any(marker in n for n in dev_after)

        landed = [n for n in os.listdir(sandbox_raw) if marker in n]
        assert landed, (
            "upload did not land in the sandbox document directory %s" % sandbox_raw
        )
