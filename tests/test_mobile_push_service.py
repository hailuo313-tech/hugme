"""
P4-10: 移动端推送服务测试

测试 FCM/APNs 推送服务的基本功能。
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from services.mobile_push_service import MobilePushService, PushResult, get_mobile_push_service


@pytest.fixture
def mock_settings():
    """模拟配置"""
    with patch('services.mobile_push_service.settings') as mock:
        mock.FCM_ENABLED = False
        mock.FCM_CREDENTIALS_PATH = None
        mock.APNS_ENABLED = False
        mock.APNS_TEAM_ID = None
        mock.APNS_KEY_ID = None
        mock.APNS_KEY_PATH = None
        mock.APNS_BUNDLE_ID = "com.hugme.app"
        mock.APNS_PRODUCTION = False
        yield mock


@pytest.fixture
def push_service(mock_settings):
    """创建推送服务实例"""
    service = MobilePushService()
    return service


class TestMobilePushService:
    """移动端推送服务测试"""

    def test_initialization(self, push_service):
        """测试服务初始化"""
        assert push_service._fcm_enabled == False
        assert push_service._apns_enabled == False
        assert push_service._apns_production == False

    def test_get_mobile_push_service_singleton(self, mock_settings):
        """测试单例模式"""
        service1 = get_mobile_push_service()
        service2 = get_mobile_push_service()
        assert service1 is service2

    @pytest.mark.asyncio
    async def test_fcm_disabled(self, push_service):
        """测试 FCM 禁用时的行为"""
        result = await push_service.send_fcm_notification(
            device_token="test_token",
            title="Test Title",
            body="Test Body"
        )
        assert result.success == False
        assert result.provider == "fcm"
        assert "not enabled" in result.error_message

    @pytest.mark.asyncio
    async def test_apns_disabled(self, push_service):
        """测试 APNs 禁用时的行为"""
        result = await push_service.send_apns_notification(
            device_token="test_token",
            title="Test Title",
            body="Test Body"
        )
        assert result.success == False
        assert result.provider == "apns"
        assert "not enabled" in result.error_message

    @pytest.mark.asyncio
    async def test_send_notification_unsupported_platform(self, push_service):
        """测试不支持的平台"""
        result = await push_service.send_notification(
            device_token="test_token",
            platform="windows",
            title="Test Title",
            body="Test Body"
        )
        assert result.success == False
        assert result.provider == "unknown"
        assert "Unsupported platform" in result.error_message

    @pytest.mark.asyncio
    async def test_send_notification_android_when_disabled(self, push_service):
        """测试 Android 推送在禁用时的行为"""
        result = await push_service.send_notification(
            device_token="test_token",
            platform="android",
            title="Test Title",
            body="Test Body"
        )
        assert result.success == False
        assert result.provider == "fcm"

    @pytest.mark.asyncio
    async def test_send_notification_ios_when_disabled(self, push_service):
        """测试 iOS 推送在禁用时的行为"""
        result = await push_service.send_notification(
            device_token="test_token",
            platform="ios",
            title="Test Title",
            body="Test Body"
        )
        assert result.success == False
        assert result.provider == "apns"

    def test_apns_bundle_id_property(self, push_service):
        """测试 APNs Bundle ID 属性"""
        assert push_service._apns_bundle_id == "com.hugme.app"


@pytest.mark.asyncio
class TestMobilePushServiceWithFirebase:
    """带 Firebase 模拟的测试"""

    @patch('services.mobile_push_service.os.path.exists', return_value=True)
    @patch('services.mobile_push_service.FIREBASE_AVAILABLE', True)
    @patch('services.mobile_push_service.firebase_admin')
    async def test_fcm_initialization_success(self, mock_firebase_admin, mock_settings, _exists):
        """测试 Firebase 初始化成功"""
        mock_settings.FCM_ENABLED = True
        mock_settings.FCM_CREDENTIALS_PATH = "/path/to/credentials.json"
        
        mock_creds = Mock()
        mock_firebase_admin.credentials.Certificate.return_value = mock_creds
        mock_firebase_admin.initialize_app.return_value = None
        mock_firebase_admin.get_app.return_value = Mock()
        
        service = MobilePushService()
        await service._init_firebase()
        
        assert service._firebase_app is not None
        mock_firebase_admin.credentials.Certificate.assert_called_once_with("/path/to/credentials.json")
        mock_firebase_admin.initialize_app.assert_called_once_with(mock_creds)

    @patch('services.mobile_push_service.os.path.exists', return_value=True)
    @patch('services.mobile_push_service.FIREBASE_AVAILABLE', True)
    @patch('services.mobile_push_service.firebase_admin')
    @patch('services.mobile_push_service.messaging')
    async def test_fcm_send_success(self, mock_messaging, mock_firebase_admin, mock_settings, _exists):
        """测试 FCM 发送成功"""
        mock_settings.FCM_ENABLED = True
        mock_settings.FCM_CREDENTIALS_PATH = "/path/to/credentials.json"
        
        mock_creds = Mock()
        mock_firebase_admin.credentials.Certificate.return_value = mock_creds
        mock_firebase_admin.initialize_app.return_value = None
        mock_firebase_admin.get_app.return_value = Mock()
        
        mock_messaging.send.return_value = "message_id_123"
        
        service = MobilePushService()
        result = await service.send_fcm_notification(
            device_token="test_token",
            title="Test Title",
            body="Test Body"
        )
        
        assert result.success == True
        assert result.provider == "fcm"
        assert result.message_id == "message_id_123"


@pytest.mark.asyncio
class TestMobilePushServiceWithHttpx:
    """带 httpx 模拟的测试"""

    @patch('services.mobile_push_service.HTTPX_AVAILABLE', True)
    @patch('services.mobile_push_service.httpx')
    async def test_apns_send_success(self, mock_httpx, mock_settings):
        """测试 APNs 发送成功"""
        mock_settings.APNS_ENABLED = True
        mock_settings.APNS_PRODUCTION = False
        
        # 模拟 httpx 响应
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'apns-id': 'apns_id_123'}
        
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        
        mock_httpx.AsyncClient.return_value = mock_client
        
        service = MobilePushService()
        result = await service.send_apns_notification(
            device_token="test_token",
            title="Test Title",
            body="Test Body"
        )
        
        assert result.success == True
        assert result.provider == "apns"
        assert result.message_id == "apns_id_123"

    @patch('services.mobile_push_service.HTTPX_AVAILABLE', True)
    @patch('services.mobile_push_service.httpx')
    async def test_apns_send_failure(self, mock_httpx, mock_settings):
        """测试 APNs 发送失败"""
        mock_settings.APNS_ENABLED = True
        mock_settings.APNS_PRODUCTION = False
        
        # 模拟 httpx 错误响应
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Bad device token"
        
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        
        mock_httpx.AsyncClient.return_value = mock_client
        
        service = MobilePushService()
        result = await service.send_apns_notification(
            device_token="test_token",
            title="Test Title",
            body="Test Body"
        )
        
        assert result.success == False
        assert result.provider == "apns"
        assert "400" in result.error_message


class TestPushResult:
    """PushResult 数据类测试"""

    def test_push_result_creation(self):
        """测试 PushResult 创建"""
        result = PushResult(
            success=True,
            device_token="test_token",
            provider="fcm",
            message_id="msg_123"
        )
        assert result.success == True
        assert result.device_token == "test_token"
        assert result.provider == "fcm"
        assert result.message_id == "msg_123"
        assert result.error_message is None

    def test_push_result_with_error(self):
        """测试带错误的 PushResult"""
        result = PushResult(
            success=False,
            device_token="test_token",
            provider="apns",
            error_message="Invalid token"
        )
        assert result.success == False
        assert result.device_token == "test_token"
        assert result.provider == "apns"
        assert result.error_message == "Invalid token"
        assert result.message_id is None