"""
Unit tests for entity registry module
"""
import pytest
from unittest.mock import Mock, patch
import tempfile
import os

from src.backend.entities.registry import (
    Entity, EntityRegistry, get_entity_registry
)


class TestEntity:
    """Test Entity dataclass"""
    
    def test_entity_creation(self):
        """Test creating an Entity"""
        entity = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            aliases=["John", "J. Doe", "JD"],
            department="Engineering",
            job_title="Senior Developer"
        )
        
        assert entity.employee_id == "123"
        assert entity.email == "john.doe@company.com"
        assert entity.canonical_name == "John Doe"
        assert len(entity.aliases) == 3
        assert "John" in entity.aliases
        assert entity.department == "Engineering"
        assert entity.job_title == "Senior Developer"
    
    def test_entity_defaults(self):
        """Test Entity creation with defaults"""
        entity = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe"
        )
        
        assert entity.aliases == []
        assert entity.department is None
        assert entity.job_title is None
    
    def test_entity_serialization(self):
        """Test Entity serialization to dict"""
        entity = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            aliases=["John", "J. Doe"],
            department="Engineering",
            job_title="Senior Developer"
        )
        
        entity_dict = entity.to_dict()
        
        assert entity_dict["employee_id"] == "123"
        assert entity_dict["email"] == "john.doe@company.com"
        assert entity_dict["canonical_name"] == "John Doe"
        assert entity_dict["aliases"] == ["John", "J. Doe"]
        assert entity_dict["department"] == "Engineering"
        assert entity_dict["job_title"] == "Senior Developer"
    
    def test_entity_from_dict(self):
        """Test Entity creation from dict"""
        entity_dict = {
            "employee_id": "123",
            "email": "john.doe@company.com",
            "canonical_name": "John Doe",
            "aliases": ["John", "J. Doe"],
            "department": "Engineering",
            "job_title": "Senior Developer"
        }
        
        entity = Entity.from_dict(entity_dict)
        
        assert entity.employee_id == "123"
        assert entity.email == "john.doe@company.com"
        assert entity.canonical_name == "John Doe"
        assert len(entity.aliases) == 2
        assert entity.department == "Engineering"
        assert entity.job_title == "Senior Developer"
    
    def test_entity_equality(self):
        """Test Entity equality comparison"""
        entity1 = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe"
        )
        
        entity2 = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe"
        )
        
        entity3 = Entity(
            employee_id="456",
            email="jane.smith@company.com",
            canonical_name="Jane Smith"
        )
        
        assert entity1 == entity2
        assert entity1 != entity3
        assert hash(entity1) == hash(entity2)
        assert hash(entity1) != hash(entity3)


class TestEntityRegistry:
    """Test EntityRegistry class"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.entities.registry.is_feature_enabled', return_value=True):
            self.registry = EntityRegistry()
    
    def test_entity_registry_initialization(self):
        """Test EntityRegistry initialization"""
        assert len(self.registry.entities) == 0
        assert len(self.registry.entities_by_id) == 0
        assert len(self.registry.entities_by_email) == 0
        assert len(self.registry.entities_by_name) == 0
    
    def test_add_entity(self):
        """Test adding an entity to the registry"""
        entity = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            department="Engineering"
        )
        
        self.registry.add_entity(entity)
        
        assert len(self.registry.entities) == 1
        assert self.registry.entities_by_id["123"] == entity
        assert self.registry.entities_by_email["john.doe@company.com"] == entity
        assert self.registry.entities_by_name["John Doe"] == entity
    
    def test_add_entity_with_aliases(self):
        """Test adding an entity with aliases"""
        entity = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            aliases=["John", "J. Doe", "JD"],
            department="Engineering"
        )
        
        self.registry.add_entity(entity)
        
        # Check that aliases are indexed
        assert self.registry.entities_by_name["John"] == entity
        assert self.registry.entities_by_name["J. Doe"] == entity
        assert self.registry.entities_by_name["JD"] == entity
        assert self.registry.entities_by_name["John Doe"] == entity
    
    def test_add_duplicate_entity(self):
        """Test adding a duplicate entity (should update existing)"""
        entity1 = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            department="Engineering"
        )
        
        entity2 = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            department="Engineering",
            job_title="Senior Developer"  # Updated field
        )
        
        self.registry.add_entity(entity1)
        self.registry.add_entity(entity2)
        
        # Should only have one entity
        assert len(self.registry.entities) == 1
        assert self.registry.entities_by_id["123"].job_title == "Senior Developer"
    
    def test_find_by_employee_id(self):
        """Test finding entity by employee ID"""
        entity = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            department="Engineering"
        )
        
        self.registry.add_entity(entity)
        
        found = self.registry.find_by_employee_id("123")
        assert found == entity
        
        not_found = self.registry.find_by_employee_id("456")
        assert not_found is None
    
    def test_find_by_email(self):
        """Test finding entity by email"""
        entity = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            department="Engineering"
        )
        
        self.registry.add_entity(entity)
        
        found = self.registry.find_by_email("john.doe@company.com")
        assert found == entity
        
        not_found = self.registry.find_by_email("jane.smith@company.com")
        assert not_found is None
    
    def test_find_by_name(self):
        """Test finding entity by canonical name"""
        entity = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            department="Engineering"
        )
        
        self.registry.add_entity(entity)
        
        found = self.registry.find_by_name("John Doe")
        assert found == entity
        
        not_found = self.registry.find_by_name("Jane Smith")
        assert not_found is None
    
    def test_find_by_alias(self):
        """Test finding entity by alias"""
        entity = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            aliases=["John", "J. Doe", "JD"],
            department="Engineering"
        )
        
        self.registry.add_entity(entity)
        
        # Find by various aliases
        assert self.registry.find_by_name("John") == entity
        assert self.registry.find_by_name("J. Doe") == entity
        assert self.registry.find_by_name("JD") == entity
        assert self.registry.find_by_name("John Doe") == entity
    
    def test_fuzzy_name_search(self):
        """Test fuzzy name search"""
        entity = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            aliases=["John", "J. Doe"],
            department="Engineering"
        )
        
        self.registry.add_entity(entity)
        
        # Exact matches
        results = self.registry.search_by_name("John Doe")
        assert len(results) == 1
        assert results[0] == entity
        
        # Partial matches
        results = self.registry.search_by_name("John")
        assert len(results) == 1
        assert results[0] == entity
        
        results = self.registry.search_by_name("Doe")
        assert len(results) == 1
        assert results[0] == entity
        
        # No matches
        results = self.registry.search_by_name("Jane Smith")
        assert len(results) == 0
    
    def test_fuzzy_name_search_case_insensitive(self):
        """Test fuzzy name search is case insensitive"""
        entity = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            department="Engineering"
        )
        
        self.registry.add_entity(entity)
        
        # Case insensitive matches
        results = self.registry.search_by_name("john doe")
        assert len(results) == 1
        assert results[0] == entity
        
        results = self.registry.search_by_name("JOHN DOE")
        assert len(results) == 1
        assert results[0] == entity
        
        results = self.registry.search_by_name("John")
        assert len(results) == 1
        assert results[0] == entity
    
    def test_update_entity(self):
        """Test updating an existing entity"""
        entity = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            department="Engineering"
        )
        
        self.registry.add_entity(entity)
        
        # Update the entity
        updated_entity = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            department="Engineering",
            job_title="Senior Developer"
        )
        
        self.registry.update_entity(updated_entity)
        
        found = self.registry.find_by_employee_id("123")
        assert found.job_title == "Senior Developer"
    
    def test_remove_entity(self):
        """Test removing an entity from the registry"""
        entity = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            aliases=["John", "J. Doe"],
            department="Engineering"
        )
        
        self.registry.add_entity(entity)
        assert len(self.registry.entities) == 1
        
        self.registry.remove_entity("123")
        
        assert len(self.registry.entities) == 0
        assert len(self.registry.entities_by_id) == 0
        assert len(self.registry.entities_by_email) == 0
        assert len(self.registry.entities_by_name) == 0
    
    def test_get_all_entities(self):
        """Test getting all entities"""
        entity1 = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            department="Engineering"
        )
        
        entity2 = Entity(
            employee_id="456",
            email="jane.smith@company.com",
            canonical_name="Jane Smith",
            department="HR"
        )
        
        self.registry.add_entity(entity1)
        self.registry.add_entity(entity2)
        
        all_entities = self.registry.get_all_entities()
        assert len(all_entities) == 2
        
        employee_ids = [e.employee_id for e in all_entities]
        assert "123" in employee_ids
        assert "456" in employee_ids
    
    def test_get_entities_by_department(self):
        """Test getting entities by department"""
        entity1 = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            department="Engineering"
        )
        
        entity2 = Entity(
            employee_id="456",
            email="jane.smith@company.com",
            canonical_name="Jane Smith",
            department="HR"
        )
        
        entity3 = Entity(
            employee_id="789",
            email="bob.jones@company.com",
            canonical_name="Bob Jones",
            department="Engineering"
        )
        
        self.registry.add_entity(entity1)
        self.registry.add_entity(entity2)
        self.registry.add_entity(entity3)
        
        engineering_entities = self.registry.get_entities_by_department("Engineering")
        assert len(engineering_entities) == 2
        
        hr_entities = self.registry.get_entities_by_department("HR")
        assert len(hr_entities) == 1
        assert hr_entities[0].canonical_name == "Jane Smith"
    
    def test_clear_registry(self):
        """Test clearing the entire registry"""
        entity = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            department="Engineering"
        )
        
        self.registry.add_entity(entity)
        assert len(self.registry.entities) == 1
        
        self.registry.clear()
        
        assert len(self.registry.entities) == 0
        assert len(self.registry.entities_by_id) == 0
        assert len(self.registry.entities_by_email) == 0
        assert len(self.registry.entities_by_name) == 0


class TestEntityRegistryFeatureFlags:
    """Test EntityRegistry with feature flags"""
    
    def test_feature_disabled(self):
        """Test registry behavior when feature is disabled"""
        with patch('src.backend.entities.registry.is_feature_enabled', return_value=False):
            registry = EntityRegistry()
            
            entity = Entity(
                employee_id="123",
                email="john.doe@company.com",
                canonical_name="John Doe"
            )
            
            # Should still work but log that feature is disabled
            registry.add_entity(entity)
            assert len(registry.entities) == 1


class TestEntityRegistryEdgeCases:
    """Test EntityRegistry edge cases"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.entities.registry.is_feature_enabled', return_value=True):
            self.registry = EntityRegistry()
    
    def test_add_entity_with_none_values(self):
        """Test adding entity with None values"""
        entity = Entity(
            employee_id="123",
            email=None,
            canonical_name="John Doe",
            department=None
        )
        
        self.registry.add_entity(entity)
        
        # Should still be indexed by employee_id and canonical_name
        assert self.registry.find_by_employee_id("123") == entity
        assert self.registry.find_by_name("John Doe") == entity
        
        # But not by email
        assert self.registry.find_by_email(None) is None
    
    def test_add_entity_with_empty_strings(self):
        """Test adding entity with empty strings"""
        entity = Entity(
            employee_id="123",
            email="",
            canonical_name="",
            department=""
        )
        
        self.registry.add_entity(entity)
        
        # Should still be indexed
        assert self.registry.find_by_employee_id("123") == entity
        assert self.registry.find_by_name("") == entity
        assert self.registry.find_by_email("") == entity
    
    def test_fuzzy_search_with_special_characters(self):
        """Test fuzzy search with special characters"""
        entity = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John-Doe O'Connor",
            aliases=["John-Doe", "O'Connor"],
            department="Engineering"
        )
        
        self.registry.add_entity(entity)
        
        # Search with special characters
        results = self.registry.search_by_name("John-Doe")
        assert len(results) == 1
        assert results[0] == entity
        
        results = self.registry.search_by_name("O'Connor")
        assert len(results) == 1
        assert results[0] == entity
    
    def test_duplicate_aliases(self):
        """Test handling of duplicate aliases"""
        entity1 = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            aliases=["John", "JD"],
            department="Engineering"
        )
        
        entity2 = Entity(
            employee_id="456",
            email="jane.doe@company.com",
            canonical_name="Jane Doe",
            aliases=["Jane", "JD"],  # Same alias
            department="HR"
        )
        
        self.registry.add_entity(entity1)
        self.registry.add_entity(entity2)
        
        # Both should be findable by "JD"
        results = self.registry.search_by_name("JD")
        assert len(results) == 2
        
        # But specific lookups should work
        assert self.registry.find_by_name("John Doe") == entity1
        assert self.registry.find_by_name("Jane Doe") == entity2


class TestEntityRegistryPersistence:
    """Test EntityRegistry persistence methods"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.entities.registry.is_feature_enabled', return_value=True):
            self.registry = EntityRegistry()
    
    def test_save_and_load_json(self):
        """Test saving and loading registry to/from JSON"""
        entity1 = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            department="Engineering"
        )
        
        entity2 = Entity(
            employee_id="456",
            email="jane.smith@company.com",
            canonical_name="Jane Smith",
            department="HR"
        )
        
        self.registry.add_entity(entity1)
        self.registry.add_entity(entity2)
        
        # Save to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_file = f.name
        
        try:
            self.registry.save_to_json(temp_file)
            
            # Create new registry and load
            new_registry = EntityRegistry()
            new_registry.load_from_json(temp_file)
            
            # Verify data
            assert len(new_registry.entities) == 2
            assert new_registry.find_by_employee_id("123") is not None
            assert new_registry.find_by_employee_id("456") is not None
            
        finally:
            # Clean up
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def test_save_and_load_csv(self):
        """Test saving and loading registry to/from CSV"""
        entity1 = Entity(
            employee_id="123",
            email="john.doe@company.com",
            canonical_name="John Doe",
            department="Engineering",
            job_title="Developer"
        )
        
        entity2 = Entity(
            employee_id="456",
            email="jane.smith@company.com",
            canonical_name="Jane Smith",
            department="HR",
            job_title="Manager"
        )
        
        self.registry.add_entity(entity1)
        self.registry.add_entity(entity2)
        
        # Save to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            temp_file = f.name
        
        try:
            self.registry.save_to_csv(temp_file)
            
            # Create new registry and load
            new_registry = EntityRegistry()
            new_registry.load_from_csv(temp_file)
            
            # Verify data
            assert len(new_registry.entities) == 2
            loaded_entity1 = new_registry.find_by_employee_id("123")
            assert loaded_entity1 is not None
            assert loaded_entity1.job_title == "Developer"
            
        finally:
            # Clean up
            if os.path.exists(temp_file):
                os.unlink(temp_file)


class TestGlobalFunctions:
    """Test global functions"""
    
    def test_get_entity_registry(self):
        """Test get_entity_registry function"""
        registry = get_entity_registry()
        assert isinstance(registry, EntityRegistry)
        
        # Should return the same instance
        registry2 = get_entity_registry()
        assert registry is registry2


if __name__ == "__main__":
    pytest.main([__file__])
