"""
Query Rewriter for FinSyntra RAG
Resolves pronouns and references to maintain conversational consistency
"""
import re
import logging
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

from src.backend.memory.session_kv import ActiveSubject, get_session_memory
from src.config.feature_flags import is_feature_enabled

logger = logging.getLogger(__name__)

@dataclass
class RewrittenQuery:
    """Result of query rewriting"""
    original_query: str
    rewritten_query: str
    active_subject: Optional[ActiveSubject]
    confidence: float
    changes_made: List[str]

class QueryRewriter:
    """
    Rewrites queries to resolve pronouns and references
    Uses session memory to maintain conversational consistency
    """
    
    def __init__(self):
        self.session_memory = get_session_memory()
        
        # Pronoun patterns
        self.pronoun_patterns = {
            'he': r'\b(he|him|his)\b',
            'she': r'\b(she|her|hers)\b',
            'they': r'\b(they|them|their|theirs)\b',
            'this_person': r'\b(this person|this employee|this worker)\b',
            'employee_id': r'\b(employee id (\d+)|employee (\d+)|id (\d+))\b',
            'name_reference': r'\b(that person|the person|the employee)\b'
        }
        
        # Subject indicators
        self.subject_indicators = [
            'salary', 'email', 'department', 'job title', 'position',
            'role', 'manager', 'supervisor', 'team', 'location'
        ]
        
        logger.info("QueryRewriter initialized")
    
    def rewrite_query(self, session_id: str, query: str) -> RewrittenQuery:
        """
        Rewrite a query to resolve pronouns and references
        Returns the rewritten query with confidence and changes made
        """
        if not is_feature_enabled('ENABLE_QUERY_REWRITER'):
            return RewrittenQuery(
                original_query=query,
                rewritten_query=query,
                active_subject=None,
                confidence=1.0,
                changes_made=[]
            )
        
        original_query = query.strip()
        rewritten_query = original_query
        changes_made = []
        confidence = 1.0
        
        # Get active subject from session memory
        active_subject = self.session_memory.get_active_subject(session_id)
        
        if not active_subject:
            logger.debug(f"No active subject found for session {session_id}")
            return RewrittenQuery(
                original_query=original_query,
                rewritten_query=rewritten_query,
                active_subject=None,
                confidence=confidence,
                changes_made=changes_made
            )
        
        # Check if query contains pronouns or references
        if self._contains_references(original_query):
            rewritten_query, changes, conf = self._resolve_references(
                original_query, active_subject
            )
            changes_made.extend(changes)
            confidence = min(confidence, conf)
        
        # Check if query needs subject context
        if self._needs_subject_context(original_query) and active_subject:
            rewritten_query, changes, conf = self._add_subject_context(
                rewritten_query, active_subject
            )
            changes_made.extend(changes)
            confidence = min(confidence, conf)
        
        logger.info(f"Query rewritten: '{original_query}' -> '{rewritten_query}'")
        logger.debug(f"Changes: {changes_made}, Confidence: {confidence}")
        
        return RewrittenQuery(
            original_query=original_query,
            rewritten_query=rewritten_query,
            active_subject=active_subject,
            confidence=confidence,
            changes_made=changes_made
        )
    
    def _contains_references(self, query: str) -> bool:
        """Check if query contains pronouns or references"""
        query_lower = query.lower()
        
        # Check for pronouns
        for pattern in self.pronoun_patterns.values():
            if re.search(pattern, query_lower):
                return True
        
        # Check for subject indicators without explicit subjects
        has_subject_indicator = any(indicator in query_lower for indicator in self.subject_indicators)
        has_explicit_subject = self._has_explicit_subject(query)
        
        return has_subject_indicator and not has_explicit_subject
    
    def _has_explicit_subject(self, query: str) -> bool:
        """Check if query has an explicit subject (name, email, ID)"""
        # Simple heuristics for explicit subjects
        explicit_patterns = [
            r'\b[A-Z][a-z]+ [A-Z][a-z]+\b',  # First Last
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Email
            r'\b[A-Z]{2,}-\d+\b',  # ID format like NEO-1329
            r'\b\d{1,4}\b'  # Short numeric ID
        ]
        
        for pattern in explicit_patterns:
            if re.search(pattern, query):
                return True
        
        return False
    
    def _resolve_references(self, query: str, active_subject: ActiveSubject) -> Tuple[str, List[str], float]:
        """Resolve pronouns and references in the query"""
        rewritten_query = query
        changes_made = []
        confidence = 0.8  # Start with moderate confidence
        
        # Resolve pronouns
        if re.search(self.pronoun_patterns['he'], query, re.IGNORECASE):
            if active_subject.canonical_name:
                rewritten_query = re.sub(
                    self.pronoun_patterns['he'],
                    active_subject.canonical_name,
                    query,
                    flags=re.IGNORECASE
                )
                changes_made.append(f"Resolved 'he/him/his' to '{active_subject.canonical_name}'")
                confidence = 0.9
            else:
                confidence = 0.6
        
        elif re.search(self.pronoun_patterns['she'], query, re.IGNORECASE):
            if active_subject.canonical_name:
                rewritten_query = re.sub(
                    self.pronoun_patterns['she'],
                    active_subject.canonical_name,
                    query,
                    flags=re.IGNORECASE
                )
                changes_made.append(f"Resolved 'she/her/hers' to '{active_subject.canonical_name}'")
                confidence = 0.9
            else:
                confidence = 0.6
        
        elif re.search(self.pronoun_patterns['they'], query, re.IGNORECASE):
            if active_subject.canonical_name:
                rewritten_query = re.sub(
                    self.pronoun_patterns['they'],
                    active_subject.canonical_name,
                    query,
                    flags=re.IGNORECASE
                )
                changes_made.append(f"Resolved 'they/them/their' to '{active_subject.canonical_name}'")
                confidence = 0.9
            else:
                confidence = 0.6
        
        # Resolve generic references
        elif re.search(self.pronoun_patterns['this_person'], query, re.IGNORECASE):
            if active_subject.canonical_name:
                rewritten_query = re.sub(
                    self.pronoun_patterns['this_person'],
                    active_subject.canonical_name,
                    query,
                    flags=re.IGNORECASE
                )
                changes_made.append(f"Resolved 'this person' to '{active_subject.canonical_name}'")
                confidence = 0.9
            else:
                confidence = 0.6
        
        # Resolve employee ID references
        elif re.search(self.pronoun_patterns['employee_id'], query, re.IGNORECASE):
            if active_subject.employee_id:
                # Replace with canonical name if available, otherwise keep ID
                replacement = active_subject.canonical_name or active_subject.employee_id
                rewritten_query = re.sub(
                    self.pronoun_patterns['employee_id'],
                    replacement,
                    query,
                    flags=re.IGNORECASE
                )
                changes_made.append(f"Resolved employee ID reference to '{replacement}'")
                confidence = 0.95
            else:
                confidence = 0.6
        
        return rewritten_query, changes_made, confidence
    
    def _add_subject_context(self, query: str, active_subject: ActiveSubject) -> Tuple[str, List[str], float]:
        """Add subject context to queries that need it"""
        rewritten_query = query
        changes_made = []
        confidence = 0.9
        
        # If query is about salary, email, etc. but doesn't specify who
        if self._needs_subject_context(query) and active_subject.canonical_name:
            # Check if query already has the subject
            if active_subject.canonical_name.lower() not in query.lower():
                # Add subject to the beginning
                rewritten_query = f"{active_subject.canonical_name}'s {query}"
                changes_made.append(f"Added subject context: '{active_subject.canonical_name}'")
                confidence = 0.9
        
        return rewritten_query, changes_made, confidence
    
    def _needs_subject_context(self, query: str) -> bool:
        """Check if query needs explicit subject context"""
        query_lower = query.lower()
        
        # Queries about specific attributes that need a subject
        context_needed = [
            'salary', 'email', 'department', 'job title', 'position',
            'role', 'manager', 'supervisor', 'team', 'location',
            'phone', 'address', 'start date', 'hire date'
        ]
        
        return any(term in query_lower for term in context_needed)
    
    def get_disambiguation_suggestions(self, query: str, candidates: List[Dict[str, Any]]) -> List[str]:
        """Generate disambiguation suggestions for ambiguous queries"""
        suggestions = []
        
        for candidate in candidates:
            name = candidate.get('name', 'Unknown')
            employee_id = candidate.get('employee_id', 'Unknown')
            department = candidate.get('department', 'Unknown')
            
            suggestion = f"{name} (ID: {employee_id}, Dept: {department})"
            suggestions.append(suggestion)
        
        return suggestions
    
    def validate_rewrite(self, original: str, rewritten: str) -> bool:
        """Validate that the rewritten query makes sense"""
        if not rewritten or rewritten.strip() == '':
            return False
        
        # Check that we didn't lose important information
        if len(rewritten) < len(original) * 0.5:
            return False
        
        # Check that we have a reasonable query
        if len(rewritten.split()) < 2:
            return False
        
        return True

# Global query rewriter instance
query_rewriter = QueryRewriter()

def get_query_rewriter() -> QueryRewriter:
    """Get the global query rewriter instance"""
    return query_rewriter
