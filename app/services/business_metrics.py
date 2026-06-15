"""
P5-05: Custom Prometheus metrics service for business metrics tracking.

This module provides custom Prometheus metrics for tracking key business indicators
beyond the default HTTP metrics provided by prometheus_fastapi_instrumentator.
"""

from prometheus_client import Counter, Histogram, Gauge, Info
from prometheus_client import CollectorRegistry
from typing import Optional
import time


class BusinessMetrics:
    """Business metrics for ERIS system"""
    
    def __init__(self):
        self.registry = CollectorRegistry()
        
        # HTTP Request Metrics (custom beyond auto-instrumented)
        self.http_requests_total = Counter(
            'eris_http_requests_total',
            'Total HTTP requests',
            ['method', 'endpoint', 'status'],
            registry=self.registry
        )
        
        self.http_request_duration_seconds = Histogram(
            'eris_http_request_duration_seconds',
            'HTTP request latency in seconds',
            ['method', 'endpoint'],
            registry=self.registry
        )
        
        # User Metrics
        self.users_total = Gauge(
            'eris_users_total',
            'Total number of users',
            ['level', 'status'],
            registry=self.registry
        )
        
        self.users_active = Gauge(
            'eris_users_active',
            'Number of active users',
            registry=self.registry
        )
        
        self.user_registrations_total = Counter(
            'eris_user_registrations_total',
            'Total user registrations',
            ['channel'],
            registry=self.registry
        )
        
        # Conversation Metrics
        self.conversations_total = Gauge(
            'eris_conversations_total',
            'Total number of conversations',
            ['status'],
            registry=self.registry
        )
        
        self.messages_total = Counter(
            'eris_messages_total',
            'Total messages sent',
            ['direction', 'channel'],
            registry=self.registry
        )
        
        self.message_processing_duration_seconds = Histogram(
            'eris_message_processing_duration_seconds',
            'Message processing time in seconds',
            ['message_type'],
            registry=self.registry
        )
        
        # Handoff Task Metrics
        self.handoff_tasks_total = Gauge(
            'eris_handoff_tasks_total',
            'Total handoff tasks',
            ['status', 'priority'],
            registry=self.registry
        )
        
        self.handoff_task_duration_seconds = Histogram(
            'eris_handoff_task_duration_seconds',
            'Handoff task duration in seconds',
            ['priority'],
            registry=self.registry
        )
        
        # LLM Processing Metrics
        self.llm_requests_total = Counter(
            'eris_llm_requests_total',
            'Total LLM API requests',
            ['model', 'status'],
            registry=self.registry
        )
        
        self.llm_request_duration_seconds = Histogram(
            'eris_llm_request_duration_seconds',
            'LLM API request latency in seconds',
            ['model', 'operation'],
            registry=self.registry
        )
        
        self.llm_tokens_total = Counter(
            'eris_llm_tokens_total',
            'Total LLM tokens processed',
            ['model', 'direction'],  # direction: input/output
            registry=self.registry
        )
        
        # WebSocket Metrics
        self.websocket_connections_total = Gauge(
            'eris_websocket_connections_total',
            'Current WebSocket connections',
            ['type'],  # operator, user, etc.
            registry=self.registry
        )
        
        self.websocket_messages_total = Counter(
            'eris_websocket_messages_total',
            'Total WebSocket messages',
            ['direction', 'message_type'],
            registry=self.registry
        )
        
        # Telegram Account Metrics
        self.telegram_accounts_total = Gauge(
            'eris_telegram_accounts_total',
            'Total Telegram accounts',
            ['status'],  # connected, disconnected, banned
            registry=self.registry
        )
        
        self.telegram_message_send_duration_seconds = Histogram(
            'eris_telegram_message_send_duration_seconds',
            'Telegram message send duration in seconds',
            registry=self.registry
        )
        
        # Database Metrics
        self.db_query_duration_seconds = Histogram(
            'eris_db_query_duration_seconds',
            'Database query latency in seconds',
            ['operation', 'table'],
            registry=self.registry
        )
        
        self.db_connections_active = Gauge(
            'eris_db_connections_active',
            'Active database connections',
            registry=self.registry
        )
        
        # Cache Metrics
        self.cache_operations_total = Counter(
            'eris_cache_operations_total',
            'Total cache operations',
            ['operation', 'cache_type', 'status'],
            registry=self.registry
        )
        
        self.cache_hit_rate = Gauge(
            'eris_cache_hit_rate',
            'Cache hit rate',
            ['cache_type'],
            registry=self.registry
        )
        
        # Script Matching Metrics
        self.script_matching_requests_total = Counter(
            'eris_script_matching_requests_total',
            'Total script matching requests',
            ['hook_type', 'status'],
            registry=self.registry
        )
        
        self.script_matching_duration_seconds = Histogram(
            'eris_script_matching_duration_seconds',
            'Script matching latency in seconds',
            ['hook_type'],
            registry=self.registry
        )
        
        # System Info
        self.system_info = Info(
            'eris_system_info',
            'System information',
            registry=self.registry
        )
        
        # Worker Metrics
        self.worker_tasks_processed_total = Counter(
            'eris_worker_tasks_processed_total',
            'Total tasks processed by workers',
            ['worker_name', 'status'],
            registry=self.registry
        )
        
        self.worker_queue_size = Gauge(
            'eris_worker_queue_size',
            'Current worker queue size',
            ['worker_name'],
            registry=self.registry
        )

        self.orchestrator_context_load_total = Counter(
            'eris_orchestrator_context_load_total',
            'Orchestrator conversation context load attempts',
            ['result'],
            registry=self.registry
        )
        
        # Error Metrics
        self.errors_total = Counter(
            'eris_errors_total',
            'Total errors',
            ['type', 'severity'],
            registry=self.registry
        )
        
        # Update system info
        self._update_system_info()
    
    def _update_system_info(self):
        """Update system information"""
        import platform
        import socket
        
        try:
            self.system_info.info({
                'version': '0.1.0',
                'python_version': platform.python_version(),
                'system': platform.system(),
                'machine': platform.machine(),
                'hostname': socket.gethostname(),
            })
        except Exception:
            pass
    
    def get_registry(self) -> CollectorRegistry:
        """Get the Prometheus registry"""
        return self.registry
    
    def increment_http_request(self, method: str, endpoint: str, status_code: int):
        """Increment HTTP request counter"""
        self.http_requests_total.labels(
            method=method,
            endpoint=endpoint,
            status=status_code
        ).inc()
    
    def observe_http_request_duration(self, method: str, endpoint: str, duration: float):
        """Observe HTTP request duration"""
        self.http_request_duration_seconds.labels(
            method=method,
            endpoint=endpoint
        ).observe(duration)
    
    def update_users_total(self, level: str, status: str, count: int):
        """Update total users gauge"""
        self.users_total.labels(level=level, status=status).set(count)
    
    def update_users_active(self, count: int):
        """Update active users gauge"""
        self.users_active.set(count)
    
    def increment_user_registration(self, channel: str):
        """Increment user registration counter"""
        self.user_registrations_total.labels(channel=channel).inc()
    
    def update_conversations_total(self, status: str, count: int):
        """Update conversations total gauge"""
        self.conversations_total.labels(status=status).set(count)
    
    def increment_message(self, direction: str, channel: str):
        """Increment message counter"""
        self.messages_total.labels(direction=direction, channel=channel).inc()
    
    def observe_message_processing_duration(self, message_type: str, duration: float):
        """Observe message processing duration"""
        self.message_processing_duration_seconds.labels(message_type=message_type).observe(duration)
    
    def update_handoff_tasks_total(self, status: str, priority: str, count: int):
        """Update handoff tasks total gauge"""
        self.handoff_tasks_total.labels(status=status, priority=priority).set(count)
    
    def observe_handoff_task_duration(self, priority: str, duration: float):
        """Observe handoff task duration"""
        self.handoff_task_duration_seconds.labels(priority=priority).observe(duration)
    
    def increment_llm_request(self, model: str, status: str):
        """Increment LLM request counter"""
        self.llm_requests_total.labels(model=model, status=status).inc()
    
    def observe_llm_request_duration(self, model: str, operation: str, duration: float):
        """Observe LLM request duration"""
        self.llm_request_duration_seconds.labels(model=model, operation=operation).observe(duration)
    
    def increment_llm_tokens(self, model: str, direction: str, count: int):
        """Increment LLM tokens counter"""
        self.llm_tokens_total.labels(model=model, direction=direction).inc(count)
    
    def update_websocket_connections(self, connection_type: str, count: int):
        """Update WebSocket connections gauge"""
        self.websocket_connections_total.labels(type=connection_type).set(count)
    
    def increment_websocket_message(self, direction: str, message_type: str):
        """Increment WebSocket message counter"""
        self.websocket_messages_total.labels(direction=direction, message_type=message_type).inc()
    
    def update_telegram_accounts_total(self, status: str, count: int):
        """Update Telegram accounts total gauge"""
        self.telegram_accounts_total.labels(status=status).set(count)
    
    def observe_telegram_message_send_duration(self, duration: float):
        """Observe Telegram message send duration"""
        self.telegram_message_send_duration_seconds.observe(duration)
    
    def observe_db_query_duration(self, operation: str, table: str, duration: float):
        """Observe database query duration"""
        self.db_query_duration_seconds.labels(operation=operation, table=table).observe(duration)
    
    def update_db_connections_active(self, count: int):
        """Update active database connections gauge"""
        self.db_connections_active.set(count)
    
    def increment_cache_operation(self, operation: str, cache_type: str, status: str):
        """Increment cache operation counter"""
        self.cache_operations_total.labels(operation=operation, cache_type=cache_type, status=status).inc()
    
    def update_cache_hit_rate(self, cache_type: str, hit_rate: float):
        """Update cache hit rate gauge"""
        self.cache_hit_rate.labels(cache_type=cache_type).set(hit_rate)
    
    def increment_script_matching_request(self, hook_type: str, status: str):
        """Increment script matching request counter"""
        self.script_matching_requests_total.labels(hook_type=hook_type, status=status).inc()
    
    def observe_script_matching_duration(self, hook_type: str, duration: float):
        """Observe script matching duration"""
        self.script_matching_duration_seconds.labels(hook_type=hook_type).observe(duration)
    
    def increment_worker_task(self, worker_name: str, status: str):
        """Increment worker task counter"""
        self.worker_tasks_processed_total.labels(worker_name=worker_name, status=status).inc()
    
    def update_worker_queue_size(self, worker_name: str, size: int):
        """Update worker queue size gauge"""
        self.worker_queue_size.labels(worker_name=worker_name).set(size)

    def record_orchestrator_context_load(self, *, success: bool) -> None:
        """Increment orchestrator Redis/history context load counter."""
        result = "success" if success else "failed"
        self.orchestrator_context_load_total.labels(result=result).inc()
    
    def increment_error(self, error_type: str, severity: str):
        """Increment error counter"""
        self.errors_total.labels(type=error_type, severity=severity).inc()


# Global metrics instance
business_metrics = BusinessMetrics()