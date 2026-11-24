"""
Unit tests for policy engine module
"""
import pytest
from unittest.mock import Mock, patch

from src.backend.policy.engine import (
    PolicyEngine, PolicyRule, PolicyDecision, PolicyAction, DataSensitivity,
    get_policy_engine
)
from src.config.roles import Role, Department


class TestPolicyRule:
    """Test PolicyRule dataclass"""
    
    def test_policy_rule_creation(self):
        """Test creating a PolicyRule"""
        rule = PolicyRule(
            field_name="salary",
            department=Department.HR,
            sensitivity=DataSensitivity.RESTRICTED,
            allowed_roles={Role.HR, Role.C_LEVEL},
            action=PolicyAction.ALLOW_WITH_JUSTIFICATION,
            justification_required=True,
            audit_logging=True,
            masking_pattern="***"
        )
        
        assert rule.field_name == "salary"
        assert rule.department == Department.HR
        assert rule.sensitivity == DataSensitivity.RESTRICTED
        assert Role.HR in rule.allowed_roles
        assert Role.C_LEVEL in rule.allowed_roles
        assert rule.action == PolicyAction.ALLOW_WITH_JUSTIFICATION
        assert rule.justification_required is True
        assert rule.audit_logging is True
        assert rule.masking_pattern == "***"
    
    def test_policy_rule_defaults(self):
        """Test PolicyRule with default values"""
        rule = PolicyRule(
            field_name="email",
            department=Department.HR,
            sensitivity=DataSensitivity.CONFIDENTIAL,
            allowed_roles={Role.HR},
            action=PolicyAction.ALLOW
        )
        
        assert rule.justification_required is False
        assert rule.audit_logging is True
        assert rule.masking_pattern is None


class TestPolicyDecision:
    """Test PolicyDecision dataclass"""
    
    def test_policy_decision_creation(self):
        """Test creating a PolicyDecision"""
        decision = PolicyDecision(
            allowed=True,
            action=PolicyAction.ALLOW,
            justification_required=False,
            masked_value=None,
            reason="User has HR role",
            audit_data={"rule_type": "explicitly_allowed"}
        )
        
        assert decision.allowed is True
        assert decision.action == PolicyAction.ALLOW
        assert decision.justification_required is False
        assert decision.masked_value is None
        assert decision.reason == "User has HR role"
        assert decision.audit_data["rule_type"] == "explicitly_allowed"


class TestPolicyEngine:
    """Test PolicyEngine class"""
    
    def setup_method(self):
        """Setup test method"""
        # Mock feature flags to enable policy enforcement
        with patch('src.backend.policy.engine.is_feature_enabled', return_value=True):
            self.policy_engine = PolicyEngine()
    
    def test_policy_engine_initialization(self):
        """Test PolicyEngine initialization"""
        assert len(self.policy_engine.rules) > 0
        
        # Check that default policies were created
        hr_salary_rule = self.policy_engine.rules.get("hr:salary")
        assert hr_salary_rule is not None
        assert hr_salary_rule.field_name == "salary"
        assert hr_salary_rule.department == Department.HR
        assert hr_salary_rule.sensitivity == DataSensitivity.RESTRICTED
    
    def test_add_rule(self):
        """Test adding a new policy rule"""
        new_rule = PolicyRule(
            field_name="test_field",
            department=Department.ENGINEERING,
            sensitivity=DataSensitivity.INTERNAL,
            allowed_roles={Role.ENGINEERING},
            action=PolicyAction.ALLOW
        )
        
        self.policy_engine.add_rule(new_rule)
        
        rule_key = "engineering:test_field"
        assert rule_key in self.policy_engine.rules
        assert self.policy_engine.rules[rule_key] == new_rule
    
    def test_remove_rule(self):
        """Test removing a policy rule"""
        # Add a rule first
        test_rule = PolicyRule(
            field_name="test_field",
            department=Department.FINANCE,
            sensitivity=DataSensitivity.CONFIDENTIAL,
            allowed_roles={Role.FINANCE},
            action=PolicyAction.ALLOW
        )
        self.policy_engine.add_rule(test_rule)
        
        # Remove the rule
        result = self.policy_engine.remove_rule(Department.FINANCE, "test_field")
        assert result is True
        
        # Verify rule was removed
        rule_key = "finance:test_field"
        assert rule_key not in self.policy_engine.rules
    
    def test_remove_nonexistent_rule(self):
        """Test removing a nonexistent rule"""
        result = self.policy_engine.remove_rule(Department.FINANCE, "nonexistent_field")
        assert result is False
    
    def test_evaluate_access_allowed(self):
        """Test access evaluation for allowed access"""
        decision = self.policy_engine.evaluate_access(
            user_role=Role.HR,
            user_department=Department.HR,
            field_name="salary",
            data_department=Department.HR
        )
        
        assert decision.allowed is True
        assert decision.action == PolicyAction.ALLOW_WITH_JUSTIFICATION
        assert decision.justification_required is True
        assert "salary" in decision.reason
    
    def test_evaluate_access_denied(self):
        """Test access evaluation for denied access"""
        decision = self.policy_engine.evaluate_access(
            user_role=Role.ENGINEERING,
            user_department=Department.ENGINEERING,
            field_name="salary",
            data_department=Department.HR
        )
        
        assert decision.allowed is False
        assert decision.action == PolicyAction.DENY
        assert "not allowed" in decision.reason
    
    def test_evaluate_access_same_department(self):
        """Test access evaluation for same department"""
        decision = self.policy_engine.evaluate_access(
            user_role=Role.FINANCE,
            user_department=Department.FINANCE,
            field_name="budget",
            data_department=Department.FINANCE
        )
        
        assert decision.allowed is True
        assert decision.action == PolicyAction.ALLOW
        assert "Same department" in decision.reason
    
    def test_evaluate_access_cross_department_denied(self):
        """Test access evaluation for cross-department access"""
        decision = self.policy_engine.evaluate_access(
            user_role=Role.ENGINEERING,
            user_department=Department.ENGINEERING,
            field_name="budget",
            data_department=Department.FINANCE
        )
        
        assert decision.allowed is False
        assert decision.action == PolicyAction.DENY
        assert "Cross-department" in decision.reason
    
    def test_check_salary_access_allowed(self):
        """Test salary access check for allowed role"""
        decision = self.policy_engine.check_salary_access(
            user_role=Role.HR,
            user_department=Department.HR
        )
        
        assert decision.allowed is True
        assert decision.action == PolicyAction.ALLOW_WITH_JUSTIFICATION
        assert decision.justification_required is True
    
    def test_check_salary_access_denied(self):
        """Test salary access check for denied role"""
        decision = self.policy_engine.check_salary_access(
            user_role=Role.ENGINEERING,
            user_department=Department.ENGINEERING
        )
        
        assert decision.allowed is False
        assert decision.action == PolicyAction.DENY
    
    def test_check_email_access_allowed(self):
        """Test email access check for allowed role"""
        decision = self.policy_engine.check_email_access(
            user_role=Role.HR,
            user_department=Department.HR
        )
        
        assert decision.allowed is True
        assert decision.action == PolicyAction.ALLOW
        assert decision.justification_required is False
    
    def test_check_pii_access_denied(self):
        """Test PII access check (should be denied for all)"""
        decision = self.policy_engine.check_pii_access(
            user_role=Role.HR,
            user_department=Department.HR,
            field_name="ssn"
        )
        
        assert decision.allowed is False
        assert decision.action == PolicyAction.DENY
    
    def test_get_consent_prompt(self):
        """Test consent prompt generation"""
        prompt = self.policy_engine.get_consent_prompt(
            field_name="salary",
            employee_name="John Doe"
        )
        
        assert "salary information" in prompt
        assert "John Doe" in prompt
        assert "confirm your purpose" in prompt
    
    def test_get_masked_value(self):
        """Test value masking"""
        # Test salary masking
        masked_salary = self.policy_engine.get_masked_value("salary", "$50000")
        assert masked_salary == "***"
        
        # Test email masking
        masked_email = self.policy_engine.get_masked_value("email", "john@example.com")
        assert masked_email == "***@***.***"
        
        # Test phone masking
        masked_phone = self.policy_engine.get_masked_value("phone", "555-123-4567")
        assert masked_phone == "***-***-****"
    
    def test_get_policy_summary(self):
        """Test policy summary generation"""
        summary = self.policy_engine.get_policy_summary()
        
        assert "total_rules" in summary
        assert "rules_by_department" in summary
        assert "rules_by_sensitivity" in summary
        assert "rules_by_action" in summary
        
        assert summary["total_rules"] > 0
        assert len(summary["rules_by_department"]) > 0
        assert len(summary["rules_by_sensitivity"]) > 0
        assert len(summary["rules_by_action"]) > 0
    
    def test_validate_justification_valid(self):
        """Test justification validation with valid justification"""
        valid_justification = "I need this information for payroll processing and employee compensation analysis."
        result = self.policy_engine.validate_justification(valid_justification, "salary")
        assert result is True
    
    def test_validate_justification_invalid(self):
        """Test justification validation with invalid justification"""
        invalid_justifications = [
            "just curious",
            "want to know",
            "none",
            "testing",
            "debug"
        ]
        
        for justification in invalid_justifications:
            result = self.policy_engine.validate_justification(justification, "salary")
            assert result is False
    
    def test_validate_justification_too_short(self):
        """Test justification validation with too short justification"""
        short_justification = "payroll"
        result = self.policy_engine.validate_justification(short_justification, "salary")
        assert result is False


class TestPolicyEngineFeatureDisabled:
    """Test PolicyEngine when feature is disabled"""
    
    def setup_method(self):
        """Setup test method"""
        # Mock feature flags to disable policy enforcement
        with patch('src.backend.policy.engine.is_feature_enabled', return_value=False):
            self.policy_engine = PolicyEngine()
    
    def test_policy_engine_disabled_initialization(self):
        """Test PolicyEngine initialization when disabled"""
        assert len(self.policy_engine.rules) == 0
    
    def test_evaluate_access_disabled(self):
        """Test access evaluation when policy enforcement is disabled"""
        decision = self.policy_engine.evaluate_access(
            user_role=Role.ENGINEERING,
            user_department=Department.ENGINEERING,
            field_name="salary",
            data_department=Department.HR
        )
        
        assert decision.allowed is True
        assert decision.action == PolicyAction.ALLOW
        assert "disabled" in decision.reason
    
    def test_check_salary_access_disabled(self):
        """Test salary access check when policy enforcement is disabled"""
        decision = self.policy_engine.check_salary_access(
            user_role=Role.ENGINEERING,
            user_department=Department.ENGINEERING
        )
        
        assert decision.allowed is True
        assert decision.action == PolicyAction.ALLOW
    
    def test_get_masked_value_disabled(self):
        """Test value masking when policy enforcement is disabled"""
        original_value = "$50000"
        masked_value = self.policy_engine.get_masked_value("salary", original_value)
        assert masked_value == original_value  # No masking when disabled


class TestPolicyEngineEdgeCases:
    """Test PolicyEngine edge cases"""
    
    def setup_method(self):
        """Setup test method"""
        with patch('src.backend.policy.engine.is_feature_enabled', return_value=True):
            self.policy_engine = PolicyEngine()
    
    def test_evaluate_access_with_context(self):
        """Test access evaluation with additional context"""
        context = {"request_purpose": "payroll", "approval_level": "manager"}
        
        decision = self.policy_engine.evaluate_access(
            user_role=Role.HR,
            user_department=Department.HR,
            field_name="salary",
            data_department=Department.HR,
            context=context
        )
        
        assert decision.allowed is True
        assert decision.audit_data is not None
    
    def test_evaluate_access_unknown_field(self):
        """Test access evaluation for unknown field"""
        decision = self.policy_engine.evaluate_access(
            user_role=Role.HR,
            user_department=Department.HR,
            field_name="unknown_field",
            data_department=Department.HR
        )
        
        # Should fall back to department-based access
        assert decision.allowed is True
        assert "Same department" in decision.reason
    
    def test_add_duplicate_rule(self):
        """Test adding a rule that already exists"""
        # Add initial rule
        rule1 = PolicyRule(
            field_name="test_field",
            department=Department.FINANCE,
            sensitivity=DataSensitivity.CONFIDENTIAL,
            allowed_roles={Role.FINANCE},
            action=PolicyAction.ALLOW
        )
        self.policy_engine.add_rule(rule1)
        
        # Add duplicate rule (should replace)
        rule2 = PolicyRule(
            field_name="test_field",
            department=Department.FINANCE,
            sensitivity=DataSensitivity.RESTRICTED,
            allowed_roles={Role.C_LEVEL},
            action=PolicyAction.DENY
        )
        self.policy_engine.add_rule(rule2)
        
        # Verify rule was replaced
        rule_key = "finance:test_field"
        stored_rule = self.policy_engine.rules[rule_key]
        assert stored_rule.sensitivity == DataSensitivity.RESTRICTED
        assert stored_rule.action == PolicyAction.DENY


class TestGlobalFunctions:
    """Test global functions"""
    
    def test_get_policy_engine(self):
        """Test get_policy_engine function"""
        policy_engine = get_policy_engine()
        assert isinstance(policy_engine, PolicyEngine)
        
        # Should return the same instance
        policy_engine2 = get_policy_engine()
        assert policy_engine is policy_engine2


if __name__ == "__main__":
    pytest.main([__file__])
