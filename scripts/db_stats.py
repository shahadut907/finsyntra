#!/usr/bin/env python3
"""
ChromaDB Statistics and Health Check
"""
import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import chromadb
from src.config.settings import settings

def main():
    print("🔍 ChromaDB Statistics")
    print("=" * 50)
    
    try:
        # Connect to ChromaDB
        persist_path = settings.vector_db_path
        print(f"📁 Connecting to: {persist_path}")
        
        if not os.path.exists(persist_path):
            print(f"❌ Path does not exist: {persist_path}")
            return
        
        client = chromadb.PersistentClient(path=persist_path)
        
        # List all collections
        collections = client.list_collections()
        print(f"\n📚 Found {len(collections)} collection(s):")
        
        total_chunks = 0
        for collection in collections:
            coll = client.get_collection(collection.name)
            count = coll.count()
            total_chunks += count
            print(f"  - {collection.name}: {count} chunks")
            
            # Sample a few documents to check metadata
            if count > 0:
                sample = coll.get(limit=3, include=["metadatas"])
                if sample.get("metadatas"):
                    print(f"    Sample metadata keys: {list(sample['metadatas'][0].keys())}")
        
        print(f"\n📊 Total chunks across all collections: {total_chunks}")
        
        # Check expected collection
        expected_collection = settings.vector_collection_name
        print(f"\n🎯 Expected collection name: '{expected_collection}'")
        
        collection_names = [c.name for c in collections]
        if expected_collection in collection_names:
            print(f"✅ Expected collection found!")
        else:
            print(f"❌ Expected collection NOT found!")
            print(f"Available collections: {collection_names}")
            
        # Check for common issues
        print(f"\n🔧 Health Checks:")
        sqlite_file = os.path.join(persist_path, "chroma.sqlite3")
        if os.path.exists(sqlite_file):
            size_mb = os.path.getsize(sqlite_file) / (1024 * 1024)
            print(f"✅ SQLite DB exists ({size_mb:.1f} MB)")
        else:
            print(f"❌ SQLite DB missing: {sqlite_file}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
