"""
Cross-process cache invalidation manager for enterprise RAG features
"""
import json
import logging
import redis
from typing import Optional, Dict, Any
from datetime import datetime
from src.config.settings import settings

logger = logging.getLogger(__name__)


class CrossProcessCacheManager:
    """Manages cache invalidation across multiple service instances"""
    
    def __init__(self):
        self.redis_client = None
        self.enabled = settings.ENABLE_CROSS_PROCESS_CACHE_SYNC
        
        if self.enabled:
            self._initialize_redis()
    
    def _initialize_redis(self) -> bool:
        """Initialize Redis connection for cross-process communication"""
        try:
            if settings.redis_url:
                self.redis_client = redis.from_url(settings.redis_url)
                # Test connection
                self.redis_client.ping()
                logger.info("[+] Cross-process cache sync enabled with Redis")
                return True
            else:
                logger.warning("Redis URL not configured, disabling cross-process cache sync")
                self.enabled = False
                return False
        except Exception as e:
            logger.warning(f"Failed to connect to Redis, disabling cross-process cache sync: {e}")
            self.enabled = False
            return False
    
    def invalidate_document_cache(self, doc_id: str, source: str, tenant_id: Optional[str] = None) -> bool:
        """Invalidate caches related to a specific document across all processes"""
        if not self.enabled or not self.redis_client:
            return False
        
        try:
            # Build cache invalidation patterns
            patterns = [
                f"response:*:{doc_id}:*",
                f"response:*:{source}:*", 
                f"embedding:{doc_id}:*",
                f"chunk:{doc_id}:*",
                f"search_cache:*:{source}:*"
            ]
            
            if tenant_id:
                patterns.extend([
                    f"response:{tenant_id}:*",
                    f"doc_count:{tenant_id}",
                    f"index_stats:{tenant_id}"
                ])
            
            # Delete matching cache keys
            invalidated = 0
            for pattern in patterns:
                keys = list(self.redis_client.scan_iter(match=pattern))
                if keys:
                    self.redis_client.delete(*keys)
                    invalidated += len(keys)
            
            # Publish invalidation event for other processes
            event = {
                "type": "document_invalidation",
                "doc_id": doc_id,
                "source": source,
                "tenant_id": tenant_id,
                "timestamp": datetime.utcnow().isoformat(),
                "patterns": patterns
            }
            
            self.redis_client.publish(
                settings.REDIS_CACHE_INVALIDATION_CHANNEL,
                json.dumps(event)
            )
            
            if settings.ENABLE_UPLOAD_LOGGING:
                logger.info(f"📤 Invalidated {invalidated} cache entries for doc {doc_id}, published event")
            
            return True
            
        except Exception as e:
            logger.error(f"Cross-process cache invalidation failed: {e}")
            return False
    
    def invalidate_upload_cache(self, filename: str, tenant_id: Optional[str] = None) -> bool:
        """Invalidate caches after successful upload"""
        if not self.enabled or not self.redis_client:
            return False
        
        try:
            # Clear upload-related caches
            patterns = [
                f"response:*",  # Clear all response caches to ensure fresh results
                f"search_cache:*",  # Clear search result caches
                f"embedding_cache:*"  # Clear query embedding caches
            ]
            
            if tenant_id:
                patterns.extend([
                    f"tenant_docs:{tenant_id}",
                    f"doc_count:{tenant_id}"
                ])
            
            # Publish upload completion event
            event = {
                "type": "upload_completed",
                "filename": filename,
                "tenant_id": tenant_id,
                "timestamp": datetime.utcnow().isoformat(),
                "action": "invalidate_search_caches"
            }
            
            self.redis_client.publish(
                settings.REDIS_CACHE_INVALIDATION_CHANNEL,
                json.dumps(event)
            )
            
            if settings.ENABLE_UPLOAD_LOGGING:
                logger.info(f"📤 Published upload completion event for {filename}")
            
            return True
            
        except Exception as e:
            logger.error(f"Upload cache invalidation failed: {e}")
            return False
    
    def subscribe_to_invalidation_events(self, callback_func):
        """Subscribe to cache invalidation events (for background workers)"""
        if not self.enabled or not self.redis_client:
            return
        
        try:
            pubsub = self.redis_client.pubsub()
            pubsub.subscribe(settings.REDIS_CACHE_INVALIDATION_CHANNEL)
            
            for message in pubsub.listen():
                if message['type'] == 'message':
                    try:
                        event = json.loads(message['data'].decode('utf-8'))
                        callback_func(event)
                    except Exception as e:
                        logger.error(f"Error processing cache invalidation event: {e}")
                        
        except Exception as e:
            logger.error(f"Failed to subscribe to cache invalidation events: {e}")


# Global instance
cache_manager = CrossProcessCacheManager()
