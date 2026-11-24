#!/usr/bin/env python3
"""
Diagnose vector store issues - check for orphaned documents and metadata
"""
import os
import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

import chromadb
from src.config.settings import settings
from src.backend.services.vector_store import VectorStore


def diagnose_vector_store():
    """Run diagnostics on vector store"""
    print("🔍 Vector Store Diagnostics")
    print("=" * 50)
    
    # Check paths
    print(f"\n📁 Configuration:")
    print(f"   Vector DB Path: {settings.vector_db_path}")
    print(f"   Collection Name: {settings.vector_collection_name}")
    
    # Check for backup directories
    embeddings_dir = Path(settings.vector_db_path).parent
    if embeddings_dir.exists():
        subdirs = [d for d in embeddings_dir.iterdir() if d.is_dir()]
        print(f"\n📂 Directories in {embeddings_dir}:")
        for d in subdirs:
            print(f"   - {d.name}")
            if "BACKUP" in d.name or "backup" in d.name:
                print(f"     ⚠️  This looks like a backup folder!")
    
    # Initialize vector store
    try:
        vector_store = VectorStore()
        print(f"\n✅ Connected to collection: {vector_store.collection_name}")
    except Exception as e:
        print(f"\n❌ Failed to connect to vector store: {e}")
        return False
    
    # Get collection stats
    try:
        count = vector_store.collection.count()
        print(f"\n📊 Collection Statistics:")
        print(f"   Total chunks: {count}")
        
        # Sample metadata
        if count > 0:
            sample = vector_store.collection.get(
                limit=min(10, count),
                include=["metadatas", "documents"]
            )
            
            print(f"\n🔍 Sample Metadata (first {len(sample['metadatas'])} chunks):")
            for i, meta in enumerate(sample['metadatas']):
                print(f"\n   Chunk {i+1}:")
                print(f"     Source: {meta.get('source', 'N/A')}")
                print(f"     Department: {meta.get('department', 'N/A')}")
                print(f"     Indexed: {meta.get('indexed_at', 'N/A')}")
                print(f"     Metadata keys: {list(meta.keys())}")
                
                # Check for lifecycle fields
                has_lifecycle = 'is_active' in meta or 'deleted_at' in meta
                has_tenant = 'tenant_id' in meta
                
                if not has_lifecycle:
                    print(f"     ⚠️  Missing lifecycle fields (is_active, deleted_at)")
                if not has_tenant:
                    print(f"     ⚠️  Missing tenant_id field")
        
        # Get unique sources
        sources = vector_store.get_unique_sources()
        print(f"\n📄 Unique Documents: {len(sources)}")
        if sources:
            print("   First 5 sources:")
            for source in sorted(sources)[:5]:
                print(f"   - {source}")
            if len(sources) > 5:
                print(f"   ... and {len(sources) - 5} more")
        
        # Check for potential issues
        print(f"\n⚠️  Potential Issues:")
        issues_found = False
        
        # Check for deleted/archived files
        suspicious_sources = [s for s in sources if any(
            keyword in s.lower() 
            for keyword in ['deleted', 'archive', 'backup', 'old', 'temp']
        )]
        if suspicious_sources:
            issues_found = True
            print(f"   - Found {len(suspicious_sources)} suspicious source names:")
            for source in suspicious_sources[:3]:
                print(f"     • {source}")
        
        # Check metadata completeness
        if count > 0 and 'metadatas' in sample:
            incomplete_meta = sum(
                1 for meta in sample['metadatas'] 
                if not all(key in meta for key in ['source', 'department', 'chunk_id'])
            )
            if incomplete_meta > 0:
                issues_found = True
                print(f"   - {incomplete_meta}/{len(sample['metadatas'])} chunks have incomplete metadata")
        
        if not issues_found:
            print("   ✅ No obvious issues found")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error during diagnostics: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = diagnose_vector_store()
    sys.exit(0 if success else 1)
