"""
HR Card Formatter for FinSyntra RAG
Renders employee information with consistent formatting
"""
import re
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime
import locale

from src.config.feature_flags import is_feature_enabled

logger = logging.getLogger(__name__)

@dataclass
class EmployeeCard:
    """Represents a formatted employee card"""
    employee_id: str
    name: str
    email: Optional[str] = None
    department: Optional[str] = None
    job_title: Optional[str] = None
    salary: Optional[str] = None
    manager: Optional[str] = None
    start_date: Optional[str] = None
    location: Optional[str] = None
    phone: Optional[str] = None
    formatted_fields: Dict[str, str] = None
    
    def __post_init__(self):
        if self.formatted_fields is None:
            self.formatted_fields = {}

class HRCardFormatter:
    """
    Formats employee information into consistent, readable cards
    Handles currency, dates, and missing values consistently
    """
    
    def __init__(self):
        self.enabled = is_feature_enabled('ENABLE_CSV_NORMALIZATION')
        self.default_locale = 'en_US'
        self.currency_symbol = '$'
        
        # Set locale for formatting
        try:
            locale.setlocale(locale.LC_ALL, self.default_locale)
        except locale.Error:
            logger.warning(f"Could not set locale to {self.default_locale}, using system default")
        
        logger.info("HRCardFormatter initialized")
    
    def format_employee_card(
        self, 
        employee_data: Dict[str, Any],
        include_sensitive: bool = False,
        user_role: Optional[str] = None
    ) -> EmployeeCard:
        """
        Format employee data into a consistent card
        Handles sensitive data based on user role and permissions
        """
        # Extract basic information
        employee_id = str(employee_data.get('employee_id', 'N/A'))
        name = employee_data.get('name', 'Unknown')
        email = employee_data.get('email')
        department = employee_data.get('department')
        job_title = employee_data.get('job_title')
        salary = employee_data.get('salary')
        manager = employee_data.get('manager')
        start_date = employee_data.get('start_date')
        location = employee_data.get('location')
        phone = employee_data.get('phone')
        
        # Format fields
        formatted_fields = {}
        
        # Format salary (handle sensitive data)
        if salary and include_sensitive:
            formatted_salary = self._format_currency(salary)
            formatted_fields['salary'] = formatted_salary
        elif salary and not include_sensitive:
            # Show salary range instead of exact value
            formatted_salary = self._format_salary_range(salary)
            formatted_fields['salary'] = formatted_salary
        else:
            formatted_fields['salary'] = 'N/A'
        
        # Format dates
        if start_date:
            formatted_start_date = self._format_date(start_date)
            formatted_fields['start_date'] = formatted_start_date
        else:
            formatted_fields['start_date'] = 'N/A'
        
        # Format other fields
        formatted_fields['email'] = self._format_email(email) if email else 'N/A'
        formatted_fields['phone'] = self._format_phone(phone) if phone else 'N/A'
        formatted_fields['department'] = department.title() if department else 'N/A'
        formatted_fields['job_title'] = job_title.title() if job_title else 'N/A'
        formatted_fields['manager'] = manager.title() if manager else 'N/A'
        formatted_fields['location'] = location.title() if location else 'N/A'
        
        return EmployeeCard(
            employee_id=employee_id,
            name=name,
            email=email,
            department=department,
            job_title=job_title,
            salary=salary,
            manager=manager,
            start_date=start_date,
            location=location,
            phone=phone,
            formatted_fields=formatted_fields
        )
    
    def _format_currency(self, value: Any) -> str:
        """Format value as currency"""
        if not self.enabled:
            return str(value)
        
        try:
            if value is None or value == '' or str(value).lower() in ['nan', 'none', 'null']:
                return 'N/A'
            
            # Convert to float
            if isinstance(value, str):
                # Remove currency symbols and commas
                clean_value = re.sub(r'[^\d.-]', '', value)
                if not clean_value:
                    return 'N/A'
                numeric_value = float(clean_value)
            else:
                numeric_value = float(value)
            
            # Format as USD with 2 decimal places and thousands separators
            formatted = f"${numeric_value:,.2f}"
            return formatted
            
        except (ValueError, TypeError):
            return 'N/A'
    
    def _format_salary_range(self, salary: Any) -> str:
        """Format salary as a range for privacy"""
        if not self.enabled:
            return 'N/A'
        
        try:
            if salary is None or salary == '' or str(salary).lower() in ['nan', 'none', 'null']:
                return 'N/A'
            
            # Convert to float
            if isinstance(salary, str):
                clean_salary = re.sub(r'[^\d.-]', '', salary)
                if not clean_salary:
                    return 'N/A'
                numeric_salary = float(clean_salary)
            else:
                numeric_salary = float(salary)
            
            # Create range buckets
            if numeric_salary < 50000:
                return '$30,000 - $50,000'
            elif numeric_salary < 75000:
                return '$50,000 - $75,000'
            elif numeric_salary < 100000:
                return '$75,000 - $100,000'
            elif numeric_salary < 150000:
                return '$100,000 - $150,000'
            elif numeric_salary < 200000:
                return '$150,000 - $200,000'
            else:
                return '$200,000+'
                
        except (ValueError, TypeError):
            return 'N/A'
    
    def _format_date(self, value: Any) -> str:
        """Format date consistently"""
        if not self.enabled:
            return str(value)
        
        try:
            if value is None or value == '' or str(value).lower() in ['nan', 'none', 'null']:
                return 'N/A'
            
            # Parse date
            if isinstance(value, str):
                # Try common date formats
                date_formats = [
                    '%Y-%m-%d',
                    '%m/%d/%Y',
                    '%d/%m/%Y',
                    '%Y-%m-%d %H:%M:%S',
                    '%B %d, %Y',
                    '%b %d, %Y'
                ]
                
                parsed_date = None
                for fmt in date_formats:
                    try:
                        parsed_date = datetime.strptime(value, fmt)
                        break
                    except ValueError:
                        continue
                
                if not parsed_date:
                    # Try pandas-style parsing
                    try:
                        import pandas as pd
                        parsed_date = pd.to_datetime(value)
                    except:
                        return 'N/A'
            else:
                parsed_date = value
            
            # Format as ISO date (YYYY-MM-DD)
            formatted_date = parsed_date.strftime('%Y-%m-%d')
            return formatted_date
            
        except (ValueError, TypeError):
            return 'N/A'
    
    def _format_email(self, email: str) -> str:
        """Format email consistently"""
        if not email:
            return 'N/A'
        
        # Basic email validation and formatting
        email = email.strip().lower()
        
        # Simple email pattern check
        email_pattern = r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$'
        if re.match(email_pattern, email):
            return email
        else:
            return 'N/A'
    
    def _format_phone(self, phone: str) -> str:
        """Format phone number consistently"""
        if not phone:
            return 'N/A'
        
        # Remove all non-digit characters
        digits = re.sub(r'\D', '', str(phone))
        
        if len(digits) == 10:
            # Format as (XXX) XXX-XXXX
            return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        elif len(digits) == 11 and digits[0] == '1':
            # Format as 1 (XXX) XXX-XXXX
            return f"1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        else:
            # Return as-is if format is unknown
            return str(phone)
    
    def render_card_text(self, card: EmployeeCard, format_type: str = "detailed") -> str:
        """Render employee card as formatted text"""
        if format_type == "compact":
            return self._render_compact_card(card)
        elif format_type == "summary":
            return self._render_summary_card(card)
        else:
            return self._render_detailed_card(card)
    
    def _render_compact_card(self, card: EmployeeCard) -> str:
        """Render compact employee card"""
        lines = [
            f"👤 {card.name}",
            f"🆔 {card.employee_id}",
            f"🏢 {card.formatted_fields['department']}",
            f"💼 {card.formatted_fields['job_title']}"
        ]
        
        return "\n".join(lines)
    
    def _render_summary_card(self, card: EmployeeCard) -> str:
        """Render summary employee card"""
        lines = [
            f"👤 **{card.name}**",
            f"🆔 Employee ID: {card.employee_id}",
            f"🏢 Department: {card.formatted_fields['department']}",
            f"💼 Job Title: {card.formatted_fields['job_title']}",
            f"📧 Email: {card.formatted_fields['email']}",
            f"💰 Salary: {card.formatted_fields['salary']}",
            f"📅 Start Date: {card.formatted_fields['start_date']}"
        ]
        
        return "\n".join(lines)
    
    def _render_detailed_card(self, card: EmployeeCard) -> str:
        """Render detailed employee card"""
        lines = [
            f"👤 **{card.name}**",
            f"🆔 Employee ID: {card.employee_id}",
            f"🏢 Department: {card.formatted_fields['department']}",
            f"💼 Job Title: {card.formatted_fields['job_title']}",
            f"📧 Email: {card.formatted_fields['email']}",
            f"💰 Salary: {card.formatted_fields['salary']}",
            f"👨‍💼 Manager: {card.formatted_fields['manager']}",
            f"📅 Start Date: {card.formatted_fields['start_date']}",
            f"📍 Location: {card.formatted_fields['location']}",
            f"📞 Phone: {card.formatted_fields['phone']}"
        ]
        
        return "\n".join(lines)
    
    def render_card_html(self, card: EmployeeCard, format_type: str = "detailed") -> str:
        """Render employee card as HTML"""
        if format_type == "compact":
            return self._render_compact_html(card)
        elif format_type == "summary":
            return self._render_summary_html(card)
        else:
            return self._render_detailed_html(card)
    
    def _render_compact_html(self, card: EmployeeCard) -> str:
        """Render compact HTML card"""
        html = f"""
        <div class="employee-card compact">
            <div class="employee-header">
                <span class="employee-name">{card.name}</span>
                <span class="employee-id">ID: {card.employee_id}</span>
            </div>
            <div class="employee-details">
                <span class="department">{card.formatted_fields['department']}</span>
                <span class="job-title">{card.formatted_fields['job_title']}</span>
            </div>
        </div>
        """
        return html.strip()
    
    def _render_summary_html(self, card: EmployeeCard) -> str:
        """Render summary HTML card"""
        html = f"""
        <div class="employee-card summary">
            <div class="employee-header">
                <h3 class="employee-name">{card.name}</h3>
                <span class="employee-id">Employee ID: {card.employee_id}</span>
            </div>
            <div class="employee-details">
                <div class="detail-row">
                    <span class="label">Department:</span>
                    <span class="value">{card.formatted_fields['department']}</span>
                </div>
                <div class="detail-row">
                    <span class="label">Job Title:</span>
                    <span class="value">{card.formatted_fields['job_title']}</span>
                </div>
                <div class="detail-row">
                    <span class="label">Email:</span>
                    <span class="value">{card.formatted_fields['email']}</span>
                </div>
                <div class="detail-row">
                    <span class="label">Salary:</span>
                    <span class="value">{card.formatted_fields['salary']}</span>
                </div>
                <div class="detail-row">
                    <span class="label">Start Date:</span>
                    <span class="value">{card.formatted_fields['start_date']}</span>
                </div>
            </div>
        </div>
        """
        return html.strip()
    
    def _render_detailed_html(self, card: EmployeeCard) -> str:
        """Render detailed HTML card"""
        html = f"""
        <div class="employee-card detailed">
            <div class="employee-header">
                <h3 class="employee-name">{card.name}</h3>
                <span class="employee-id">Employee ID: {card.employee_id}</span>
            </div>
            <div class="employee-details">
                <div class="detail-row">
                    <span class="label">Department:</span>
                    <span class="value">{card.formatted_fields['department']}</span>
                </div>
                <div class="detail-row">
                    <span class="label">Job Title:</span>
                    <span class="value">{card.formatted_fields['job_title']}</span>
                </div>
                <div class="detail-row">
                    <span class="label">Email:</span>
                    <span class="value">{card.formatted_fields['email']}</span>
                </div>
                <div class="detail-row">
                    <span class="label">Salary:</span>
                    <span class="value">{card.formatted_fields['salary']}</span>
                </div>
                <div class="detail-row">
                    <span class="label">Manager:</span>
                    <span class="value">{card.formatted_fields['manager']}</span>
                </div>
                <div class="detail-row">
                    <span class="label">Start Date:</span>
                    <span class="value">{card.formatted_fields['start_date']}</span>
                </div>
                <div class="detail-row">
                    <span class="label">Location:</span>
                    <span class="value">{card.formatted_fields['location']}</span>
                </div>
                <div class="detail-row">
                    <span class="label">Phone:</span>
                    <span class="value">{card.formatted_fields['phone']}</span>
                </div>
            </div>
        </div>
        """
        return html.strip()
    
    def get_card_css(self) -> str:
        """Get CSS styles for employee cards"""
        return """
        .employee-card {
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 16px;
            margin: 12px 0;
            background: #ffffff;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .employee-card.compact {
            padding: 12px;
        }
        
        .employee-card.summary {
            padding: 16px;
        }
        
        .employee-card.detailed {
            padding: 20px;
        }
        
        .employee-header {
            border-bottom: 1px solid #f0f0f0;
            padding-bottom: 12px;
            margin-bottom: 16px;
        }
        
        .employee-name {
            font-size: 18px;
            font-weight: 600;
            color: #333;
            display: block;
            margin-bottom: 4px;
        }
        
        .employee-id {
            font-size: 14px;
            color: #666;
            font-family: monospace;
        }
        
        .employee-details {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        
        .detail-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 4px 0;
        }
        
        .label {
            font-weight: 500;
            color: #555;
            min-width: 100px;
        }
        
        .value {
            color: #333;
            text-align: right;
        }
        
        .department, .job-title {
            display: inline-block;
            padding: 4px 8px;
            background: #f8f9fa;
            border-radius: 4px;
            font-size: 12px;
            color: #666;
        }
        """

# Global HR card formatter instance
hr_card_formatter = HRCardFormatter()

def get_hr_card_formatter() -> HRCardFormatter:
    """Get the global HR card formatter instance"""
    return hr_card_formatter
