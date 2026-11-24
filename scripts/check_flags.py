#!/usr/bin/env python3
"""
Check current feature flag status
"""
import os
import sys

# Add src to path
sys.path.append('src')

def check_flags():
    """Display current feature flags"""
    print("Current Feature Flags:")
    print("=" * 50)
    
    # Core enterprise flags
    print(f"STRICT_MODE: {os.getenv('STRICT_MODE', 'false')}")
    print(f"TENANT_SCOPING_ON: {os.getenv('TENANT_SCOPING_ON', 'false')}")
    print(f"ENABLE_DELETION_WORKER: {os.getenv('ENABLE_DELETION_WORKER', 'false')}")
    print(f"ENABLE_RECONCILIATION: {os.getenv('ENABLE_RECONCILIATION', 'false')}")
    print(f"BLOCK_BACKUP_FOLDERS: {os.getenv('BLOCK_BACKUP_FOLDERS', 'true')}")
    
    print("\nCollection/Cache Flags:")
    print(f"CANONICAL_COLLECTION_ENFORCED: {os.getenv('CANONICAL_COLLECTION_ENFORCED', 'false')}")
    print(f"ENABLE_CROSS_PROCESS_CACHE_SYNC: {os.getenv('ENABLE_CROSS_PROCESS_CACHE_SYNC', 'false')}")
    print(f"ENABLE_UPLOAD_LOGGING: {os.getenv('ENABLE_UPLOAD_LOGGING', 'false')}")
    
    # Test loading settings
    try:
        from src.config.settings import settings
        print(f"\n✅ Settings loaded successfully")
        print(f"Collection name: {settings.vector_collection_name}")
        
        # Test flags in settings object
        print(f"\nSettings object flags:")
        print(f"CANONICAL_COLLECTION_ENFORCED: {settings.CANONICAL_COLLECTION_ENFORCED}")
        print(f"ENABLE_CROSS_PROCESS_CACHE_SYNC: {settings.ENABLE_CROSS_PROCESS_CACHE_SYNC}")
        print(f"ENABLE_UPLOAD_LOGGING: {settings.ENABLE_UPLOAD_LOGGING}")
        
    except Exception as e:
        print(f"❌ Error loading settings: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = check_flags()
    sys.exit(0 if success else 1)
