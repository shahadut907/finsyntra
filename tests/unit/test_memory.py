"""
Unit tests for session memory module
"""
import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from src.backend.memory.session_kv import (
    SessionMemory, ActiveSubject, Fact, get_session_memory
)


class TestActiveSubject:
    """Test ActiveSubject dataclass"""
    
    def test_active_subject_creation(self):
        """Test creating an ActiveSubject"""
        subject = ActiveSubject(
            employee_id="123",
            email="test@example.com",
            canonical_name="Test User",
            department="Engineering",
            job_title="Developer"
        )
        
        assert subject.employee_id == "123"
        assert subject.email == "test@example.com"
        assert subject.canonical_name == "Test User"
        assert subject.department == "Engineering"
        assert subject.job_title == "Developer"
        assert subject.confidence == 0.0
        assert subject.last_updated is not None
    
    def test_active_subject_defaults(self):
        """Test ActiveSubject with default values"""
        subject = ActiveSubject()
        
        assert subject.employee_id is None
        assert subject.email is None
        assert subject.canonical_name is None
        assert subject.department is None
        assert subject.job_title is None
        assert subject.confidence == 0.0
        assert subject.last_updated is not None
    
    def test_active_subject_serialization(self):
        """Test ActiveSubject serialization to/from dict"""
        subject = ActiveSubject(
            employee_id="123",
            canonical_name="Test User",
            department="Engineering"
        )
        
        # Convert to dict
        subject_dict = subject.to_dict()
        assert isinstance(subject_dict, dict)
        assert subject_dict['employee_id'] == "123"
        assert subject_dict['canonical_name'] == "Test User"
        assert 'last_updated' in subject_dict
        
        # Convert back from dict
        restored_subject = ActiveSubject.from_dict(subject_dict)
        assert restored_subject.employee_id == subject.employee_id
        assert restored_subject.canonical_name == subject.canonical_name
        assert restored_subject.department == subject.department


class TestFact:
    """Test Fact dataclass"""
    
    def test_fact_creation(self):
        """Test creating a Fact"""
        fact = Fact(
            value="Test Value",
            source_doc_id="doc123",
            chunk_id="chunk456",
            timestamp=datetime.now()
        )
        
        assert fact.value == "Test Value"
        assert fact.source_doc_id == "doc123"
        assert fact.chunk_id == "chunk456"
        assert fact.confidence == 1.0
        assert fact.timestamp is not None
    
    def test_fact_defaults(self):
        """Test Fact with default values"""
        fact = Fact(
            value="Test Value",
            source_doc_id="doc123",
            chunk_id="chunk456"
        )
        
        assert fact.value == "Test Value"
        assert fact.source_doc_id == "doc123"
        assert fact.chunk_id == "chunk456"
        assert fact.confidence == 1.0
        assert fact.timestamp is not None
    
    def test_fact_serialization(self):
        """Test Fact serialization to/from dict"""
        fact = Fact(
            value="Test Value",
            source_doc_id="doc123",
            chunk_id="chunk456"
        )
        
        # Convert to dict
        fact_dict = fact.to_dict()
        assert isinstance(fact_dict, dict)
        assert fact_dict['value'] == "Test Value"
        assert fact_dict['source_doc_id'] == "doc123"
        assert 'timestamp' in fact_dict
        
        # Convert back from dict
        restored_fact = Fact.from_dict(fact_dict)
        assert restored_fact.value == fact.value
        assert restored_fact.source_doc_id == fact.source_doc_id
        assert restored_fact.chunk_id == fact.chunk_id


class TestSessionMemory:
    """Test SessionMemory class"""
    
    def setup_method(self):
        """Setup test method"""
        self.session_memory = SessionMemory(ttl_hours=1, max_facts_per_session=10)
        self.session_id = "test_session_123"
        self.test_subject = ActiveSubject(
            employee_id="123",
            canonical_name="Test User",
            department="Engineering"
        )
        self.test_fact = Fact(
            value="Test Fact",
            source_doc_id="doc123",
            chunk_id="chunk456"
        )
    
    def test_session_memory_initialization(self):
        """Test SessionMemory initialization"""
        assert self.session_memory.ttl_hours == 1
        assert self.session_memory.max_facts_per_session == 10
        assert self.session_memory._sessions == {}
        assert self.session_memory._redis_client is None
    
    def test_set_active_subject(self):
        """Test setting active subject"""
        self.session_memory.set_active_subject(self.session_id, self.test_subject)
        
        # Check in-memory storage
        stored_subject = self.session_memory._sessions[self.session_id]['active_subject']
        assert stored_subject.employee_id == self.test_subject.employee_id
        assert stored_subject.canonical_name == self.test_subject.canonical_name
        assert stored_subject.department == self.test_subject.department
    
    def test_get_active_subject(self):
        """Test getting active subject"""
        # Set subject first
        self.session_memory.set_active_subject(self.session_id, self.test_subject)
        
        # Get subject
        retrieved_subject = self.session_memory.get_active_subject(self.session_id)
        assert retrieved_subject is not None
        assert retrieved_subject.employee_id == self.test_subject.employee_id
        assert retrieved_subject.canonical_name == self.test_subject.canonical_name
    
    def test_get_active_subject_nonexistent(self):
        """Test getting active subject for nonexistent session"""
        retrieved_subject = self.session_memory.get_active_subject("nonexistent_session")
        assert retrieved_subject is None
    
    def test_add_fact(self):
        """Test adding a fact"""
        self.session_memory.add_fact(self.session_id, "test_fact", self.test_fact)
        
        # Check in-memory storage
        stored_facts = self.session_memory._sessions[self.session_id]['facts']
        assert "test_fact" in stored_facts
        assert stored_facts["test_fact"].value == self.test_fact.value
        assert stored_facts["test_fact"].source_doc_id == self.test_fact.source_doc_id
    
    def test_get_fact(self):
        """Test getting a fact"""
        # Add fact first
        self.session_memory.add_fact(self.session_id, "test_fact", self.test_fact)
        
        # Get fact
        retrieved_fact = self.session_memory.get_fact(self.session_id, "test_fact")
        assert retrieved_fact is not None
        assert retrieved_fact.value == self.test_fact.value
        assert retrieved_fact.source_doc_id == self.test_fact.source_doc_id
    
    def test_get_fact_nonexistent(self):
        """Test getting nonexistent fact"""
        retrieved_fact = self.session_memory.get_fact(self.session_id, "nonexistent_fact")
        assert retrieved_fact is None
    
    def test_get_all_facts(self):
        """Test getting all facts for a session"""
        # Add multiple facts
        fact1 = Fact(value="Fact 1", source_doc_id="doc1", chunk_id="chunk1")
        fact2 = Fact(value="Fact 2", source_doc_id="doc2", chunk_id="chunk2")
        
        self.session_memory.add_fact(self.session_id, "fact1", fact1)
        self.session_memory.add_fact(self.session_id, "fact2", fact2)
        
        # Get all facts
        all_facts = self.session_memory.get_all_facts(self.session_id)
        assert len(all_facts) == 2
        assert "fact1" in all_facts
        assert "fact2" in all_facts
    
    def test_fact_limit_enforcement(self):
        """Test that fact limit is enforced"""
        # Add more facts than the limit
        for i in range(15):
            fact = Fact(
                value=f"Fact {i}",
                source_doc_id=f"doc{i}",
                chunk_id=f"chunk{i}"
            )
            self.session_memory.add_fact(self.session_id, f"fact{i}", fact)
        
        # Check that only max_facts_per_session facts remain
        all_facts = self.session_memory.get_all_facts(self.session_id)
        assert len(all_facts) == 10  # max_facts_per_session
        
        # Check that oldest facts were removed
        assert "fact0" not in all_facts
        assert "fact14" in all_facts  # Newest fact should remain
    
    def test_check_contradiction(self):
        """Test contradiction checking"""
        # Add a fact first
        fact = Fact(value="John is a developer", source_doc_id="doc1", chunk_id="chunk1")
        self.session_memory.add_fact(self.session_id, "john_role", fact)
        
        # Check for contradiction
        new_claims = [
            {"text": "John is a manager", "value": "manager"}
        ]
        
        contradictions = self.session_memory.check_contradiction(self.session_id, new_claims)
        assert len(contradictions) > 0
        assert "Contradiction" in contradictions[0]
    
    def test_clear_session(self):
        """Test clearing a session"""
        # Add subject and facts
        self.session_memory.set_active_subject(self.session_id, self.test_subject)
        self.session_memory.add_fact(self.session_id, "test_fact", self.test_fact)
        
        # Clear session
        self.session_memory.clear_session(self.session_id)
        
        # Verify session is cleared
        assert self.session_id not in self.session_memory._sessions
        retrieved_subject = self.session_memory.get_active_subject(self.session_id)
        assert retrieved_subject is None
    
    def test_cleanup_expired_sessions(self):
        """Test cleanup of expired sessions"""
        # Add a session with old timestamp
        self.session_memory._sessions[self.session_id] = {
            'last_updated': time.time() - 7200  # 2 hours ago
        }
        
        # Cleanup expired sessions
        cleaned_count = self.session_memory.cleanup_expired_sessions()
        assert cleaned_count == 1
        
        # Verify session was removed
        assert self.session_id not in self.session_memory._sessions
    
    def test_get_session_stats(self):
        """Test getting session statistics"""
        # Add some sessions and facts
        self.session_memory.set_active_subject(self.session_id, self.test_subject)
        self.session_memory.add_fact(self.session_id, "fact1", self.test_fact)
        
        stats = self.session_memory.get_session_stats()
        assert stats['total_sessions'] == 1
        assert stats['total_facts'] == 1
        assert stats['ttl_hours'] == 1
        assert stats['max_facts_per_session'] == 10


class TestSessionMemoryRedis:
    """Test SessionMemory with Redis integration"""
    
    def setup_method(self):
        """Setup test method"""
        self.session_memory = SessionMemory()
        self.session_id = "test_session_redis"
        self.test_subject = ActiveSubject(
            employee_id="123",
            canonical_name="Test User",
            department="Engineering"
        )
    
    @patch('redis.asyncio.Redis')
    def test_redis_client_setting(self, mock_redis):
        """Test setting Redis client"""
        mock_client = Mock()
        self.session_memory.set_redis_client(mock_client)
        
        assert self.session_memory._redis_client == mock_client
    
    @patch('redis.asyncio.Redis')
    def test_redis_persistence_active_subject(self, mock_redis):
        """Test Redis persistence for active subject"""
        mock_client = Mock()
        self.session_memory.set_redis_client(mock_client)
        
        # Set active subject
        self.session_memory.set_active_subject(self.session_id, self.test_subject)
        
        # Verify Redis was called
        mock_client.setex.assert_called_once()
        call_args = mock_client.setex.call_args
        assert "finsolve:session:" in call_args[0][0]  # Key
        assert call_args[0][1] == 86400  # TTL (24 hours)
    
    @patch('redis.asyncio.Redis')
    def test_redis_retrieval_active_subject(self, mock_redis):
        """Test Redis retrieval for active subject"""
        mock_client = Mock()
        mock_client.get.return_value = '{"employee_id": "123", "canonical_name": "Test User", "department": "Engineering", "last_updated": "2024-01-01T00:00:00"}'
        self.session_memory.set_redis_client(mock_client)
        
        # Get active subject (should retrieve from Redis)
        retrieved_subject = self.session_memory.get_active_subject(self.session_id)
        
        assert retrieved_subject is not None
        assert retrieved_subject.employee_id == "123"
        assert retrieved_subject.canonical_name == "Test User"
        assert retrieved_subject.department == "Engineering"


class TestGlobalFunctions:
    """Test global functions"""
    
    def test_get_session_memory(self):
        """Test get_session_memory function"""
        session_memory = get_session_memory()
        assert isinstance(session_memory, SessionMemory)
        
        # Should return the same instance
        session_memory2 = get_session_memory()
        assert session_memory is session_memory2


if __name__ == "__main__":
    pytest.main([__file__])
