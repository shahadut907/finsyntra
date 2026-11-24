"""
Unit tests for query rewriter module
"""
import pytest
from unittest.mock import Mock, patch

from src.backend.rag.query_rewriter import (
    QueryRewriter, RewrittenQuery, get_query_rewriter
)
from src.backend.memory.session_kv import ActiveSubject


class TestRewrittenQuery:
    """Test RewrittenQuery dataclass"""
    
    def test_rewritten_query_creation(self):
        """Test creating a RewrittenQuery"""
        query = RewrittenQuery(
            original_query="What is his salary?",
            rewritten_query="What is John Doe's salary?",
            active_subject=None,
            confidence=0.9,
            changes_made=["Resolved 'his' to 'John Doe'"]
        )
        
        assert query.original_query == "What is his salary?"
        assert query.rewritten_query == "What is John Doe's salary?"
        assert query.active_subject is None
        assert query.confidence == 0.9
        assert len(query.changes_made) == 1
        assert "Resolved 'his' to 'John Doe'" in query.changes_made


class TestQueryRewriter:
    """Test QueryRewriter class"""
    
    def setup_method(self):
        """Setup test method"""
        # Mock session memory
        self.mock_session_memory = Mock()
        with patch('src.backend.rag.query_rewriter.get_session_memory', return_value=self.mock_session_memory):
            self.query_rewriter = QueryRewriter()
    
    def test_query_rewriter_initialization(self):
        """Test QueryRewriter initialization"""
        assert self.query_rewriter.session_memory == self.mock_session_memory
        assert len(self.query_rewriter.pronoun_patterns) > 0
        assert len(self.query_rewriter.subject_indicators) > 0
    
    def test_rewrite_query_feature_disabled(self):
        """Test query rewriting when feature is disabled"""
        with patch('src.backend.rag.query_rewriter.is_feature_enabled', return_value=False):
            result = self.query_rewriter.rewrite_query("test_session", "What is his salary?")
            
            assert result.original_query == "What is his salary?"
            assert result.rewritten_query == "What is his salary?"
            assert result.active_subject is None
            assert result.confidence == 1.0
            assert len(result.changes_made) == 0
    
    def test_rewrite_query_no_active_subject(self):
        """Test query rewriting when no active subject exists"""
        with patch('src.backend.rag.query_rewriter.is_feature_enabled', return_value=True):
            self.mock_session_memory.get_active_subject.return_value = None
            
            result = self.query_rewriter.rewrite_query("test_session", "What is his salary?")
            
            assert result.original_query == "What is his salary?"
            assert result.rewritten_query == "What is his salary?"
            assert result.active_subject is None
            assert result.confidence == 1.0
            assert len(result.changes_made) == 0
    
    def test_rewrite_query_with_pronouns(self):
        """Test query rewriting with pronouns"""
        with patch('src.backend.rag.query_rewriter.is_feature_enabled', return_value=True):
            active_subject = ActiveSubject(
                employee_id="123",
                canonical_name="John Doe",
                department="Engineering"
            )
            self.mock_session_memory.get_active_subject.return_value = active_subject
            
            result = self.query_rewriter.rewrite_query("test_session", "What is his salary?")
            
            assert result.original_query == "What is his salary?"
            assert result.rewritten_query == "What is John Doe's salary?"
            assert result.active_subject == active_subject
            assert result.confidence == 0.9
            assert len(result.changes_made) == 1
            assert "Resolved 'he/him/his' to 'John Doe'" in result.changes_made[0]
    
    def test_rewrite_query_with_she_pronouns(self):
        """Test query rewriting with 'she' pronouns"""
        with patch('src.backend.rag.query_rewriter.is_feature_enabled', return_value=True):
            active_subject = ActiveSubject(
                employee_id="456",
                canonical_name="Jane Smith",
                department="HR"
            )
            self.mock_session_memory.get_active_subject.return_value = active_subject
            
            result = self.query_rewriter.rewrite_query("test_session", "What is her department?")
            
            assert result.rewritten_query == "What is Jane Smith's department?"
            assert result.confidence == 0.9
            assert "Resolved 'she/her/hers' to 'Jane Smith'" in result.changes_made[0]
    
    def test_rewrite_query_with_they_pronouns(self):
        """Test query rewriting with 'they' pronouns"""
        with patch('src.backend.rag.query_rewriter.is_feature_enabled', return_value=True):
            active_subject = ActiveSubject(
                employee_id="789",
                canonical_name="Alex Johnson",
                department="Marketing"
            )
            self.mock_session_memory.get_active_subject.return_value = active_subject
            
            result = self.query_rewriter.rewrite_query("test_session", "What is their job title?")
            
            assert result.rewritten_query == "What is Alex Johnson's job title?"
            assert result.confidence == 0.9
            assert "Resolved 'they/them/their' to 'Alex Johnson'" in result.changes_made[0]
    
    def test_rewrite_query_with_this_person(self):
        """Test query rewriting with 'this person' references"""
        with patch('src.backend.rag.query_rewriter.is_feature_enabled', return_value=True):
            active_subject = ActiveSubject(
                employee_id="123",
                canonical_name="John Doe",
                department="Engineering"
            )
            self.mock_session_memory.get_active_subject.return_value = active_subject
            
            result = self.query_rewriter.rewrite_query("test_session", "What is this person's salary?")
            
            assert result.rewritten_query == "What is John Doe's salary?"
            assert result.confidence == 0.9
            assert "Resolved 'this person' to 'John Doe'" in result.changes_made[0]
    
    def test_rewrite_query_with_employee_id(self):
        """Test query rewriting with employee ID references"""
        with patch('src.backend.rag.query_rewriter.is_feature_enabled', return_value=True):
            active_subject = ActiveSubject(
                employee_id="123",
                canonical_name="John Doe",
                department="Engineering"
            )
            self.mock_session_memory.get_active_subject.return_value = active_subject
            
            result = self.query_rewriter.rewrite_query("test_session", "What is employee 123's salary?")
            
            assert result.rewritten_query == "What is John Doe's salary?"
            assert result.confidence == 0.95
            assert "Resolved employee ID reference to 'John Doe'" in result.changes_made[0]
    
    def test_rewrite_query_needs_subject_context(self):
        """Test query rewriting that needs subject context"""
        with patch('src.backend.rag.query_rewriter.is_feature_enabled', return_value=True):
            active_subject = ActiveSubject(
                employee_id="123",
                canonical_name="John Doe",
                department="Engineering"
            )
            self.mock_session_memory.get_active_subject.return_value = active_subject
            
            result = self.query_rewriter.rewrite_query("test_session", "What is the salary?")
            
            assert result.rewritten_query == "John Doe's salary?"
            assert result.confidence == 0.9
            assert "Added subject context: 'John Doe'" in result.changes_made[0]
    
    def test_rewrite_query_no_changes_needed(self):
        """Test query rewriting when no changes are needed"""
        with patch('src.backend.rag.query_rewriter.is_feature_enabled', return_value=True):
            active_subject = ActiveSubject(
                employee_id="123",
                canonical_name="John Doe",
                department="Engineering"
            )
            self.mock_session_memory.get_active_subject.return_value = active_subject
            
            result = self.query_rewriter.rewrite_query("test_session", "What is John Doe's salary?")
            
            assert result.original_query == "What is John Doe's salary?"
            assert result.rewritten_query == "What is John Doe's salary?"
            assert result.confidence == 1.0
            assert len(result.changes_made) == 0
    
    def test_contains_references_with_pronouns(self):
        """Test reference detection with pronouns"""
        assert self.query_rewriter._contains_references("What is his salary?") is True
        assert self.query_rewriter._contains_references("What is her department?") is True
        assert self.query_rewriter._contains_references("What is their job title?") is True
        assert self.query_rewriter._contains_references("What is this person's email?") is True
    
    def test_contains_references_with_subject_indicators(self):
        """Test reference detection with subject indicators"""
        assert self.query_rewriter._contains_references("What is the salary?") is True
        assert self.query_rewriter._contains_references("What is the email?") is True
        assert self.query_rewriter._contains_references("What is the job title?") is True
    
    def test_contains_references_with_explicit_subject(self):
        """Test reference detection with explicit subjects"""
        assert self.query_rewriter._contains_references("What is John Doe's salary?") is False
        assert self.query_rewriter._contains_references("What is john@example.com?") is False
        assert self.query_rewriter._contains_references("What is employee 123's salary?") is False
    
    def test_has_explicit_subject(self):
        """Test explicit subject detection"""
        assert self.query_rewriter._has_explicit_subject("What is John Doe's salary?") is True
        assert self.query_rewriter._has_explicit_subject("What is john@example.com?") is True
        assert self.query_rewriter._has_explicit_subject("What is employee 123's salary?") is True
        assert self.query_rewriter._has_explicit_subject("What is the salary?") is False
    
    def test_needs_subject_context(self):
        """Test subject context need detection"""
        assert self.query_rewriter._needs_subject_context("What is the salary?") is True
        assert self.query_rewriter._needs_subject_context("What is the email?") is True
        assert self.query_rewriter._needs_subject_context("What is the job title?") is True
        assert self.query_rewriter._needs_subject_context("What is the weather?") is False
        assert self.query_rewriter._needs_subject_context("What is John Doe's salary?") is False
    
    def test_get_disambiguation_suggestions(self):
        """Test disambiguation suggestion generation"""
        candidates = [
            {"name": "John Doe", "employee_id": "123", "department": "Engineering"},
            {"name": "Jane Smith", "employee_id": "456", "department": "HR"}
        ]
        
        suggestions = self.query_rewriter.get_disambiguation_suggestions("What is John's salary?", candidates)
        
        assert len(suggestions) == 2
        assert "John Doe (ID: 123, Dept: Engineering)" in suggestions
        assert "Jane Smith (ID: 456, Dept: HR)" in suggestions
    
    def test_validate_rewrite(self):
        """Test rewrite validation"""
        assert self.query_rewriter.validate_rewrite("Original query", "Rewritten query") is True
        assert self.query_rewriter.validate_rewrite("Original query", "") is False
        assert self.query_rewriter.validate_rewrite("Original query", "Short") is False
        assert self.query_rewriter.validate_rewrite("Original query", "A") is False


class TestQueryRewriterEdgeCases:
    """Test QueryRewriter edge cases"""
    
    def setup_method(self):
        """Setup test method"""
        self.mock_session_memory = Mock()
        with patch('src.backend.rag.query_rewriter.get_session_memory', return_value=self.mock_session_memory):
            self.query_rewriter = QueryRewriter()
    
    def test_rewrite_query_multiple_pronouns(self):
        """Test query rewriting with multiple pronouns"""
        with patch('src.backend.rag.query_rewriter.is_feature_enabled', return_value=True):
            active_subject = ActiveSubject(
                employee_id="123",
                canonical_name="John Doe",
                department="Engineering"
            )
            self.mock_session_memory.get_active_subject.return_value = active_subject
            
            result = self.query_rewriter.rewrite_query("test_session", "What is his salary and his department?")
            
            # Should resolve both pronouns
            assert "John Doe" in result.rewritten_query
            assert result.confidence < 1.0
    
    def test_rewrite_query_mixed_references(self):
        """Test query rewriting with mixed references"""
        with patch('src.backend.rag.query_rewriter.is_feature_enabled', return_value=True):
            active_subject = ActiveSubject(
                employee_id="123",
                canonical_name="John Doe",
                department="Engineering"
            )
            self.mock_session_memory.get_active_subject.return_value = active_subject
            
            result = self.query_rewriter.rewrite_query("test_session", "What is his salary and Jane's email?")
            
            # Should resolve 'his' but leave 'Jane' as is
            assert "John Doe's salary" in result.rewritten_query
            assert "Jane's email" in result.rewritten_query
    
    def test_rewrite_query_case_insensitive(self):
        """Test query rewriting is case insensitive"""
        with patch('src.backend.rag.query_rewriter.is_feature_enabled', return_value=True):
            active_subject = ActiveSubject(
                employee_id="123",
                canonical_name="John Doe",
                department="Engineering"
            )
            self.mock_session_memory.get_active_subject.return_value = active_subject
            
            result = self.query_rewriter.rewrite_query("test_session", "What is HIS salary?")
            
            assert result.rewritten_query == "What is John Doe's salary?"
            assert result.confidence == 0.9
    
    def test_rewrite_query_no_canonical_name(self):
        """Test query rewriting when active subject has no canonical name"""
        with patch('src.backend.rag.query_rewriter.is_feature_enabled', return_value=True):
            active_subject = ActiveSubject(
                employee_id="123",
                canonical_name=None,
                department="Engineering"
            )
            self.mock_session_memory.get_active_subject.return_value = active_subject
            
            result = self.query_rewriter.rewrite_query("test_session", "What is his salary?")
            
            # Should not rewrite without canonical name
            assert result.rewritten_query == "What is his salary?"
            assert result.confidence == 0.6
    
    def test_rewrite_query_empty_query(self):
        """Test query rewriting with empty query"""
        with patch('src.backend.rag.query_rewriter.is_feature_enabled', return_value=True):
            result = self.query_rewriter.rewrite_query("test_session", "")
            
            assert result.original_query == ""
            assert result.rewritten_query == ""
            assert result.confidence == 1.0
    
    def test_rewrite_query_whitespace_only(self):
        """Test query rewriting with whitespace-only query"""
        with patch('src.backend.rag.query_rewriter.is_feature_enabled', return_value=True):
            result = self.query_rewriter.rewrite_query("test_session", "   ")
            
            assert result.original_query == "   "
            assert result.rewritten_query == "   "
            assert result.confidence == 1.0


class TestQueryRewriterIntegration:
    """Test QueryRewriter integration scenarios"""
    
    def setup_method(self):
        """Setup test method"""
        self.mock_session_memory = Mock()
        with patch('src.backend.rag.query_rewriter.get_session_memory', return_value=self.mock_session_memory):
            self.query_rewriter = QueryRewriter()
    
    def test_complete_conversation_flow(self):
        """Test complete conversation flow with query rewriting"""
        with patch('src.backend.rag.query_rewriter.is_feature_enabled', return_value=True):
            active_subject = ActiveSubject(
                employee_id="123",
                canonical_name="John Doe",
                department="Engineering",
                job_title="Senior Developer"
            )
            self.mock_session_memory.get_active_subject.return_value = active_subject
            
            # Simulate conversation flow
            queries = [
                "What is his salary?",
                "What department does he work in?",
                "What is his job title?",
                "Can you tell me about this person's manager?"
            ]
            
            expected_rewrites = [
                "What is John Doe's salary?",
                "What department does John Doe work in?",
                "What is John Doe's job title?",
                "Can you tell me about John Doe's manager?"
            ]
            
            for i, query in enumerate(queries):
                result = self.query_rewriter.rewrite_query("test_session", query)
                assert result.rewritten_query == expected_rewrites[i]
                assert result.confidence >= 0.9
                assert len(result.changes_made) > 0
    
    def test_query_rewriting_with_context_switching(self):
        """Test query rewriting when context switches between entities"""
        with patch('src.backend.rag.query_rewriter.is_feature_enabled', return_value=True):
            # First entity
            entity1 = ActiveSubject(
                employee_id="123",
                canonical_name="John Doe",
                department="Engineering"
            )
            
            # Second entity
            entity2 = ActiveSubject(
                employee_id="456",
                canonical_name="Jane Smith",
                department="HR"
            )
            
            # Simulate context switching
            self.mock_session_memory.get_active_subject.return_value = entity1
            result1 = self.query_rewriter.rewrite_query("test_session", "What is his salary?")
            assert "John Doe" in result1.rewritten_query
            
            self.mock_session_memory.get_active_subject.return_value = entity2
            result2 = self.query_rewriter.rewrite_query("test_session", "What is her salary?")
            assert "Jane Smith" in result2.rewritten_query


class TestGlobalFunctions:
    """Test global functions"""
    
    def test_get_query_rewriter(self):
        """Test get_query_rewriter function"""
        query_rewriter = get_query_rewriter()
        assert isinstance(query_rewriter, QueryRewriter)
        
        # Should return the same instance
        query_rewriter2 = get_query_rewriter()
        assert query_rewriter is query_rewriter2


if __name__ == "__main__":
    pytest.main([__file__])
