"""
Enterprise RAG test suite with regression and scale tests
Tests both legacy (flags off) and new (flags on) behavior
"""
import pytest
import asyncio
import asyncpg
import uuid
import time
import os
import tempfile
from typing import List, Dict, Any
from datetime import datetime
import numpy as np

# Set test environment
os.environ["ENVIRONMENT"] = "test"
os.environ["VECTOR_SCHEMA_VERSION"] = "1"

from src.backend.services.rag_service import RAGService
from src.backend.services.vector_store import VectorStore
from src.backend.workers.vector_deletion_worker import VectorDeletionWorker, enqueue_deletion
from src.backend.utils.document_processor import DocumentChunk
from src.config.settings import settings  # the Settings instance, not the module
from src.config.roles import Role


class TestEnterpriseRAG:
    """Test suite for enterprise RAG features"""
    
    @pytest.fixture(autouse=True)
    def reset_flags(self):
        """Reset feature flags before each test"""
        # Save original values
        original_strict = settings.STRICT_MODE
        original_tenant = settings.TENANT_SCOPING_ON
        original_reconcile = settings.ENABLE_RECONCILIATION
        original_worker = settings.ENABLE_DELETION_WORKER
        original_block = settings.BLOCK_BACKUP_FOLDERS
        
        yield
        
        # Restore original values
        settings.STRICT_MODE = original_strict
        settings.TENANT_SCOPING_ON = original_tenant
        settings.ENABLE_RECONCILIATION = original_reconcile
        settings.ENABLE_DELETION_WORKER = original_worker
        settings.BLOCK_BACKUP_FOLDERS = original_block
    
    @pytest.fixture
    async def db_pool(self):
        """Database connection pool for tests"""
        DATABASE_URL = os.getenv("TEST_DATABASE_URL", 
                                 "postgresql://postgres:password@localhost:5432/test_finsolve")
        
        # The deletion worker / reconciler are PostgreSQL-only and disabled in the
        # SQLite launch architecture (ENABLE_DELETION_WORKER=false). Their tests
        # need a reachable PostgreSQL; without one they are reported as skipped
        # with this reason rather than as failures.
        try:
            pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=1,
                max_size=5
            )
        except (OSError, asyncpg.PostgresError) as exc:
            pytest.skip(f"PostgreSQL not reachable for deletion-worker tests ({type(exc).__name__})")

        # Ensure test tables exist
        async with pool.acquire() as conn:
            # Create minimal schema for testing
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    filename VARCHAR(255),
                    organization_id UUID,
                    file_path VARCHAR(500),
                    created_at TIMESTAMP DEFAULT NOW(),
                    -- Lifecycle fields (nullable for backwards compatibility)
                    is_active BOOLEAN DEFAULT true,
                    deleted_at TIMESTAMP,
                    deleted_by UUID,
                    version INTEGER DEFAULT 1,
                    checksum VARCHAR(64),
                    tenant_id UUID
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS vector_deletion_jobs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    doc_id UUID,
                    tenant_id UUID,
                    source_filename VARCHAR(255),
                    status VARCHAR(50) DEFAULT 'pending',
                    attempts INTEGER DEFAULT 0,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    processed_at TIMESTAMP,
                    metadata JSON
                )
            """)
        
        yield pool
        
        # Cleanup
        async with pool.acquire() as conn:
            await conn.execute("TRUNCATE documents, vector_deletion_jobs CASCADE")
        
        await pool.close()
    
    @pytest.fixture
    def vector_store(self, tmp_path):
        """Clean vector store for testing.

        Was `persist_directory="./test_embeddings"`, which wrote a Chroma store
        into the repository root. Now pinned to tmp_path, with the singleton
        reset so the temporary path actually takes effect.
        """
        from conftest import assert_not_dev_chroma
        from tests.conftest import reset_vector_store_singleton

        chroma_dir = tmp_path / "test_embeddings"
        chroma_dir.mkdir(parents=True, exist_ok=True)
        assert_not_dev_chroma(chroma_dir, "allocate the enterprise-rag store at")

        reset_vector_store_singleton()
        vs = VectorStore(collection_name="test_collection",
                         persist_directory=str(chroma_dir))

        # Clear any existing data
        try:
            vs.clear_collection()
        except Exception:
            pass

        yield vs

        # Cleanup
        try:
            vs.clear_collection()
        except Exception:
            pass
        reset_vector_store_singleton()
    
    # ========== REGRESSION TESTS (FLAGS OFF) ==========
    
    @pytest.mark.asyncio
    async def test_legacy_upload_search_delete_with_flags_off(self, vector_store):
        """Test that legacy path works unchanged with flags off"""
        # Ensure flags are off
        settings.STRICT_MODE = False
        settings.TENANT_SCOPING_ON = False
        settings.ENABLE_DELETION_WORKER = False
        
        # 1. Upload document (simulated)
        doc_id = str(uuid.uuid4())
        chunks = [
            DocumentChunk(
                content=f"Legacy test content chunk {i}",
                metadata={
                    "source": "legacy_test.txt",
                    "department": "general",
                    "chunk_id": i
                }
            ) for i in range(3)
        ]
        tenant_id = "tenant_legacy"
        
        # Add to vector store
        success = vector_store.add_documents(chunks, tenant_id=tenant_id)
        assert success, "Failed to add documents in legacy mode"
        
        # 2. Search for document
        results = vector_store.search_documents(
            query="legacy test content",
            user_role=Role.EMPLOYEE,
            limit=5,
            tenant_id=tenant_id,
        )
        
        assert len(results) > 0, "No results found in legacy search"
        assert any("legacy_test.txt" in r.get("source", r.get("metadata", {}).get("source", "")) 
                  for r in results), "Legacy document not found"
        
        # 3. Delete document (legacy synchronous deletion)
        deleted = vector_store.delete_documents_by_sources(["legacy_test.txt"], tenant_id=tenant_id)
        assert deleted > 0, "No documents deleted in legacy mode"
        
        # 4. Verify deletion
        results_after = vector_store.search_documents(
            query="legacy test content",
            user_role=Role.EMPLOYEE,
            limit=5,
            tenant_id=tenant_id,
        )
        
        assert not any("legacy_test.txt" in r.get("source", r.get("metadata", {}).get("source", "")) 
                      for r in results_after), "Document still found after legacy deletion"
    
    # ========== NEW FEATURE TESTS (FLAGS ON) ==========
    
    @pytest.mark.asyncio
    async def test_deletion_propagation_with_worker(self, db_pool, vector_store):
        """Test that deletion removes all chunks when worker is enabled"""
        # Enable new features
        settings.STRICT_MODE = True
        settings.ENABLE_DELETION_WORKER = True
        
        # Add test document
        doc_id = str(uuid.uuid4())
        chunks = [
            DocumentChunk(
                content=f"Test chunk {i} for deletion",
                metadata={
                    "doc_id": doc_id,
                    "source": "test_delete.txt",
                    "tenant_id": "test_tenant",
                    "is_active": True,
                    "deleted_at": None,
                    "version": 1
                }
            ) for i in range(5)
        ]
        
        vector_store.add_documents(chunks)
        
        # Verify chunks exist
        initial_results = vector_store.collection.get(
            where={"doc_id": {"$eq": doc_id}},
            limit=10
        )
        assert len(initial_results["documents"]) == 5, "Not all chunks were added"
        
        # Process deletion via worker
        worker = VectorDeletionWorker(db_pool, redis_client=None)
        await worker.initialize()
        
        result = await worker.delete_from_vector_store(
            doc_id, "test_delete.txt", "test_tenant"
        )
        
        assert result["success"], f"Deletion failed: {result.get('error')}"
        assert result["chunks_deleted"] == 5, f"Expected 5 chunks deleted, got {result['chunks_deleted']}"
        
        # Verify all chunks removed
        final_results = vector_store.collection.get(
            where={"doc_id": {"$eq": doc_id}},
            limit=10
        )
        assert len(final_results["documents"]) == 0, "Chunks still exist after deletion"
    
    @pytest.mark.asyncio
    async def test_backup_folder_blocking(self, tmp_path, tmp_path_factory):
        """Test that backup folders are blocked when flag is on.

        Paths are now under tmp_path; previously these wrote Chroma stores into
        the development ./data/ directory alongside finsolve.db.
        """
        from tests.conftest import reset_vector_store_singleton

        settings.BLOCK_BACKUP_FOLDERS = True

        # Test 1: Reject backup in path
        reset_vector_store_singleton()
        with pytest.raises(ValueError, match="Backup folder detected"):
            VectorStore(persist_directory=str(tmp_path / "chroma_db_BACKUP_123"))

        # Test 2: Reject backup in collection name
        reset_vector_store_singleton()
        with pytest.raises(ValueError, match="Backup folder detected"):
            VectorStore(persist_directory=str(tmp_path / "backup_folder" / "chroma"))

        # Test 3: Accept normal paths
        reset_vector_store_singleton()
        try:
            # tmp_path is named after this test and so itself contains "backup";
            # the control case needs a directory whose name does not.
            vs = VectorStore(persist_directory=str(tmp_path_factory.mktemp("store") / "normal_chroma"))
            # Should not raise
        except ValueError as e:
            if "Backup" in str(e):
                pytest.fail(f"Normal path rejected: {e}")
        finally:
            reset_vector_store_singleton()
    
    @pytest.mark.asyncio
    async def test_tenant_isolation_with_strict_mode(self, vector_store):
        """Test that tenants cannot see each other's data"""
        settings.STRICT_MODE = True
        settings.TENANT_SCOPING_ON = True
        
        # Add documents for different tenants
        for tenant_id in ["tenant_a", "tenant_b", "tenant_c"]:
            chunks = [
                DocumentChunk(
                    content=f"Confidential data for {tenant_id}: financial records",
                    metadata={
                        "doc_id": str(uuid.uuid4()),
                        "source": f"{tenant_id}_data.txt",
                        "tenant_id": tenant_id,
                        "department": "finance",
                        "chunk_id": 0,
                    }
                )
            ]
            assert vector_store.add_documents(chunks, tenant_id=tenant_id)
        
        # Query as tenant_a with strict filters
        results = vector_store.collection.query(
            query_texts=["financial records"],
            where={"tenant_id": {"$eq": "tenant_a"}},
            n_results=10
        )
        assert results.get("metadatas", [[]])[0], "tenant_a's own document was not returned"
        
        # Verify only tenant_a data returned
        for metadata in results.get("metadatas", [[]])[0]:
            assert metadata["tenant_id"] == "tenant_a", f"Got wrong tenant: {metadata['tenant_id']}"
        
        # Verify no cross-tenant leakage
        all_docs = results.get("documents", [[]])[0]
        for doc in all_docs:
            assert "tenant_b" not in doc, "tenant_b data leaked"
            assert "tenant_c" not in doc, "tenant_c data leaked"
    
    @pytest.mark.asyncio
    async def test_strict_retrieval_fails_closed(self, vector_store):
        """Test that strict mode returns no results rather than wrong results"""
        settings.STRICT_MODE = True
        settings.TENANT_SCOPING_ON = True
        
        # Index a document, then delete it the way the admin delete path does
        # (verified hard delete; lifecycle flags are not stored on vectors).
        chunks = [
            DocumentChunk(
                content="This document is deleted",
                metadata={
                    "doc_id": "deleted_doc",
                    "source": "deleted.txt",
                    "tenant_id": "test",
                    "department": "general",
                    "chunk_id": 0,
                }
            )
        ]
        assert vector_store.add_documents(chunks, tenant_id="test")
        vector_store.delete_documents_by_sources(["deleted.txt"], tenant_id="test", raise_on_error=True)

        # Query with strict filters
        results = vector_store.search_documents(
            query="deleted document",
            user_role=Role.EMPLOYEE,
            limit=5,
            tenant_id="test"
        )
        
        # Should return empty, not the deleted document
        assert len(results) == 0, "Strict mode returned deleted documents"
    
    @pytest.mark.asyncio
    async def test_idempotent_deletion_jobs(self, db_pool):
        """Test that deletion jobs are idempotent"""
        settings.ENABLE_DELETION_WORKER = True
        
        doc_id = str(uuid.uuid4())
        
        # Enqueue same deletion multiple times
        job_id1 = await enqueue_deletion(db_pool, doc_id, "test.txt", "tenant1")
        job_id2 = await enqueue_deletion(db_pool, doc_id, "test.txt", "tenant1")
        job_id3 = await enqueue_deletion(db_pool, doc_id, "test.txt", "tenant1")
        
        # Should return same job ID (idempotent)
        assert job_id1 == job_id2 == job_id3, "Deletion jobs not idempotent"
        
        # Verify only one job in database
        async with db_pool.acquire() as conn:
            count = await conn.fetchval("""
                SELECT COUNT(*) FROM vector_deletion_jobs
                WHERE doc_id = $1
            """, doc_id)
            
            assert count == 1, f"Expected 1 job, found {count}"
    
    # ========== SCALE TESTS ==========
    
    @pytest.fixture
    async def scale_fixture_10k(self, vector_store) -> List[DocumentChunk]:
        """Generate 10k document fixture for scale testing"""
        print("\n📊 Generating 10k document fixture...")
        chunks = []
        
        # Generate diverse content
        departments = ["finance", "hr", "engineering", "marketing", "general"]
        doc_types = ["report", "policy", "guide", "memo", "presentation"]
        
        for doc_idx in range(10000):
            tenant_id = f"tenant_{doc_idx % 10}"
            department = departments[doc_idx % len(departments)]
            doc_type = doc_types[doc_idx % len(doc_types)]
            
            # Create realistic content (~50 tokens)
            content = f"""
            Document {doc_idx}: {doc_type.title()} for {department} department.
            This is a {doc_type} containing important information about our operations.
            Key topics covered include compliance, procedures, and best practices.
            Reference ID: DOC-{doc_idx:05d}. Last updated: 2024-01-15.
            """
            
            chunk = DocumentChunk(
                content=content,
                metadata={
                    "doc_id": str(uuid.uuid4()),
                    "source": f"{doc_type}_{doc_idx}.txt",
                    "tenant_id": tenant_id,
                    "department": department,
                    "doc_type": doc_type,
                    "chunk_id": 0,
                }
            )
            chunks.append(chunk)
        
        # Batch add to vector store
        print("💾 Adding chunks to vector store in batches...")
        batch_size = 500
        start_time = time.time()
        
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i+batch_size]
            assert vector_store.add_documents(batch)
            if (i + batch_size) % 2000 == 0:
                print(f"   Progress: {i + batch_size}/10000 chunks")
        
        elapsed = time.time() - start_time
        print(f"✅ Created {len(chunks)} chunks in {elapsed:.2f}s")
        
        return chunks
    
    @pytest.mark.benchmark
    @pytest.mark.asyncio
    async def test_scale_p95_latency(self, scale_fixture_10k, vector_store):
        """Test P95 retrieval latency < 2s on 10k documents"""
        settings.STRICT_MODE = True
        settings.TENANT_SCOPING_ON = True
        
        # Test queries
        test_queries = [
            "financial compliance report",
            "employee benefits policy",
            "engineering best practices",
            "marketing campaign guide",
            "operational procedures memo",
            "quarterly financial analysis",
            "HR onboarding documentation",
            "technical architecture review",
            "sales performance metrics",
            "executive summary presentation"
        ] * 10  # 100 total queries
        
        latencies = []
        
        print("\n⏱️  Running latency benchmark...")
        
        for i, query in enumerate(test_queries):
            tenant_id = f"tenant_{i % 10}"
            
            start = time.perf_counter()
            
            # Perform retrieval with strict filters
            results = vector_store.collection.query(
                query_texts=[query],
                where={"tenant_id": {"$eq": tenant_id}},
                n_results=5
            )

            latency = time.perf_counter() - start
            latencies.append(latency)
            
            if (i + 1) % 20 == 0:
                print(f"   Completed {i + 1}/100 queries")
        
        # Calculate statistics
        p50 = np.percentile(latencies, 50)
        p95 = np.percentile(latencies, 95)
        p99 = np.percentile(latencies, 99)
        avg = np.mean(latencies)
        
        print(f"\n📊 Latency Results (10k docs):")
        print(f"   Average: {avg:.3f}s")
        print(f"   P50: {p50:.3f}s")
        print(f"   P95: {p95:.3f}s")
        print(f"   P99: {p99:.3f}s")
        print(f"   Max: {max(latencies):.3f}s")
        
        # Assert P95 < 2s
        assert p95 < 2.0, f"P95 latency {p95:.3f}s exceeds 2s threshold"
    
    @pytest.mark.benchmark
    @pytest.mark.asyncio
    async def test_citation_precision_at_5(self, vector_store):
        """Test citation precision@5 >= 0.8"""
        # Create known relevant documents
        relevant_docs = []
        for i in range(10):
            doc = DocumentChunk(
                content=f"Python programming best practices: Use type hints, write tests, follow PEP8. Document {i}",
                metadata={
                    "doc_id": f"relevant_{i}",
                    "source": f"python_guide_{i}.txt",
                    "tenant_id": "test",
                    "department": "general",
                    "chunk_id": 0,
                }
            )
            relevant_docs.append(doc)
        
        # Create noise documents
        noise_docs = []
        for i in range(50):
            doc = DocumentChunk(
                content=f"Unrelated content about {['cooking', 'sports', 'music', 'travel'][i % 4]}. Document {i}",
                metadata={
                    "doc_id": f"noise_{i}",
                    "source": f"noise_{i}.txt",
                    "tenant_id": "test",
                    "department": "general",
                    "chunk_id": 0,
                }
            )
            noise_docs.append(doc)
        
        # Add all documents
        assert vector_store.add_documents(relevant_docs + noise_docs, tenant_id="test")
        
        # Test queries
        test_queries = [
            "Python programming best practices",
            "Python type hints and testing",
            "PEP8 coding standards",
            "Python development guidelines",
            "Python code quality"
        ]
        
        precisions = []
        
        for query in test_queries:
            # Get top 5 results
            results = vector_store.collection.query(
                query_texts=[query],
                where={"tenant_id": {"$eq": "test"}},
                n_results=5
            )
            
            # Count relevant results in top 5
            relevant_count = 0
            for metadata in results.get("metadatas", [[]])[0]:
                if metadata.get("source", "").startswith("python_guide_"):
                    relevant_count += 1
            
            precision = relevant_count / 5.0
            precisions.append(precision)
        
        avg_precision = np.mean(precisions)
        
        print(f"\n📊 Citation Precision@5: {avg_precision:.2f}")
        print(f"   Individual: {precisions}")
        
        # Assert precision >= 0.8
        assert avg_precision >= 0.8, f"Precision@5 {avg_precision:.2f} below 0.8 threshold"
    
    # ========== RECONCILIATION TESTS ==========
    
    @pytest.mark.asyncio
    async def test_reconciliation_fixes_drift(self, db_pool, vector_store):
        """Test that reconciliation identifies and fixes drift"""
        settings.ENABLE_RECONCILIATION = True
        settings.STRICT_MODE = True
        
        from scripts.reconcile_vectors import EnterpriseReconciler
        
        # Create drift scenario
        
        # 1. Add orphaned vectors (in vector store but not DB)
        orphan_chunks = [
            DocumentChunk(
                content="Orphaned content that should be removed",
                metadata={
                    "doc_id": "orphan_1",
                    "source": "orphan.txt",
                    "tenant_id": "test",
                    "is_active": True,
                    "deleted_at": None
                }
            )
        ]
        vector_store.add_documents(orphan_chunks)
        
        # 2. Add document to DB without vector (missing)
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO documents (id, filename, is_active, tenant_id)
                VALUES ($1, $2, true, $3)
            """, uuid.uuid4(), "missing.txt", uuid.uuid4())
        
        # Run reconciliation (dry run first)
        DATABASE_URL = os.getenv("TEST_DATABASE_URL", 
                                "postgresql://postgres:password@localhost:5432/test_finsolve")
        
        reconciler = EnterpriseReconciler(DATABASE_URL, dry_run=True)
        dry_stats = await reconciler.run()
        
        # Verify drift detected
        assert len(dry_stats["orphaned"]) > 0, "Orphaned documents not detected"
        assert len(dry_stats["missing"]) > 0, "Missing documents not detected"
        
        # Run actual reconciliation
        reconciler = EnterpriseReconciler(DATABASE_URL, dry_run=False)
        stats = await reconciler.run()
        
        # Verify drift fixed
        assert stats["completed"], f"Reconciliation failed: {stats.get('error')}"
        assert stats["final_drift"] == 0, f"Drift not fixed: {stats['final_drift']} remaining"
        
        # Verify orphaned vector removed
        results = vector_store.collection.get(
            where={"source": {"$eq": "orphan.txt"}},
            limit=10
        )
        assert len(results["documents"]) == 0, "Orphaned vector not removed"


# Run tests with pytest
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
