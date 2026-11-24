"""
Unit tests for answer consistency checker module
"""
import pytest
from unittest.mock import Mock, patch

from src.backend.rag.answer_consistency import (
    FactualClaim, ConsistencyCheck, AnswerConsistencyChecker, get_answer_consistency_checker
)
from src.backend.memory.session_kv import ActiveSubject, Fact


class TestFactualClaim:
    """Test FactualClaim dataclass"""
    
    def test_factual_claim_creation(self):
        """Test creating a FactualClaim"""
        claim = FactualClaim(
            text="John Doe's salary is $100,000",
            entity="John Doe",
            attribute="salary",
            value="$100,000",
            confidence=0.9,
            source_chunk="Employee: John Doe, Salary: $100,000"
        )
        
        assert claim.text == "John Doe's salary is $100,000"
        assert claim.entity == "John Doe"
        assert claim.attribute == "salary"
        assert claim.value == "$100,000"
        assert claim.confidence == 0.9
        assert claim.source_chunk == "Employee: John Doe, Salary: $100,000"
    
    def test_factual_claim_defaults(self):
        """Test FactualClaim creation with defaults"""
        claim = FactualClaim(
            text="John Doe's salary is $100,000",
            entity="John Doe",
            attribute="salary"
        )
        
        assert claim.value is None
        assert claim.confidence == 1.0
        assert claim.source_chunk is None
    
    def test_factual_claim_serialization(self):
        """Test FactualClaim serialization to dict"""
        claim = FactualClaim(
            text="John Doe's salary is $100,000",
            entity="John Doe",
            attribute="salary",
            value="$100,000",
            confidence=0.9,
            source_chunk="Employee: John Doe, Salary: $100,000"
        )
        
        claim_dict = claim.to_dict()
        
        assert claim_dict["text"] == "John Doe's salary is $100,000"
        assert claim_dict["entity"] == "John Doe"
        assert claim_dict["attribute"] == "salary"
        assert claim_dict["value"] == "$100,000"
        assert claim_dict["confidence"] == 0.9
        assert claim_dict["source_chunk"] == "Employee: John Doe, Salary: $100,000"


class TestConsistencyCheck:
    """Test ConsistencyCheck dataclass"""
    
    def test_consistency_check_creation(self):
        """Test creating a ConsistencyCheck"""
        check = ConsistencyCheck(
            is_consistent=True,
            confidence_score=0.95,
            contradictions=[],
            missing_context=[],
            suggestions=["Add more specific salary information"],
            overall_score=0.9
        )
        
        assert check.is_consistent is True
        assert check.confidence_score == 0.95
        assert len(check.contradictions) == 0
        assert len(check.missing_context) == 0
        assert len(check.suggestions) == 1
        assert check.overall_score == 0.9
    
    def test_consistency_check_defaults(self):
        """Test ConsistencyCheck creation with defaults"""
        check = ConsistencyCheck(
            is_consistent=True,
            confidence_score=0.95
        )
        
        assert check.contradictions == []
        assert check.missing_context == []
        assert check.suggestions == []
        assert check.overall_score == 1.0
    
    def test_consistency_check_inconsistent(self):
        """Test ConsistencyCheck for inconsistent answers"""
        check = ConsistencyCheck(
            is_consistent=False,
            confidence_score=0.3,
            contradictions=["Salary amount differs from session facts"],
            missing_context=["No active subject context"],
            suggestions=["Verify salary from HR records"],
            overall_score=0.4
        )
        
        assert check.is_consistent is False
        assert check.confidence_score == 0.3
        assert len(check.contradictions) == 1
        assert len(check.missing_context) == 1
        assert len(check.suggestions) == 1
        assert check.overall_score == 0.4


class TestAnswerConsistencyChecker:
    """Test AnswerConsistencyChecker class"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.rag.answer_consistency.is_feature_enabled', return_value=True):
            self.checker = AnswerConsistencyChecker()
    
    def test_consistency_checker_initialization(self):
        """Test AnswerConsistencyChecker initialization"""
        assert self.checker.min_consistency_score == 0.7
        assert self.checker.max_claims_per_answer == 15
    
    def test_extract_factual_claims_from_answer(self):
        """Test extracting factual claims from answer text"""
        answer = "John Doe's salary is $100,000 and he works in Engineering. His email is john@company.com."
        
        claims = self.checker.extract_factual_claims_from_answer(answer)
        
        assert len(claims) >= 3  # Should extract multiple claims
        
        # Check for salary claim
        salary_claims = [c for c in claims if c.attribute == "salary"]
        assert len(salary_claims) >= 1
        
        # Check for department claim
        dept_claims = [c for c in claims if c.attribute == "department"]
        assert len(dept_claims) >= 1
        
        # Check for email claim
        email_claims = [c for c in claims if c.attribute == "email"]
        assert len(email_claims) >= 1
    
    def test_extract_factual_claims_with_confidence(self):
        """Test claim extraction with confidence scoring"""
        answer = "John Doe's salary is $100,000 according to HR records."
        
        claims = self.checker.extract_factual_claims_from_answer(answer)
        
        assert len(claims) >= 1
        
        # High confidence for explicit statements
        salary_claim = next((c for c in claims if c.attribute == "salary"), None)
        assert salary_claim is not None
        assert salary_claim.confidence > 0.8
    
    def test_check_consistency_with_session_facts(self):
        """Test checking consistency with session facts"""
        # Mock session memory with facts
        mock_session_memory = Mock()
        mock_session_memory.get_session_facts.return_value = {
            "john_doe_salary": Fact(
                key="john_doe_salary",
                value="$100,000",
                source="HR records",
                timestamp=1234567890
            ),
            "john_doe_department": Fact(
                key="john_doe_department",
                value="Engineering",
                source="HR records",
                timestamp=1234567890
            )
        }
        
        with patch('src.backend.rag.answer_consistency.get_session_memory', return_value=mock_session_memory):
            answer = "John Doe's salary is $100,000 and he works in Engineering."
            
            check = self.checker.check_consistency_with_session_facts("test_session", answer)
            
            assert check.is_consistent is True
            assert check.confidence_score > 0.8
            assert len(check.contradictions) == 0
    
    def test_check_consistency_with_session_facts_contradiction(self):
        """Test checking consistency with contradictory session facts"""
        # Mock session memory with facts
        mock_session_memory = Mock()
        mock_session_memory.get_session_facts.return_value = {
            "john_doe_salary": Fact(
                key="john_doe_salary",
                value="$150,000",  # Different from answer
                source="HR records",
                timestamp=1234567890
            )
        }
        
        with patch('src.backend.rag.answer_consistency.get_session_memory', return_value=mock_session_memory):
            answer = "John Doe's salary is $100,000."
            
            check = self.checker.check_consistency_with_session_facts("test_session", answer)
            
            assert check.is_consistent is False
            assert check.confidence_score < 0.7
            assert len(check.contradictions) >= 1
            assert "salary" in str(check.contradictions).lower()
    
    def test_check_consistency_with_active_subject(self):
        """Test checking consistency with active subject"""
        # Mock session memory with active subject
        mock_session_memory = Mock()
        active_subject = ActiveSubject(
            employee_id="123",
            canonical_name="John Doe",
            department="Engineering",
            job_title="Senior Developer"
        )
        mock_session_memory.get_active_subject.return_value = active_subject
        
        with patch('src.backend.rag.answer_consistency.get_session_memory', return_value=mock_session_memory):
            answer = "John Doe's salary is $100,000 and he works in Engineering."
            
            check = self.checker.check_consistency_with_active_subject("test_session", answer)
            
            assert check.is_consistent is True
            assert check.confidence_score > 0.8
            assert len(check.contradictions) == 0
    
    def test_check_consistency_with_active_subject_mismatch(self):
        """Test checking consistency with mismatched active subject"""
        # Mock session memory with active subject
        mock_session_memory = Mock()
        active_subject = ActiveSubject(
            employee_id="123",
            canonical_name="John Doe",
            department="Engineering"
        )
        mock_session_memory.get_active_subject.return_value = active_subject
        
        with patch('src.backend.rag.answer_consistency.get_session_memory', return_value=mock_session_memory):
            answer = "Jane Smith's salary is $80,000 and she works in HR."
            
            check = self.checker.check_consistency_with_active_subject("test_session", answer)
            
            assert check.is_consistent is False
            assert check.confidence_score < 0.7
            assert len(check.contradictions) >= 1
            assert "entity" in str(check.contradictions).lower()
    
    def test_check_answer_consistency(self):
        """Test complete answer consistency check"""
        # Mock session memory
        mock_session_memory = Mock()
        mock_session_memory.get_session_facts.return_value = {
            "john_doe_salary": Fact(
                key="john_doe_salary",
                value="$100,000",
                source="HR records",
                timestamp=1234567890
            )
        }
        active_subject = ActiveSubject(
            employee_id="123",
            canonical_name="John Doe",
            department="Engineering"
        )
        mock_session_memory.get_active_subject.return_value = active_subject
        
        with patch('src.backend.rag.answer_consistency.get_session_memory', return_value=mock_session_memory):
            answer = "John Doe's salary is $100,000 and he works in Engineering."
            
            check = self.checker.check_answer_consistency("test_session", answer)
            
            assert check.is_consistent is True
            assert check.confidence_score > 0.8
            assert check.overall_score > 0.8
    
    def test_check_answer_consistency_with_contradictions(self):
        """Test answer consistency check with contradictions"""
        # Mock session memory with contradictory facts
        mock_session_memory = Mock()
        mock_session_memory.get_session_facts.return_value = {
            "john_doe_salary": Fact(
                key="john_doe_salary",
                value="$150,000",  # Different from answer
                source="HR records",
                timestamp=1234567890
            )
        }
        active_subject = ActiveSubject(
            employee_id="123",
            canonical_name="John Doe",
            department="Engineering"
        )
        mock_session_memory.get_active_subject.return_value = active_subject
        
        with patch('src.backend.rag.answer_consistency.get_session_memory', return_value=mock_session_memory):
            answer = "John Doe's salary is $100,000 and he works in Engineering."
            
            check = self.checker.check_answer_consistency("test_session", answer)
            
            assert check.is_consistent is False
            assert check.confidence_score < 0.7
            assert check.overall_score < 0.7
            assert len(check.contradictions) >= 1
    
    def test_detect_contradictions_between_claims(self):
        """Test detecting contradictions between claims"""
        claims = [
            FactualClaim(
                text="John Doe's salary is $100,000",
                entity="John Doe",
                attribute="salary",
                value="$100,000"
            ),
            FactualClaim(
                text="John Doe's salary is $150,000",
                entity="John Doe",
                attribute="salary",
                value="$150,000"
            )
        ]
        
        contradictions = self.checker.detect_contradictions_between_claims(claims)
        
        assert len(contradictions) >= 1
        assert "salary" in str(contradictions).lower()
    
    def test_detect_contradictions_no_conflicts(self):
        """Test detecting contradictions when none exist"""
        claims = [
            FactualClaim(
                text="John Doe's salary is $100,000",
                entity="John Doe",
                attribute="salary",
                value="$100,000"
            ),
            FactualClaim(
                text="John Doe works in Engineering",
                entity="John Doe",
                attribute="department",
                value="Engineering"
            )
        ]
        
        contradictions = self.checker.detect_contradictions_between_claims(claims)
        
        assert len(contradictions) == 0
    
    def test_detect_contradictions_with_session_facts(self):
        """Test detecting contradictions with session facts"""
        # Mock session memory with facts
        mock_session_memory = Mock()
        mock_session_memory.get_session_facts.return_value = {
            "john_doe_salary": Fact(
                key="john_doe_salary",
                value="$150,000",
                source="HR records",
                timestamp=1234567890
            )
        }
        
        with patch('src.backend.rag.answer_consistency.get_session_memory', return_value=mock_session_memory):
            claims = [
                FactualClaim(
                    text="John Doe's salary is $100,000",
                    entity="John Doe",
                    attribute="salary",
                    value="$100,000"
                )
            ]
            
            contradictions = self.checker.detect_contradictions_with_session_facts("test_session", claims)
            
            assert len(contradictions) >= 1
            assert "salary" in str(contradictions).lower()
    
    def test_calculate_consistency_score(self):
        """Test calculating consistency score"""
        claims = [
            FactualClaim(
                text="John Doe's salary is $100,000",
                entity="John Doe",
                attribute="salary",
                value="$100,000",
                confidence=0.9
            ),
            FactualClaim(
                text="John Doe works in Engineering",
                entity="John Doe",
                attribute="department",
                value="Engineering",
                confidence=0.8
            )
        ]
        
        score = self.checker.calculate_consistency_score(claims)
        
        assert 0.8 <= score <= 0.9
    
    def test_generate_consistency_suggestions(self):
        """Test generating consistency suggestions"""
        check = ConsistencyCheck(
            is_consistent=False,
            confidence_score=0.5,
            contradictions=["Salary amount differs from session facts"],
            missing_context=["No active subject context"]
        )
        
        suggestions = self.checker.generate_consistency_suggestions(check)
        
        assert len(suggestions) >= 1
        assert any("salary" in s.lower() for s in suggestions)
        assert any("context" in s.lower() for s in suggestions)
    
    def test_validate_claim_against_fact(self):
        """Test validating a claim against a session fact"""
        claim = FactualClaim(
            text="John Doe's salary is $100,000",
            entity="John Doe",
            attribute="salary",
            value="$100,000"
        )
        
        fact = Fact(
            key="john_doe_salary",
            value="$100,000",
            source="HR records",
            timestamp=1234567890
        )
        
        is_consistent, confidence = self.checker.validate_claim_against_fact(claim, fact)
        
        assert is_consistent is True
        assert confidence > 0.8
    
    def test_validate_claim_against_fact_mismatch(self):
        """Test validating a claim against a mismatched fact"""
        claim = FactualClaim(
            text="John Doe's salary is $100,000",
            entity="John Doe",
            attribute="salary",
            value="$100,000"
        )
        
        fact = Fact(
            key="john_doe_salary",
            value="$150,000",  # Different value
            source="HR records",
            timestamp=1234567890
        )
        
        is_consistent, confidence = self.checker.validate_claim_against_fact(claim, fact)
        
        assert is_consistent is False
        assert confidence < 0.5


class TestAnswerConsistencyCheckerFeatureFlags:
    """Test AnswerConsistencyChecker with feature flags"""
    
    def test_feature_disabled(self):
        """Test checker behavior when feature is disabled"""
        with patch('src.backend.rag.answer_consistency.is_feature_enabled', return_value=False):
            checker = AnswerConsistencyChecker()
            
            answer = "John Doe's salary is $100,000"
            
            # Should return consistent check when feature is disabled
            check = checker.check_answer_consistency("test_session", answer)
            assert check.is_consistent is True
            assert check.confidence_score == 1.0
            assert check.overall_score == 1.0


class TestAnswerConsistencyCheckerEdgeCases:
    """Test AnswerConsistencyChecker edge cases"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.rag.answer_consistency.is_feature_enabled', return_value=True):
            self.checker = AnswerConsistencyChecker()
    
    def test_empty_answer_consistency(self):
        """Test checking consistency of empty answer"""
        answer = ""
        
        check = self.checker.check_answer_consistency("test_session", answer)
        
        assert check.is_consistent is True
        assert check.confidence_score == 1.0
        assert check.overall_score == 1.0
    
    def test_whitespace_only_answer(self):
        """Test checking consistency of whitespace-only answer"""
        answer = "   \n\t  "
        
        check = self.checker.check_answer_consistency("test_session", answer)
        
        assert check.is_consistent is True
        assert check.confidence_score == 1.0
        assert check.overall_score == 1.0
    
    def test_very_long_answer(self):
        """Test checking consistency of very long answer"""
        answer = "John Doe's salary is $100,000. " * 100  # Very long answer
        
        check = self.checker.check_answer_consistency("test_session", answer)
        
        # Should still work but may take longer
        assert check.confidence_score > 0.5
    
    def test_answer_with_no_factual_claims(self):
        """Test checking consistency of answer with no factual claims"""
        answer = "Hello, how can I help you today?"
        
        check = self.checker.check_answer_consistency("test_session", answer)
        
        # Should handle gracefully
        assert check.is_consistent is True
        assert check.confidence_score == 1.0
    
    def test_answer_with_ambiguous_claims(self):
        """Test checking consistency of answer with ambiguous claims"""
        answer = "The employee's salary is around $100,000 and they work in some department."
        
        check = self.checker.check_answer_consistency("test_session", answer)
        
        # Should detect low confidence due to ambiguity
        assert check.confidence_score < 0.8
    
    def test_answer_with_mixed_confidence_claims(self):
        """Test checking consistency of answer with mixed confidence claims"""
        answer = "John Doe's salary is $100,000 (high confidence) and he might work in Engineering (uncertain)."
        
        check = self.checker.check_answer_consistency("test_session", answer)
        
        # Should average the confidence scores
        assert 0.5 < check.confidence_score < 1.0


class TestAnswerConsistencyCheckerIntegration:
    """Test AnswerConsistencyChecker integration scenarios"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.rag.answer_consistency.is_feature_enabled', return_value=True):
            self.checker = AnswerConsistencyChecker()
    
    def test_complete_consistency_workflow(self):
        """Test complete consistency workflow"""
        # Mock session memory with comprehensive data
        mock_session_memory = Mock()
        mock_session_memory.get_session_facts.return_value = {
            "john_doe_salary": Fact(
                key="john_doe_salary",
                value="$100,000",
                source="HR records",
                timestamp=1234567890
            ),
            "john_doe_department": Fact(
                key="john_doe_department",
                value="Engineering",
                source="HR records",
                timestamp=1234567890
            ),
            "john_doe_start_date": Fact(
                key="john_doe_start_date",
                value="2020-01-01",
                source="HR records",
                timestamp=1234567890
            )
        }
        
        active_subject = ActiveSubject(
            employee_id="123",
            canonical_name="John Doe",
            department="Engineering",
            job_title="Senior Developer"
        )
        mock_session_memory.get_active_subject.return_value = active_subject
        
        with patch('src.backend.rag.answer_consistency.get_session_memory', return_value=mock_session_memory):
            # Test consistent answer
            consistent_answer = "John Doe's salary is $100,000 and he works in Engineering. He started on 2020-01-01."
            
            check = self.checker.check_answer_consistency("test_session", consistent_answer)
            
            assert check.is_consistent is True
            assert check.confidence_score > 0.8
            assert check.overall_score > 0.8
            assert len(check.contradictions) == 0
            
            # Test inconsistent answer
            inconsistent_answer = "John Doe's salary is $150,000 and he works in Marketing. He started on 2021-01-01."
            
            check = self.checker.check_answer_consistency("test_session", inconsistent_answer)
            
            assert check.is_consistent is False
            assert check.confidence_score < 0.7
            assert check.overall_score < 0.7
            assert len(check.contradictions) >= 1
    
    def test_consistency_with_entity_variations(self):
        """Test consistency with entity name variations"""
        # Mock session memory
        mock_session_memory = Mock()
        mock_session_memory.get_session_facts.return_value = {}
        active_subject = ActiveSubject(
            employee_id="123",
            canonical_name="John Doe",
            department="Engineering"
        )
        mock_session_memory.get_active_subject.return_value = active_subject
        
        with patch('src.backend.rag.answer_consistency.get_session_memory', return_value=mock_session_memory):
            # Test with variations of the same entity
            answer = "John's salary is $100,000 and he works in Engineering"
            
            check = self.checker.check_answer_consistency("test_session", answer)
            
            # Should handle "John" as variation of "John Doe"
            assert check.is_consistent is True
            assert check.confidence_score > 0.7


class TestGlobalFunctions:
    """Test global functions"""
    
    def test_get_consistency_checker(self):
        """Test get_answer_consistency_checker function"""
        checker = get_answer_consistency_checker()
        assert isinstance(checker, AnswerConsistencyChecker)
        
        # Should return the same instance
        checker2 = get_answer_consistency_checker()
        assert checker is checker2


if __name__ == "__main__":
    pytest.main([__file__])
