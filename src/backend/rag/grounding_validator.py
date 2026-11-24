"""
Grounding Validator for FinSyntra RAG
Ensures citations are accurate and facts are properly grounded in source documents
"""
import re
import logging
from typing import Dict, Any, Optional, List, Tuple, Set
from dataclasses import dataclass
from enum import Enum

from src.config.feature_flags import is_feature_enabled

logger = logging.getLogger(__name__)

class ValidationResult(Enum):
    """Validation result types"""
    VALID = "valid"
    INVALID = "invalid"
    PARTIAL = "partial"
    UNVERIFIABLE = "unverifiable"

@dataclass
class GroundedFact:
    """Represents a fact that has been validated against source documents"""
    fact_text: str
    source_doc_id: str
    chunk_id: str
    confidence: float
    validation_result: ValidationResult
    supporting_evidence: List[str]
    contradictions: List[str]

@dataclass
class CitationValidation:
    """Result of citation validation"""
    is_valid: bool
    confidence: float
    missing_sources: List[str]
    invalid_claims: List[str]
    suggestions: List[str]

class GroundingValidator:
    """
    Validates that facts and citations are properly grounded in source documents
    Ensures accuracy and prevents hallucination
    """
    
    def __init__(self):
        self.strict_mode = is_feature_enabled('ENABLE_STRICT_GROUNDING')
        self.min_confidence = 0.7
        self.logger = logging.getLogger(__name__)
        
        logger.info("GroundingValidator initialized")
    
    def validate_answer(
        self, 
        answer_text: str, 
        cited_chunks: List[Dict[str, Any]],
        all_available_chunks: List[Dict[str, Any]]
    ) -> CitationValidation:
        """
        Validate that an answer is properly grounded in cited chunks
        Returns validation result with confidence and issues
        """
        if not self.strict_mode:
            return CitationValidation(
                is_valid=True,
                confidence=1.0,
                missing_sources=[],
                invalid_claims=[],
                suggestions=[]
            )
        
        # Extract factual claims from answer
        factual_claims = self._extract_factual_claims(answer_text)
        
        if not factual_claims:
            return CitationValidation(
                is_valid=True,
                confidence=1.0,
                missing_sources=[],
                invalid_claims=[],
                suggestions=[]
            )
        
        # Validate each claim against cited chunks
        validation_results = []
        missing_sources = []
        invalid_claims = []
        
        for claim in factual_claims:
            claim_validation = self._validate_claim(claim, cited_chunks)
            validation_results.append(claim_validation)
            
            if claim_validation.validation_result == ValidationResult.INVALID:
                invalid_claims.append(claim.fact_text)
            elif claim_validation.validation_result == ValidationResult.UNVERIFIABLE:
                missing_sources.append(claim.fact_text)
        
        # Calculate overall confidence
        valid_claims = sum(1 for r in validation_results if r.validation_result == ValidationResult.VALID)
        total_claims = len(validation_results)
        confidence = valid_claims / total_claims if total_claims > 0 else 0.0
        
        # Determine if answer is valid
        is_valid = confidence >= self.min_confidence and len(invalid_claims) == 0
        
        # Generate suggestions for improvement
        suggestions = self._generate_validation_suggestions(validation_results)
        
        return CitationValidation(
            is_valid=is_valid,
            confidence=confidence,
            missing_sources=missing_sources,
            invalid_claims=invalid_claims,
            suggestions=suggestions
        )
    
    def _extract_factual_claims(self, text: str) -> List[GroundedFact]:
        """Extract factual claims from text that need validation"""
        claims = []
        
        # Split text into sentences
        sentences = re.split(r'[.!?]+', text)
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            # Look for factual statements (avoid questions, opinions, etc.)
            if self._is_factual_statement(sentence):
                # Extract key facts
                facts = self._extract_facts_from_sentence(sentence)
                for fact in facts:
                    claims.append(GroundedFact(
                        fact_text=fact,
                        source_doc_id="",
                        chunk_id="",
                        confidence=0.0,
                        validation_result=ValidationResult.UNVERIFIABLE,
                        supporting_evidence=[],
                        contradictions=[]
                    ))
        
        return claims
    
    def _is_factual_statement(self, sentence: str) -> bool:
        """Check if a sentence contains factual information"""
        sentence_lower = sentence.lower()
        
        # Skip questions
        if sentence.strip().endswith('?'):
            return False
        
        # Skip opinions and subjective statements
        opinion_indicators = [
            'i think', 'i believe', 'in my opinion', 'it seems', 'probably',
            'maybe', 'might', 'could', 'would', 'should'
        ]
        
        if any(indicator in sentence_lower for indicator in opinion_indicators):
            return False
        
        # Look for factual indicators
        factual_indicators = [
            'is', 'are', 'was', 'were', 'has', 'have', 'had',
            'salary', 'department', 'title', 'email', 'id', 'name',
            'works', 'reports', 'manages', 'located', 'started'
        ]
        
        return any(indicator in sentence_lower for indicator in factual_indicators)
    
    def _extract_facts_from_sentence(self, sentence: str) -> List[str]:
        """Extract specific facts from a sentence"""
        facts = []
        
        # Look for specific patterns
        patterns = [
            # Salary information
            r'(\w+\'s salary is \$[\d,]+)',
            r'(salary of \$[\d,]+)',
            r'(\$[\d,]+ salary)',
            
            # Department information
            r'(\w+ works in \w+ department)',
            r'(\w+ is in \w+ department)',
            r'(\w+ department employee)',
            
            # Job title information
            r'(\w+ is \w+)',
            r'(\w+ works as \w+)',
            r'(\w+ position)',
            
            # Email information
            r'(\w+@\w+\.\w+)',
            r'(\w+\'s email is \w+@\w+\.\w+)',
            
            # Employee ID information
            r'(employee id \d+)',
            r'(id \d+)',
            r'(\w+ has id \d+)'
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, sentence, re.IGNORECASE)
            facts.extend(matches)
        
        # If no specific patterns found, use the whole sentence
        if not facts:
            facts.append(sentence)
        
        return facts
    
    def _validate_claim(
        self, 
        claim: GroundedFact, 
        cited_chunks: List[Dict[str, Any]]
    ) -> GroundedFact:
        """Validate a single claim against cited chunks"""
        if not cited_chunks:
            claim.validation_result = ValidationResult.UNVERIFIABLE
            claim.confidence = 0.0
            return claim
        
        # Check each cited chunk for supporting evidence
        supporting_evidence = []
        contradictions = []
        max_confidence = 0.0
        
        for chunk in cited_chunks:
            chunk_text = chunk.get('content', '')
            chunk_id = chunk.get('id', '')
            
            # Check for supporting evidence
            evidence_score = self._calculate_evidence_score(claim.fact_text, chunk_text)
            
            if evidence_score > 0.5:  # Threshold for supporting evidence
                supporting_evidence.append(f"Chunk {chunk_id}: {evidence_score:.2f}")
                max_confidence = max(max_confidence, evidence_score)
            
            # Check for contradictions
            contradiction_score = self._calculate_contradiction_score(claim.fact_text, chunk_text)
            if contradiction_score > 0.7:  # Threshold for contradiction
                contradictions.append(f"Chunk {chunk_id}: {contradiction_score:.2f}")
        
        # Determine validation result
        if supporting_evidence and not contradictions:
            if max_confidence >= 0.8:
                claim.validation_result = ValidationResult.VALID
            else:
                claim.validation_result = ValidationResult.PARTIAL
        elif contradictions:
            claim.validation_result = ValidationResult.INVALID
        else:
            claim.validation_result = ValidationResult.UNVERIFIABLE
        
        claim.confidence = max_confidence
        claim.supporting_evidence = supporting_evidence
        claim.contradictions = contradictions
        
        return claim
    
    def _calculate_evidence_score(self, claim: str, chunk_text: str) -> float:
        """Calculate how well a chunk supports a claim"""
        if not claim or not chunk_text:
            return 0.0
        
        claim_lower = claim.lower()
        chunk_lower = chunk_text.lower()
        
        # Extract key terms from claim
        claim_terms = set(re.findall(r'\b\w+\b', claim_lower))
        
        # Remove common stop words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        claim_terms = claim_terms - stop_words
        
        if not claim_terms:
            return 0.0
        
        # Count matching terms
        matches = 0
        for term in claim_terms:
            if term in chunk_lower:
                matches += 1
        
        # Calculate score based on term overlap
        score = matches / len(claim_terms)
        
        # Boost score for exact phrase matches
        if claim_lower in chunk_lower:
            score = min(1.0, score + 0.3)
        
        # Boost score for numeric matches (salary, ID, etc.)
        numbers = re.findall(r'\d+', claim)
        for number in numbers:
            if number in chunk_text:
                score = min(1.0, score + 0.2)
        
        return score
    
    def _calculate_contradiction_score(self, claim: str, chunk_text: str) -> float:
        """Calculate how much a chunk contradicts a claim"""
        if not claim or not chunk_text:
            return 0.0
        
        claim_lower = claim.lower()
        chunk_lower = chunk_text.lower()
        
        # Look for explicit contradictions
        contradiction_patterns = [
            (r'(\w+)\'s salary is \$([\d,]+)', r'\1\'s salary is \$([\d,]+)'),
            (r'(\w+) works in (\w+) department', r'\1 works in (\w+) department'),
            (r'(\w+) is (\w+)', r'\1 is (\w+)')
        ]
        
        for claim_pattern, chunk_pattern in contradiction_patterns:
            claim_match = re.search(claim_pattern, claim_lower)
            if claim_match:
                chunk_match = re.search(chunk_pattern, chunk_lower)
                if chunk_match:
                    # Check if values are different
                    if claim_match.groups() != chunk_match.groups():
                        return 0.9  # High contradiction score
        
        # Look for negations
        negation_words = ['not', 'no', 'never', 'none', 'doesn\'t', 'isn\'t', 'wasn\'t']
        if any(neg in claim_lower for neg in negation_words):
            # Check if chunk contains positive version
            positive_claim = claim_lower.replace('not ', '').replace('no ', '').replace('never ', '')
            if positive_claim in chunk_lower:
                return 0.8
        
        return 0.0
    
    def _generate_validation_suggestions(self, validation_results: List[GroundedFact]) -> List[str]:
        """Generate suggestions for improving validation"""
        suggestions = []
        
        unverifiable_count = sum(1 for r in validation_results if r.validation_result == ValidationResult.UNVERIFIABLE)
        invalid_count = sum(1 for r in validation_results if r.validation_result == ValidationResult.INVALID)
        
        if unverifiable_count > 0:
            suggestions.append(f"Add citations for {unverifiable_count} unverifiable claims")
        
        if invalid_count > 0:
            suggestions.append(f"Review and correct {invalid_count} invalid claims")
        
        # Check for low confidence claims
        low_confidence = [r for r in validation_results if r.confidence < 0.6]
        if low_confidence:
            suggestions.append(f"Provide more specific evidence for {len(low_confidence)} low-confidence claims")
        
        # Check for missing citations
        uncited_claims = [r for r in validation_results if not r.supporting_evidence]
        if uncited_claims:
            suggestions.append(f"Ensure all claims have proper citations")
        
        return suggestions
    
    def validate_citation_accuracy(
        self, 
        citation_text: str, 
        source_chunk: Dict[str, Any]
    ) -> bool:
        """Validate that a citation accurately represents the source chunk"""
        if not self.strict_mode:
            return True
        
        chunk_content = source_chunk.get('content', '')
        
        # Check if citation text appears in chunk content
        if citation_text.lower() in chunk_content.lower():
            return True
        
        # Check for paraphrased content
        citation_terms = set(re.findall(r'\b\w+\b', citation_text.lower()))
        chunk_terms = set(re.findall(r'\b\w+\b', chunk_content.lower()))
        
        # Remove stop words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        citation_terms = citation_terms - stop_words
        chunk_terms = chunk_terms - stop_words
        
        if not citation_terms:
            return True
        
        # Calculate overlap
        overlap = len(citation_terms.intersection(chunk_terms))
        overlap_ratio = overlap / len(citation_terms)
        
        return overlap_ratio >= 0.6  # At least 60% of citation terms must be in chunk
    
    def get_validation_summary(self, validation_results: List[GroundedFact]) -> Dict[str, Any]:
        """Get a summary of validation results"""
        total_claims = len(validation_results)
        valid_claims = sum(1 for r in validation_results if r.validation_result == ValidationResult.VALID)
        partial_claims = sum(1 for r in validation_results if r.validation_result == ValidationResult.PARTIAL)
        invalid_claims = sum(1 for r in validation_results if r.validation_result == ValidationResult.INVALID)
        unverifiable_claims = sum(1 for r in validation_results if r.validation_result == ValidationResult.UNVERIFIABLE)
        
        avg_confidence = sum(r.confidence for r in validation_results) / total_claims if total_claims > 0 else 0.0
        
        return {
            'total_claims': total_claims,
            'valid_claims': valid_claims,
            'partial_claims': partial_claims,
            'invalid_claims': invalid_claims,
            'unverifiable_claims': unverifiable_claims,
            'average_confidence': avg_confidence,
            'validation_rate': (valid_claims + partial_claims) / total_claims if total_claims > 0 else 0.0
        }

# Global grounding validator instance
grounding_validator = GroundingValidator()

def get_grounding_validator() -> GroundingValidator:
    """Get the global grounding validator instance"""
    return grounding_validator
