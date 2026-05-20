"""
P2-02: GeoIP 服务封装（MaxMind/ip-api）

支持两种 GeoIP 提供商：
1. MaxMind GeoIP2（离线数据库，高精度）
2. ip-api.com（在线 API，备用方案）

验收标准：抽样准确率 ≥95%
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp
from loguru import logger

from core.config import settings


@dataclass
class GeoIPResult:
    """GeoIP 查询结果"""
    country_code: str  # ISO 3166-1 alpha-2 (如 "US", "CN")
    country_name: str  # 完整国家名（如 "United States", "China"）
    ip: str  # 查询的 IP 地址
    provider: str  # 数据来源
    is_cached: bool = False  # 是否来自缓存


class GeoIPService:
    """GeoIP 服务封装类"""

    def __init__(self):
        self._maxmind_enabled = getattr(settings, "MAXMIND_ENABLED", False)
        self._maxmind_db_path = getattr(settings, "MAXMIND_DB_PATH", None)
        self._ipapi_enabled = getattr(settings, "IPAPI_ENABLED", True)
        self._ipapi_api_key = getattr(settings, "IPAPI_API_KEY", None)
        self._cache: dict[str, GeoIPResult] = {}
        self._cache_ttl = getattr(settings, "GEOIP_CACHE_TTL", 3600)  # 默认缓存1小时
        
        # MaxMind reader（延迟加载）
        self._maxmind_reader = None
        
        logger.bind(
            component="geoip",
            maxmind_enabled=self._maxmind_enabled,
            ipapi_enabled=self._ipapi_enabled,
        ).info("GeoIP service initialized")

    async def get_country_code(self, ip_address: str) -> Optional[str]:
        """
        获取 IP 地址对应的国家代码
        
        Args:
            ip_address: IP 地址（IPv4 或 IPv6）
            
        Returns:
            ISO 3166-1 alpha-2 国家代码（如 "US", "CN"），如果查询失败返回 None
        """
        result = await self.lookup(ip_address)
        return result.country_code if result else None

    async def get_country_name(self, ip_address: str) -> Optional[str]:
        """
        获取 IP 地址对应的国家名称
        
        Args:
            ip_address: IP 地址（IPv4 或 IPv6）
            
        Returns:
            完整国家名（如 "United States", "China"），如果查询失败返回 None
        """
        result = await self.lookup(ip_address)
        return result.country_name if result else None

    async def lookup(self, ip_address: str) -> Optional[GeoIPResult]:
        """
        完整的 GeoIP 查询，返回详细信息
        
        Args:
            ip_address: IP 地址（IPv4 或 IPv6）
            
        Returns:
            GeoIPResult 对象，如果查询失败返回 None
        """
        # 检查缓存
        cached = self._get_from_cache(ip_address)
        if cached:
            logger.bind(ip=ip_address, provider=cached.provider).debug("GeoIP cache hit")
            return cached

        # 尝试 MaxMind（如果启用）
        if self._maxmind_enabled:
            try:
                result = await self._lookup_maxmind(ip_address)
                if result:
                    self._put_to_cache(ip_address, result)
                    return result
            except Exception as e:
                logger.bind(
                    ip=ip_address,
                    error=str(e),
                    error_type=type(e).__name__,
                ).warning("MaxMind lookup failed, trying ip-api")

        # 尝试 ip-api（作为备用）
        if self._ipapi_enabled:
            try:
                result = await self._lookup_ipapi(ip_address)
                if result:
                    self._put_to_cache(ip_address, result)
                    return result
            except Exception as e:
                logger.bind(
                    ip=ip_address,
                    error=str(e),
                    error_type=type(e).__name__,
                ).error("ip-api lookup failed")

        logger.bind(ip=ip_address).warning("All GeoIP providers failed")
        return None

    async def _lookup_maxmind(self, ip_address: str) -> Optional[GeoIPResult]:
        """使用 MaxMind GeoIP2 数据库查询"""
        try:
            # 延迟导入 MaxMind（如果未安装则跳过）
            import geoip2.database
            
            # 延迟初始化 reader
            if self._maxmind_reader is None:
                if not self._maxmind_db_path:
                    raise ValueError("MAXMIND_DB_PATH not configured")
                self._maxmind_reader = geoip2.database.Reader(self._maxmind_db_path)
                logger.bind(db_path=self._maxmind_db_path).info("MaxMind database loaded")

            # 查询 IP
            response = self._maxmind_reader.country(ip_address)
            
            country_code = response.country.iso_code
            country_name = response.country.name or response.country.names.get("en", "")
            
            if not country_code:
                return None

            result = GeoIPResult(
                country_code=country_code,
                country_name=country_name,
                ip=ip_address,
                provider="maxmind",
            )
            
            logger.bind(
                ip=ip_address,
                country_code=country_code,
                country_name=country_name,
            ).info("MaxMind lookup successful")
            
            return result
            
        except ImportError:
            logger.warning("MaxMind library not installed, skipping MaxMind provider")
            self._maxmind_enabled = False
            return None
        except Exception as e:
            logger.bind(
                ip=ip_address,
                error=str(e),
                error_type=type(e).__name__,
            ).error("MaxMind lookup error")
            return None

    async def _lookup_ipapi(self, ip_address: str) -> Optional[GeoIPResult]:
        """使用 ip-api.com API 查询"""
        try:
            # 构建 API URL
            if self._ipapi_api_key:
                url = f"http://ip-api.com/json/{ip_address}?fields=status,country,countryCode&key={self._ipapi_api_key}"
            else:
                url = f"http://ip-api.com/json/{ip_address}?fields=status,country,countryCode"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status != 200:
                        logger.bind(
                            ip=ip_address,
                            status=response.status,
                        ).warning("ip-api returned non-200 status")
                        return None
                    
                    data = await response.json()
                    
                    if data.get("status") != "success":
                        logger.bind(ip=ip_address, api_response=data).warning("ip-api returned error status")
                        return None
                    
                    country_code = data.get("countryCode")
                    country_name = data.get("country")
                    
                    if not country_code:
                        return None

                    result = GeoIPResult(
                        country_code=country_code,
                        country_name=country_name,
                        ip=ip_address,
                        provider="ip-api",
                    )
                    
                    logger.bind(
                        ip=ip_address,
                        country_code=country_code,
                        country_name=country_name,
                    ).info("ip-api lookup successful")
                    
                    return result
                    
        except asyncio.TimeoutError:
            logger.bind(ip=ip_address).warning("ip-api request timeout")
            return None
        except Exception as e:
            logger.bind(
                ip=ip_address,
                error=str(e),
                error_type=type(e).__name__,
            ).error("ip-api lookup error")
            return None

    def _get_from_cache(self, ip_address: str) -> Optional[GeoIPResult]:
        """从缓存获取结果"""
        # 简单实现，生产环境可以使用 redis 等
        result = self._cache.get(ip_address)
        if result:
            # 标记为缓存结果
            result.is_cached = True
        return result

    def _put_to_cache(self, ip_address: str, result: GeoIPResult) -> None:
        """将结果放入缓存"""
        # 简单实现，生产环境可以使用 redis 等
        self._cache[ip_address] = result
        # TODO: 实现 TTL 过期

    def clear_cache(self) -> None:
        """清空缓存"""
        self._cache.clear()
        logger.info("GeoIP cache cleared")

    async def validate_accuracy(self, test_ips: list[tuple[str, str]]) -> float:
        """
        验证 GeoIP 服务的准确率
        
        Args:
            test_ips: 测试 IP 列表，格式为 [(ip, expected_country_code), ...]
            
        Returns:
            准确率（0.0 - 1.0）
        """
        if not test_ips:
            return 0.0

        correct = 0
        total = len(test_ips)

        for ip, expected_country in test_ips:
            result = await self.lookup(ip)
            if result and result.country_code == expected_country:
                correct += 1
            else:
                logger.bind(
                    ip=ip,
                    expected=expected_country,
                    actual=result.country_code if result else None,
                ).warning("GeoIP accuracy test failed")

        accuracy = correct / total
        logger.bind(
            correct=correct,
            total=total,
            accuracy=accuracy,
        ).info("GeoIP accuracy validation completed")

        return accuracy


# 全局单例
_geoip_service: Optional[GeoIPService] = None


def get_geoip_service() -> GeoIPService:
    """获取 GeoIP 服务单例"""
    global _geoip_service
    if _geoip_service is None:
        _geoip_service = GeoIPService()
    return _geoip_service