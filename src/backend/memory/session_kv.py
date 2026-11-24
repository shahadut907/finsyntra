"""
Session Memory Module for FinSyntra RAG
Stores active subjects and facts to maintain conversational consistency
"""
import time
import json
import hashlib
from typing import Dict, Any, Optional, List, Tuple, Union
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import logging
from threading import Lock

logger = logging.getLogger(__name__)

@dataclass
class ActiveSubject:
    """Represents the currently active subject in conversation"""
    employee_id: Optional[str] = None
    email: Optional[str] = None
    canonical_name: Optional[str] = None
    department: Optional[str] = None
    job_title: Optional[str] = None
    confidence: float = 0.0
    last_updated: datetime = None
    
    def __post_init__(self):
        if self.last_updated is None:
            self.last_updated = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        data = asdict(self)
        data['last_updated'] = self.last_updated.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ActiveSubject':
        """Create from dictionary"""
        if 'last_updated' in data and isinstance(data['last_updated'], str):
            data['last_updated'] = datetime.fromisoformat(data['last_updated'])
        return cls(**data)

@dataclass
class Fact:
    """Represents a verified fact from conversation"""
    key: str
    value: str
    source: str
    timestamp: Union[datetime, int] = None
    confidence: float = 1.0
    # Legacy fields for backward compatibility
    source_doc_id: Optional[str] = None
    chunk_id: Optional[str] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        elif isinstance(self.timestamp, int):
            # Convert Unix timestamp to datetime
            self.timestamp = datetime.fromtimestamp(self.timestamp)
        
        # Set legacy fields if not provided
        if self.source_doc_id is None:
            self.source_doc_id = self.source
        if self.chunk_id is None:
            self.chunk_id = "default"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Fact':
        """Create from dictionary"""
        if 'timestamp' in data and isinstance(data['timestamp'], str):
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)

class SessionMemory:
    """
    In-memory session storage with optional Redis persistence
    Maintains active subjects and facts for conversational consistency
    """
    
    def __init__(self, ttl_hours: int = 24, max_facts_per_session: int = 100):
        self.ttl_hours = ttl_hours
        self.max_facts_per_session = max_facts_per_session
        
        # In-memory storage
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()
        
        # Optional Redis adapter (can be set later)
        self._redis_client = None
        
        logger.info(f"SessionMemory initialized with TTL: {ttl_hours}h, max facts: {max_facts_per_session}")
    
    def set_redis_client(self, redis_client):
        """Set Redis client for persistence (optional)"""
        self._redis_client = redis_client
        logger.info("Redis client set for session persistence")
    
    def _get_session_key(self, session_id: str) -> str:
        """Generate Redis key for session"""
        return f"finsolve:session:{session_id}"
    
    def _get_facts_key(self, session_id: str) -> str:
        """Generate Redis key for session facts"""
        return f"finsolve:facts:{session_id}"
    
    def set_active_subject(self, session_id: str, subject: ActiveSubject) -> None:
        """Set the active subject for a session"""
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = {}
            
            self._sessions[session_id]['active_subject'] = subject
            self._sessions[session_id]['last_updated'] = time.time()
            
            # Try Redis persistence
            if self._redis_client:
                try:
                    key = self._get_session_key(session_id)
                    data = subject.to_dict()
                    self._redis_client.setex(
                        key, 
                        self.ttl_hours * 3600, 
                        json.dumps(data)
                    )
                except Exception as e:
                    logger.warning(f"Failed to persist active subject to Redis: {e}")
            
            logger.info(f"Active subject set for session {session_id}: {subject.canonical_name}")
    
    def get_active_subject(self, session_id: str) -> Optional[ActiveSubject]:
        """Get the active subject for a session"""
        with self._lock:
            # Try in-memory first
            if session_id in self._sessions:
                subject_data = self._sessions[session_id].get('active_subject')
                if subject_data:
                    return subject_data
            
            # Try Redis if available
            if self._redis_client:
                try:
                    key = self._get_session_key(session_id)
                    data = self._redis_client.get(key)
                    if data:
                        subject_dict = json.loads(data)
                        subject = ActiveSubject.from_dict(subject_dict)
                        # Cache in memory
                        if session_id not in self._sessions:
                            self._sessions[session_id] = {}
                        self._sessions[session_id]['active_subject'] = subject
                        return subject
                except Exception as e:
                    logger.warning(f"Failed to retrieve active subject from Redis: {e}")
            
            return None
    
    def add_fact(self, session_id: str, fact_key: str, fact: Fact) -> None:
        """Add a fact to the session"""
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = {}
            
            if 'facts' not in self._sessions[session_id]:
                self._sessions[session_id]['facts'] = {}
            
            # Store fact
            self._sessions[session_id]['facts'][fact_key] = fact
            self._sessions[session_id]['last_updated'] = time.time()
            
            # Enforce max facts limit
            facts = self._sessions[session_id]['facts']
            if len(facts) > self.max_facts_per_session:
                # Remove oldest facts
                sorted_facts = sorted(facts.items(), key=lambda x: x[1].timestamp)
                facts_to_remove = len(facts) - self.max_facts_per_session
                for i in range(facts_to_remove):
                    del facts[sorted_facts[i][0]]
            
            # Try Redis persistence
            if self._redis_client:
                try:
                    key = self._get_facts_key(session_id)
                    facts_data = {k: v.to_dict() for k, v in facts.items()}
                    self._redis_client.setex(
                        key,
                        self.ttl_hours * 3600,
                        json.dumps(facts_data)
                    )
                except Exception as e:
                    logger.warning(f"Failed to persist facts to Redis: {e}")
            
            logger.info(f"Fact added for session {session_id}: {fact_key}={fact.value}")
    
    def get_fact(self, session_id: str, fact_key: str) -> Optional[Fact]:
        """Get a specific fact from the session"""
        with self._lock:
            # Try in-memory first
            if session_id in self._sessions:
                facts = self._sessions[session_id].get('facts', {})
                if fact_key in facts:
                    return facts[fact_key]
            
            # Try Redis if available
            if self._redis_client:
                try:
                    key = self._get_facts_key(session_id)
                    data = self._redis_client.get(key)
                    if data:
                        facts_data = json.loads(data)
                        if fact_key in facts_data:
                            fact = Fact.from_dict(facts_data[fact_key])
                            # Cache in memory
                            if session_id not in self._sessions:
                                self._sessions[session_id] = {}
                            if 'facts' not in self._sessions[session_id]:
                                self._sessions[session_id]['facts'] = {}
                            self._sessions[session_id]['facts'][fact_key] = fact
                            return fact
                except Exception as e:
                    logger.warning(f"Failed to retrieve fact from Redis: {e}")
            
            return None
    
    def get_all_facts(self, session_id: str) -> Dict[str, Fact]:
        """Get all facts for a session"""
        with self._lock:
            # Try in-memory first
            if session_id in self._sessions:
                return self._sessions[session_id].get('facts', {})
            
            # Try Redis if available
            if self._redis_client:
                try:
                    key = self._get_facts_key(session_id)
                    data = self._redis_client.get(key)
                    if data:
                        facts_data = json.loads(data)
                        facts = {k: Fact.from_dict(v) for k, v in facts_data.items()}
                        # Cache in memory 
                        if session_id not in self._sessions:
                            self._sessions[session_id] = {}
                        self._sessions[session_id]['facts'] = facts
                        return facts
                except Exception as e:
                    logger.warning(f"Failed to retrieve facts from Redis: {e}")
            
            return {}
    
    def check_contradiction(self, session_id: str, new_claims: List[Dict[str, Any]]) -> List[str]:
        """Check for contradictions with existing session facts"""
        contradictions = []
        facts = self.get_all_facts(session_id)
        
        for claim in new_claims:
            claim_text = claim.get('text', '').lower()
            claim_value = claim.get('value', '').lower()
            
            for fact_key, fact in facts.items():
                if fact_key in claim_text:
                    if fact.value.lower() != claim_value:
                        contradictions.append(
                            f"Contradiction: Previously found {fact_key}={fact.value} "
                            f"in {fact.source_doc_id}, but now claiming {claim_value}."
                        )
        
        return contradictions
    
    def clear_session(self, session_id: str) -> None:
        """Clear all data for a session"""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
            
            # Clear from Redis if available
            if self._redis_client:
                try:
                    session_key = self._get_session_key(session_id)
                    facts_key = self._get_facts_key(session_id)
                    self._redis_client.delete(session_key, facts_key)
                except Exception as e:
                    logger.warning(f"Failed to clear session from Redis: {e}")
            
            logger.info(f"Session {session_id} cleared")
    
    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions and return count of cleaned sessions"""
        current_time = time.time()
        expired_sessions = []
        
        with self._lock:
            for session_id, session_data in self._sessions.items():
                last_updated = session_data.get('last_updated', 0)
                if current_time - last_updated > self.ttl_hours * 3600:
                    expired_sessions.append(session_id)
            
            for session_id in expired_sessions:
                del self._sessions[session_id]
        
        logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")
        return len(expired_sessions)
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get statistics about active sessions"""
        with self._lock:
            total_sessions = len(self._sessions)
            total_facts = sum(
                len(session.get('facts', {})) 
                for session in self._sessions.values()
            )
            
            return {
                'total_sessions': total_sessions,
                'total_facts': total_facts,
                'ttl_hours': self.ttl_hours,
                'max_facts_per_session': self.max_facts_per_session
            }

# Global session memory instance
session_memory = SessionMemory()

def get_session_memory() -> SessionMemory:
    """Get the global session memory instance"""
    return session_memory
