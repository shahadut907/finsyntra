"""
Production Monitoring and Observability for FinSyntra
Includes metrics collection, health checks, performance monitoring, and alerting
"""

import time
import psutil
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from collections import defaultdict, deque
import asyncio
import json
from dataclasses import dataclass, asdict
from src.config.settings import settings
from src.backend.database.database import db_manager

logger = logging.getLogger(__name__)

@dataclass
class HealthCheck:
    """Health check result"""
    service: str
    status: str  # 'healthy', 'degraded', 'unhealthy'
    message: str
    response_time_ms: float
    timestamp: datetime
    metadata: Dict[str, Any] = None

@dataclass
class Metric:
    """Performance metric"""
    name: str
    value: float
    unit: str
    timestamp: datetime
    tags: Dict[str, str] = None

class SystemMonitor:
    """System resource and performance monitoring"""
    
    def __init__(self):
        self.metrics_history = defaultdict(deque)
        self.max_history = 1000
        self.start_time = datetime.now()
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """Get current system metrics"""
        try:
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            
            # Memory metrics
            memory = psutil.virtual_memory()
            
            # Disk metrics
            disk = psutil.disk_usage('/')
            
            # Network metrics (if available)
            try:
                network = psutil.net_io_counters()
                network_stats = {
                    "bytes_sent": network.bytes_sent,
                    "bytes_recv": network.bytes_recv,
                    "packets_sent": network.packets_sent,
                    "packets_recv": network.packets_recv
                }
            except:
                network_stats = {}
            
            return {
                "cpu": {
                    "percent": cpu_percent,
                    "count": cpu_count
                },
                "memory": {
                    "total": memory.total,
                    "available": memory.available,
                    "percent": memory.percent,
                    "used": memory.used
                },
                "disk": {
                    "total": disk.total,
                    "used": disk.used,
                    "free": disk.free,
                    "percent": (disk.used / disk.total) * 100
                },
                "network": network_stats,
                "uptime": (datetime.now() - self.start_time).total_seconds()
            }
        except Exception as e:
            logger.error(f"Failed to get system metrics: {e}")
            return {}
    
    def record_metric(self, metric: Metric):
        """Record a performance metric"""
        history = self.metrics_history[metric.name]
        history.append(metric)
        
        # Keep only recent metrics
        while len(history) > self.max_history:
            history.popleft()
        
        # Also store in database for persistence
        if settings.enable_metrics:
            try:
                db_manager.record_metric(
                    metric_name=metric.name,
                    metric_value=str(metric.value),
                    metric_type="gauge"
                )
            except Exception as e:
                logger.error(f"Failed to persist metric: {e}")
    
    def get_metric_summary(self, metric_name: str, window_minutes: int = 5) -> Dict[str, float]:
        """Get metric summary for the specified time window"""
        if metric_name not in self.metrics_history:
            return {}
        
        cutoff_time = datetime.now() - timedelta(minutes=window_minutes)
        recent_metrics = [
            m for m in self.metrics_history[metric_name] 
            if m.timestamp >= cutoff_time
        ]
        
        if not recent_metrics:
            return {}
        
        values = [m.value for m in recent_metrics]
        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "latest": values[-1]
        }

class HealthChecker:
    """Health check manager"""
    
    def __init__(self):
        self.checks = {}
        self.last_check_time = {}
    
    async def check_database(self) -> HealthCheck:
        """Check database connectivity"""
        start_time = time.time()
        try:
            # Simple database query
            db = db_manager.get_db()
            db.execute("SELECT 1")
            db_manager.close_db(db)
            
            response_time = (time.time() - start_time) * 1000
            return HealthCheck(
                service="database",
                status="healthy",
                message="Database connection successful",
                response_time_ms=response_time,
                timestamp=datetime.now()
            )
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return HealthCheck(
                service="database",
                status="unhealthy",
                message=f"Database connection failed: {str(e)}",
                response_time_ms=response_time,
                timestamp=datetime.now()
            )
    
    async def check_ollama(self) -> HealthCheck:
        """Check Ollama LLM service"""
        start_time = time.time()
        try:
            import requests
            response = requests.get(
                f"{settings.ollama_base_url}/api/tags",
                timeout=5
            )
            response_time = (time.time() - start_time) * 1000
            
            if response.status_code == 200:
                return HealthCheck(
                    service="ollama",
                    status="healthy",
                    message="Ollama service responding",
                    response_time_ms=response_time,
                    timestamp=datetime.now(),
                    metadata={"models": response.json().get("models", [])}
                )
            else:
                return HealthCheck(
                    service="ollama",
                    status="degraded",
                    message=f"Ollama returned status {response.status_code}",
                    response_time_ms=response_time,
                    timestamp=datetime.now()
                )
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return HealthCheck(
                service="ollama",
                status="unhealthy",
                message=f"Ollama check failed: {str(e)}",
                response_time_ms=response_time,
                timestamp=datetime.now()
            )
    
    async def check_vector_store(self) -> HealthCheck:
        """Check vector store health"""
        start_time = time.time()
        try:
            from src.backend.services.rag_service import RAGService
            rag = RAGService()
            
            # Check if vector store is initialized
            if hasattr(rag, 'vector_store') and rag.vector_store:
                stats = rag.vector_store.get_collection_stats()
                response_time = (time.time() - start_time) * 1000
                
                doc_count = stats.get("total_documents", 0)
                if doc_count > 0:
                    return HealthCheck(
                        service="vector_store",
                        status="healthy",
                        message=f"Vector store operational with {doc_count} documents",
                        response_time_ms=response_time,
                        timestamp=datetime.now(),
                        metadata=stats
                    )
                else:
                    return HealthCheck(
                        service="vector_store",
                        status="degraded",
                        message="Vector store empty - no documents indexed",
                        response_time_ms=response_time,
                        timestamp=datetime.now()
                    )
            else:
                response_time = (time.time() - start_time) * 1000
                return HealthCheck(
                    service="vector_store",
                    status="unhealthy",
                    message="Vector store not initialized",
                    response_time_ms=response_time,
                    timestamp=datetime.now()
                )
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return HealthCheck(
                service="vector_store",
                status="unhealthy",
                message=f"Vector store check failed: {str(e)}",
                response_time_ms=response_time,
                timestamp=datetime.now()
            )
    
    async def check_redis(self) -> HealthCheck:
        """Check Redis cache"""
        if not db_manager.redis:
            return HealthCheck(
                service="redis",
                status="degraded",
                message="Redis not configured (optional)",
                response_time_ms=0,
                timestamp=datetime.now()
            )
        
        start_time = time.time()
        try:
            db_manager.redis.ping()
            response_time = (time.time() - start_time) * 1000
            
            return HealthCheck(
                service="redis",
                status="healthy",
                message="Redis cache responding",
                response_time_ms=response_time,
                timestamp=datetime.now()
            )
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return HealthCheck(
                service="redis",
                status="unhealthy",
                message=f"Redis check failed: {str(e)}",
                response_time_ms=response_time,
                timestamp=datetime.now()
            )
    
    async def run_all_checks(self) -> Dict[str, HealthCheck]:
        """Run all health checks"""
        checks = await asyncio.gather(
            self.check_database(),
            self.check_ollama(),
            self.check_vector_store(),
            self.check_redis(),
            return_exceptions=True
        )
        
        results = {}
        check_names = ["database", "ollama", "vector_store", "redis"]
        
        for i, check in enumerate(checks):
            if isinstance(check, Exception):
                results[check_names[i]] = HealthCheck(
                    service=check_names[i],
                    status="unhealthy",
                    message=f"Health check failed: {str(check)}",
                    response_time_ms=0,
                    timestamp=datetime.now()
                )
            else:
                results[check_names[i]] = check
        
        return results

class PerformanceTracker:
    """Track API performance and user interactions"""
    
    def __init__(self):
        self.request_times = deque(maxlen=1000)
        self.error_counts = defaultdict(int)
        self.endpoint_metrics = defaultdict(list)
    
    def track_request(self, endpoint: str, method: str, response_time: float, status_code: int):
        """Track API request performance"""
        timestamp = datetime.now()
        
        # Record request time
        self.request_times.append(response_time)
        
        # Record endpoint-specific metrics
        self.endpoint_metrics[f"{method}:{endpoint}"].append({
            "response_time": response_time,
            "status_code": status_code,
            "timestamp": timestamp
        })
        
        # Track errors
        if status_code >= 400:
            self.error_counts[status_code] += 1
        
        # Record metric
        system_monitor.record_metric(Metric(
            name="api_response_time",
            value=response_time,
            unit="seconds",
            timestamp=timestamp,
            tags={"endpoint": endpoint, "method": method}
        ))
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary"""
        if not self.request_times:
            return {"status": "no_data"}
        
        times = list(self.request_times)
        return {
            "total_requests": len(times),
            "avg_response_time": sum(times) / len(times),
            "min_response_time": min(times),
            "max_response_time": max(times),
            "p95_response_time": sorted(times)[int(len(times) * 0.95)] if len(times) > 0 else 0,
            "error_counts": dict(self.error_counts),
            "endpoints": {
                endpoint: {
                    "count": len(metrics),
                    "avg_time": sum(m["response_time"] for m in metrics) / len(metrics)
                }
                for endpoint, metrics in self.endpoint_metrics.items()
            }
        }

# Global monitoring instances
system_monitor = SystemMonitor()
health_checker = HealthChecker()
performance_tracker = PerformanceTracker()

class AlertManager:
    """Basic alerting for critical issues"""
    
    def __init__(self):
        self.alert_thresholds = {
            "cpu_percent": 80,
            "memory_percent": 85,
            "disk_percent": 90,
            "response_time": 5.0,  # seconds
            "error_rate": 0.1  # 10%
        }
        self.last_alerts = {}
        self.alert_cooldown = 300  # 5 minutes
    
    def check_alerts(self, system_metrics: Dict, performance_summary: Dict):
        """Check for alert conditions"""
        alerts = []
        now = datetime.now()
        
        # CPU alert
        cpu_percent = system_metrics.get("cpu", {}).get("percent", 0)
        if cpu_percent > self.alert_thresholds["cpu_percent"]:
            if self._should_alert("high_cpu", now):
                alerts.append({
                    "type": "high_cpu",
                    "severity": "warning",
                    "message": f"CPU usage at {cpu_percent:.1f}%",
                    "value": cpu_percent,
                    "threshold": self.alert_thresholds["cpu_percent"]
                })
        
        # Memory alert
        memory_percent = system_metrics.get("memory", {}).get("percent", 0)
        if memory_percent > self.alert_thresholds["memory_percent"]:
            if self._should_alert("high_memory", now):
                alerts.append({
                    "type": "high_memory",
                    "severity": "warning",
                    "message": f"Memory usage at {memory_percent:.1f}%",
                    "value": memory_percent,
                    "threshold": self.alert_thresholds["memory_percent"]
                })
        
        # Disk alert
        disk_percent = system_metrics.get("disk", {}).get("percent", 0)
        if disk_percent > self.alert_thresholds["disk_percent"]:
            if self._should_alert("high_disk", now):
                alerts.append({
                    "type": "high_disk",
                    "severity": "critical",
                    "message": f"Disk usage at {disk_percent:.1f}%",
                    "value": disk_percent,
                    "threshold": self.alert_thresholds["disk_percent"]
                })
        
        # Response time alert
        avg_response_time = performance_summary.get("avg_response_time", 0)
        if avg_response_time > self.alert_thresholds["response_time"]:
            if self._should_alert("slow_response", now):
                alerts.append({
                    "type": "slow_response",
                    "severity": "warning",
                    "message": f"Average response time {avg_response_time:.2f}s",
                    "value": avg_response_time,
                    "threshold": self.alert_thresholds["response_time"]
                })
        
        return alerts
    
    def _should_alert(self, alert_type: str, now: datetime) -> bool:
        """Check if we should send alert (respects cooldown)"""
        last_alert = self.last_alerts.get(alert_type)
        if not last_alert:
            self.last_alerts[alert_type] = now
            return True
        
        if (now - last_alert).total_seconds() > self.alert_cooldown:
            self.last_alerts[alert_type] = now
            return True
        
        return False

alert_manager = AlertManager()

async def get_system_status() -> Dict[str, Any]:
    """Get comprehensive system status"""
    try:
        # Get all metrics
        system_metrics = system_monitor.get_system_metrics()
        health_checks = await health_checker.run_all_checks()
        performance_summary = performance_tracker.get_performance_summary()
        
        # Check for alerts
        alerts = alert_manager.check_alerts(system_metrics, performance_summary)
        
        # Determine overall status
        unhealthy_services = [
            name for name, check in health_checks.items() 
            if check.status == "unhealthy"
        ]
        
        if unhealthy_services:
            overall_status = "unhealthy"
        elif any(check.status == "degraded" for check in health_checks.values()):
            overall_status = "degraded"
        else:
            overall_status = "healthy"
        
        return {
            "status": overall_status,
            "timestamp": datetime.now().isoformat(),
            "system_metrics": system_metrics,
            "health_checks": {
                name: asdict(check) for name, check in health_checks.items()
            },
            "performance": performance_summary,
            "alerts": alerts,
            "uptime": system_metrics.get("uptime", 0)
        }
    except Exception as e:
        logger.error(f"Failed to get system status: {e}")
        return {
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }
