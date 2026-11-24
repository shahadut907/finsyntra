"""
Unit tests for HR card formatter module
"""
import pytest
from unittest.mock import Mock, patch

from src.backend.formatters.hr_card import (
    EmployeeCard, HRCardFormatter, get_hr_card_formatter
)


class TestEmployeeCard:
    """Test EmployeeCard dataclass"""
    
    def test_employee_card_creation(self):
        """Test creating an EmployeeCard"""
        card = EmployeeCard(
            employee_id="123",
            name="John Doe",
            email="john.doe@company.com",
            department="Engineering",
            job_title="Senior Developer",
            salary=100000,
            start_date="2020-01-01",
            phone="+1-555-123-4567",
            manager="Bob Smith",
            location="San Francisco"
        )
        
        assert card.employee_id == "123"
        assert card.name == "John Doe"
        assert card.email == "john.doe@company.com"
        assert card.department == "Engineering"
        assert card.job_title == "Senior Developer"
        assert card.salary == 100000
        assert card.start_date == "2020-01-01"
        assert card.phone == "+1-555-123-4567"
        assert card.manager == "Bob Smith"
        assert card.location == "San Francisco"
    
    def test_employee_card_defaults(self):
        """Test EmployeeCard creation with defaults"""
        card = EmployeeCard(
            employee_id="123",
            name="John Doe"
        )
        
        assert card.email is None
        assert card.department is None
        assert card.job_title is None
        assert card.salary is None
        assert card.start_date is None
        assert card.phone is None
        assert card.manager is None
        assert card.location is None
    
    def test_employee_card_serialization(self):
        """Test EmployeeCard serialization to dict"""
        card = EmployeeCard(
            employee_id="123",
            name="John Doe",
            email="john.doe@company.com",
            department="Engineering",
            job_title="Senior Developer",
            salary=100000,
            start_date="2020-01-01"
        )
        
        card_dict = card.to_dict()
        
        assert card_dict["employee_id"] == "123"
        assert card_dict["name"] == "John Doe"
        assert card_dict["email"] == "john.doe@company.com"
        assert card_dict["department"] == "Engineering"
        assert card_dict["job_title"] == "Senior Developer"
        assert card_dict["salary"] == 100000
        assert card_dict["start_date"] == "2020-01-01"
    
    def test_employee_card_from_dict(self):
        """Test EmployeeCard creation from dict"""
        card_dict = {
            "employee_id": "123",
            "name": "John Doe",
            "email": "john.doe@company.com",
            "department": "Engineering",
            "job_title": "Senior Developer",
            "salary": 100000,
            "start_date": "2020-01-01"
        }
        
        card = EmployeeCard.from_dict(card_dict)
        
        assert card.employee_id == "123"
        assert card.name == "John Doe"
        assert card.email == "john.doe@company.com"
        assert card.department == "Engineering"
        assert card.job_title == "Senior Developer"
        assert card.salary == 100000
        assert card.start_date == "2020-01-01"


class TestHRCardFormatter:
    """Test HRCardFormatter class"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.formatters.hr_card.is_feature_enabled', return_value=True):
            self.formatter = HRCardFormatter()
    
    def test_hr_card_formatter_initialization(self):
        """Test HRCardFormatter initialization"""
        assert self.formatter.currency_format == "USD"
        assert self.formatter.date_format == "ISO"
        assert self.formatter.enable_salary_masking is True
        assert self.formatter.salary_mask_threshold == 50000
    
    def test_format_currency(self):
        """Test currency formatting"""
        # Test various salary amounts
        assert self.formatter.format_currency(100000) == "$100,000.00"
        assert self.formatter.format_currency(50000) == "$50,000.00"
        assert self.formatter.format_currency(123456) == "$123,456.00"
        assert self.formatter.format_currency(0) == "$0.00"
        assert self.formatter.format_currency(1000.50) == "$1,000.50"
        assert self.formatter.format_currency(1000000) == "$1,000,000.00"
    
    def test_format_currency_with_none(self):
        """Test currency formatting with None values"""
        assert self.formatter.format_currency(None) == "N/A"
    
    def test_format_currency_with_string(self):
        """Test currency formatting with string values"""
        assert self.formatter.format_currency("100000") == "$100,000.00"
        assert self.formatter.format_currency("N/A") == "N/A"
    
    def test_format_date(self):
        """Test date formatting"""
        # Test various date formats
        assert self.formatter.format_date("2020-01-01") == "2020-01-01"
        assert self.formatter.format_date("01/01/2020") == "2020-01-01"
        assert self.formatter.format_date("January 1, 2020") == "2020-01-01"
        assert self.formatter.format_date("2020-1-1") == "2020-01-01"
        assert self.formatter.format_date("2020-12-31") == "2020-12-31"
    
    def test_format_date_with_none(self):
        """Test date formatting with None values"""
        assert self.formatter.format_date(None) == "N/A"
    
    def test_format_date_with_invalid_format(self):
        """Test date formatting with invalid formats"""
        assert self.formatter.format_date("invalid-date") == "N/A"
        assert self.formatter.format_date("") == "N/A"
    
    def test_format_phone(self):
        """Test phone number formatting"""
        # Test various phone formats
        assert self.formatter.format_phone("+1-555-123-4567") == "+1-555-123-4567"
        assert self.formatter.format_phone("555-123-4567") == "555-123-4567"
        assert self.formatter.format_phone("(555) 123-4567") == "(555) 123-4567"
        assert self.formatter.format_phone("5551234567") == "555-123-4567"
        assert self.formatter.format_phone("555.123.4567") == "555-123-4567"
    
    def test_format_phone_with_none(self):
        """Test phone formatting with None values"""
        assert self.formatter.format_phone(None) == "N/A"
    
    def test_format_phone_with_invalid_format(self):
        """Test phone formatting with invalid formats"""
        assert self.formatter.format_phone("invalid-phone") == "N/A"
        assert self.formatter.format_phone("") == "N/A"
    
    def test_mask_salary(self):
        """Test salary masking"""
        # Test salary masking based on threshold
        assert self.formatter.mask_salary(100000) == "$100,000.00"  # Above threshold
        assert self.formatter.mask_salary(50000) == "$50,000.00"    # At threshold
        assert self.formatter.mask_salary(25000) == "$25,000.00"    # Below threshold
        
        # Test with masking disabled
        self.formatter.enable_salary_masking = False
        assert self.formatter.mask_salary(25000) == "$25,000.00"
        
        # Re-enable masking
        self.formatter.enable_salary_masking = True
    
    def test_mask_salary_with_ranges(self):
        """Test salary masking with ranges"""
        # Test salary range masking
        assert self.formatter.mask_salary(25000) == "$25,000.00"  # Exact amount
        assert self.formatter.mask_salary(30000) == "$30,000.00"  # Exact amount
        assert self.formatter.mask_salary(40000) == "$40,000.00"  # Exact amount
    
    def test_mask_salary_with_none(self):
        """Test salary masking with None values"""
        assert self.formatter.mask_salary(None) == "N/A"
    
    def test_create_employee_card(self):
        """Test creating employee card from data"""
        employee_data = {
            "employee_id": "123",
            "name": "John Doe",
            "email": "john.doe@company.com",
            "department": "Engineering",
            "job_title": "Senior Developer",
            "salary": 100000,
            "start_date": "2020-01-01",
            "phone": "+1-555-123-4567",
            "manager": "Bob Smith",
            "location": "San Francisco"
        }
        
        card = self.formatter.create_employee_card(employee_data)
        
        assert isinstance(card, EmployeeCard)
        assert card.employee_id == "123"
        assert card.name == "John Doe"
        assert card.email == "john.doe@company.com"
        assert card.department == "Engineering"
        assert card.job_title == "Senior Developer"
        assert card.salary == 100000
        assert card.start_date == "2020-01-01"
        assert card.phone == "+1-555-123-4567"
        assert card.manager == "Bob Smith"
        assert card.location == "San Francisco"
    
    def test_create_employee_card_with_missing_fields(self):
        """Test creating employee card with missing fields"""
        employee_data = {
            "employee_id": "123",
            "name": "John Doe"
        }
        
        card = self.formatter.create_employee_card(employee_data)
        
        assert card.employee_id == "123"
        assert card.name == "John Doe"
        assert card.email is None
        assert card.department is None
        assert card.job_title is None
        assert card.salary is None
        assert card.start_date is None
        assert card.phone is None
        assert card.manager is None
        assert card.location is None
    
    def test_render_card_as_text(self):
        """Test rendering employee card as text"""
        card = EmployeeCard(
            employee_id="123",
            name="John Doe",
            email="john.doe@company.com",
            department="Engineering",
            job_title="Senior Developer",
            salary=100000,
            start_date="2020-01-01",
            phone="+1-555-123-4567",
            manager="Bob Smith",
            location="San Francisco"
        )
        
        text = self.formatter.render_card_as_text(card)
        
        # Should contain all employee information
        assert "Employee ID: 123" in text
        assert "Name: John Doe" in text
        assert "Email: john.doe@company.com" in text
        assert "Department: Engineering" in text
        assert "Job Title: Senior Developer" in text
        assert "Salary: $100,000.00" in text
        assert "Start Date: 2020-01-01" in text
        assert "Phone: +1-555-123-4567" in text
        assert "Manager: Bob Smith" in text
        assert "Location: San Francisco" in text
    
    def test_render_card_as_text_with_missing_fields(self):
        """Test rendering employee card with missing fields"""
        card = EmployeeCard(
            employee_id="123",
            name="John Doe"
        )
        
        text = self.formatter.render_card_as_text(card)
        
        # Should contain available information
        assert "Employee ID: 123" in text
        assert "Name: John Doe" in text
        
        # Should not contain missing fields
        assert "Email:" not in text
        assert "Department:" not in text
        assert "Job Title:" not in text
        assert "Salary:" not in text
        assert "Start Date:" not in text
        assert "Phone:" not in text
        assert "Manager:" not in text
        assert "Location:" not in text
    
    def test_render_card_as_html(self):
        """Test rendering employee card as HTML"""
        card = EmployeeCard(
            employee_id="123",
            name="John Doe",
            email="john.doe@company.com",
            department="Engineering",
            job_title="Senior Developer",
            salary=100000,
            start_date="2020-01-01",
            phone="+1-555-123-4567",
            manager="Bob Smith",
            location="San Francisco"
        )
        
        html = self.formatter.render_card_as_html(card)
        
        # Should contain HTML structure
        assert "<div" in html
        assert "<h3" in html
        assert "<table" in html
        assert "<tr" in html
        assert "<td" in html
        
        # Should contain all employee information
        assert "123" in html
        assert "John Doe" in html
        assert "john.doe@company.com" in html
        assert "Engineering" in html
        assert "Senior Developer" in html
        assert "$100,000.00" in html
        assert "2020-01-01" in html
        assert "+1-555-123-4567" in html
        assert "Bob Smith" in html
        assert "San Francisco" in html
    
    def test_render_card_as_html_with_missing_fields(self):
        """Test rendering employee card as HTML with missing fields"""
        card = EmployeeCard(
            employee_id="123",
            name="John Doe"
        )
        
        html = self.formatter.render_card_as_html(card)
        
        # Should contain HTML structure
        assert "<div" in html
        assert "<h3" in html
        assert "<table" in html
        
        # Should contain available information
        assert "123" in html
        assert "John Doe" in html
        
        # Should not contain missing fields
        assert "john.doe@company.com" not in html
        assert "Engineering" not in html
        assert "Senior Developer" not in html
        assert "$100,000.00" not in html
        assert "2020-01-01" not in html
        assert "+1-555-123-4567" not in html
        assert "Bob Smith" not in html
        assert "San Francisco" not in html
    
    def test_format_employee_data(self):
        """Test formatting employee data for display"""
        employee_data = {
            "employee_id": "123",
            "name": "John Doe",
            "email": "john.doe@company.com",
            "department": "Engineering",
            "job_title": "Senior Developer",
            "salary": 100000,
            "start_date": "2020-01-01",
            "phone": "+1-555-123-4567",
            "manager": "Bob Smith",
            "location": "San Francisco"
        }
        
        formatted_data = self.formatter.format_employee_data(employee_data)
        
        # Should contain formatted values
        assert formatted_data["employee_id"] == "123"
        assert formatted_data["name"] == "John Doe"
        assert formatted_data["email"] == "john.doe@company.com"
        assert formatted_data["department"] == "Engineering"
        assert formatted_data["job_title"] == "Senior Developer"
        assert formatted_data["salary"] == "$100,000.00"
        assert formatted_data["start_date"] == "2020-01-01"
        assert formatted_data["phone"] == "+1-555-123-4567"
        assert formatted_data["manager"] == "Bob Smith"
        assert formatted_data["location"] == "San Francisco"
    
    def test_format_employee_data_with_missing_values(self):
        """Test formatting employee data with missing values"""
        employee_data = {
            "employee_id": "123",
            "name": "John Doe",
            "salary": None,
            "start_date": "",
            "phone": None
        }
        
        formatted_data = self.formatter.format_employee_data(employee_data)
        
        # Should handle missing values gracefully
        assert formatted_data["employee_id"] == "123"
        assert formatted_data["name"] == "John Doe"
        assert formatted_data["salary"] == "N/A"
        assert formatted_data["start_date"] == "N/A"
        assert formatted_data["phone"] == "N/A"


class TestHRCardFormatterFeatureFlags:
    """Test HRCardFormatter with feature flags"""
    
    def test_feature_disabled(self):
        """Test formatter behavior when feature is disabled"""
        with patch('src.backend.formatters.hr_card.is_feature_enabled', return_value=False):
            formatter = HRCardFormatter()
            
            card = EmployeeCard(
                employee_id="123",
                name="John Doe",
                salary=100000
            )
            
            # Should still work but log that feature is disabled
            text = formatter.render_card_as_text(card)
            assert "John Doe" in text


class TestHRCardFormatterEdgeCases:
    """Test HRCardFormatter edge cases"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.formatters.hr_card.is_feature_enabled', return_value=True):
            self.formatter = HRCardFormatter()
    
    def test_format_currency_with_very_large_numbers(self):
        """Test currency formatting with very large numbers"""
        assert self.formatter.format_currency(999999999) == "$999,999,999.00"
        assert self.formatter.format_currency(1000000000) == "$1,000,000,000.00"
    
    def test_format_currency_with_decimal_places(self):
        """Test currency formatting with decimal places"""
        assert self.formatter.format_currency(100000.123) == "$100,000.12"  # Rounded to 2 decimal places
        assert self.formatter.format_currency(100000.999) == "$100,001.00"  # Rounded up
        assert self.formatter.format_currency(100000.001) == "$100,000.00"  # Rounded down
    
    def test_format_date_with_various_formats(self):
        """Test date formatting with various input formats"""
        # Test different date separators
        assert self.formatter.format_date("2020/01/01") == "2020-01-01"
        assert self.formatter.format_date("2020.01.01") == "2020-01-01"
        assert self.formatter.format_date("2020-01-01") == "2020-01-01"
        
        # Test different month formats
        assert self.formatter.format_date("Jan 1, 2020") == "2020-01-01"
        assert self.formatter.format_date("January 1st, 2020") == "2020-01-01"
        assert self.formatter.format_date("Jan. 1, 2020") == "2020-01-01"
        
        # Test different day formats
        assert self.formatter.format_date("January 1, 2020") == "2020-01-01"
        assert self.formatter.format_date("January 01, 2020") == "2020-01-01"
        assert self.formatter.format_date("January 1st, 2020") == "2020-01-01"
        assert self.formatter.format_date("January 1st, 2020") == "2020-01-01"
    
    def test_format_phone_with_various_formats(self):
        """Test phone formatting with various input formats"""
        # Test different country codes
        assert self.formatter.format_phone("+1-555-123-4567") == "+1-555-123-4567"
        assert self.formatter.format_phone("+44-20-7946-0958") == "+44-20-7946-0958"
        assert self.formatter.format_phone("+81-3-1234-5678") == "+81-3-1234-5678"
        
        # Test different separators
        assert self.formatter.format_phone("555.123.4567") == "555-123-4567"
        assert self.formatter.format_phone("555 123 4567") == "555-123-4567"
        assert self.formatter.format_phone("555_123_4567") == "555-123-4567"
    
    def test_salary_masking_edge_cases(self):
        """Test salary masking edge cases"""
        # Test boundary values
        assert self.formatter.mask_salary(49999) == "$49,999.00"  # Just below threshold
        assert self.formatter.mask_salary(50000) == "$50,000.00"  # At threshold
        assert self.formatter.mask_salary(50001) == "$50,001.00"  # Just above threshold
        
        # Test with zero and negative values
        assert self.formatter.mask_salary(0) == "$0.00"
        assert self.formatter.mask_salary(-1000) == "-$1,000.00"
    
    def test_handle_special_characters(self):
        """Test handling of special characters in employee data"""
        card = EmployeeCard(
            employee_id="123",
            name="José García",
            email="jose.garcia@company.com",
            department="Ingeniería",
            job_title="Senior Développeur",
            salary=100000,
            start_date="2020-01-01",
            phone="+1-555-123-4567",
            manager="Mary O'Connor",
            location="San José"
        )
        
        text = self.formatter.render_card_as_text(card)
        
        # Should handle special characters correctly
        assert "José García" in text
        assert "Ingeniería" in text
        assert "Développeur" in text
        assert "Mary O'Connor" in text
        assert "San José" in text
    
    def test_handle_very_long_values(self):
        """Test handling of very long values"""
        long_name = "John" + " Doe" * 50  # Very long name
        long_title = "Senior" + " Developer" * 20  # Very long job title
        
        card = EmployeeCard(
            employee_id="123",
            name=long_name,
            job_title=long_title,
            email="john.doe@company.com"
        )
        
        text = self.formatter.render_card_as_text(card)
        
        # Should handle long values gracefully
        assert long_name in text
        assert long_title in text
        assert "john.doe@company.com" in text


class TestHRCardFormatterIntegration:
    """Test HRCardFormatter integration scenarios"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.formatters.hr_card.is_feature_enabled', return_value=True):
            self.formatter = HRCardFormatter()
    
    def test_complete_hr_workflow(self):
        """Test complete HR workflow with card formatting"""
        # Simulate employee data from database
        employee_data = {
            "employee_id": "123",
            "name": "John Doe",
            "email": "john.doe@company.com",
            "department": "Engineering",
            "job_title": "Senior Developer",
            "salary": 100000,
            "start_date": "2020-01-01",
            "phone": "+1-555-123-4567",
            "manager": "Bob Smith",
            "location": "San Francisco",
            "bonus": 15000,
            "equity": "1000 RSUs",
            "performance_rating": "Exceeds Expectations"
        }
        
        # Create employee card
        card = self.formatter.create_employee_card(employee_data)
        
        # Format data for display
        formatted_data = self.formatter.format_employee_data(employee_data)
        
        # Render in different formats
        text_card = self.formatter.render_card_as_text(card)
        html_card = self.formatter.render_card_as_html(card)
        
        # Verify all information is present
        assert "Employee ID: 123" in text_card
        assert "Name: John Doe" in text_card
        assert "Email: john.doe@company.com" in text_card
        assert "Department: Engineering" in text_card
        assert "Job Title: Senior Developer" in text_card
        assert "Salary: $100,000.00" in text_card
        assert "Start Date: 2020-01-01" in text_card
        assert "Phone: +1-555-123-4567" in text_card
        assert "Manager: Bob Smith" in text_card
        assert "Location: San Francisco" in text_card
        
        # Verify HTML contains the same information
        assert "123" in html_card
        assert "John Doe" in html_card
        assert "john.doe@company.com" in html_card
        assert "Engineering" in html_card
        assert "Senior Developer" in html_card
        assert "$100,000.00" in html_card
        assert "2020-01-01" in html_card
        assert "+1-555-123-4567" in html_card
        assert "Bob Smith" in html_card
        assert "San Francisco" in html_card
    
    def test_multiple_employee_cards(self):
        """Test formatting multiple employee cards"""
        employees_data = [
            {
                "employee_id": "123",
                "name": "John Doe",
                "department": "Engineering",
                "salary": 100000,
                "start_date": "2020-01-01"
            },
            {
                "employee_id": "456",
                "name": "Jane Smith",
                "department": "HR",
                "salary": 80000,
                "start_date": "2020-02-01"
            },
            {
                "employee_id": "789",
                "name": "Bob Jones",
                "department": "Marketing",
                "salary": 90000,
                "start_date": "2020-03-01"
            }
        ]
        
        # Create and format multiple cards
        cards = []
        for emp_data in employees_data:
            card = self.formatter.create_employee_card(emp_data)
            formatted_data = self.formatter.format_employee_data(emp_data)
            text_card = self.formatter.render_card_as_text(card)
            
            cards.append({
                "card": card,
                "formatted_data": formatted_data,
                "text_card": text_card
            })
        
        # Verify all cards were created correctly
        assert len(cards) == 3
        
        # Verify first employee
        assert cards[0]["card"].name == "John Doe"
        assert cards[0]["card"].department == "Engineering"
        assert cards[0]["formatted_data"]["salary"] == "$100,000.00"
        
        # Verify second employee
        assert cards[1]["card"].name == "Jane Smith"
        assert cards[1]["card"].department == "HR"
        assert cards[1]["formatted_data"]["salary"] == "$80,000.00"
        
        # Verify third employee
        assert cards[2]["card"].name == "Bob Jones"
        assert cards[2]["card"].department == "Marketing"
        assert cards[2]["formatted_data"]["salary"] == "$90,000.00"


class TestGlobalFunctions:
    """Test global functions"""
    
    def test_get_hr_card_formatter(self):
        """Test get_hr_card_formatter function"""
        formatter = get_hr_card_formatter()
        assert isinstance(formatter, HRCardFormatter)
        
        # Should return the same instance
        formatter2 = get_hr_card_formatter()
        assert formatter is formatter2


if __name__ == "__main__":
    pytest.main([__file__])

