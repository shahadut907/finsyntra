"""
Policy Engine for FinSyntra RAG
Enforces RBAC at answer-time for sensitive data access
"""
import re
import logging
from typing import Dict, Any, Optional, List, Set, Tuple
from dataclasses import dataclass
from enum import Enum

from src.config.feature_flags import is_feature_enabled
from src.config.roles import Role, Department

logger = logging.getLogger(__name__)

class PolicyAction(Enum):
    """Available policy actions"""
    ALLOW = "allow"
    ALLOW_WITH_JUSTIFICATION = "allow_with_justification"
    MASK_DEFAULT = "mask_default"
    DENY = "deny"

class DataSensitivity(Enum):
    """Data sensitivity levels"""
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"

@dataclass
class PolicyRule:
    """Represents a policy rule"""
    field_name: str
    department: Department
    sensitivity: DataSensitivity
    allowed_roles: Set[Role]
    action: PolicyAction
    justification_required: bool = False
    audit_logging: bool = True
    masking_pattern: Optional[str] = None

@dataclass
class PolicyDecision:
    """Result of policy evaluation"""
    allowed: bool
    action: PolicyAction
    justification_required: bool
    reason: str
    audit_data: Dict[str, Any]
    masked_value: Optional[str] = None

class PolicyEngine:
    """
    Enforces access control policies for sensitive data
    Implements RBAC at answer-time
    """
    
    def __init__(self):
        self.rules: Dict[str, PolicyRule] = {}
        self._initialize_default_policies()
        logger.info("PolicyEngine initialized")
    
    def _initialize_default_policies(self) -> None:
        """Initialize default policy rules"""
        if not is_feature_enabled('ENABLE_POLICY_ENFORCEMENT'):
            return
        
        # HR Salary Data - Restricted to HR and C-Level
        self.add_rule(PolicyRule(
            field_name="salary",
            department=Department.HR,
            sensitivity=DataSensitivity.RESTRICTED,
            allowed_roles={Role.HR, Role.C_LEVEL, Role.ADMIN},
            action=PolicyAction.ALLOW_WITH_JUSTIFICATION,
            justification_required=True,
            audit_logging=True,
            masking_pattern="***"
        ))
        
        # HR Email Data - Internal to HR and C-Level
        self.add_rule(PolicyRule(
            field_name="email",
            department=Department.HR,
            sensitivity=DataSensitivity.CONFIDENTIAL,
            allowed_roles={Role.HR, Role.C_LEVEL, Role.ADMIN},
            action=PolicyAction.ALLOW,
            justification_required=False,
            audit_logging=True
        ))
        
        # PII Fields - Restricted access
        pii_fields = ["ssn", "phone", "address", "date_of_birth", "emergency_contact"]
        for field in pii_fields:
            self.add_rule(PolicyRule(
                field_name=field,
                department=Department.HR,
                sensitivity=DataSensitivity.RESTRICTED,
                allowed_roles={Role.HR, Role.C_LEVEL, Role.ADMIN},
                action=PolicyAction.DENY,
                justification_required=False,
                audit_logging=True
            ))
        
        # Financial Data - Department-specific access
        financial_fields = ["budget", "revenue", "expenses", "profit_margin"]
        for field in financial_fields:
            self.add_rule(PolicyRule(
                field_name=field,
                department=Department.FINANCE,
                sensitivity=DataSensitivity.CONFIDENTIAL,
                allowed_roles={Role.FINANCE, Role.C_LEVEL, Role.ADMIN},
                action=PolicyAction.ALLOW,
                justification_required=False,
                audit_logging=True
            ))
        
        # Engineering Data - Department-specific access
        engineering_fields = ["code_repository", "technical_specs", "system_architecture"]
        for field in engineering_fields:
            self.add_rule(PolicyRule(
                field_name=field,
                department=Department.ENGINEERING,
                sensitivity=DataSensitivity.INTERNAL,
                allowed_roles={Role.ENGINEERING, Role.C_LEVEL, Role.ADMIN},
                action=PolicyAction.ALLOW,
                justification_required=False,
                audit_logging=True
            ))
        
        logger.info(f"Initialized {len(self.rules)} default policy rules")
    
    def add_rule(self, rule: PolicyRule) -> None:
        """Add a new policy rule"""
        if not is_feature_enabled('ENABLE_POLICY_ENFORCEMENT'):
            return
        
        rule_key = f"{rule.department.value}:{rule.field_name}"
        self.rules[rule_key] = rule
        logger.info(f"Added policy rule: {rule_key} -> {rule.action.value}")
    
    def remove_rule(self, department: Department, field_name: str) -> bool:
        """Remove a policy rule"""
        if not is_feature_enabled('ENABLE_POLICY_ENFORCEMENT'):
            return False
        
        rule_key = f"{department.value}:{field_name}"
        if rule_key in self.rules:
            del self.rules[rule_key]
            logger.info(f"Removed policy rule: {rule_key}")
            return True
        return False
    
    def evaluate_access(
        self, 
        user_role: Role, 
        user_department: Department,
        field_name: str, 
        data_department: Department,
        context: Optional[Dict[str, Any]] = None
    ) -> PolicyDecision:
        """
        Evaluate access to a specific field
        Returns policy decision with action and requirements
        """
        if not is_feature_enabled('ENABLE_POLICY_ENFORCEMENT'):
            return PolicyDecision(
                allowed=True,
                action=PolicyAction.ALLOW,
                justification_required=False,
                reason="Policy enforcement disabled",
                audit_data={}
            )
        
        # Check for exact rule match
        rule_key = f"{data_department.value}:{field_name}"
        rule = self.rules.get(rule_key)
        
        if rule:
            return self._evaluate_rule(rule, user_role, user_department, context)
        
        # Check for wildcard field rules
        wildcard_key = f"{data_department.value}:*"
        wildcard_rule = self.rules.get(wildcard_key)
        
        if wildcard_rule:
            return self._evaluate_rule(wildcard_rule, user_role, user_department, context)
        
        # Default: allow access for same department, deny for others
        if user_department == data_department:
            return PolicyDecision(
                allowed=True,
                action=PolicyAction.ALLOW,
                justification_required=False,
                reason=f"Same department access ({user_department.value})",
                audit_data={"rule_type": "department_default"}
            )
        else:
            return PolicyDecision(
                allowed=False,
                action=PolicyAction.DENY,
                justification_required=False,
                reason=f"Cross-department access denied ({user_department.value} -> {data_department.value})",
                audit_data={"rule_type": "cross_department_denied"}
            )
    
    def _evaluate_rule(
        self, 
        rule: PolicyRule, 
        user_role: Role, 
        user_department: Department,
        context: Optional[Dict[str, Any]]
    ) -> PolicyDecision:
        """Evaluate a specific policy rule"""
        # Check if user role is allowed
        if user_role not in rule.allowed_roles:
            return PolicyDecision(
                allowed=False,
                action=PolicyAction.DENY,
                justification_required=False,
                reason=f"Role {user_role.value} not allowed for {rule.field_name}",
                audit_data={
                    "rule": rule.field_name,
                    "user_role": user_role.value,
                    "allowed_roles": [r.value for r in rule.allowed_roles],
                    "rule_type": "role_denied"
                }
            )
        
        # Role is allowed, check action
        if rule.action == PolicyAction.DENY:
            return PolicyDecision(
                allowed=False,
                action=PolicyAction.DENY,
                justification_required=False,
                reason=f"Field {rule.field_name} explicitly denied",
                audit_data={
                    "rule": rule.field_name,
                    "user_role": user_role.value,
                    "rule_type": "explicitly_denied"
                }
            )
        
        elif rule.action == PolicyAction.ALLOW:
            return PolicyDecision(
                allowed=True,
                action=PolicyAction.ALLOW,
                justification_required=rule.justification_required,
                reason=f"Field {rule.field_name} allowed for role {user_role.value}",
                audit_data={
                    "rule": rule.field_name,
                    "user_role": user_role.value,
                    "rule_type": "explicitly_allowed"
                }
            )
        
        elif rule.action == PolicyAction.ALLOW_WITH_JUSTIFICATION:
            return PolicyDecision(
                allowed=True,
                action=PolicyAction.ALLOW_WITH_JUSTIFICATION,
                justification_required=True,
                reason=f"Field {rule.field_name} requires justification for role {user_role.value}",
                audit_data={
                    "rule": rule.field_name,
                    "user_role": user_role.value,
                    "rule_type": "justification_required"
                }
            )
        
        elif rule.action == PolicyAction.MASK_DEFAULT:
            return PolicyDecision(
                allowed=True,
                action=PolicyAction.MASK_DEFAULT,
                justification_required=False,
                masked_value=rule.masking_pattern or "***",
                reason=f"Field {rule.field_name} masked for role {user_role.value}",
                audit_data={
                    "rule": rule.field_name,
                    "user_role": user_role.value,
                    "rule_type": "masked_access"
                }
            )
        
        # Default deny
        return PolicyDecision(
            allowed=False,
            action=PolicyAction.DENY,
            justification_required=False,
            reason=f"Unknown policy action for {rule.field_name}",
            audit_data={
                "rule": rule.field_name,
                "user_role": user_role.value,
                "rule_type": "unknown_action"
            }
        )
    
    def check_salary_access(
        self, 
        user_role: Role, 
        user_department: Department,
        employee_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> PolicyDecision:
        """Specialized check for salary data access"""
        return self.evaluate_access(
            user_role=user_role,
            user_department=user_department,
            field_name="salary",
            data_department=Department.HR,
            context=context
        )
    
    def check_email_access(
        self, 
        user_role: Role, 
        user_department: Department,
        employee_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> PolicyDecision:
        """Specialized check for email data access"""
        return self.evaluate_access(
            user_role=user_role,
            user_department=user_department,
            field_name="email",
            data_department=Department.HR,
            context=context
        )
    
    def check_pii_access(
        self, 
        user_role: Role, 
        user_department: Department,
        field_name: str,
        context: Optional[Dict[str, Any]] = None
    ) -> PolicyDecision:
        """Specialized check for PII data access"""
        return self.evaluate_access(
            user_role=user_role,
            user_department=user_department,
            field_name=field_name,
            data_department=Department.HR,
            context=context
        )
    
    def get_consent_prompt(
        self, 
        field_name: str, 
        employee_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Generate consent prompt for sensitive data access"""
        if not is_feature_enabled('ENABLE_CONSENT_FLOW'):
            return ""
        
        prompts = {
            "salary": f"You are requesting salary information for {employee_name or 'an employee'}. Please confirm your purpose and scope for accessing this data.",
            "email": f"You are requesting email information for {employee_name or 'an employee'}. Please confirm your purpose for accessing this data.",
            "phone": f"You are requesting phone information for {employee_name or 'an employee'}. This is restricted PII data.",
            "address": f"You are requesting address information for {employee_name or 'an employee'}. This is restricted PII data."
        }
        
        return prompts.get(field_name, f"You are requesting {field_name} information. Please confirm your purpose.")
    
    def get_masked_value(self, field_name: str, original_value: str) -> str:
        """Get masked version of a sensitive value"""
        if not is_feature_enabled('ENABLE_POLICY_ENFORCEMENT'):
            return original_value
        
        masking_patterns = {
            "salary": "***",
            "email": "***@***.***",
            "phone": "***-***-****",
            "ssn": "***-**-****",
            "address": "*** *** ***"
        }
        
        pattern = masking_patterns.get(field_name, "***")
        
        # Apply pattern-based masking
        if field_name == "email" and "@" in original_value:
            parts = original_value.split("@")
            if len(parts) == 2:
                return f"{pattern.split('@')[0]}@{pattern.split('@')[1]}"
        
        return pattern
    
    def get_policy_summary(self) -> Dict[str, Any]:
        """Get summary of all policy rules"""
        summary = {
            "total_rules": len(self.rules),
            "rules_by_department": {},
            "rules_by_sensitivity": {},
            "rules_by_action": {}
        }
        
        for rule_key, rule in self.rules.items():
            dept = rule.department.value
            sensitivity = rule.sensitivity.value
            action = rule.action.value
            
            # Count by department
            if dept not in summary["rules_by_department"]:
                summary["rules_by_department"][dept] = 0
            summary["rules_by_department"][dept] += 1
            
            # Count by sensitivity
            if sensitivity not in summary["rules_by_sensitivity"]:
                summary["rules_by_sensitivity"][sensitivity] = 0
            summary["rules_by_sensitivity"][sensitivity] += 1
            
            # Count by action
            if action not in summary["rules_by_action"]:
                summary["rules_by_action"][action] = 0
            summary["rules_by_action"][action] += 1
        
        return summary
    
    def validate_justification(self, justification: str, field_name: str) -> bool:
        """Validate user justification for sensitive data access"""
        if not is_feature_enabled('ENABLE_CONSENT_FLOW'):
            return True
        
        if not justification or len(justification.strip()) < 10:
            return False
        
        # Check for common invalid justifications
        invalid_patterns = [
            r'\b(curious|just wondering|want to know)\b',
            r'\b(none|no reason|idk)\b',
            r'\b(test|testing|debug)\b'
        ]
        
        justification_lower = justification.lower()
        for pattern in invalid_patterns:
            if re.search(pattern, justification_lower):
                return False
        
        return True

# Global policy engine instance
policy_engine = PolicyEngine()

def get_policy_engine() -> PolicyEngine:
    """Get the global policy engine instance"""
    return policy_engine
