"""
Audit Logging for FinSyntra RAG
Tracks sensitive data access and policy decisions for compliance
"""
import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
import os
from pathlib import Path

from src.config.feature_flags import is_feature_enabled

logger = logging.getLogger(__name__)

class AuditEventType(Enum):
    """Types of audit events"""
    DATA_ACCESS = "data_access"
    POLICY_DECISION = "policy_decision"
    SENSITIVE_DATA_REQUEST = "sensitive_data_request"
    CONSENT_GIVEN = "consent_given"
    CONSENT_DENIED = "consent_denied"
    ROLE_CHANGE = "role_change"
    SESSION_START = "session_start"
    SESSION_END = "session_end"

class DataSensitivityLevel(Enum):
    """Data sensitivity levels for audit logging"""
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"

@dataclass
class AuditEvent:
    """Represents an audit event"""
    event_id: str
    event_type: AuditEventType
    timestamp: datetime
    user_id: str
    user_role: str
    user_department: str
    session_id: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    
    # Event-specific data
    target_data: Optional[str] = None
    data_sensitivity: Optional[DataSensitivityLevel] = None
    policy_decision: Optional[str] = None
    justification: Optional[str] = None
    source_documents: Optional[List[str]] = None
    
    # Additional context
    context: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.context is None:
            self.context = {}
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        data = asdict(self)
        data['event_type'] = self.event_type.value
        data['timestamp'] = self.timestamp.isoformat()
        if self.data_sensitivity:
            data['data_sensitivity'] = self.data_sensitivity.value
        return data

class AuditLogger:
    """
    Handles audit logging for compliance and security monitoring
    Tracks all sensitive data access and policy decisions
    """
    
    def __init__(self, log_file: Optional[str] = None, log_level: str = "INFO"):
        self.enabled = is_feature_enabled('ENABLE_AUDIT_LOGGING')
        self.log_file = log_file
        self.log_level = getattr(logging, log_level.upper())
        
        # Initialize logging
        self._setup_logging()
        
        logger.info("AuditLogger initialized")
    
    def _setup_logging(self) -> None:
        """Setup audit logging configuration"""
        if not self.enabled:
            return
        
        # Create audit logger
        self.audit_logger = logging.getLogger('finsolve_audit')
        self.audit_logger.setLevel(self.log_level)
        
        # Prevent duplicate handlers
        if not self.audit_logger.handlers:
            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(self.log_level)
            
            # File handler if specified
            if self.log_file:
                file_handler = logging.FileHandler(self.log_file)
                file_handler.setLevel(self.log_level)
                self.audit_logger.addHandler(file_handler)
            
            # Formatter
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            console_handler.setFormatter(formatter)
            if self.log_file:
                file_handler.setFormatter(formatter)
            
            self.audit_logger.addHandler(console_handler)
    
    def log_data_access(
        self,
        user_id: str,
        user_role: str,
        user_department: str,
        session_id: str,
        target_data: str,
        data_sensitivity: DataSensitivityLevel,
        source_documents: List[str],
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log data access event"""
        if not self.enabled:
            return
        
        event = AuditEvent(
            event_id=self._generate_event_id(),
            event_type=AuditEventType.DATA_ACCESS,
            timestamp=datetime.now(),
            user_id=user_id,
            user_role=user_role,
            user_department=user_department,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent,
            target_data=target_data,
            data_sensitivity=data_sensitivity,
            source_documents=source_documents,
            context=context or {}
        )
        
        self._log_event(event)
    
    def log_policy_decision(
        self,
        user_id: str,
        user_role: str,
        user_department: str,
        session_id: str,
        target_data: str,
        data_sensitivity: DataSensitivityLevel,
        policy_decision: str,
        justification: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log policy decision event"""
        if not self.enabled:
            return
        
        event = AuditEvent(
            event_id=self._generate_event_id(),
            event_type=AuditEventType.POLICY_DECISION,
            timestamp=datetime.now(),
            user_id=user_id,
            user_role=user_role,
            user_department=user_department,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent,
            target_data=target_data,
            data_sensitivity=data_sensitivity,
            policy_decision=policy_decision,
            justification=justification,
            context=context or {}
        )
        
        self._log_event(event)
    
    def log_sensitive_data_request(
        self,
        user_id: str,
        user_role: str,
        user_department: str,
        session_id: str,
        target_data: str,
        data_sensitivity: DataSensitivityLevel,
        request_reason: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log sensitive data request event"""
        if not self.enabled:
            return
        
        event = AuditEvent(
            event_id=self._generate_event_id(),
            event_type=AuditEventType.SENSITIVE_DATA_REQUEST,
            timestamp=datetime.now(),
            user_id=user_id,
            user_role=user_role,
            user_department=user_department,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent,
            target_data=target_data,
            data_sensitivity=data_sensitivity,
            justification=request_reason,
            context=context or {}
        )
        
        self._log_event(event)
    
    def log_consent_given(
        self,
        user_id: str,
        user_role: str,
        user_department: str,
        session_id: str,
        target_data: str,
        data_sensitivity: DataSensitivityLevel,
        justification: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log consent given event"""
        if not self.enabled:
            return
        
        event = AuditEvent(
            event_id=self._generate_event_id(),
            event_type=AuditEventType.CONSENT_GIVEN,
            timestamp=datetime.now(),
            user_id=user_id,
            user_role=user_role,
            user_department=user_department,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent,
            target_data=target_data,
            data_sensitivity=data_sensitivity,
            justification=justification,
            context=context or {}
        )
        
        self._log_event(event)
    
    def log_consent_denied(
        self,
        user_id: str,
        user_role: str,
        user_department: str,
        session_id: str,
        target_data: str,
        data_sensitivity: DataSensitivityLevel,
        reason: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log consent denied event"""
        if not self.enabled:
            return
        
        event = AuditEvent(
            event_id=self._generate_event_id(),
            event_type=AuditEventType.CONSENT_DENIED,
            timestamp=datetime.now(),
            user_id=user_id,
            user_role=user_role,
            user_department=user_department,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent,
            target_data=target_data,
            data_sensitivity=data_sensitivity,
            justification=reason,
            context=context or {}
        )
        
        self._log_event(event)
    
    def log_session_start(
        self,
        user_id: str,
        user_role: str,
        user_department: str,
        session_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log session start event"""
        if not self.enabled:
            return
        
        event = AuditEvent(
            event_id=self._generate_event_id(),
            event_type=AuditEventType.SESSION_START,
            timestamp=datetime.now(),
            user_id=user_id,
            user_role=user_role,
            user_department=user_department,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent,
            context=context or {}
        )
        
        self._log_event(event)
    
    def log_session_end(
        self,
        user_id: str,
        user_role: str,
        user_department: str,
        session_id: str,
        session_duration: Optional[float] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log session end event"""
        if not self.enabled:
            return
        
        if context is None:
            context = {}
        if session_duration is not None:
            context['session_duration_seconds'] = session_duration
        
        event = AuditEvent(
            event_id=self._generate_event_id(),
            event_type=AuditEventType.SESSION_END,
            timestamp=datetime.now(),
            user_id=user_id,
            user_role=user_role,
            user_department=user_department,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent,
            context=context
        )
        
        self._log_event(event)
    
    def _log_event(self, event: AuditEvent) -> None:
        """Log an audit event"""
        if not self.enabled:
            return
        
        try:
            # Convert to JSON for logging
            event_data = event.to_dict()
            event_json = json.dumps(event_data, indent=2)
            
            # Log to audit logger
            if hasattr(self, 'audit_logger'):
                self.audit_logger.info(f"AUDIT_EVENT: {event_json}")
            
            # Also log to main logger for visibility
            logger.info(f"Audit event logged: {event.event_type.value} - {event.target_data or 'N/A'}")
            
        except Exception as e:
            logger.error(f"Failed to log audit event: {e}")
    
    def _generate_event_id(self) -> str:
        """Generate unique event ID"""
        import uuid
        return str(uuid.uuid4())
    
    def get_audit_summary(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        user_id: Optional[str] = None,
        event_type: Optional[AuditEventType] = None
    ) -> Dict[str, Any]:
        """Get summary of audit events (placeholder for future implementation)"""
        if not self.enabled:
            return {"error": "Audit logging disabled"}
        
        # This would typically query a database or log files
        # For now, return a placeholder
        return {
            "message": "Audit summary functionality not yet implemented",
            "enabled": True,
            "filters": {
                "start_time": start_time.isoformat() if start_time else None,
                "end_time": end_time.isoformat() if end_time else None,
                "user_id": user_id,
                "event_type": event_type.value if event_type else None
            }
        }
    
    def export_audit_logs(
        self,
        output_path: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        format: str = "json"
    ) -> bool:
        """Export audit logs to file (placeholder for future implementation)"""
        if not self.enabled:
            return False
        
        try:
            # This would typically read from database or log files
            # For now, create a placeholder export
            export_data = {
                "export_info": {
                    "exported_at": datetime.now().isoformat(),
                    "start_time": start_time.isoformat() if start_time else None,
                    "end_time": end_time.isoformat() if end_time else None,
                    "format": format
                },
                "message": "Audit export functionality not yet implemented"
            }
            
            with open(output_path, 'w') as f:
                if format.lower() == "json":
                    json.dump(export_data, f, indent=2)
                else:
                    f.write(str(export_data))
            
            logger.info(f"Audit logs exported to {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to export audit logs: {e}")
            return False

# Global audit logger instance
audit_logger = AuditLogger()

def get_audit_logger() -> AuditLogger:
    """Get the global audit logger instance"""
    return audit_logger
