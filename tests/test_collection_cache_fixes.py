"""
Test collection canonicalization and cross-process cache invalidation fixes
"""
import pytest
import asyncio
import os
import tempfile
import time
from unittest.mock import patch, MagicMock
from datetime import datetime

# Set test environment
os.environ["ENVIRONMENT"] = "test"
os.environ["VECTOR_SCHEMA_VERSION"] = "1"

from src.backend.services.vector_store import VectorStore
from src.backend.services.cache_manager import CrossProcessCacheManager
from src.backend.utils.document_processor import DocumentChunk
from src.config import settings


class TestCollectionCanonical:
    """Test canonical collection naming enforcement"""
    
    @pytest.fixture(autouse=True)
    def reset_flags(self):
        """Reset feature flags before each test"""
        original_canonical = settings.CANONICAL_COLLECTION_ENFORCED
        original_upload_logging = settings.ENABLE_UPLOAD_LOGGING
        original_reconciliation = settings.ENABLE_RECONCILIATION
        original_tenant_scoping = settings.TENANT_SCOPING_ON
        
        yield
        
        # Restore original values
        settings.CANONICAL_COLLECTION_ENFORCED = original_canonical
        settings.ENABLE_UPLOAD_LOGGING = original_upload_logging
        settings.ENABLE_RECONCILIATION = original_reconciliation
        settings.TENANT_SCOPING_ON = original_tenant_scoping
    
    def test_legacy_collection_name_preserved(self):
        """Test that legacy collection name is preserved when flags are OFF"""
        settings.CANONICAL_COLLECTION_ENFORCED = False
        settings.ENABLE_RECONCILIATION = False
        settings.TENANT_SCOPING_ON = False
        
        vector_store = VectorStore()
        
        # Should use legacy collection name from settings
        assert vector_store.collection_name == settings.vector_collection_name
        assert vector_store.collection_name == "company_docs"
    
    def test_canonical_collection_enforced(self):
        """Test canonical collection naming when flag is ON"""
        settings.CANONICAL_COLLECTION_ENFORCED = True
        settings.TENANT_SCOPING_ON = False
        
        with patch.dict(os.environ, {"ENVIRONMENT": "test", "VECTOR_SCHEMA_VERSION": "1"}):
            vector_store = VectorStore()
            
            # Should use canonical enterprise naming
            expected_name = "test_finsolve_primary_v1"
            assert vector_store.collection_name == expected_name
    
    def test_canonical_with_tenant_scoping(self):
        """Test canonical collection naming with tenant scoping"""
        settings.CANONICAL_COLLECTION_ENFORCED = True
        settings.TENANT_SCOPING_ON = True
        
        with patch.dict(os.environ, {
            "ENVIRONMENT": "test", 
            "VECTOR_SCHEMA_VERSION": "1",
            "DEFAULT_TENANT_ID": "test_tenant"
        }):
            vector_store = VectorStore()
            
            # Should include tenant in name
            expected_name = "test_finsolve_test_tenant_v1"
            assert vector_store.collection_name == expected_name
    
    def test_legacy_vs_canonical_consistency(self):
        """Test that multiple instances use same collection when canonical enforced"""
        settings.CANONICAL_COLLECTION_ENFORCED = True
        settings.TENANT_SCOPING_ON = False
        
        with patch.dict(os.environ, {"ENVIRONMENT": "test", "VECTOR_SCHEMA_VERSION": "1"}):
            # Create multiple instances
            vs1 = VectorStore()
            vs2 = VectorStore()
            
            # Both should use identical collection name
            assert vs1.collection_name == vs2.collection_name
            assert vs1.persist_directory == vs2.persist_directory
    
    def test_upload_logging_collection_visibility(self):
        """Test that upload logging shows collection names"""
        settings.ENABLE_UPLOAD_LOGGING = True
        settings.CANONICAL_COLLECTION_ENFORCED = False
        
        with patch('src.backend.services.vector_store.logger') as mock_logger:
            vector_store = VectorStore()
            
            # Should log legacy collection name
            mock_logger.info.assert_called_with(f"📁 Using legacy collection: {settings.vector_collection_name}")


class TestCrossProcessCache:
    """Test cross-process cache invalidation"""
    
    @pytest.fixture(autouse=True)
    def reset_cache_flags(self):
        """Reset cache flags before each test"""
        original_cache_sync = settings.ENABLE_CROSS_PROCESS_CACHE_SYNC
        original_redis_url = settings.redis_url
        
        yield
        
        settings.ENABLE_CROSS_PROCESS_CACHE_SYNC = original_cache_sync
        settings.redis_url = original_redis_url
    
    def test_cache_manager_disabled_by_default(self):
        """Test that cache manager is disabled when flag is OFF"""
        settings.ENABLE_CROSS_PROCESS_CACHE_SYNC = False
        
        cache_manager = CrossProcessCacheManager()
        
        assert not cache_manager.enabled
        assert cache_manager.redis_client is None
    
    @patch('src.backend.services.cache_manager.redis')
    def test_cache_manager_enabled_with_redis(self, mock_redis):
        """Test cache manager enables when Redis available"""
        settings.ENABLE_CROSS_PROCESS_CACHE_SYNC = True
        settings.redis_url = "redis://localhost:6379/0"
        
        # Mock Redis connection
        mock_client = MagicMock()
        mock_redis.from_url.return_value = mock_client
        mock_client.ping.return_value = True
        
        cache_manager = CrossProcessCacheManager()
        
        assert cache_manager.enabled
        assert cache_manager.redis_client == mock_client
    
    @patch('src.backend.services.cache_manager.redis')
    def test_cache_manager_graceful_redis_failure(self, mock_redis):
        """Test cache manager gracefully handles Redis connection failure"""
        settings.ENABLE_CROSS_PROCESS_CACHE_SYNC = True
        settings.redis_url = "redis://localhost:6379/0"
        
        # Mock Redis connection failure
        mock_redis.from_url.side_effect = Exception("Redis connection failed")
        
        cache_manager = CrossProcessCacheManager()
        
        # Should disable gracefully
        assert not cache_manager.enabled
        assert cache_manager.redis_client is None
    
    @patch('src.backend.services.cache_manager.redis')
    def test_document_cache_invalidation(self, mock_redis):
        """Test document cache invalidation patterns"""
        settings.ENABLE_CROSS_PROCESS_CACHE_SYNC = True
        settings.redis_url = "redis://localhost:6379/0"
        
        # Mock Redis client
        mock_client = MagicMock()
        mock_redis.from_url.return_value = mock_client
        mock_client.ping.return_value = True
        mock_client.scan_iter.return_value = ["key1", "key2", "key3"]
        
        cache_manager = CrossProcessCacheManager()
        
        # Test document invalidation
        result = cache_manager.invalidate_document_cache(
            doc_id="test_doc_123",
            source="test.txt",
            tenant_id="test_tenant"
        )
        
        assert result is True
        
        # Verify Redis operations
        mock_client.delete.assert_called_once_with("key1", "key2", "key3")
        mock_client.publish.assert_called_once()
        
        # Check published event structure
        publish_call = mock_client.publish.call_args
        channel, message = publish_call[0]
        assert channel == settings.REDIS_CACHE_INVALIDATION_CHANNEL
        
        import json
        event = json.loads(message)
        assert event["type"] == "document_invalidation"
        assert event["doc_id"] == "test_doc_123"
        assert event["source"] == "test.txt"
        assert event["tenant_id"] == "test_tenant"
    
    @patch('src.backend.services.cache_manager.redis')  
    def test_upload_cache_invalidation(self, mock_redis):
        """Test upload completion cache invalidation"""
        settings.ENABLE_CROSS_PROCESS_CACHE_SYNC = True
        settings.redis_url = "redis://localhost:6379/0"
        
        # Mock Redis client
        mock_client = MagicMock()
        mock_redis.from_url.return_value = mock_client
        mock_client.ping.return_value = True
        
        cache_manager = CrossProcessCacheManager()
        
        # Test upload invalidation
        result = cache_manager.invalidate_upload_cache(
            filename="test_upload.txt",
            tenant_id="test_tenant"
        )
        
        assert result is True
        
        # Verify event published
        mock_client.publish.assert_called_once()
        
        publish_call = mock_client.publish.call_args
        channel, message = publish_call[0]
        
        import json
        event = json.loads(message)
        assert event["type"] == "upload_completed"
        assert event["filename"] == "test_upload.txt"
        assert event["tenant_id"] == "test_tenant"


class TestRegressionPreservation:
    """Test that legacy behavior is preserved when flags are OFF"""
    
    @pytest.fixture(autouse=True)
    def ensure_flags_off(self):
        """Ensure all new flags are OFF for regression tests"""
        settings.CANONICAL_COLLECTION_ENFORCED = False
        settings.ENABLE_CROSS_PROCESS_CACHE_SYNC = False
        settings.ENABLE_UPLOAD_LOGGING = False
        yield
    
    def test_legacy_collection_unchanged(self):
        """Test legacy collection behavior unchanged"""
        vector_store = VectorStore()
        
        # Should use original legacy collection name
        assert vector_store.collection_name == "company_docs"
        # Should use default path (simplified test - path normalization varies by environment)
        assert "chroma_db" in vector_store.persist_directory
    
    @patch('src.backend.services.cache_manager.redis')
    def test_no_redis_dependency_when_disabled(self, mock_redis):
        """Test no Redis dependency when cache sync disabled"""
        cache_manager = CrossProcessCacheManager()
        
        # Should not attempt Redis connection
        mock_redis.from_url.assert_not_called()
        
        # Operations should return False but not fail
        result = cache_manager.invalidate_document_cache("doc", "source")
        assert result is False
    
    def test_upload_logging_silent_when_disabled(self):
        """Test upload logging is silent when disabled"""
        with patch('src.backend.services.vector_store.logger') as mock_logger:
            vector_store = VectorStore()
            
            # Should not log collection info when upload logging disabled
            log_calls = [call[0][0] for call in mock_logger.info.call_args_list]
            legacy_logs = [msg for msg in log_calls if "Using legacy collection" in msg]
            assert len(legacy_logs) == 0


class TestPerformanceImpact:
    """Test performance impact of new features"""
    
    def test_canonical_collection_startup_time(self):
        """Test canonical collection doesn't significantly impact startup"""
        settings.CANONICAL_COLLECTION_ENFORCED = True
        
        start_time = time.time()
        vector_store = VectorStore()
        startup_time = time.time() - start_time
        
        # Should complete in reasonable time (< 1 second for naming logic)
        assert startup_time < 1.0
        assert vector_store.collection_name is not None
    
    @patch('src.backend.services.cache_manager.redis')
    def test_cache_invalidation_async_performance(self, mock_redis):
        """Test cache invalidation doesn't block operations"""
        settings.ENABLE_CROSS_PROCESS_CACHE_SYNC = True
        settings.redis_url = "redis://localhost:6379/0"
        
        # Mock Redis with delay
        mock_client = MagicMock()
        mock_redis.from_url.return_value = mock_client
        mock_client.ping.return_value = True
        mock_client.scan_iter.return_value = []
        mock_client.delete.return_value = 0
        mock_client.publish.return_value = 1
        
        cache_manager = CrossProcessCacheManager()
        
        # Cache invalidation should be fast
        start_time = time.time()
        result = cache_manager.invalidate_document_cache("doc", "source")
        operation_time = time.time() - start_time
        
        assert result is True
        assert operation_time < 0.1  # Should be very fast
