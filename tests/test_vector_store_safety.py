"""Wave 2: VectorStore must never destroy data as an error-recovery strategy.

Historically `VectorStore.__init__` did:

    try:    get_collection(...)
    except (ValueError, Exception):
        delete_collection(...)      # <-- destroyed the corpus on ANY error
        create_collection(...)

which meant a transient lock, permission fault, schema drift or corruption
symptom silently wiped the whole collection. These tests pin the corrected
behaviour. Everything runs against the Wave 1 sandbox, never development Chroma.
"""
import os
import sqlite3
import uuid
from unittest.mock import patch

import pytest

from conftest import DEV_CHROMA_PATH, DevDataProtectionError, is_dev_path
from src.backend.services.vector_store import (
    VectorStore,
    VectorStoreUnavailableError,
    _is_missing_collection_error,
    resolve_persist_directory,
)
from tests.conftest import reset_vector_store_singleton


def _new_store(tmp_path, name=None, subdir="chroma_db"):
    """Construct a VectorStore pinned to tmp_path with a fresh singleton."""
    path = tmp_path / subdir
    path.mkdir(parents=True, exist_ok=True)
    reset_vector_store_singleton()
    return VectorStore(
        collection_name=name or "test_%s" % uuid.uuid4().hex[:10],
        persist_directory=str(path),
    )


class TestMissingCollectionClassifier:
    """Only a genuine 'no such collection' may lead to creation."""

    def test_value_error_does_not_exist_is_missing(self):
        assert _is_missing_collection_error(ValueError("Collection x does not exist."))

    def test_value_error_not_found_is_missing(self):
        assert _is_missing_collection_error(ValueError("Collection x not found"))

    @pytest.mark.parametrize("exc", [
        ValueError("database disk image is malformed"),
        sqlite3.DatabaseError("database disk image is malformed"),
        sqlite3.OperationalError("database is locked"),
        PermissionError("access denied"),
        RuntimeError("schema version mismatch"),
        OSError("stale NFS file handle"),
    ])
    def test_other_errors_are_not_missing(self, exc):
        """Transient / corruption / schema faults must NOT look like 'absent'."""
        assert not _is_missing_collection_error(exc)


class TestCollectionLifecycle:
    def test_case_a_missing_collection_is_created(self, tmp_path):
        """Case A: collection does not exist -> created normally."""
        name = "created_%s" % uuid.uuid4().hex[:8]
        store = _new_store(tmp_path, name=name)
        try:
            assert store.collection is not None
            assert store.collection_name == name
            assert store.collection.count() == 0
        finally:
            reset_vector_store_singleton()

    def test_case_b_existing_collection_is_reused(self, tmp_path):
        """Case B: collection exists -> reused, contents preserved."""
        name = "reuse_%s" % uuid.uuid4().hex[:8]
        path = tmp_path / "chroma_db"

        store = _new_store(tmp_path, name=name)
        store.collection.add(
            ids=["a1"], documents=["hello world"],
            metadatas=[{"tenant_id": "tenant_acme", "source": "s.md"}],
            embeddings=[[0.1] * 384],
        )
        assert store.collection.count() == 1
        reset_vector_store_singleton()

        reopened = VectorStore(collection_name=name, persist_directory=str(path))
        try:
            assert reopened.collection.count() == 1, "existing data was not preserved"
        finally:
            reset_vector_store_singleton()


class TestNonDestructiveErrorHandling:
    """The core regression: unexpected errors must not delete anything."""

    def test_unexpected_get_collection_error_never_calls_delete(self, tmp_path):
        """Case C: transient/unexpected exception -> no delete_collection call."""
        name = "nodelete_%s" % uuid.uuid4().hex[:8]
        path = tmp_path / "chroma_db"
        _new_store(tmp_path, name=name)  # materialise the collection first
        reset_vector_store_singleton()

        import chromadb
        real_client_factory = chromadb.PersistentClient

        deleted = []

        class Sabotaged:
            """Client whose get_collection fails in a non-'missing' way."""
            def __init__(self, inner):
                self._inner = inner

            def get_collection(self, *a, **kw):
                raise sqlite3.OperationalError("database is locked")

            def delete_collection(self, *a, **kw):
                deleted.append(kw.get("name") or (a[0] if a else None))
                return self._inner.delete_collection(*a, **kw)

            def create_collection(self, *a, **kw):
                return self._inner.create_collection(*a, **kw)

        def factory(*a, **kw):
            return Sabotaged(real_client_factory(*a, **kw))

        with patch("chromadb.PersistentClient", side_effect=factory):
            with pytest.raises(VectorStoreUnavailableError) as excinfo:
                VectorStore(collection_name=name, persist_directory=str(path))

        reset_vector_store_singleton()

        assert deleted == [], (
            "delete_collection was called during error recovery: %r" % deleted
        )
        msg = str(excinfo.value)
        assert "NOT deleted" in msg
        assert "database is locked" in msg

    def test_transient_failure_leaves_persistence_files_intact(self, tmp_path):
        """Case D/E: after a failed open, the on-disk store is untouched."""
        name = "intact_%s" % uuid.uuid4().hex[:8]
        path = tmp_path / "chroma_db"

        store = _new_store(tmp_path, name=name)
        store.collection.add(
            ids=["keep1", "keep2"],
            documents=["alpha", "beta"],
            metadatas=[{"tenant_id": "tenant_acme"}, {"tenant_id": "tenant_acme"}],
            embeddings=[[0.2] * 384, [0.3] * 384],
        )
        assert store.collection.count() == 2
        reset_vector_store_singleton()

        before = sorted(
            (os.path.relpath(os.path.join(dp, f), str(path)), os.path.getsize(os.path.join(dp, f)))
            for dp, _, fs in os.walk(str(path)) for f in fs
        )

        import chromadb
        real_client_factory = chromadb.PersistentClient

        class Sabotaged:
            def __init__(self, inner):
                self._inner = inner

            def get_collection(self, *a, **kw):
                raise RuntimeError("unexpected chroma schema version")

            def delete_collection(self, *a, **kw):
                raise AssertionError("delete_collection must never be called here")

            def create_collection(self, *a, **kw):
                raise AssertionError("create_collection must never be called here")

        with patch("chromadb.PersistentClient", side_effect=lambda *a, **kw: Sabotaged(real_client_factory(*a, **kw))):
            with pytest.raises(VectorStoreUnavailableError):
                VectorStore(collection_name=name, persist_directory=str(path))

        reset_vector_store_singleton()

        after = sorted(
            (os.path.relpath(os.path.join(dp, f), str(path)), os.path.getsize(os.path.join(dp, f)))
            for dp, _, fs in os.walk(str(path)) for f in fs
        )
        assert after == before, "persistence files changed after a failed open"

        # And the data is still readable.
        reopened = VectorStore(collection_name=name, persist_directory=str(path))
        try:
            assert reopened.collection.count() == 2
        finally:
            reset_vector_store_singleton()

    def test_client_open_failure_raises_unavailable_not_generic(self, tmp_path):
        with patch("chromadb.PersistentClient", side_effect=PermissionError("denied")):
            reset_vector_store_singleton()
            with pytest.raises(VectorStoreUnavailableError) as excinfo:
                VectorStore(collection_name="x", persist_directory=str(tmp_path / "c"))
            reset_vector_store_singleton()
        assert "No data was modified" in str(excinfo.value)


class TestExplicitDestructionStillWorks:
    def test_clear_collection_works_on_isolated_store(self, tmp_path):
        """Deliberate operator action must still function."""
        store = _new_store(tmp_path)
        store.collection.add(
            ids=["z1"], documents=["gone soon"],
            metadatas=[{"tenant_id": "tenant_acme"}], embeddings=[[0.4] * 384],
        )
        assert store.collection.count() == 1
        try:
            store.clear_collection()
            assert store.collection.count() == 0
        finally:
            reset_vector_store_singleton()

    def test_guard_still_blocks_dev_path(self):
        """Wave 1 fail-closed guard must remain armed."""
        reset_vector_store_singleton()
        try:
            with pytest.raises(DevDataProtectionError):
                VectorStore(collection_name="company_docs",
                            persist_directory=DEV_CHROMA_PATH)
        finally:
            reset_vector_store_singleton()
        assert not is_dev_path(resolve_persist_directory(), DEV_CHROMA_PATH)
