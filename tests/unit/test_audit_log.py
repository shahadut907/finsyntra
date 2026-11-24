"""
Unit tests for audit logger module
"""
import pytest
from unittest.mock import Mock, patch, mock_open
import tempfile
import os
import json
from datetime import datetime

from src.backend.audit.log import (
    AuditEvent, DataSensitivityLevel, AuditLogger, get_audit_logger
)


class TestDataSensitivityLevel:
    """Test DataSensitivityLevel enum"""
    
    def test_sensitivity_levels(self):
        """Test all sensitivity levels exist"""
        assert DataSensitivityLevel.PUBLIC is not None
        assert DataSensitivityLevel.INTERNAL is not None
        assert DataSensitivityLevel.CONFIDENTIAL is not None
        assert DataSensitivityLevel.RESTRICTED is not None
        assert DataSensitivityLevel.HIGHLY_RESTRICTED is not None
    
    def test_sensitivity_level_comparison(self):
        """Test sensitivity level comparison"""
        assert DataSensitivityLevel.PUBLIC < DataSensitivityLevel.INTERNAL
        assert DataSensitivityLevel.INTERNAL < DataSensitivityLevel.CONFIDENTIAL
        assert DataSensitivityLevel.CONFIDENTIAL < DataSensitivityLevel.RESTRICTED
        assert DataSensitivityLevel.RESTRICTED < DataSensitivityLevel.HIGHLY_RESTRICTED


class TestAuditEvent:
    """Test AuditEvent dataclass"""
    
    def test_audit_event_creation(self):
        """Test creating an AuditEvent"""
        event = AuditEvent(
            event_id="evt_001",
            timestamp=datetime.now(),
            user_id="user_123",
            user_role="HR",
            action="ACCESS_SENSITIVE_DATA",
            resource_type="employee_salary",
            resource_id="emp_456",
            sensitivity_level=DataSensitivityLevel.RESTRICTED,
            policy_decision="ALLOWED",
            justification="HR business need",
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0",
            session_id="sess_789",
            metadata={"department": "HR", "purpose": "compensation review"}
        )
        
        assert event.event_id == "evt_001"
        assert event.user_id == "user_123"
        assert event.user_role == "HR"
        assert event.action == "ACCESS_SENSITIVE_DATA"
        assert event.resource_type == "employee_salary"
        assert event.resource_id == "emp_456"
        assert event.sensitivity_level == DataSensitivityLevel.RESTRICTED
        assert event.policy_decision == "ALLOWED"
        assert event.justification == "HR business need"
        assert event.ip_address == "192.168.1.100"
        assert event.user_agent == "Mozilla/5.0"
        assert event.session_id == "sess_789"
        assert event.metadata["department"] == "HR"
        assert event.metadata["purpose"] == "compensation review"
    
    def test_audit_event_defaults(self):
        """Test AuditEvent creation with defaults"""
        event = AuditEvent(
            event_id="evt_001",
            timestamp=datetime.now(),
            user_id="user_123",
            action="ACCESS_SENSITIVE_DATA"
        )
        
        assert event.user_role is None
        assert event.resource_type is None
        assert event.resource_id is None
        assert event.sensitivity_level == DataSensitivityLevel.PUBLIC
        assert event.policy_decision is None
        assert event.justification is None
        assert event.ip_address is None
        assert event.user_agent is None
        assert event.session_id is None
        assert event.metadata == {}
    
    def test_audit_event_serialization(self):
        """Test AuditEvent serialization to dict"""
        timestamp = datetime.now()
        event = AuditEvent(
            event_id="evt_001",
            timestamp=timestamp,
            user_id="user_123",
            user_role="HR",
            action="ACCESS_SENSITIVE_DATA",
            resource_type="employee_salary",
            resource_id="emp_456",
            sensitivity_level=DataSensitivityLevel.RESTRICTED,
            policy_decision="ALLOWED",
            justification="HR business need"
        )
        
        event_dict = event.to_dict()
        
        assert event_dict["event_id"] == "evt_001"
        assert event_dict["user_id"] == "user_123"
        assert event_dict["user_role"] == "HR"
        assert event_dict["action"] == "ACCESS_SENSITIVE_DATA"
        assert event_dict["resource_type"] == "employee_salary"
        assert event_dict["resource_id"] == "emp_456"
        assert event_dict["sensitivity_level"] == "RESTRICTED"
        assert event_dict["policy_decision"] == "ALLOWED"
        assert event_dict["justification"] == "HR business need"
    
    def test_audit_event_from_dict(self):
        """Test AuditEvent creation from dict"""
        timestamp = datetime.now()
        event_dict = {
            "event_id": "evt_001",
            "timestamp": timestamp.isoformat(),
            "user_id": "user_123",
            "user_role": "HR",
            "action": "ACCESS_SENSITIVE_DATA",
            "resource_type": "employee_salary",
            "resource_id": "emp_456",
            "sensitivity_level": "RESTRICTED",
            "policy_decision": "ALLOWED",
            "justification": "HR business need"
        }
        
        event = AuditEvent.from_dict(event_dict)
        
        assert event.event_id == "evt_001"
        assert event.user_id == "user_123"
        assert event.user_role == "HR"
        assert event.action == "ACCESS_SENSITIVE_DATA"
        assert event.resource_type == "employee_salary"
        assert event.resource_id == "emp_456"
        assert event.sensitivity_level == DataSensitivityLevel.RESTRICTED
        assert event.policy_decision == "ALLOWED"
        assert event.justification == "HR business need"


class TestAuditLogger:
    """Test AuditLogger class"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.audit.log.is_feature_enabled', return_value=True):
            self.logger = AuditLogger()
    
    def test_audit_logger_initialization(self):
        """Test AuditLogger initialization"""
        assert self.logger.log_file is None
        assert self.logger.enable_file_logging is False
        assert self.logger.enable_console_logging is True
        assert self.logger.min_sensitivity_level == DataSensitivityLevel.INTERNAL
    
    def test_log_sensitive_data_access(self):
        """Test logging sensitive data access"""
        event = AuditEvent(
            event_id="evt_001",
            timestamp=datetime.now(),
            user_id="user_123",
            user_role="HR",
            action="ACCESS_SENSITIVE_DATA",
            resource_type="employee_salary",
            resource_id="emp_456",
            sensitivity_level=DataSensitivityLevel.RESTRICTED,
            policy_decision="ALLOWED",
            justification="HR business need"
        )
        
        # Should log to console by default
        with patch('builtins.print') as mock_print:
            self.logger.log_event(event)
            mock_print.assert_called()
    
    def test_log_policy_decision(self):
        """Test logging policy decision"""
        event = AuditEvent(
            event_id="evt_002",
            timestamp=datetime.now(),
            user_id="user_456",
            user_role="Engineering",
            action="REQUEST_SENSITIVE_DATA",
            resource_type="employee_salary",
            resource_id="emp_789",
            sensitivity_level=DataSensitivityLevel.RESTRICTED,
            policy_decision="DENIED",
            justification="Insufficient role permissions"
        )
        
        with patch('builtins.print') as mock_print:
            self.logger.log_event(event)
            mock_print.assert_called()
    
    def test_log_consent_granted(self):
        """Test logging consent granted"""
        event = AuditEvent(
            event_id="evt_003",
            timestamp=datetime.now(),
            user_id="user_789",
            user_role="C_LEVEL",
            action="CONSENT_GRANTED",
            resource_type="employee_pii",
            resource_id="emp_123",
            sensitivity_level=DataSensitivityLevel.HIGHLY_RESTRICTED,
            policy_decision="ALLOWED_WITH_CONSENT",
            justification="Executive approval for compliance review"
        )
        
        with patch('builtins.print') as mock_print:
            self.logger.log_event(event)
            mock_print.assert_called()
    
    def test_log_file_logging(self):
        """Test file logging when enabled"""
        # Create temporary log file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
            temp_file = f.name
        
        try:
            # Enable file logging
            self.logger.enable_file_logging = True
            self.logger.log_file = temp_file
            
            event = AuditEvent(
                event_id="evt_001",
                timestamp=datetime.now(),
                user_id="user_123",
                action="ACCESS_SENSITIVE_DATA"
            )
            
            # Log event
            self.logger.log_event(event)
            
            # Check file was written
            with open(temp_file, 'r') as f:
                content = f.read()
                assert "evt_001" in content
                assert "user_123" in content
                assert "ACCESS_SENSITIVE_DATA" in content
            
        finally:
            # Clean up
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def test_log_file_logging_disabled(self):
        """Test file logging when disabled"""
        # Create temporary log file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
            temp_file = f.name
        
        try:
            # Disable file logging
            self.logger.enable_file_logging = False
            self.logger.log_file = temp_file
            
            event = AuditEvent(
                event_id="evt_001",
                timestamp=datetime.now(),
                user_id="user_123",
                action="ACCESS_SENSITIVE_DATA"
            )
            
            # Log event
            self.logger.log_event(event)
            
            # Check file was not written
            with open(temp_file, 'r') as f:
                content = f.read()
                assert content == ""  # File should be empty
            
        finally:
            # Clean up
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def test_log_sensitivity_level_filtering(self):
        """Test sensitivity level filtering"""
        # Set minimum sensitivity level
        self.logger.min_sensitivity_level = DataSensitivityLevel.CONFIDENTIAL
        
        # Low sensitivity event (should not be logged)
        low_event = AuditEvent(
            event_id="evt_001",
            timestamp=datetime.now(),
            user_id="user_123",
            action="ACCESS_PUBLIC_DATA",
            sensitivity_level=DataSensitivityLevel.PUBLIC
        )
        
        # High sensitivity event (should be logged)
        high_event = AuditEvent(
            event_id="evt_002",
            timestamp=datetime.now(),
            user_id="user_456",
            action="ACCESS_SENSITIVE_DATA",
            sensitivity_level=DataSensitivityLevel.RESTRICTED
        )
        
        with patch('builtins.print') as mock_print:
            # Log low sensitivity event
            self.logger.log_event(low_event)
            # Should not be logged due to sensitivity level
            assert mock_print.call_count == 0
            
            # Log high sensitivity event
            self.logger.log_event(high_event)
            # Should be logged
            assert mock_print.call_count == 1
    
    def test_log_console_logging_disabled(self):
        """Test console logging when disabled"""
        # Disable console logging
        self.logger.enable_console_logging = False
        
        event = AuditEvent(
            event_id="evt_001",
            timestamp=datetime.now(),
            user_id="user_123",
            action="ACCESS_SENSITIVE_DATA"
        )
        
        with patch('builtins.print') as mock_print:
            self.logger.log_event(event)
            # Should not print to console
            mock_print.assert_not_called()
    
    def test_generate_event_id(self):
        """Test event ID generation"""
        event_id1 = self.logger.generate_event_id()
        event_id2 = self.logger.generate_event_id()
        
        # Should be unique
        assert event_id1 != event_id2
        
        # Should have expected format
        assert event_id1.startswith("evt_")
        assert event_id2.startswith("evt_")
    
    def test_format_log_message(self):
        """Test log message formatting"""
        event = AuditEvent(
            event_id="evt_001",
            timestamp=datetime(2023, 1, 1, 12, 0, 0),
            user_id="user_123",
            user_role="HR",
            action="ACCESS_SENSITIVE_DATA",
            resource_type="employee_salary",
            resource_id="emp_456",
            sensitivity_level=DataSensitivityLevel.RESTRICTED,
            policy_decision="ALLOWED",
            justification="HR business need"
        )
        
        message = self.logger.format_log_message(event)
        
        # Should contain key information
        assert "evt_001" in message
        assert "user_123" in message
        assert "HR" in message
        assert "ACCESS_SENSITIVE_DATA" in message
        assert "employee_salary" in message
        assert "emp_456" in message
        assert "RESTRICTED" in message
        assert "ALLOWED" in message
        assert "HR business need" in message
    
    def test_log_event_with_metadata(self):
        """Test logging event with metadata"""
        event = AuditEvent(
            event_id="evt_001",
            timestamp=datetime.now(),
            user_id="user_123",
            action="ACCESS_SENSITIVE_DATA",
            metadata={
                "department": "HR",
                "purpose": "compensation review",
                "request_id": "req_789",
                "approver": "manager_456"
            }
        )
        
        with patch('builtins.print') as mock_print:
            self.logger.log_event(event)
            mock_print.assert_called()
            
            # Check metadata was included in log
            call_args = mock_print.call_args[0][0]
            assert "department: HR" in call_args
            assert "purpose: compensation review" in call_args
            assert "request_id: req_789" in call_args
            assert "approver: manager_456" in call_args


class TestAuditLoggerFeatureFlags:
    """Test AuditLogger with feature flags"""
    
    def test_feature_disabled(self):
        """Test logger behavior when feature is disabled"""
        with patch('src.backend.audit.log.is_feature_enabled', return_value=False):
            logger = AuditLogger()
            
            event = AuditEvent(
                event_id="evt_001",
                timestamp=datetime.now(),
                user_id="user_123",
                action="ACCESS_SENSITIVE_DATA"
            )
            
            # Should still work but log that feature is disabled
            with patch('builtins.print') as mock_print:
                logger.log_event(event)
                # Should still log but indicate feature is disabled
                mock_print.assert_called()


class TestAuditLoggerEdgeCases:
    """Test AuditLogger edge cases"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.audit.log.is_feature_enabled', return_value=True):
            self.logger = AuditLogger()
    
    def test_log_event_with_none_values(self):
        """Test logging event with None values"""
        event = AuditEvent(
            event_id="evt_001",
            timestamp=datetime.now(),
            user_id="user_123",
            action="ACCESS_SENSITIVE_DATA",
            user_role=None,
            resource_type=None,
            resource_id=None,
            policy_decision=None,
            justification=None
        )
        
        with patch('builtins.print') as mock_print:
            self.logger.log_event(event)
            mock_print.assert_called()
    
    def test_log_event_with_empty_strings(self):
        """Test logging event with empty strings"""
        event = AuditEvent(
            event_id="evt_001",
            timestamp=datetime.now(),
            user_id="user_123",
            action="ACCESS_SENSITIVE_DATA",
            user_role="",
            resource_type="",
            resource_id="",
            policy_decision="",
            justification=""
        )
        
        with patch('builtins.print') as mock_print:
            self.logger.log_event(event)
            mock_print.assert_called()
    
    def test_log_event_with_special_characters(self):
        """Test logging event with special characters"""
        event = AuditEvent(
            event_id="evt_001",
            timestamp=datetime.now(),
            user_id="user_123",
            action="ACCESS_SENSITIVE_DATA",
            user_role="HR & Compliance",
            resource_type="employee_salary",
            resource_id="emp_456",
            justification="Review for José García's compensation"
        )
        
        with patch('builtins.print') as mock_print:
            self.logger.log_event(event)
            mock_print.assert_called()
    
    def test_log_event_with_very_long_values(self):
        """Test logging event with very long values"""
        long_justification = "This is a very long justification that exceeds normal length limits " * 10
        
        event = AuditEvent(
            event_id="evt_001",
            timestamp=datetime.now(),
            user_id="user_123",
            action="ACCESS_SENSITIVE_DATA",
            justification=long_justification
        )
        
        with patch('builtins.print') as mock_print:
            self.logger.log_event(event)
            mock_print.assert_called()
    
    def test_log_event_with_complex_metadata(self):
        """Test logging event with complex metadata"""
        complex_metadata = {
            "nested": {
                "level1": {
                    "level2": "value"
                }
            },
            "list": [1, 2, 3, "string"],
            "boolean": True,
            "number": 42.5,
            "null_value": None
        }
        
        event = AuditEvent(
            event_id="evt_001",
            timestamp=datetime.now(),
            user_id="user_123",
            action="ACCESS_SENSITIVE_DATA",
            metadata=complex_metadata
        )
        
        with patch('builtins.print') as mock_print:
            self.logger.log_event(event)
            mock_print.assert_called()


class TestAuditLoggerIntegration:
    """Test AuditLogger integration scenarios"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.audit.log.is_feature_enabled', return_value=True):
            self.logger = AuditLogger()
    
    def test_complete_audit_workflow(self):
        """Test complete audit workflow"""
        # Create temporary log file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
            temp_file = f.name
        
        try:
            # Enable file logging
            self.logger.enable_file_logging = True
            self.logger.log_file = temp_file
            
            # Simulate complete workflow
            events = [
                # 1. User requests sensitive data
                AuditEvent(
                    event_id="evt_001",
                    timestamp=datetime.now(),
                    user_id="user_123",
                    user_role="HR",
                    action="REQUEST_SENSITIVE_DATA",
                    resource_type="employee_salary",
                    resource_id="emp_456",
                    sensitivity_level=DataSensitivityLevel.RESTRICTED,
                    policy_decision="PENDING_CONSENT",
                    justification="Compensation review"
                ),
                
                # 2. Consent granted
                AuditEvent(
                    event_id="evt_002",
                    timestamp=datetime.now(),
                    user_id="user_123",
                    user_role="HR",
                    action="CONSENT_GRANTED",
                    resource_type="employee_salary",
                    resource_id="emp_456",
                    sensitivity_level=DataSensitivityLevel.RESTRICTED,
                    policy_decision="ALLOWED_WITH_CONSENT",
                    justification="Compensation review - approved"
                ),
                
                # 3. Data accessed
                AuditEvent(
                    event_id="evt_003",
                    timestamp=datetime.now(),
                    user_id="user_123",
                    user_role="HR",
                    action="ACCESS_SENSITIVE_DATA",
                    resource_type="employee_salary",
                    resource_id="emp_456",
                    sensitivity_level=DataSensitivityLevel.RESTRICTED,
                    policy_decision="ALLOWED_WITH_CONSENT",
                    justification="Compensation review - approved"
                )
            ]
            
            # Log all events
            for event in events:
                self.logger.log_event(event)
            
            # Check file contains all events
            with open(temp_file, 'r') as f:
                content = f.read()
                assert "evt_001" in content
                assert "evt_002" in content
                assert "evt_003" in content
                assert "REQUEST_SENSITIVE_DATA" in content
                assert "CONSENT_GRANTED" in content
                assert "ACCESS_SENSITIVE_DATA" in content
            
        finally:
            # Clean up
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def test_audit_logger_with_different_sensitivity_levels(self):
        """Test audit logger with different sensitivity levels"""
        events = [
            # Public data access
            AuditEvent(
                event_id="evt_001",
                timestamp=datetime.now(),
                user_id="user_123",
                action="ACCESS_PUBLIC_DATA",
                sensitivity_level=DataSensitivityLevel.PUBLIC
            ),
            
            # Internal data access
            AuditEvent(
                event_id="evt_002",
                timestamp=datetime.now(),
                user_id="user_456",
                action="ACCESS_INTERNAL_DATA",
                sensitivity_level=DataSensitivityLevel.INTERNAL
            ),
            
            # Confidential data access
            AuditEvent(
                event_id="evt_003",
                timestamp=datetime.now(),
                user_id="user_789",
                action="ACCESS_CONFIDENTIAL_DATA",
                sensitivity_level=DataSensitivityLevel.CONFIDENTIAL
            ),
            
            # Restricted data access
            AuditEvent(
                event_id="evt_004",
                timestamp=datetime.now(),
                user_id="user_101",
                action="ACCESS_RESTRICTED_DATA",
                sensitivity_level=DataSensitivityLevel.RESTRICTED
            ),
            
            # Highly restricted data access
            AuditEvent(
                event_id="evt_005",
                timestamp=datetime.now(),
                user_id="user_202",
                action="ACCESS_HIGHLY_RESTRICTED_DATA",
                sensitivity_level=DataSensitivityLevel.HIGHLY_RESTRICTED
            )
        ]
        
        # Test with different minimum sensitivity levels
        for min_level in DataSensitivityLevel:
            self.logger.min_sensitivity_level = min_level
            
            with patch('builtins.print') as mock_print:
                for event in events:
                    self.logger.log_event(event)
                
                # Count how many events were logged
                logged_count = mock_print.call_count
                
                # Verify expected behavior based on sensitivity level
                if min_level == DataSensitivityLevel.PUBLIC:
                    assert logged_count == 5  # All events logged
                elif min_level == DataSensitivityLevel.INTERNAL:
                    assert logged_count == 4  # All except PUBLIC
                elif min_level == DataSensitivityLevel.CONFIDENTIAL:
                    assert logged_count == 3  # CONFIDENTIAL and above
                elif min_level == DataSensitivityLevel.RESTRICTED:
                    assert logged_count == 2  # RESTRICTED and above
                elif min_level == DataSensitivityLevel.HIGHLY_RESTRICTED:
                    assert logged_count == 1  # Only HIGHLY_RESTRICTED


class TestGlobalFunctions:
    """Test global functions"""
    
    def test_get_audit_logger(self):
        """Test get_audit_logger function"""
        logger = get_audit_logger()
        assert isinstance(logger, AuditLogger)
        
        # Should return the same instance
        logger2 = get_audit_logger()
        assert logger is logger2


if __name__ == "__main__":
    pytest.main([__file__])

