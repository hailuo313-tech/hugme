"""
P2-02: GeoIP API 端点

提供 GeoIP 查询的 HTTP 接口，用于测试和调试。
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from loguru import logger

from services.geoip_service import get_geoip_service

router = APIRouter()


class GeoIPRequest(BaseModel):
    """GeoIP 查询请求"""
    ip: str


class GeoIPResponse(BaseModel):
    """GeoIP 查询响应"""
    country_code: str | None
    country_name: str | None
    ip: str
    provider: str | None
    is_cached: bool = False
    success: bool


@router.post("/geoip/lookup")
async def lookup_geoip(request: GeoIPRequest):
    """
    查询 IP 地址的地理位置信息
    
    Args:
        request: 包含 IP 地址的请求
        
    Returns:
        GeoIP 响应，包含国家代码、国家名称等信息
    """
    trace_id = f"geoip-{request.ip}"
    log = logger.bind(
        trace_id=trace_id,
        component="geoip_api",
        ip=request.ip,
    )
    
    log.info("geoip.lookup.start")
    
    try:
        service = get_geoip_service()
        result = await service.lookup(request.ip)
        
        if result:
            response = GeoIPResponse(
                country_code=result.country_code,
                country_name=result.country_name,
                ip=result.ip,
                provider=result.provider,
                is_cached=result.is_cached,
                success=True
            )
            log.bind(
                country_code=result.country_code,
                country_name=result.country_name,
                provider=result.provider,
            ).info("geoip.lookup.success")
        else:
            response = GeoIPResponse(
                country_code=None,
                country_name=None,
                ip=request.ip,
                provider=None,
                success=False
            )
            log.warning("geoip.lookup.failed")
        
        return response
        
    except Exception as e:
        log.bind(
            error_type=type(e).__name__,
            error=str(e),
        ).error("geoip.lookup.error")
        raise HTTPException(status_code=500, detail=f"GeoIP lookup failed: {str(e)}")


@router.get("/geoip/country-code")
async def get_country_code(
    ip: str = Query(..., description="IP 地址")
):
    """
    获取 IP 地址的国家代码
    
    Args:
        ip: IP 地址
        
    Returns:
        ISO 3166-1 alpha-2 国家代码
    """
    trace_id = f"geoip-cc-{ip}"
    log = logger.bind(
        trace_id=trace_id,
        component="geoip_api",
        ip=ip,
    )
    
    log.info("geoip.get_country_code.start")
    
    try:
        service = get_geoip_service()
        country_code = await service.get_country_code(ip)
        
        log.bind(country_code=country_code).info("geoip.get_country_code.success")
        
        return {
            "ip": ip,
            "country_code": country_code,
            "success": country_code is not None
        }
        
    except Exception as e:
        log.bind(
            error_type=type(e).__name__,
            error=str(e),
        ).error("geoip.get_country_code.error")
        raise HTTPException(status_code=500, detail=f"Failed to get country code: {str(e)}")


@router.get("/geoip/country-name")
async def get_country_name(
    ip: str = Query(..., description="IP 地址")
):
    """
    获取 IP 地址的国家名称
    
    Args:
        ip: IP 地址
        
    Returns:
        完整国家名称
    """
    trace_id = f"geoip-cn-{ip}"
    log = logger.bind(
        trace_id=trace_id,
        component="geoip_api",
        ip=ip,
    )
    
    log.info("geoip.get_country_name.start")
    
    try:
        service = get_geoip_service()
        country_name = await service.get_country_name(ip)
        
        log.bind(country_name=country_name).info("geoip.get_country_name.success")
        
        return {
            "ip": ip,
            "country_name": country_name,
            "success": country_name is not None
        }
        
    except Exception as e:
        log.bind(
            error_type=type(e).__name__,
            error=str(e),
        ).error("geoip.get_country_name.error")
        raise HTTPException(status_code=500, detail=f"Failed to get country name: {str(e)}")


@router.post("/geoip/cache/clear")
async def clear_cache():
    """
    清空 GeoIP 缓存
    
    Returns:
        操作结果
    """
    trace_id = "geoip-cache-clear"
    log = logger.bind(
        trace_id=trace_id,
        component="geoip_api",
    )
    
    log.info("geoip.cache_clear.start")
    
    try:
        service = get_geoip_service()
        service.clear_cache()
        
        log.info("geoip.cache_clear.success")
        
        return {
            "success": True,
            "message": "GeoIP cache cleared successfully"
        }
        
    except Exception as e:
        log.bind(
            error_type=type(e).__name__,
            error=str(e),
        ).error("geoip.cache_clear.error")
        raise HTTPException(status_code=500, detail=f"Failed to clear cache: {str(e)}")