"""Regression tests for the chat-welcome knowledge statistics.

Root cause of "Documents: 0": the tenant-scoped branch of
VectorStore.get_collection_stats never defined ``sample_size``, so the return
statement raised NameError and the broad ``except`` reported zero documents.

No embedding model or Chroma data is loaded: the vector store is faked.
"""
import pytest

from src.backend.api import knowledge
from src.backend.services import vector_store as vector_store_module
from src.backend.services.vector_store import VectorStore

TENANT = "tenant_demo"

METADATAS = [
    {"tenant_id": TENANT, "department": "general", "source": "handbook.md"},
    {"tenant_id": TENANT, "department": "general", "source": "handbook.md"},
    {"tenant_id": TENANT, "department": "finance", "source": "summary.md"},
    {"tenant_id": TENANT, "department": "hr", "source": "people.csv"},
]


class _FakeCollection:
    def get(self, where=None, include=None, limit=None):
        rows = [m for m in METADATAS if not where or m.get("tenant_id") == where["tenant_id"]]
        return {"metadatas": rows}

    def count(self):
        return len(METADATAS)


class _FakeStore:
    collection = _FakeCollection()


def test_tenant_scoped_collection_stats_does_not_raise():
    store = object.__new__(VectorStore)  # NOT the singleton: never mutate shared state
    store.collection = _FakeCollection()
    store.get_performance_stats = lambda: {}

    stats = store.get_collection_stats(tenant_id=TENANT)

    assert "error" not in stats
    assert stats["total_documents"] == len(METADATAS)
    assert stats["sample_size"] == len(METADATAS)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role, expected_total, expected_departments",
    [
        ("employee", 1, {"general": 1}),
        ("finance", 2, {"general": 1, "finance": 1}),
        ("hr", 2, {"general": 1, "hr": 1}),
        ("admin", 3, {"general": 1, "finance": 1, "hr": 1}),
    ],
)
async def test_knowledge_stats_are_role_scoped_distinct_documents(
    monkeypatch, role, expected_total, expected_departments
):
    monkeypatch.setattr(vector_store_module, "VectorStore", _FakeStore)

    stats = await knowledge.get_knowledge_stats(
        current_user={"role": role, "tenant_id": TENANT}
    )

    assert stats["total_documents"] == expected_total
    assert stats["departments"] == expected_departments
    assert stats["user_role"] == role
    assert stats["tenant_id"] == TENANT


@pytest.mark.asyncio
async def test_knowledge_stats_never_count_other_tenants(monkeypatch):
    monkeypatch.setattr(vector_store_module, "VectorStore", _FakeStore)

    stats = await knowledge.get_knowledge_stats(
        current_user={"role": "admin", "tenant_id": "some_other_tenant"}
    )

    assert stats["total_documents"] == 0
