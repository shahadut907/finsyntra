#!/usr/bin/env python3
"""
Backfill script to add lifecycle metadata to existing documents and vectors
Safe, idempotent, and resumable
"""
import asyncio
import asyncpg
import os
import sys
import json
import hashlib
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import uuid

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.backend.services.vector_store import VectorStore
from src.config.settings import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MetadataBackfiller:
    """Backfill lifecycle metadata for existing data"""
    
    def __init__(self, database_url: str, batch_size: int = 100, dry_run: bool = False):
        self.database_url = database_url
        self.batch_size = batch_size
        self.dry_run = dry_run
        self.vector_store = None
        self.stats = {
            "started_at": datetime.utcnow().isoformat(),
            "db_documents_processed": 0,
            "db_documents_updated": 0,
            "vector_chunks_processed": 0,
            "vector_chunks_updated": 0,
            "errors": [],
            "completed": False
        }
    
    def calculate_checksum(self, content: str) -> str:
        """Calculate content checksum"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    async def backfill_database(self, conn: asyncpg.Connection) -> int:
        """Backfill database documents with lifecycle fields"""
        logger.info("📝 Backfilling database documents...")
        
        # Check which columns exist
        columns = await conn.fetch("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'documents'
        """)
        
        column_names = {row['column_name'] for row in columns}
        
        # Only proceed if new columns exist
        if 'is_active' not in column_names:
            logger.warning("Lifecycle columns not found. Run migrations first.")
            return 0
        
        # Get documents missing lifecycle data
        query = """
            SELECT id, filename, organization_id, created_at
            FROM documents
            WHERE is_active IS NULL 
               OR version IS NULL
               OR checksum IS NULL
            LIMIT $1
        """
        
        updated = 0
        offset = 0
        
        while True:
            rows = await conn.fetch(query, self.batch_size)
            
            if not rows:
                break
            
            for row in rows:
                self.stats["db_documents_processed"] += 1
                
                if self.dry_run:
                    logger.info(f"[DRY RUN] Would update document {row['filename']}")
                    continue
                
                try:
                    # Generate default values
                    default_tenant = row['organization_id'] or None
                    
                    # Update with defaults
                    await conn.execute("""
                        UPDATE documents
                        SET is_active = COALESCE(is_active, true),
                            deleted_at = COALESCE(deleted_at, NULL),
                            version = COALESCE(version, 1),
                            checksum = COALESCE(checksum, $2),
                            tenant_id = COALESCE(tenant_id, $3)
                        WHERE id = $1
                    """, row['id'], 
                        self.calculate_checksum(row['filename']),
                        default_tenant)
                    
                    updated += 1
                    self.stats["db_documents_updated"] += 1
                    
                except Exception as e:
                    logger.error(f"Failed to update document {row['id']}: {e}")
                    self.stats["errors"].append(str(e))
            
            logger.info(f"   Processed {self.stats['db_documents_processed']} documents...")
            
            if len(rows) < self.batch_size:
                break
        
        logger.info(f"✅ Updated {updated} database documents")
        return updated
    
    async def backfill_vectors(self) -> int:
        """Backfill vector store chunks with lifecycle metadata"""
        logger.info("🔍 Backfilling vector store metadata...")
        
        if self.dry_run:
            logger.info("[DRY RUN] Would update vector metadata")
            return 0
        
        try:
            # Get all chunks
            all_data = self.vector_store.collection.get(
                include=["metadatas", "documents"],
                limit=1000000  # High limit
            )
            
            if not all_data["metadatas"]:
                logger.info("No vectors to backfill")
                return 0
            
            updated = 0
            batch_ids = []
            batch_metadatas = []
            batch_documents = []
            batch_embeddings = []
            
            for i, metadata in enumerate(all_data["metadatas"]):
                self.stats["vector_chunks_processed"] += 1
                
                # Check if already has lifecycle fields
                if all(key in metadata for key in ['is_active', 'version', 'tenant_id']):
                    continue
                
                # Generate missing fields
                updated_metadata = metadata.copy()
                
                # Add lifecycle fields if missing
                if 'is_active' not in updated_metadata:
                    updated_metadata['is_active'] = True
                if 'deleted_at' not in updated_metadata:
                    updated_metadata['deleted_at'] = None
                if 'version' not in updated_metadata:
                    updated_metadata['version'] = 1
                if 'tenant_id' not in updated_metadata:
                    updated_metadata['tenant_id'] = 'default'
                if 'doc_id' not in updated_metadata and 'source' in updated_metadata:
                    # Generate doc_id from source
                    updated_metadata['doc_id'] = str(uuid.uuid5(
                        uuid.NAMESPACE_DNS, 
                        updated_metadata['source']
                    ))
                
                # Collect for batch update
                chunk_id = all_data.get("ids", [])[i] if i < len(all_data.get("ids", [])) else str(uuid.uuid4())
                chunk_doc = all_data["documents"][i] if i < len(all_data["documents"]) else ""
                
                batch_ids.append(chunk_id)
                batch_metadatas.append(updated_metadata)
                batch_documents.append(chunk_doc)
                
                # Process batch
                if len(batch_ids) >= self.batch_size:
                    try:
                        # Delete old entries
                        self.vector_store.collection.delete(ids=batch_ids)
                        
                        # Re-add with updated metadata
                        # Generate embeddings
                        from src.backend.services.vector_store import VectorStore
                        temp_vs = VectorStore()
                        
                        embeddings = []
                        for doc in batch_documents:
                            emb = temp_vs._get_single_embedding(doc)
                            embeddings.append(emb)
                        
                        # Add back with new metadata
                        self.vector_store.collection.add(
                            ids=batch_ids,
                            documents=batch_documents,
                            metadatas=batch_metadatas,
                            embeddings=embeddings
                        )
                        
                        updated += len(batch_ids)
                        self.stats["vector_chunks_updated"] += len(batch_ids)
                        
                        logger.info(f"   Updated {updated} chunks...")
                        
                    except Exception as e:
                        logger.error(f"Failed to update batch: {e}")
                        self.stats["errors"].append(str(e))
                    
                    # Reset batch
                    batch_ids = []
                    batch_metadatas = []
                    batch_documents = []
                    batch_embeddings = []
            
            # Process remaining batch
            if batch_ids and not self.dry_run:
                try:
                    # Similar batch processing as above
                    self.vector_store.collection.delete(ids=batch_ids)
                    
                    temp_vs = VectorStore()
                    embeddings = []
                    for doc in batch_documents:
                        emb = temp_vs._get_single_embedding(doc)
                        embeddings.append(emb)
                    
                    self.vector_store.collection.add(
                        ids=batch_ids,
                        documents=batch_documents,
                        metadatas=batch_metadatas,
                        embeddings=embeddings
                    )
                    
                    updated += len(batch_ids)
                    self.stats["vector_chunks_updated"] += len(batch_ids)
                    
                except Exception as e:
                    logger.error(f"Failed to update final batch: {e}")
                    self.stats["errors"].append(str(e))
            
            logger.info(f"✅ Updated {updated} vector chunks")
            return updated
            
        except Exception as e:
            logger.error(f"Vector backfill failed: {e}")
            self.stats["errors"].append(str(e))
            return 0
    
    async def run(self) -> dict:
        """Run complete backfill"""
        logger.info("🚀 Starting metadata backfill...")
        
        if not self.dry_run:
            response = input("⚠️  This will modify existing data. Continue? (y/N): ")
            if response.lower() != 'y':
                logger.info("Backfill cancelled")
                self.stats["error"] = "User cancelled"
                return self.stats
        
        conn = None
        try:
            # Initialize vector store
            self.vector_store = VectorStore()
            logger.info(f"Connected to vector store: {self.vector_store.collection_name}")
            
            # Connect to database
            conn = await asyncpg.connect(self.database_url)
            logger.info("Connected to database")
            
            # Backfill database
            db_updated = await self.backfill_database(conn)
            
            # Backfill vectors
            vector_updated = await self.backfill_vectors()
            
            self.stats["completed"] = True
            
            # Summary
            logger.info("\n📊 Backfill Summary:")
            logger.info(f"   Database documents processed: {self.stats['db_documents_processed']}")
            logger.info(f"   Database documents updated: {self.stats['db_documents_updated']}")
            logger.info(f"   Vector chunks processed: {self.stats['vector_chunks_processed']}")
            logger.info(f"   Vector chunks updated: {self.stats['vector_chunks_updated']}")
            
            if self.stats["errors"]:
                logger.warning(f"   Errors encountered: {len(self.stats['errors'])}")
            
        except Exception as e:
            logger.error(f"Backfill failed: {e}")
            self.stats["error"] = str(e)
            import traceback
            traceback.print_exc()
            
        finally:
            if conn:
                await conn.close()
        
        return self.stats


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Backfill lifecycle metadata')
    parser.add_argument('--batch-size', type=int, default=100, 
                       help='Batch size for processing')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Preview changes without applying')
    parser.add_argument('--output', help='Save results to JSON file')
    args = parser.parse_args()
    
    DATABASE_URL = os.getenv("DATABASE_URL", 
                             "postgresql://postgres:password@localhost:5432/finsolve")
    
    backfiller = MetadataBackfiller(
        DATABASE_URL, 
        batch_size=args.batch_size,
        dry_run=args.dry_run
    )
    
    stats = await backfiller.run()
    
    # Save results if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(stats, f, indent=2, default=str)
        logger.info(f"Results saved to {args.output}")
    
    # Exit code
    if stats.get("error"):
        return 1
    else:
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
