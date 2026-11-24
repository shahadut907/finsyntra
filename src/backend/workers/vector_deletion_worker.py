"""Async worker for vector store deletion with retry logic and metrics"""
import asyncio
import asyncpg
import logging
import os
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import redis
from prometheus_client import Counter, Histogram, Gauge

from src.backend.services.vector_store import VectorStore
from src.config.settings import settings

logger = logging.getLogger(__name__)

# Prometheus Metrics
deletion_jobs_processed = Counter('vector_deletion_jobs_processed', 'Total deletion jobs processed')
deletion_jobs_failed = Counter('vector_deletion_jobs_failed', 'Total deletion jobs failed')
deletion_jobs_retried = Counter('vector_deletion_jobs_retried', 'Total deletion jobs retried')
deletion_latency = Histogram('vector_deletion_latency_seconds', 'Deletion job latency')
pending_jobs_gauge = Gauge('vector_deletion_pending_jobs', 'Number of pending deletion jobs')
deletion_chunks_removed = Counter('vector_deletion_chunks_removed', 'Total chunks removed from vector store')

class VectorDeletionWorker:
    """Idempotent deletion worker with retry logic"""
    
    def __init__(self, db_pool: asyncpg.Pool, redis_client: Optional[redis.Redis] = None):
        self.db_pool = db_pool
        self.redis_client = redis_client
        self.vector_store = None
        self.running = False
        self.max_retries = 3
        self.retry_delay = 5  # seconds
        
    async def initialize(self):
        """Initialize vector store connection"""
        if not settings.ENABLE_DELETION_WORKER:
            logger.info("Deletion worker disabled by feature flag")
            return False
            
        try:
            self.vector_store = VectorStore()
            logger.info("[+] Vector store initialized for deletion worker")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize vector store: {e}")
            return False
    
    async def delete_from_vector_store(self, doc_id: str, source: str, tenant_id: Optional[str]) -> Dict[str, Any]:
        """Delete with idempotency check"""
        result = {
            "success": False,
            "chunks_deleted": 0,
            "error": None,
            "idempotent": False
        }
        
        try:
            # Check if already deleted (idempotency)
            existing_check = self.vector_store.collection.get(
                where={"doc_id": {"$eq": doc_id}},
                limit=1
            )
            
            if not existing_check["documents"]:
                logger.info(f"Document {doc_id} already deleted (idempotent)")
                result["success"] = True
                result["idempotent"] = True
                return result
            
            # Build deletion filter
            where_filter = {
                "$and": [
                    {"doc_id": {"$eq": doc_id}},
                    {"source": {"$eq": source}}
                ]
            }
            
            # Add tenant filter if scoping is enabled
            if settings.TENANT_SCOPING_ON and tenant_id:
                where_filter["$and"].append({"tenant_id": {"$eq": tenant_id}})
            
            # Get count before deletion
            before_count = self.vector_store.collection.count()
            
            # Perform deletion
            with deletion_latency.time():
                self.vector_store.collection.delete(where=where_filter)
            
            # Verify deletion
            after_count = self.vector_store.collection.count()
            chunks_deleted = before_count - after_count
            
            deletion_chunks_removed.inc(chunks_deleted)
            
            # Invalidate caches if Redis available
            if self.redis_client:
                await self.invalidate_caches(doc_id, tenant_id)
            
            # Cross-process cache invalidation if enabled
            if settings.ENABLE_CROSS_PROCESS_CACHE_SYNC:
                from src.backend.services.cache_manager import cache_manager
                cache_manager.invalidate_document_cache(
                    doc_id=doc_id,
                    source=source,
                    tenant_id=tenant_id
                )
            
            logger.info(f"[+] Deleted {chunks_deleted} chunks for doc_id={doc_id}")
            
            result["success"] = True
            result["chunks_deleted"] = chunks_deleted
            
        except Exception as e:
            logger.error(f"Error deleting doc {doc_id}: {e}")
            result["error"] = str(e)
            
        return result
    
    async def invalidate_caches(self, doc_id: str, tenant_id: Optional[str]):
        """Invalidate related caches in Redis"""
        try:
            patterns = [
                f"response:*:{doc_id}:*",
                f"embedding:{doc_id}:*",
                f"chunk:{doc_id}:*"
            ]
            
            if tenant_id:
                patterns.extend([
                    f"response:{tenant_id}:*",
                    f"doc_count:{tenant_id}",
                    f"index_stats:{tenant_id}"
                ])
            
            invalidated = 0
            for pattern in patterns:
                for key in self.redis_client.scan_iter(match=pattern):
                    self.redis_client.delete(key)
                    invalidated += 1
            
            # Publish invalidation event
            event = json.dumps({
                "type": "document_deleted",
                "doc_id": doc_id,
                "tenant_id": tenant_id,
                "timestamp": datetime.utcnow().isoformat()
            })
            self.redis_client.publish('cache_invalidation', event)
            
            logger.info(f"Invalidated {invalidated} cache entries for doc {doc_id}")
            
        except Exception as e:
            logger.warning(f"Cache invalidation failed: {e}")
    
    async def process_job(self, job: Dict[str, Any]) -> bool:
        """Process a single deletion job with retries"""
        job_id = job['id']
        
        try:
            # Perform deletion
            result = await self.delete_from_vector_store(
                job['doc_id'],
                job['source_filename'],
                job.get('tenant_id')
            )
            
            if result["success"]:
                # Mark job as completed
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE vector_deletion_jobs 
                        SET status = 'completed', 
                            processed_at = NOW(),
                            error_message = NULL,
                            metadata = $2
                        WHERE id = $1
                    """, job_id, json.dumps({
                        "chunks_deleted": result["chunks_deleted"],
                        "idempotent": result["idempotent"]
                    }))
                
                deletion_jobs_processed.inc()
                return True
            else:
                raise Exception(result.get("error", "Unknown error"))
                
        except Exception as e:
            deletion_jobs_failed.inc()
            logger.error(f"Failed job {job_id}: {e}")
            
            # Update job with retry logic
            async with self.db_pool.acquire() as conn:
                new_attempts = job['attempts'] + 1
                
                if new_attempts >= self.max_retries:
                    # Mark as permanently failed
                    await conn.execute("""
                        UPDATE vector_deletion_jobs 
                        SET status = 'failed',
                            attempts = $2,
                            error_message = $3
                        WHERE id = $1
                    """, job_id, new_attempts, str(e))
                else:
                    # Schedule for retry
                    deletion_jobs_retried.inc()
                    await conn.execute("""
                        UPDATE vector_deletion_jobs 
                        SET attempts = $2,
                            error_message = $3,
                            status = 'pending'
                        WHERE id = $1
                    """, job_id, new_attempts, str(e))
            
            return False
    
    async def run(self):
        """Main worker loop"""
        if not settings.ENABLE_DELETION_WORKER:
            logger.info("Deletion worker disabled by feature flag")
            return
            
        if not await self.initialize():
            logger.error("Failed to initialize worker")
            return
            
        self.running = True
        logger.info("[*] Vector deletion worker started")
        
        while self.running:
            try:
                async with self.db_pool.acquire() as conn:
                    # Get pending jobs (with retry backoff)
                    jobs = await conn.fetch("""
                        SELECT id, doc_id, tenant_id, source_filename, attempts
                        FROM vector_deletion_jobs
                        WHERE status = 'pending' 
                        AND attempts < $1
                        AND (
                            attempts = 0 
                            OR created_at < NOW() - INTERVAL '%s seconds' * attempts
                        )
                        ORDER BY created_at
                        LIMIT $2
                    """, self.max_retries, settings.DELETION_WORKER_BATCH_SIZE, self.retry_delay)
                    
                    pending_jobs_gauge.set(len(jobs))
                    
                    if jobs:
                        logger.info(f"Processing {len(jobs)} deletion jobs")
                        
                        for job in jobs:
                            if not self.running:
                                break
                            await self.process_job(dict(job))
                    
                # Sleep between batches
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                await asyncio.sleep(10)
    
    def stop(self):
        """Stop the worker gracefully"""
        self.running = False
        logger.info("Vector deletion worker stopping...")


async def enqueue_deletion(
    db_pool: asyncpg.Pool, 
    doc_id: str, 
    source: str, 
    tenant_id: Optional[str],
    metadata: Optional[Dict] = None
) -> Optional[str]:
    """Enqueue a deletion job (idempotent)"""
    if not settings.ENABLE_DELETION_WORKER:
        # If worker is disabled, perform synchronous deletion (legacy behavior)
        logger.info("Deletion worker disabled, falling back to synchronous deletion")
        try:
            vs = VectorStore()
            vs.delete_documents_by_sources([source])
            return None
        except Exception as e:
            logger.error(f"Synchronous deletion failed: {e}")
            return None
    
    try:
        async with db_pool.acquire() as conn:
            # Check if job already exists (idempotency)
            existing = await conn.fetchval("""
                SELECT id FROM vector_deletion_jobs
                WHERE doc_id = $1 
                AND status IN ('pending', 'completed')
            """, doc_id)
            
            if existing:
                logger.info(f"Deletion job already exists for doc {doc_id}: {existing}")
                return str(existing)
            
            # Create new job
            job_id = await conn.fetchval("""
                INSERT INTO vector_deletion_jobs (doc_id, tenant_id, source_filename, metadata)
                VALUES ($1, $2, $3, $4)
                RETURNING id
            """, doc_id, tenant_id, source, json.dumps(metadata or {}))
            
            logger.info(f"Enqueued deletion job {job_id} for doc {doc_id}")
            return str(job_id)
            
    except Exception as e:
        logger.error(f"Failed to enqueue deletion: {e}")
        return None


# Standalone worker script entry point
async def main():
    """Run worker as standalone process"""
    import sys
    
    DATABASE_URL = os.getenv("DATABASE_URL")
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    if not DATABASE_URL:
        logger.error("[-] DATABASE_URL environment variable not set")
        raise ValueError("DATABASE_URL environment variable is required")
    
    # Create database pool
    db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=5,
        command_timeout=60
    )
    
    # Create Redis client
    redis_client = None
    if REDIS_URL:
        try:
            redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            redis_client.ping()
            logger.info("[+] Connected to Redis")
        except Exception as e:
            logger.warning(f"Redis not available: {e}")
    
    # Create and run worker
    worker = VectorDeletionWorker(db_pool, redis_client)
    
    # Handle shutdown signals
    import signal
    
    def handle_shutdown(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        worker.stop()
    
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    try:
        await worker.run()
    finally:
        await db_pool.close()
        if redis_client:
            redis_client.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
