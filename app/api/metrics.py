"""P5-05: Prometheus metrics API endpoints."""

from fastapi import APIRouter
from prometheus_client import generate_latest
from prometheus_client.core import REGISTRY
from loguru import logger

from services.business_metrics import business_metrics

router = APIRouter()


@router.get("/metrics")
async def get_metrics():
    """
    Prometheus metrics endpoint.
    
    Returns both default HTTP metrics and custom business metrics in Prometheus format.
    This endpoint can be scraped by Prometheus server.
    """
    try:
        # Merge default registry with custom business metrics registry
        from prometheus_client import CollectorRegistry
        
        merged_registry = CollectorRegistry()
        
        # Add default metrics (HTTP, process, etc.)
        for collector in REGISTRY._collector_to_names:
            merged_registry.register(collector)
        
        # Add custom business metrics
        for collector in business_metrics.get_registry()._collector_to_names:
            merged_registry.register(collector)
        
        # Generate metrics in Prometheus text format
        return generate_latest(merged_registry)
        
    except Exception as e:
        logger.error(f"Error generating metrics: {e}")
        # Fallback to default metrics only
        return generate_latest(REGISTRY)


@router.get("/metrics/business")
async def get_business_metrics():
    """
    Business-specific metrics endpoint.
    
    Returns only custom business metrics, excluding default HTTP metrics.
    """
    try:
        return generate_latest(business_metrics.get_registry())
    except Exception as e:
        logger.error(f"Error generating business metrics: {e}")
        # Return empty metrics on error
        return ""


@router.get("/metrics/health")
async def get_metrics_health():
    """Health check for metrics collection."""
    try:
        return {
            "status": "healthy",
            "business_metrics_enabled": True,
            "registry_collectors": len(business_metrics.get_registry()._collector_to_names),
            "default_registry_collectors": len(REGISTRY._collector_to_names),
        }
    except Exception as e:
        logger.error(f"Metrics health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
        }