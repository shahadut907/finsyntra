"""
Unit tests for grounding validator module
"""
import pytest
from unittest.mock import Mock, patch

from src.backend.rag.grounding_validator import (
    GroundedFact, CitationValidation, GroundingValidator, get_grounding_validator
)


class TestGroundedFact:
    """Test GroundedFact dataclass"""
    
    def test_grounded_fact_creation(self):
        """Test creating a GroundedFact"""
        from src.backend.rag.grounding_validator import ValidationResult
        fact = GroundedFact(
            fact_text="John Doe's salary is $100,000",
            source_doc_id="doc1",
            chunk_id="chunk1",
            confidence=0.9,
            validation_result=ValidationResult.VALID,
            supporting_evidence=[],
            contradictions=[]
        )
        
        assert fact.fact_text == "John Doe's salary is $100,000"
        assert fact.source_doc_id == "doc1"
        assert fact.chunk_id == "chunk1"
        assert fact.confidence == 0.9
        assert fact.validation_result == ValidationResult.VALID
    
    def test_claim_defaults(self):
        """Test Claim creation with defaults"""
        claim = Claim(
            text="John Doe's salary is $100,000",
            entity="John Doe",
            attribute="salary"
        )
        
        assert claim.value is None
        assert claim.confidence == 1.0
    
    def test_claim_serialization(self):
        """Test Claim serialization to dict"""
        claim = Claim(
            text="John Doe's salary is $100,000",
            entity="John Doe",
            attribute="salary",
            value="$100,000",
            confidence=0.9
        )
        
        claim_dict = claim.to_dict()
        
        assert claim_dict["text"] == "John Doe's salary is $100,000"
        assert claim_dict["entity"] == "John Doe"
        assert claim_dict["attribute"] == "salary"
        assert claim_dict["value"] == "$100,000"
        assert claim_dict["confidence"] == 0.9


class TestCitationValidation:
    """Test CitationValidation dataclass"""
    
    def test_citation_validation_creation(self):
        """Test creating a CitationValidation"""
        validation = CitationValidation(
            is_valid=True,
            evidence_score=0.95,
            missing_citations=[],
            contradictions=[],
            suggestions=["Add more specific salary information"],
            confidence=0.9
        )
        
        assert validation.is_valid is True
        assert validation.evidence_score == 0.95
        assert len(validation.missing_citations) == 0
        assert len(validation.contradictions) == 0
        assert len(validation.suggestions) == 1
        assert validation.confidence == 0.9
    
    def test_citation_validation_defaults(self):
        """Test CitationValidation creation with defaults"""
        validation = CitationValidation(
            is_valid=True,
            evidence_score=0.95
        )
        
        assert validation.missing_citations == []
        assert validation.contradictions == []
        assert validation.suggestions == []
        assert validation.confidence == 1.0
    
    def test_citation_validation_invalid(self):
        """Test CitationValidation for invalid citations"""
        validation = CitationValidation(
            is_valid=False,
            evidence_score=0.3,
            missing_citations=["John Doe's salary"],
            contradictions=["Salary amount differs from source"],
            suggestions=["Verify salary from HR records"],
            confidence=0.7
        )
        
        assert validation.is_valid is False
        assert validation.evidence_score == 0.3
        assert len(validation.missing_citations) == 1
        assert len(validation.contradictions) == 1
        assert len(validation.suggestions) == 1


class TestGroundingValidator:
    """Test GroundingValidator class"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.rag.grounding_validator.is_feature_enabled', return_value=True):
            self.validator = GroundingValidator()
    
    def test_grounding_validator_initialization(self):
        """Test GroundingValidator initialization"""
        assert self.validator.min_evidence_score == 0.7
        assert self.validator.max_claims_per_answer == 10
    
    def test_extract_claims_from_text(self):
        """Test extracting claims from text"""
        text = "John Doe's salary is $100,000 and he works in Engineering. Jane Smith's email is jane@company.com."
        
        claims = self.validator.extract_claims_from_text(text)
        
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
    
    def test_extract_claims_with_confidence(self):
        """Test claim extraction with confidence scoring"""
        text = "John Doe's salary is $100,000 according to HR records."
        
        claims = self.validator.extract_claims_from_text(text)
        
        assert len(claims) >= 1
        
        # High confidence for explicit statements
        salary_claim = next((c for c in claims if c.attribute == "salary"), None)
        assert salary_claim is not None
        assert salary_claim.confidence > 0.8
    
    def test_validate_claim_against_chunk(self):
        """Test validating a claim against a source chunk"""
        claim = Claim(
            text="John Doe's salary is $100,000",
            entity="John Doe",
            attribute="salary",
            value="$100,000"
        )
        
        chunk_text = "Employee: John Doe, Department: Engineering, Salary: $100,000, Start Date: 2020-01-01"
        
        is_valid, evidence_score = self.validator.validate_claim_against_chunk(claim, chunk_text)
        
        assert is_valid is True
        assert evidence_score > 0.8
    
    def test_validate_claim_against_chunk_mismatch(self):
        """Test validating a claim that doesn't match the chunk"""
        claim = Claim(
            text="John Doe's salary is $150,000",
            entity="John Doe",
            attribute="salary",
            value="$150,000"
        )
        
        chunk_text = "Employee: John Doe, Department: Engineering, Salary: $100,000, Start Date: 2020-01-01"
        
        is_valid, evidence_score = self.validator.validate_claim_against_chunk(claim, chunk_text)
        
        assert is_valid is False
        assert evidence_score < 0.5
    
    def test_validate_claim_against_chunk_partial_match(self):
        """Test validating a claim with partial match"""
        claim = Claim(
            text="John Doe works in Engineering",
            entity="John Doe",
            attribute="department",
            value="Engineering"
        )
        
        chunk_text = "Employee: John Doe, Department: Engineering, Salary: $100,000"
        
        is_valid, evidence_score = self.validator.validate_claim_against_chunk(claim, chunk_text)
        
        assert is_valid is True
        assert evidence_score > 0.7
    
    def test_validate_claim_against_chunk_normalized_values(self):
        """Test validating claims with normalized values"""
        claim = Claim(
            text="John Doe's salary is $100,000",
            entity="John Doe",
            attribute="salary",
            value="$100,000"
        )
        
        # Different formats of the same value
        chunk_texts = [
            "Salary: $100,000",
            "Salary: 100000",
            "Salary: 100,000",
            "Salary: $100000"
        ]
        
        for chunk_text in chunk_texts:
            is_valid, evidence_score = self.validator.validate_claim_against_chunk(claim, chunk_text)
            assert is_valid is True, f"Failed for chunk: {chunk_text}"
            assert evidence_score > 0.7
    
    def test_validate_answer_grounding(self):
        """Test validating entire answer grounding"""
        answer = "John Doe's salary is $100,000 and he works in Engineering. His email is john@company.com."
        
        cited_chunks = [
            "Employee: John Doe, Department: Engineering, Salary: $100,000",
            "Contact: John Doe, Email: john@company.com, Phone: 555-1234"
        ]
        
        validation = self.validator.validate_answer_grounding(answer, cited_chunks)
        
        assert validation.is_valid is True
        assert validation.evidence_score > 0.8
        assert len(validation.missing_citations) == 0
        assert len(validation.contradictions) == 0
    
    def test_validate_answer_grounding_missing_citations(self):
        """Test validating answer with missing citations"""
        answer = "John Doe's salary is $100,000 and he works in Engineering. His manager is Bob Smith."
        
        cited_chunks = [
            "Employee: John Doe, Department: Engineering, Salary: $100,000"
        ]
        
        validation = self.validator.validate_answer_grounding(answer, cited_chunks)
        
        assert validation.is_valid is False
        assert validation.evidence_score < 0.8
        assert len(validation.missing_citations) >= 1
        assert "manager" in str(validation.missing_citations).lower()
    
    def test_validate_answer_grounding_contradictions(self):
        """Test validating answer with contradictions"""
        answer = "John Doe's salary is $150,000 and he works in Engineering."
        
        cited_chunks = [
            "Employee: John Doe, Department: Engineering, Salary: $100,000"
        ]
        
        validation = self.validator.validate_answer_grounding(answer, cited_chunks)
        
        assert validation.is_valid is False
        assert validation.evidence_score < 0.7
        assert len(validation.contradictions) >= 1
        assert "salary" in str(validation.contradictions).lower()
    
    def test_detect_contradictions(self):
        """Test detecting contradictions between claims"""
        claims = [
            Claim(
                text="John Doe's salary is $100,000",
                entity="John Doe",
                attribute="salary",
                value="$100,000"
            ),
            Claim(
                text="John Doe's salary is $150,000",
                entity="John Doe",
                attribute="salary",
                value="$150,000"
            )
        ]
        
        contradictions = self.validator.detect_contradictions(claims)
        
        assert len(contradictions) >= 1
        assert "salary" in str(contradictions).lower()
    
    def test_detect_contradictions_no_conflicts(self):
        """Test detecting contradictions when none exist"""
        claims = [
            Claim(
                text="John Doe's salary is $100,000",
                entity="John Doe",
                attribute="salary",
                value="$100,000"
            ),
            Claim(
                text="John Doe works in Engineering",
                entity="John Doe",
                attribute="department",
                value="Engineering"
            )
        ]
        
        contradictions = self.validator.detect_contradictions(claims)
        
        assert len(contradictions) == 0
    
    def test_calculate_evidence_score(self):
        """Test calculating evidence score for claims"""
        claims = [
            Claim(
                text="John Doe's salary is $100,000",
                entity="John Doe",
                attribute="salary",
                value="$100,000",
                confidence=0.9
            ),
            Claim(
                text="John Doe works in Engineering",
                entity="John Doe",
                attribute="department",
                value="Engineering",
                confidence=0.8
            )
        ]
        
        evidence_score = self.validator.calculate_evidence_score(claims)
        
        assert 0.8 <= evidence_score <= 0.9
    
    def test_generate_validation_suggestions(self):
        """Test generating validation suggestions"""
        validation = CitationValidation(
            is_valid=False,
            evidence_score=0.5,
            missing_citations=["John Doe's manager"],
            contradictions=["Salary amount differs"]
        )
        
        suggestions = self.validator.generate_validation_suggestions(validation)
        
        assert len(suggestions) >= 1
        assert any("manager" in s.lower() for s in suggestions)
        assert any("salary" in s.lower() for s in suggestions)


class TestGroundingValidatorFeatureFlags:
    """Test GroundingValidator with feature flags"""
    
    def test_feature_disabled(self):
        """Test validator behavior when feature is disabled"""
        with patch('src.backend.rag.grounding_validator.is_feature_enabled', return_value=False):
            validator = GroundingValidator()
            
            answer = "John Doe's salary is $100,000"
            cited_chunks = ["Employee: John Doe, Salary: $100,000"]
            
            # Should return valid validation when feature is disabled
            validation = validator.validate_answer_grounding(answer, cited_chunks)
            assert validation.is_valid is True
            assert validation.evidence_score == 1.0


class TestGroundingValidatorEdgeCases:
    """Test GroundingValidator edge cases"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.rag.grounding_validator.is_feature_enabled', return_value=True):
            self.validator = GroundingValidator()
    
    def test_empty_answer_validation(self):
        """Test validating empty answer"""
        answer = ""
        cited_chunks = []
        
        validation = self.validator.validate_answer_grounding(answer, cited_chunks)
        
        assert validation.is_valid is True
        assert validation.evidence_score == 1.0
    
    def test_empty_chunks_validation(self):
        """Test validating answer with empty chunks"""
        answer = "John Doe's salary is $100,000"
        cited_chunks = []
        
        validation = self.validator.validate_answer_grounding(answer, cited_chunks)
        
        assert validation.is_valid is False
        assert validation.evidence_score == 0.0
        assert len(validation.missing_citations) >= 1
    
    def test_whitespace_only_answer(self):
        """Test validating whitespace-only answer"""
        answer = "   \n\t  "
        cited_chunks = ["Some content"]
        
        validation = self.validator.validate_answer_grounding(answer, cited_chunks)
        
        assert validation.is_valid is True
        assert validation.evidence_score == 1.0
    
    def test_very_long_answer(self):
        """Test validating very long answer"""
        answer = "John Doe's salary is $100,000. " * 100  # Very long answer
        cited_chunks = ["Employee: John Doe, Salary: $100,000"]
        
        validation = self.validator.validate_answer_grounding(answer, cited_chunks)
        
        # Should still work but may take longer
        assert validation.is_valid is True
        assert validation.evidence_score > 0.7
    
    def test_unicode_characters(self):
        """Test validating answer with unicode characters"""
        answer = "José García's salary is $100,000 and he works in Ingeniería"
        cited_chunks = ["Employee: José García, Department: Ingeniería, Salary: $100,000"]
        
        validation = self.validator.validate_answer_grounding(answer, cited_chunks)
        
        assert validation.is_valid is True
        assert validation.evidence_score > 0.8
    
    def test_numbers_and_formats(self):
        """Test validating claims with various number formats"""
        claim = Claim(
            text="John Doe's salary is $100,000",
            entity="John Doe",
            attribute="salary",
            value="$100,000"
        )
        
        # Test various number formats
        chunk_texts = [
            "Salary: $100,000.00",
            "Salary: 100000",
            "Salary: 100,000.00",
            "Salary: $100000.00",
            "Salary: 100000.0"
        ]
        
        for chunk_text in chunk_texts:
            is_valid, evidence_score = self.validator.validate_claim_against_chunk(claim, chunk_text)
            assert is_valid is True, f"Failed for chunk: {chunk_text}"
            assert evidence_score > 0.7
    
    def test_date_formats(self):
        """Test validating claims with various date formats"""
        claim = Claim(
            text="John Doe started on 2020-01-01",
            entity="John Doe",
            attribute="start_date",
            value="2020-01-01"
        )
        
        # Test various date formats
        chunk_texts = [
            "Start Date: 2020-01-01",
            "Start Date: 01/01/2020",
            "Start Date: January 1, 2020",
            "Start Date: 1/1/2020",
            "Start Date: 2020-1-1"
        ]
        
        for chunk_text in chunk_texts:
            is_valid, evidence_score = self.validator.validate_claim_against_chunk(claim, chunk_text)
            # Some formats may not match exactly, but should have reasonable evidence scores
            assert evidence_score > 0.3, f"Very low evidence for chunk: {chunk_text}"


class TestGroundingValidatorIntegration:
    """Test GroundingValidator integration scenarios"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.rag.grounding_validator.is_feature_enabled', return_value=True):
            self.validator = GroundingValidator()
    
    def test_complete_validation_workflow(self):
        """Test complete validation workflow"""
        # Complex answer with multiple claims
        answer = """
        John Doe is a Senior Developer in the Engineering department with a salary of $100,000.
        He started on January 1, 2020 and reports to Bob Smith. His email is john@company.com
        and he works on the FinSyntra project.
        """
        
        # Cited chunks with some missing information
        cited_chunks = [
            "Employee: John Doe, Department: Engineering, Salary: $100,000, Start Date: 2020-01-01",
            "Contact: John Doe, Email: john@company.com, Phone: 555-1234",
            "Project: FinSyntra, Team: Engineering, Lead: John Doe"
        ]
        
        validation = self.validator.validate_answer_grounding(answer, cited_chunks)
        
        # Should detect missing citations for manager and job title
        assert validation.is_valid is False
        assert validation.evidence_score < 0.9
        assert len(validation.missing_citations) >= 1
        assert len(validation.suggestions) >= 1
    
    def test_validation_with_entity_variations(self):
        """Test validation with entity name variations"""
        answer = "John's salary is $100,000 and he works in Engineering"
        
        cited_chunks = [
            "Employee: John Doe, Department: Engineering, Salary: $100,000"
        ]
        
        validation = self.validator.validate_answer_grounding(answer, cited_chunks)
        
        # Should handle "John" as variation of "John Doe"
        assert validation.is_valid is True
        assert validation.evidence_score > 0.7


class TestGlobalFunctions:
    """Test global functions"""
    
    def test_get_grounding_validator(self):
        """Test get_grounding_validator function"""
        validator = get_grounding_validator()
        assert isinstance(validator, GroundingValidator)
        
        # Should return the same instance
        validator2 = get_grounding_validator()
        assert validator is validator2


if __name__ == "__main__":
    pytest.main([__file__])
