"""
Unit tests for table retriever module
"""
import pytest
from unittest.mock import Mock, patch, mock_open
import tempfile
import os
import pandas as pd
import sqlite3

from src.backend.retrieval.table_retriever import (
    TableRow, TableRetriever, get_table_retriever
)


class TestTableRow:
    """Test TableRow dataclass"""
    
    def test_table_row_creation(self):
        """Test creating a TableRow"""
        row = TableRow(
            row_id=1,
            data={
                "employee_id": "123",
                "name": "John Doe",
                "department": "Engineering",
                "salary": 100000
            },
            source_file="employees.csv",
            chunk_id="chunk_001"
        )
        
        assert row.row_id == 1
        assert row.data["employee_id"] == "123"
        assert row.data["name"] == "John Doe"
        assert row.data["department"] == "Engineering"
        assert row.data["salary"] == 100000
        assert row.source_file == "employees.csv"
        assert row.chunk_id == "chunk_001"
    
    def test_table_row_defaults(self):
        """Test TableRow creation with defaults"""
        row = TableRow(
            row_id=1,
            data={"employee_id": "123"}
        )
        
        assert row.source_file is None
        assert row.chunk_id is None
    
    def test_table_row_get_value(self):
        """Test getting values from TableRow"""
        row = TableRow(
            row_id=1,
            data={
                "employee_id": "123",
                "name": "John Doe",
                "department": "Engineering"
            }
        )
        
        assert row.get_value("employee_id") == "123"
        assert row.get_value("name") == "John Doe"
        assert row.get_value("department") == "Engineering"
        assert row.get_value("nonexistent") is None
    
    def test_table_row_serialization(self):
        """Test TableRow serialization to dict"""
        row = TableRow(
            row_id=1,
            data={
                "employee_id": "123",
                "name": "John Doe",
                "department": "Engineering"
            },
            source_file="employees.csv",
            chunk_id="chunk_001"
        )
        
        row_dict = row.to_dict()
        
        assert row_dict["row_id"] == 1
        assert row_dict["data"]["employee_id"] == "123"
        assert row_dict["data"]["name"] == "John Doe"
        assert row_dict["data"]["department"] == "Engineering"
        assert row_dict["source_file"] == "employees.csv"
        assert row_dict["chunk_id"] == "chunk_001"
    
    def test_table_row_from_dict(self):
        """Test TableRow creation from dict"""
        row_dict = {
            "row_id": 1,
            "data": {
                "employee_id": "123",
                "name": "John Doe",
                "department": "Engineering"
            },
            "source_file": "employees.csv",
            "chunk_id": "chunk_001"
        }
        
        row = TableRow.from_dict(row_dict)
        
        assert row.row_id == 1
        assert row.data["employee_id"] == "123"
        assert row.data["name"] == "John Doe"
        assert row.data["department"] == "Engineering"
        assert row.source_file == "employees.csv"
        assert row.chunk_id == "chunk_001"


class TestTableRetriever:
    """Test TableRetriever class"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.retrieval.table_retriever.is_feature_enabled', return_value=True):
            self.retriever = TableRetriever()
    
    def test_table_retriever_initialization(self):
        """Test TableRetriever initialization"""
        assert self.retriever.db_path == ":memory:"
        assert self.retriever.tables == {}
        assert self.retriever.column_mappings == {}
    
    def test_load_csv_file(self):
        """Test loading a CSV file"""
        # Create a temporary CSV file
        csv_content = """employee_id,name,department,salary
123,John Doe,Engineering,100000
456,Jane Smith,HR,80000
789,Bob Jones,Marketing,90000"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            temp_file = f.name
        
        try:
            # Load the CSV
            table_name = "employees"
            self.retriever.load_csv_file(temp_file, table_name)
            
            # Check that table was created
            assert table_name in self.retriever.tables
            assert len(self.retriever.tables[table_name]) == 3
            
            # Check column mappings
            assert "employee_id" in self.retriever.column_mappings[table_name]
            assert "name" in self.retriever.column_mappings[table_name]
            assert "department" in self.retriever.column_mappings[table_name]
            assert "salary" in self.retriever.column_mappings[table_name]
            
        finally:
            # Clean up
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def test_load_csv_file_with_normalization(self):
        """Test loading CSV with data normalization"""
        # Create CSV with various data formats
        csv_content = """employee_id,name,department,salary,start_date
123,John Doe,Engineering,$100,000,2020-01-01
456,Jane Smith,HR,80000,2020-02-01
789,Bob Jones,Marketing,N/A,2020-03-01"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            temp_file = f.name
        
        try:
            table_name = "employees"
            self.retriever.load_csv_file(temp_file, table_name)
            
            # Check normalization
            table = self.retriever.tables[table_name]
            
            # Salary should be normalized to numbers
            assert table[0].data["salary"] == 100000
            assert table[1].data["salary"] == 80000
            assert table[2].data["salary"] == "N/A"
            
            # Dates should be normalized
            assert table[0].data["start_date"] == "2020-01-01"
            
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def test_find_by_employee_id(self):
        """Test finding employee by ID"""
        # Load test data
        csv_content = """employee_id,name,department,salary
123,John Doe,Engineering,100000
456,Jane Smith,HR,80000"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            temp_file = f.name
        
        try:
            table_name = "employees"
            self.retriever.load_csv_file(temp_file, table_name)
            
            # Find by employee ID
            result = self.retriever.find_by_employee_id("123")
            assert result is not None
            assert result.data["name"] == "John Doe"
            assert result.data["department"] == "Engineering"
            
            # Find non-existent employee
            result = self.retriever.find_by_employee_id("999")
            assert result is None
            
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def test_find_by_email(self):
        """Test finding employee by email"""
        # Load test data with emails
        csv_content = """employee_id,name,email,department
123,John Doe,john@company.com,Engineering
456,Jane Smith,jane@company.com,HR"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            temp_file = f.name
        
        try:
            table_name = "employees"
            self.retriever.load_csv_file(temp_file, table_name)
            
            # Find by email
            result = self.retriever.find_by_email("john@company.com")
            assert result is not None
            assert result.data["name"] == "John Doe"
            assert result.data["employee_id"] == "123"
            
            # Find non-existent email
            result = self.retriever.find_by_email("nonexistent@company.com")
            assert result is None
            
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def test_find_by_name(self):
        """Test finding employee by name"""
        # Load test data
        csv_content = """employee_id,name,department,salary
123,John Doe,Engineering,100000
456,Jane Smith,HR,80000
789,John Smith,Marketing,90000"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            temp_file = f.name
        
        try:
            table_name = "employees"
            self.retriever.load_csv_file(temp_file, table_name)
            
            # Find by exact name
            result = self.retriever.find_by_name("John Doe")
            assert result is not None
            assert result.data["employee_id"] == "123"
            
            # Find by partial name
            results = self.retriever.search_by_name("John")
            assert len(results) == 2
            employee_ids = [r.data["employee_id"] for r in results]
            assert "123" in employee_ids
            assert "789" in employee_ids
            
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def test_search_by_department(self):
        """Test searching employees by department"""
        # Load test data
        csv_content = """employee_id,name,department,salary
123,John Doe,Engineering,100000
456,Jane Smith,HR,80000
789,Bob Jones,Engineering,95000
101,Alice Brown,HR,75000"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            temp_file = f.name
        
        try:
            table_name = "employees"
            self.retriever.load_csv_file(temp_file, table_name)
            
            # Search by department
            engineering_results = self.retriever.search_by_department("Engineering")
            assert len(engineering_results) == 2
            
            hr_results = self.retriever.search_by_department("HR")
            assert len(hr_results) == 2
            
            # Search non-existent department
            results = self.retriever.search_by_department("Marketing")
            assert len(results) == 0
            
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def test_get_all_rows(self):
        """Test getting all rows from a table"""
        # Load test data
        csv_content = """employee_id,name,department
123,John Doe,Engineering
456,Jane Smith,HR
789,Bob Jones,Marketing"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            temp_file = f.name
        
        try:
            table_name = "employees"
            self.retriever.load_csv_file(temp_file, table_name)
            
            # Get all rows
            all_rows = self.retriever.get_all_rows(table_name)
            assert len(all_rows) == 3
            
            # Check row data
            employee_ids = [row.data["employee_id"] for row in all_rows]
            assert "123" in employee_ids
            assert "456" in employee_ids
            assert "789" in employee_ids
            
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def test_normalize_column_names(self):
        """Test column name normalization"""
        # Test various column name formats
        column_names = [
            "Employee ID",
            "employee_id",
            "EmployeeID",
            "employee-id",
            "employee.id",
            "EMPLOYEE_ID"
        ]
        
        normalized = self.retriever.normalize_column_names(column_names)
        
        # Should all normalize to the same format
        expected = "employee_id"
        for name in normalized:
            assert normalized[name] == expected
    
    def test_infer_data_types(self):
        """Test data type inference"""
        # Test various data types
        sample_data = {
            "employee_id": ["123", "456", "789"],
            "name": ["John Doe", "Jane Smith", "Bob Jones"],
            "salary": ["100000", "80000", "90000"],
            "start_date": ["2020-01-01", "2020-02-01", "2020-03-01"],
            "is_active": ["true", "false", "true"]
        }
        
        data_types = self.retriever.infer_data_types(sample_data)
        
        assert data_types["employee_id"] == "string"
        assert data_types["name"] == "string"
        assert data_types["salary"] == "integer"
        assert data_types["start_date"] == "date"
        assert data_types["is_active"] == "boolean"
    
    def test_normalize_value(self):
        """Test value normalization"""
        # Test currency normalization
        assert self.retriever.normalize_value("$100,000", "currency") == 100000
        assert self.retriever.normalize_value("100000", "currency") == 100000
        assert self.retriever.normalize_value("$100,000.50", "currency") == 100000.50
        
        # Test date normalization
        assert self.retriever.normalize_value("2020-01-01", "date") == "2020-01-01"
        assert self.retriever.normalize_value("01/01/2020", "date") == "2020-01-01"
        assert self.retriever.normalize_value("January 1, 2020", "date") == "2020-01-01"
        
        # Test missing value normalization
        assert self.retriever.normalize_value("N/A", "string") == "N/A"
        assert self.retriever.normalize_value("", "string") == "N/A"
        assert self.retriever.normalize_value("null", "string") == "N/A"
    
    def test_create_sqlite_table(self):
        """Test creating SQLite table"""
        # Load test data
        csv_content = """employee_id,name,department,salary
123,John Doe,Engineering,100000
456,Jane Smith,HR,80000"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            temp_file = f.name
        
        try:
            table_name = "employees"
            self.retriever.load_csv_file(temp_file, table_name)
            
            # Check that SQLite table was created
            assert hasattr(self.retriever, 'db_connection')
            
            # Test SQL query
            cursor = self.retriever.db_connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM employees")
            count = cursor.fetchone()[0]
            assert count == 2
            
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)


class TestTableRetrieverFeatureFlags:
    """Test TableRetriever with feature flags"""
    
    def test_feature_disabled(self):
        """Test retriever behavior when feature is disabled"""
        with patch('src.backend.retrieval.table_retriever.is_feature_enabled', return_value=False):
            retriever = TableRetriever()
            
            # Should still work but log that feature is disabled
            result = retriever.find_by_employee_id("123")
            assert result is None


class TestTableRetrieverEdgeCases:
    """Test TableRetriever edge cases"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.retrieval.table_retriever.is_feature_enabled', return_value=True):
            self.retriever = TableRetriever()
    
    def test_empty_csv_file(self):
        """Test loading empty CSV file"""
        # Create empty CSV
        csv_content = "employee_id,name,department\n"
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            temp_file = f.name
        
        try:
            table_name = "employees"
            self.retriever.load_csv_file(temp_file, table_name)
            
            # Should handle empty file gracefully
            assert table_name in self.retriever.tables
            assert len(self.retriever.tables[table_name]) == 0
            
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def test_csv_with_missing_values(self):
        """Test CSV with missing values"""
        # Create CSV with missing values
        csv_content = """employee_id,name,department,salary
123,John Doe,Engineering,100000
456,,HR,
789,Bob Jones,,90000"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            temp_file = f.name
        
        try:
            table_name = "employees"
            self.retriever.load_csv_file(temp_file, table_name)
            
            # Should normalize missing values
            table = self.retriever.tables[table_name]
            
            # Row 1: complete
            assert table[0].data["name"] == "John Doe"
            assert table[0].data["department"] == "Engineering"
            assert table[0].data["salary"] == 100000
            
            # Row 2: missing name and salary
            assert table[1].data["name"] == "N/A"
            assert table[1].data["department"] == "HR"
            assert table[1].data["salary"] == "N/A"
            
            # Row 3: missing department
            assert table[2].data["name"] == "Bob Jones"
            assert table[2].data["department"] == "N/A"
            assert table[2].data["salary"] == 90000
            
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def test_csv_with_special_characters(self):
        """Test CSV with special characters"""
        # Create CSV with special characters
        csv_content = """employee_id,name,department,salary
123,José García,Ingeniería,100000
456,Mary O'Connor,HR,80000
789,Li Wei,Marketing,90000"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            temp_file = f.name
        
        try:
            table_name = "employees"
            self.retriever.load_csv_file(temp_file, table_name)
            
            # Should handle special characters correctly
            table = self.retriever.tables[table_name]
            
            assert table[0].data["name"] == "José García"
            assert table[0].data["department"] == "Ingeniería"
            assert table[1].data["name"] == "Mary O'Connor"
            assert table[2].data["name"] == "Li Wei"
            
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def test_csv_with_large_numbers(self):
        """Test CSV with large numbers"""
        # Create CSV with large numbers
        csv_content = """employee_id,name,salary,bonus
123,John Doe,100000,15000
456,Jane Smith,80000,12000
789,Bob Jones,90000,13500"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            temp_file = f.name
        
        try:
            table_name = "employees"
            self.retriever.load_csv_file(temp_file, table_name)
            
            # Should handle large numbers correctly
            table = self.retriever.tables[table_name]
            
            assert table[0].data["salary"] == 100000
            assert table[0].data["bonus"] == 15000
            assert table[1].data["salary"] == 80000
            assert table[1].data["bonus"] == 12000
            
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def test_duplicate_employee_ids(self):
        """Test handling of duplicate employee IDs"""
        # Create CSV with duplicate IDs
        csv_content = """employee_id,name,department
123,John Doe,Engineering
123,John Smith,Marketing
456,Jane Smith,HR"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            temp_file = f.name
        
        try:
            table_name = "employees"
            self.retriever.load_csv_file(temp_file, table_name)
            
            # Should handle duplicates (last one wins)
            table = self.retriever.tables[table_name]
            assert len(table) == 3
            
            # Find by ID should return the last occurrence
            result = self.retriever.find_by_employee_id("123")
            assert result is not None
            assert result.data["name"] == "John Smith"
            assert result.data["department"] == "Marketing"
            
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)


class TestTableRetrieverIntegration:
    """Test TableRetriever integration scenarios"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.retrieval.table_retriever.is_feature_enabled', return_value=True):
            self.retriever = TableRetriever()
    
    def test_complete_hr_workflow(self):
        """Test complete HR workflow with table retriever"""
        # Load comprehensive HR data
        csv_content = """employee_id,name,email,department,job_title,salary,start_date,manager
123,John Doe,john@company.com,Engineering,Senior Developer,100000,2020-01-01,Bob Smith
456,Jane Smith,jane@company.com,HR,Manager,80000,2020-02-01,Alice Brown
789,Bob Jones,bob@company.com,Engineering,Team Lead,95000,2019-06-01,John Doe
101,Alice Brown,alice@company.com,HR,Director,120000,2018-03-01,CEO
202,Charlie Wilson,charlie@company.com,Marketing,Specialist,75000,2021-01-01,Jane Smith"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            temp_file = f.name
        
        try:
            table_name = "employees"
            self.retriever.load_csv_file(temp_file, table_name)
            
            # Test various search scenarios
            
            # 1. Find by employee ID
            employee = self.retriever.find_by_employee_id("123")
            assert employee.data["name"] == "John Doe"
            assert employee.data["job_title"] == "Senior Developer"
            
            # 2. Find by email
            employee = self.retriever.find_by_email("jane@company.com")
            assert employee.data["name"] == "Jane Smith"
            assert employee.data["department"] == "HR"
            
            # 3. Search by department
            engineering_employees = self.retriever.search_by_department("Engineering")
            assert len(engineering_employees) == 2
            
            hr_employees = self.retriever.search_by_department("HR")
            assert len(hr_employees) == 2
            
            # 4. Search by name
            john_results = self.retriever.search_by_name("John")
            assert len(john_results) == 1
            
            # 5. Get all employees
            all_employees = self.retriever.get_all_rows(table_name)
            assert len(all_employees) == 5
            
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def test_multiple_table_support(self):
        """Test loading and querying multiple tables"""
        # Create multiple CSV files
        employees_csv = """employee_id,name,department
123,John Doe,Engineering
456,Jane Smith,HR"""
        
        projects_csv = """project_id,name,lead_employee_id,status
P001,FinSyntra,123,Active
P002,DataSync,456,Completed"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as emp_file:
            emp_file.write(employees_csv)
            emp_temp = emp_file.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as proj_file:
            proj_file.write(projects_csv)
            proj_temp = proj_file.name
        
        try:
            # Load both tables
            self.retriever.load_csv_file(emp_temp, "employees")
            self.retriever.load_csv_file(proj_temp, "projects")
            
            # Check both tables exist
            assert "employees" in self.retriever.tables
            assert "projects" in self.retriever.tables
            
            # Query across tables
            john = self.retriever.find_by_employee_id("123")
            assert john.data["name"] == "John Doe"
            
            johns_projects = self.retriever.search_by_field("projects", "lead_employee_id", "123")
            assert len(johns_projects) == 1
            assert johns_projects[0].data["name"] == "FinSyntra"
            
        finally:
            # Clean up
            for temp_file in [emp_temp, proj_temp]:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)


class TestGlobalFunctions:
    """Test global functions"""
    
    def test_get_table_retriever(self):
        """Test get_table_retriever function"""
        retriever = get_table_retriever()
        assert isinstance(retriever, TableRetriever)
        
        # Should return the same instance
        retriever2 = get_table_retriever()
        assert retriever is retriever2


if __name__ == "__main__":
    pytest.main([__file__])
