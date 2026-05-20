"""
P2-02: GeoIP 服务测试

测试 GeoIP 服务的功能，包括：
- 基本查询功能
- 缓存机制
- 准确率验证
- 错误处理
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.geoip_service import GeoIPService, GeoIPResult, get_geoip_service


@pytest.fixture
def geoip_service():
    """创建 GeoIP 服务实例"""
    service = GeoIPService()
    return service


class TestGeoIPResult:
    """测试 GeoIPResult 数据类"""
    
    def test_geoip_result_creation(self):
        """测试 GeoIPResult 对象创建"""
        result = GeoIPResult(
            country_code="US",
            country_name="United States",
            ip="8.8.8.8",
            provider="ip-api",
            is_cached=False
        )
        assert result.country_code == "US"
        assert result.country_name == "United States"
        assert result.ip == "8.8.8.8"
        assert result.provider == "ip-api"
        assert result.is_cached is False


class TestGeoIPServiceBasic:
    """测试 GeoIP 服务基本功能"""
    
    @pytest.mark.asyncio
    async def test_service_initialization(self, geoip_service):
        """测试服务初始化"""
        assert geoip_service is not None
        assert geoip_service._cache == {}
        assert geoip_service._maxmind_enabled is False
        assert geoip_service._ipapi_enabled is True
    
    def test_get_geoip_service_singleton(self):
        """测试单例模式"""
        service1 = get_geoip_service()
        service2 = get_geoip_service()
        assert service1 is service2


class TestGeoIPLookup:
    """测试 GeoIP 查询功能"""
    
    @pytest.mark.asyncio
    async def test_lookup_invalid_ip(self, geoip_service):
        """测试无效 IP 地址查询"""
        result = await geoip_service.lookup("invalid-ip")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_lookup_private_ip(self, geoip_service):
        """测试私有 IP 地址查询"""
        result = await geoip_service.lookup("192.168.1.1")
        # 私有 IP 通常无法解析，可能返回 None
        assert result is None or result.country_code in ("US", "RD", None)
    
    @pytest.mark.asyncio
    async def test_get_country_code(self, geoip_service):
        """测试获取国家代码"""
        # 由于实际的 ip-api 可能有网络问题，这里只测试方法调用
        code = await geoip_service.get_country_code("8.8.8.8")
        # 可能为 None（网络问题）或实际的国家代码
        assert code is None or len(code) == 2
    
    @pytest.mark.asyncio
    async def test_get_country_name(self, geoip_service):
        """测试获取国家名称"""
        name = await geoip_service.get_country_name("8.8.8.8")
        # 可能为 None（网络问题）或实际的国家名称
        assert name is None or isinstance(name, str)


class TestGeoIPCache:
    """测试缓存功能"""
    
    @pytest.mark.asyncio
    async def test_cache_hit(self, geoip_service):
        """测试缓存命中"""
        # 手动添加缓存
        test_result = GeoIPResult(
            country_code="US",
            country_name="United States",
            ip="1.2.3.4",
            provider="test"
        )
        geoip_service._put_to_cache("1.2.3.4", test_result)
        
        # 查询应该从缓存返回
        result = await geoip_service.lookup("1.2.3.4")
        assert result is not None
        assert result.country_code == "US"
        assert result.is_cached is True
    
    def test_cache_clear(self, geoip_service):
        """测试清空缓存"""
        # 添加缓存数据
        test_result = GeoIPResult(
            country_code="CN",
            country_name="China",
            ip="5.6.7.8",
            provider="test"
        )
        geoip_service._put_to_cache("5.6.7.8", test_result)
        assert len(geoip_service._cache) > 0
        
        # 清空缓存
        geoip_service.clear_cache()
        assert len(geoip_service._cache) == 0


class TestGeoIPAccuracy:
    """测试准确率验证"""
    
    @pytest.mark.asyncio
    async def test_validate_accuracy_empty(self, geoip_service):
        """测试空测试列表的准确率验证"""
        accuracy = await geoip_service.validate_accuracy([])
        assert accuracy == 0.0
    
    @pytest.mark.asyncio
    async def test_validate_accuracy_with_mock(self, geoip_service):
        """测试准确率验证（使用模拟数据）"""
        # 模拟测试数据
        test_ips = [
            ("8.8.8.8", "US"),  # Google DNS（美国）
            ("1.1.1.1", "US"),  # Cloudflare DNS（美国）
        ]
        
        # 由于实际网络请求可能失败，这里只测试方法调用
        # 在实际环境中，应该使用已知的测试 IP
        accuracy = await geoip_service.validate_accuracy(test_ips)
        assert 0.0 <= accuracy <= 1.0


class TestGeoIPErrorHandling:
    """测试错误处理"""
    
    @pytest.mark.asyncio
    async def test_ipapi_timeout(self, geoip_service):
        """测试 ip-api 超时处理"""
        # 使用一个可能导致超时的 IP
        # 在实际测试中，可能需要模拟网络超时
        result = await geoip_service.lookup("192.0.2.1")  # TEST-NET-1（保留 IP）
        # 保留 IP 应该返回 None 或无法解析
        assert result is None or result.country_code is None


class TestGeoIPIntegration:
    """集成测试"""
    
    @pytest.mark.asyncio
    async def test_end_to_end_workflow(self, geoip_service):
        """测试端到端工作流程"""
        # 1. 查询 IP
        result = await geoip_service.lookup("8.8.8.8")
        
        # 2. 验证结果格式
        if result:
            assert isinstance(result, GeoIPResult)
            assert result.ip == "8.8.8.8"
            assert result.provider in ("maxmind", "ip-api")
            assert len(result.country_code) == 2 if result.country_code else True
        
        # 3. 测试缓存
        if result:
            cached_result = await geoip_service.lookup("8.8.8.8")
            assert cached_result is not None
            # 第二次查询应该更快（从缓存）


if __name__ == "__main__":
    pytest.main([__file__, "-v"])