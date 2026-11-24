#!/usr/bin/env python3
"""
Enterprise reconciliation with metrics, safety checks, and feature flags
"""
import asyncio
import asyncpg
import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.backend.services.vector_store import VectorStore
from src.config.settings import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EnterpriseReconciler:
    """Production-grade reconciliation with idempotency and metrics"""
    
    def __init__(self, database_url: str, dry_run: bool = False):
        self.database_url = database_url
        self.dry_run = dry_run
        self.vector_store = None
        self.stats = {
            "started_at": datetime.utcnow().isoformat(),
            "db_docs": 0,
            "vector_sources": 0,
            "orphaned": [],
            "missing": [],
            "version_conflicts": [],
            "completed": False,
            "error": None,
            "final_drift": None
        }
    
    async def initialize(self) -> bool:
        """Initialize connections"""
        try:
            # Initialize vector store
            self.vector_store = VectorStore()
            logger.info(f"✅ Connected to collection: {self.vector_store.collection_name}")
            
            # Test database connection
            conn = await asyncpg.connect(self.database_url)
            await conn.close()
            logger.info("✅ Database connection verified")
            
            return True
        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            self.stats["error"] = str(e)
            return False
    
    async def get_db_documents(self, conn: asyncpg.Connection) -> Dict[str, dict]:
        """Get all documents from database"""
        query = """
            SELECT id, filename, created_at,
                   is_active, deleted_at, version, checksum, tenant_id
            FROM documents
            ORDER BY filename
        """
        
        # Adjust query if lifecycle fields don't exist yet (backwards compatibility)
        try:
            rows = await conn.fetch(query)
        except asyncpg.UndefinedColumnError:
            # Fallback for databases without lifecycle fields
            logger.info("Lifecycle fields not found, using legacy query")
            rows = await conn.fetch("""
                SELECT id, filename, created_at
                FROM documents
                ORDER BY filename
            """)
        
        db_docs = {}
        for row in rows:
            # Handle both new and legacy schemas
            doc = dict(row)
            doc['is_active'] = doc.get('is_active', True)
            doc['deleted_at'] = doc.get('deleted_at', None)
            doc['version'] = doc.get('version', 1)
            doc['tenant_id'] = str(doc.get('tenant_id', 'default')) if doc.get('tenant_id') else 'default'
            
            db_docs[doc['filename']] = doc
        
        return db_docs
    
    async def get_vector_sources(self) -> Set[str]:
        """Get unique sources from vector store"""
        try:
            sources = self.vector_store.get_unique_sources()
            return set(sources)
        except Exception as e:
            logger.error(f"Failed to get vector sources: {e}")
            return set()
    
    async def identify_drift(self, db_docs: Dict[str, dict], vector_sources: Set[str]) -> Tuple[List[str], List[str]]:
        """Identify orphaned and missing documents"""
        orphaned = []
        missing = []
        
        # Apply different logic based on feature flags
        if settings.STRICT_MODE:
            # Strict mode: consider lifecycle fields
            db_active = {
                filename for filename, doc in db_docs.items()
                if doc['is_active'] and not doc['deleted_at']
            }
            
            # Orphaned: in vector but not active in DB
            orphaned = list(vector_sources - db_active)
            
            # Missing: active in DB but not in vector
            missing = list(db_active - vector_sources)
            
        else:
            # Legacy mode: simple set difference
            db_filenames = set(db_docs.keys())
            
            # Orphaned: in vector but not in DB
            orphaned = list(vector_sources - db_filenames)
            
            # Missing: in DB but not in vector
            missing = list(db_filenames - vector_sources)
        
        return orphaned, missing
    
    async def delete_orphaned(self, orphaned: List[str]) -> int:
        """Delete orphaned vectors"""
        if not orphaned:
            return 0
        
        if self.dry_run:
            logger.info(f"[DRY RUN] Would delete {len(orphaned)} orphaned sources")
            return 0
        
        deleted_count = 0
        for source in orphaned:
            try:
                count = self.vector_store.delete_documents_by_sources([source])
                deleted_count += count
                logger.info(f"   ✅ Deleted vectors for: {source}")
            except Exception as e:
                logger.error(f"   ❌ Failed to delete {source}: {e}")
        
        return deleted_count
    
    async def log_reconciliation_run(self, conn: asyncpg.Connection):
        """Log reconciliation run to database"""
        try:
            # Check if reconciliation_runs table exists
            table_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'reconciliation_runs'
                )
            """)
            
            if table_exists:
                await conn.execute("""
                    INSERT INTO reconciliation_runs 
                    (started_at, completed_at, status, db_docs, vector_sources, 
                     orphaned_count, missing_count, final_drift, dry_run, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """, 
                    datetime.fromisoformat(self.stats["started_at"]),
                    datetime.utcnow(),
                    "completed" if self.stats["completed"] else "failed",
                    self.stats["db_docs"],
                    self.stats["vector_sources"],
                    len(self.stats["orphaned"]),
                    len(self.stats["missing"]),
                    self.stats["final_drift"],
                    self.dry_run,
                    json.dumps(self.stats)
                )
                logger.info("📝 Reconciliation run logged to database")
        except Exception as e:
            logger.warning(f"Could not log reconciliation run: {e}")
    
    async def run(self) -> dict:
        """Run reconciliation"""
        if not settings.ENABLE_RECONCILIATION and not self.dry_run:
            logger.warning("Reconciliation disabled by feature flag (use --dry-run to preview)")
            self.stats["error"] = "Feature disabled"
            return self.stats
        
        if not await self.initialize():
            return self.stats
        
        conn = None
        try:
            # Connect to database
            conn = await asyncpg.connect(self.database_url)
            
            # Get current state
            db_docs = await self.get_db_documents(conn)
            vector_sources = await self.get_vector_sources()
            
            self.stats["db_docs"] = len(db_docs)
            self.stats["vector_sources"] = len(vector_sources)
            
            # Identify drift
            orphaned, missing = await self.identify_drift(db_docs, vector_sources)
            
            self.stats["orphaned"] = orphaned
            self.stats["missing"] = missing
            
            # Report findings
            logger.info("\n📊 Reconciliation Analysis:")
            logger.info(f"   Database documents: {len(db_docs)}")
            logger.info(f"   Vector store sources: {len(vector_sources)}")
            logger.info(f"   Orphaned (in vector but not DB): {len(orphaned)}")
            logger.info(f"   Missing (in DB but not vector): {len(missing)}")
            
            if orphaned:
                logger.info("\n⚠️  Orphaned sources:")
                for source in orphaned[:10]:
                    logger.info(f"   - {source}")
                if len(orphaned) > 10:
                    logger.info(f"   ... and {len(orphaned) - 10} more")
            
            if missing:
                logger.info("\n⚠️  Missing from vector store:")
                for source in missing[:10]:
                    logger.info(f"   - {source}")
                if len(missing) > 10:
                    logger.info(f"   ... and {len(missing) - 10} more")
            
            # Fix issues if not dry run
            if not self.dry_run and (orphaned or missing):
                logger.info("\n🔧 Applying fixes...")
                
                if orphaned:
                    deleted = await self.delete_orphaned(orphaned)
                    logger.info(f"   Deleted {deleted} orphaned chunks")
                
                if missing:
                    logger.info(f"   ℹ️  {len(missing)} documents need reindexing")
                    logger.info("   Run sync_documents.py to reindex missing documents")
            
            # Calculate final drift
            if settings.STRICT_MODE:
                # Re-check after fixes
                db_docs_final = await self.get_db_documents(conn)
                vector_sources_final = await self.get_vector_sources()
                
                db_active_final = {
                    filename for filename, doc in db_docs_final.items()
                    if doc['is_active'] and not doc['deleted_at']
                }
                
                self.stats["final_drift"] = abs(len(db_active_final) - len(vector_sources_final))
            else:
                self.stats["final_drift"] = abs(len(db_docs) - len(missing) - (len(vector_sources) - len(orphaned)))
            
            self.stats["completed"] = True
            
            # Log run to database
            await self.log_reconciliation_run(conn)
            
            # Summary
            logger.info(f"\n{'✅' if self.stats['final_drift'] == 0 else '⚠️ '} Final drift: {self.stats['final_drift']} documents")
            
        except Exception as e:
            logger.error(f"Reconciliation failed: {e}")
            self.stats["error"] = str(e)
            import traceback
            traceback.print_exc()
            
        finally:
            if conn:
                await conn.close()
        
        return self.stats


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Enterprise vector reconciliation')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without applying')
    parser.add_argument('--output', help='Save results to JSON file')
    parser.add_argument('--force', action='store_true', help='Run even if feature flag is disabled')
    args = parser.parse_args()
    
    # Override feature flag if forced
    if args.force:
        settings.ENABLE_RECONCILIATION = True
    
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        print("❌ DATABASE_URL environment variable not set")
        raise ValueError("DATABASE_URL environment variable is required")
    
    reconciler = EnterpriseReconciler(DATABASE_URL, dry_run=args.dry_run)
    stats = await reconciler.run()
    
    # Save results if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(stats, f, indent=2, default=str)
        logger.info(f"📁 Results saved to {args.output}")
    
    # Exit with appropriate code
    if stats.get("error"):
        return 2
    elif stats.get("final_drift", 1) == 0:
        return 0
    else:
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)