"""
Entity Registry for FinSyntra RAG
Canonicalizes employee names and IDs from various sources
"""
import re
import hashlib
import logging
from typing import Dict, Any, Optional, List, Set, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import json

from src.config.feature_flags import is_feature_enabled

logger = logging.getLogger(__name__)

@dataclass
class Entity:
    """Represents a canonical entity (employee)"""
    employee_id: str
    canonical_name: str
    email: Optional[str] = None
    aliases: Set[str] = None
    department: Optional[str] = None
    job_title: Optional[str] = None
    manager: Optional[str] = None
    start_date: Optional[str] = None
    location: Optional[str] = None
    last_updated: datetime = None
    source_documents: Set[str] = None
    
    def __post_init__(self):
        if self.aliases is None:
            self.aliases = set()
        if self.source_documents is None:
            self.source_documents = set()
        if self.last_updated is None:
            self.last_updated = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        data = asdict(self)
        data['aliases'] = list(self.aliases)
        data['source_documents'] = list(self.source_documents)
        data['last_updated'] = self.last_updated.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Entity':
        """Create from dictionary"""
        if 'aliases' in data:
            data['aliases'] = set(data['aliases'])
        if 'source_documents' in data:
            data['source_documents'] = set(data['source_documents'])
        if 'last_updated' in data and isinstance(data['last_updated'], str):
            data['last_updated'] = datetime.fromisoformat(data['last_updated'])
        return cls(**data)

class EntityRegistry:
    """
    Maintains a registry of canonical entities
    Resolves names, IDs, and aliases to maintain consistency
    """
    
    def __init__(self):
        self.entities: Dict[str, Entity] = {}  # employee_id -> Entity
        self.email_index: Dict[str, str] = {}  # email -> employee_id
        self.name_index: Dict[str, str] = {}  # normalized_name -> employee_id
        self.alias_index: Dict[str, str] = {}  # alias -> employee_id
        
        logger.info("EntityRegistry initialized")
    
    def add_entity(self, entity: Entity) -> None:
        """Add or update an entity in the registry"""
        if not is_feature_enabled('ENABLE_ENTITY_REGISTRY'):
            return
        
        employee_id = entity.employee_id
        
        # Update existing entity or create new one
        if employee_id in self.entities:
            existing = self.entities[employee_id]
            # Merge aliases and source documents
            entity.aliases.update(existing.aliases)
            entity.source_documents.update(existing.source_documents)
            entity.last_updated = datetime.now()
            logger.info(f"Updated existing entity: {employee_id}")
        else:
            logger.info(f"Added new entity: {employee_id}")
        
        # Store entity
        self.entities[employee_id] = entity
        
        # Update indexes
        self._update_indexes(entity)
        
        logger.debug(f"Entity {employee_id} registered with {len(entity.aliases)} aliases")
    
    def _update_indexes(self, entity: Entity) -> None:
        """Update all indexes for an entity"""
        employee_id = entity.employee_id
        
        # Email index
        if entity.email:
            self.email_index[entity.email.lower()] = employee_id
        
        # Canonical name index
        if entity.canonical_name:
            normalized_name = self._normalize_name(entity.canonical_name)
            self.name_index[normalized_name] = employee_id
        
        # Alias indexes
        for alias in entity.aliases:
            normalized_alias = self._normalize_name(alias)
            self.alias_index[normalized_alias] = employee_id
    
    def _normalize_name(self, name: str) -> str:
        """Normalize a name for indexing (lowercase, remove extra spaces)"""
        if not name:
            return ""
        
        # Convert to lowercase and remove extra whitespace
        normalized = re.sub(r'\s+', ' ', name.lower().strip())
        return normalized
    
    def find_entity_by_id(self, employee_id: str) -> Optional[Entity]:
        """Find entity by employee ID"""
        return self.entities.get(employee_id)
    
    def find_entity_by_email(self, email: str) -> Optional[Entity]:
        """Find entity by email address"""
        if not is_feature_enabled('ENABLE_ENTITY_REGISTRY'):
            return None
        
        normalized_email = email.lower().strip()
        employee_id = self.email_index.get(normalized_email)
        if employee_id:
            return self.entities.get(employee_id)
        return None
    
    def find_entity_by_name(self, name: str) -> Optional[Entity]:
        """Find entity by name (exact or fuzzy match)"""
        if not is_feature_enabled('ENABLE_ENTITY_REGISTRY'):
            return None
        
        normalized_name = self._normalize_name(name)
        
        # Try exact match first
        employee_id = self.name_index.get(normalized_name)
        if employee_id:
            return self.entities.get(employee_id)
        
        # Try alias match
        employee_id = self.alias_index.get(normalized_name)
        if employee_id:
            return self.entities.get(employee_id)
        
        # Try fuzzy matching
        return self._fuzzy_match_name(name)
    
    def _fuzzy_match_name(self, name: str) -> Optional[Entity]:
        """Fuzzy match name against registered entities"""
        if not name:
            return None
        
        name_lower = name.lower()
        best_match = None
        best_score = 0.0
        
        for entity in self.entities.values():
            # Check canonical name
            if entity.canonical_name:
                score = self._calculate_name_similarity(name_lower, entity.canonical_name.lower())
                if score > best_score and score > 0.7:  # Threshold for fuzzy matching
                    best_score = score
                    best_match = entity
            
            # Check aliases
            for alias in entity.aliases:
                score = self._calculate_name_similarity(name_lower, alias.lower())
                if score > best_score and score > 0.7:
                    best_score = score
                    best_match = entity
        
        if best_match:
            logger.debug(f"Fuzzy matched '{name}' to '{best_match.canonical_name}' (score: {best_score:.2f})")
        
        return best_match
    
    def _calculate_name_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity between two names"""
        if not name1 or not name2:
            return 0.0
        
        # Simple token-based similarity
        tokens1 = set(name1.split())
        tokens2 = set(name2.split())
        
        if not tokens1 or not tokens2:
            return 0.0
        
        intersection = len(tokens1.intersection(tokens2))
        union = len(tokens1.union(tokens2))
        
        return intersection / union if union > 0 else 0.0
    
    def find_entities_by_department(self, department: str) -> List[Entity]:
        """Find all entities in a specific department"""
        if not is_feature_enabled('ENABLE_ENTITY_REGISTRY'):
            return []
        
        department_lower = department.lower().strip()
        return [
            entity for entity in self.entities.values()
            if entity.department and entity.department.lower() == department_lower
        ]
    
    def find_entities_by_job_title(self, job_title: str) -> List[Entity]:
        """Find all entities with a specific job title"""
        if not is_feature_enabled('ENABLE_ENTITY_REGISTRY'):
            return []
        
        job_title_lower = job_title.lower().strip()
        return [
            entity for entity in self.entities.values()
            if entity.job_title and entity.job_title.lower() == job_title_lower
        ]
    
    def get_canonical_name(self, identifier: str) -> Optional[str]:
        """Get canonical name for any identifier (ID, email, name, alias)"""
        if not is_feature_enabled('ENABLE_ENTITY_REGISTRY'):
            return None
        
        # Try to find entity
        entity = None
        
        # Check if it's an employee ID
        if identifier in self.entities:
            entity = self.entities[identifier]
        # Check if it's an email
        elif self._is_email(identifier):
            entity = self.find_entity_by_email(identifier)
        # Check if it's a name
        else:
            entity = self.find_entity_by_name(identifier)
        
        return entity.canonical_name if entity else None
    
    def _is_email(self, text: str) -> bool:
        """Check if text looks like an email address"""
        email_pattern = r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$'
        return bool(re.match(email_pattern, text))
    
    def add_alias(self, employee_id: str, alias: str) -> bool:
        """Add an alias for an existing entity"""
        if not is_feature_enabled('ENABLE_ENTITY_REGISTRY'):
            return False
        
        if employee_id not in self.entities:
            logger.warning(f"Cannot add alias for unknown employee ID: {employee_id}")
            return False
        
        entity = self.entities[employee_id]
        entity.aliases.add(alias)
        entity.last_updated = datetime.now()
        
        # Update alias index
        normalized_alias = self._normalize_name(alias)
        self.alias_index[normalized_alias] = employee_id
        
        logger.info(f"Added alias '{alias}' for employee {employee_id}")
        return True
    
    def remove_alias(self, employee_id: str, alias: str) -> bool:
        """Remove an alias for an entity"""
        if not is_feature_enabled('ENABLE_ENTITY_REGISTRY'):
            return False
        
        if employee_id not in self.entities:
            return False
        
        entity = self.entities[employee_id]
        if alias in entity.aliases:
            entity.aliases.remove(alias)
            entity.last_updated = datetime.now()
            
            # Update alias index
            normalized_alias = self._normalize_name(alias)
            if normalized_alias in self.alias_index:
                del self.alias_index[normalized_alias]
            
            logger.info(f"Removed alias '{alias}' for employee {employee_id}")
            return True
        
        return False
    
    def get_entity_summary(self, employee_id: str) -> Optional[Dict[str, Any]]:
        """Get a summary of entity information"""
        entity = self.find_entity_by_id(employee_id)
        if not entity:
            return None
        
        return {
            'employee_id': entity.employee_id,
            'canonical_name': entity.canonical_name,
            'department': entity.department,
            'job_title': entity.job_title,
            'email': entity.email,
            'aliases': list(entity.aliases),
            'source_documents': list(entity.source_documents),
            'last_updated': entity.last_updated.isoformat()
        }
    
    def get_registry_stats(self) -> Dict[str, Any]:
        """Get statistics about the entity registry"""
        total_entities = len(self.entities)
        total_aliases = sum(len(entity.aliases) for entity in self.entities.values())
        total_emails = sum(1 for entity in self.entities.values() if entity.email)
        
        departments = {}
        job_titles = {}
        
        for entity in self.entities.values():
            if entity.department:
                departments[entity.department] = departments.get(entity.department, 0) + 1
            if entity.job_title:
                job_titles[entity.job_title] = job_titles.get(entity.job_title, 0) + 1
        
        return {
            'total_entities': total_entities,
            'total_aliases': total_aliases,
            'total_emails': total_emails,
            'departments': departments,
            'job_titles': job_titles,
            'index_sizes': {
                'name_index': len(self.name_index),
                'alias_index': len(self.alias_index),
                'email_index': len(self.email_index)
            }
        }
    
    def clear_registry(self) -> None:
        """Clear all entities and indexes"""
        self.entities.clear()
        self.email_index.clear()
        self.name_index.clear()
        self.alias_index.clear()
        logger.info("Entity registry cleared")
    
    def export_registry(self) -> str:
        """Export registry to JSON string"""
        data = {
            'entities': {eid: entity.to_dict() for eid, entity in self.entities.items()},
            'exported_at': datetime.now().isoformat()
        }
        return json.dumps(data, indent=2)
    
    def import_registry(self, json_data: str) -> bool:
        """Import registry from JSON string"""
        try:
            data = json.loads(json_data)
            entities_data = data.get('entities', {})
            
            for employee_id, entity_data in entities_data.items():
                entity = Entity.from_dict(entity_data)
                self.add_entity(entity)
            
            logger.info(f"Imported {len(entities_data)} entities from JSON")
            return True
        except Exception as e:
            logger.error(f"Failed to import registry: {e}")
            return False

# Global entity registry instance
entity_registry = EntityRegistry()

def get_entity_registry() -> EntityRegistry:
    """Get the global entity registry instance"""
    return entity_registry
