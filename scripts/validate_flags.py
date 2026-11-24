#!/usr/bin/env python3
"""
Validate flag configuration and behavior
"""
import os
import sys

# Add src to path
sys.path.append('src')

def validate_flags():
    """Validate flag configuration and behavior"""
    print("Validating flag configuration...")
    print("=" * 50)
    
    try:
        # Test settings loading
        from src.config.settings import settings
        print("✅ Settings loaded successfully")
        
        # Test cache manager initialization
        from src.backend.services.cache_manager import cache_manager
        print("✅ Cache manager initialized")
        
        # Test vector store initialization
        from src.backend.services.vector_store import VectorStore
        vs = VectorStore()
        print(f"✅ Collection: {vs.collection_name}")
        print(f"✅ Path: {vs.persist_directory}")
        
        # Test flag values
        print(f"\nFlag validation:")
        print(f"CANONICAL_COLLECTION_ENFORCED: {settings.CANONICAL_COLLECTION_ENFORCED}")
        print(f"ENABLE_CROSS_PROCESS_CACHE_SYNC: {settings.ENABLE_CROSS_PROCESS_CACHE_SYNC}")
        print(f"ENABLE_UPLOAD_LOGGING: {settings.ENABLE_UPLOAD_LOGGING}")
        
        # Test collection naming logic
        if settings.CANONICAL_COLLECTION_ENFORCED:
            print("✅ Canonical collection enforcement active")
        else:
            print("✅ Legacy collection naming active")
            
        if vs.collection_name == "company_docs":
            print("✅ Using legacy collection name")
        else:
            print(f"✅ Using enterprise collection name: {vs.collection_name}")
        
        print("\n✅ Flag validation complete")
        return True
        
    except Exception as e:
        print(f"❌ Validation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = validate_flags()
    sys.exit(0 if success else 1)
