"""
Feature Flags Configuration for FinSyntra RAG Pipeline Improvements
Controls new features while preserving backward compatibility
"""
import os
from typing import Dict, Any
from dataclasses import dataclass

@dataclass
class FeatureFlags:
    """Feature flags for RAG pipeline improvements"""
    
    # Conversational Memory & Query Rewriting
    ENABLE_CONVO_MEMORY: bool = False
    ENABLE_QUERY_REWRITER: bool = False
    
    # Coreference Resolution & Entity Canonicalization
    ENABLE_COREF_CANON: bool = False
    ENABLE_ENTITY_REGISTRY: bool = False
    
    # Grounding & Stable Citations
    ENABLE_STRICT_GROUNDING: bool = False
    ENABLE_STABLE_DOC_IDS: bool = False
    
    # RBAC at Answer-Time (Policy Enforcement)
    ENABLE_POLICY_ENFORCEMENT: bool = False
    ENABLE_CONSENT_FLOW: bool = False
    ENABLE_AUDIT_LOGGING: bool = False
    
    # Schema-Aware Structured Data (CSV/Tabular)
    ENABLE_TABLE_RETRIEVER: bool = False
    ENABLE_CSV_NORMALIZATION: bool = False
    
    # UX Enhancements
    ENABLE_SUBJECT_PIN_UI: bool = False
    ENABLE_DISAMBIGUATION_CHIPS: bool = False
    ENABLE_CONSENT_MODAL: bool = False
    
    # Quality Gates & Anomaly Detection
    ENABLE_QUALITY_GATES: bool = False
    ENABLE_ANOMALY_DETECTION: bool = False

    def __post_init__(self):
        """Load flags from environment variables with safe defaults"""
        # All flags default to False for backward compatibility
        for field_name in self.__dataclass_fields__:
            env_var = f"FINSOLVE_{field_name}"
            if env_var in os.environ:
                value = os.environ[env_var].lower()
                if value in ('true', '1', 'yes', 'on'):
                    setattr(self, field_name, True)
                elif value in ('false', '0', 'no', 'off'):
                    setattr(self, field_name, False)
    
    def get_enabled_features(self) -> Dict[str, bool]:
        """Get dictionary of enabled features"""
        return {k: v for k, v in self.__dict__.items() if v}
    
    def is_feature_enabled(self, feature_name: str) -> bool:
        """Check if a specific feature is enabled"""
        return getattr(self, feature_name, False)
    
    def enable_feature(self, feature_name: str) -> None:
        """Enable a specific feature"""
        if hasattr(self, feature_name):
            setattr(self, feature_name, True)
    
    def disable_feature(self, feature_name: str) -> None:
        """Disable a specific feature"""
        if hasattr(self, feature_name):
            setattr(self, feature_name, False)

# Global feature flags instance
feature_flags = FeatureFlags()

def get_feature_flags() -> FeatureFlags:
    """Get the global feature flags instance"""
    return feature_flags

def is_feature_enabled(feature_name: str) -> bool:
    """Check if a specific feature is enabled"""
    return feature_flags.is_feature_enabled(feature_name)

def enable_feature(feature_name: str) -> None:
    """Enable a specific feature"""
    feature_flags.enable_feature(feature_name)

def disable_feature(feature_name: str) -> None:
    """Disable a specific feature"""
    feature_flags.disable_feature(feature_name)
