"""
P4-10: 移动端推送服务（FCM/APNs）

支持 Firebase Cloud Messaging（FCM）用于 Android 和 Apple Push Notification service（APNs）用于 iOS。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional, Dict

from loguru import logger

try:
    import firebase_admin
    from firebase_admin import credentials, messaging
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    logger.warning("firebase_admin not installed, FCM will be disabled")

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    logger.warning("httpx not installed, APNs will be disabled")

from core.config import settings


@dataclass
class PushResult:
    """推送结果"""
    success: bool
    device_token: str
    provider: str  # "fcm" or "apns"
    error_message: Optional[str] = None
    message_id: Optional[str] = None


class MobilePushService:
    """移动端推送服务类"""

    def __init__(self):
        self._fcm_enabled = getattr(settings, "FCM_ENABLED", False)
        self._fcm_credentials_path = getattr(settings, "FCM_CREDENTIALS_PATH", None)
        self._apns_enabled = getattr(settings, "APNS_ENABLED", False)
        self._apns_team_id = getattr(settings, "APNS_TEAM_ID", None)
        self._apns_key_id = getattr(settings, "APNS_KEY_ID", None)
        self._apns_key_path = getattr(settings, "APNS_KEY_PATH", None)
        
        # FCM 初始化（延迟加载）
        self._firebase_app = None
        
        # APNs 配置
        self._apns_production = getattr(settings, "APNS_PRODUCTION", False)
        
        logger.bind(
            fcm_enabled=self._fcm_enabled,
            apns_enabled=self._apns_enabled,
            firebase_available=FIREBASE_AVAILABLE,
            httpx_available=HTTPX_AVAILABLE,
        ).info("Mobile push service initialized")

    async def send_fcm_notification(
        self,
        device_token: str,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        notification_id: Optional[str] = None,
    ) -> PushResult:
        """
        发送 FCM 推送（Android）
        
        Args:
            device_token: 设备令牌
            title: 通知标题
            body: 通知内容
            data: 自定义数据
            notification_id: 可选的通知ID
            
        Returns:
            PushResult 对象
        """
        if not self._fcm_enabled or not FIREBASE_AVAILABLE:
            return PushResult(
                success=False,
                device_token=device_token,
                provider="fcm",
                error_message="FCM not enabled or firebase_admin not installed"
            )
        
        try:
            # 延迟初始化 Firebase
            if self._firebase_app is None:
                await self._init_firebase()
            
            # 构建消息
            message = messaging.Message(
                notification=messaging.Notification(
                    title=title,
                    body=body,
                ),
                data=data or {},
                token=device_token,
            )
            
            # 发送推送
            response = messaging.send(message, app=self._firebase_app)
            
            logger.bind(
                device_token=device_token[:20] + "...",
                message_id=response,
                title=title,
            ).info("FCM notification sent successfully")
            
            return PushResult(
                success=True,
                device_token=device_token,
                provider="fcm",
                message_id=response
            )
            
        except Exception as e:
            logger.bind(
                device_token=device_token[:20] + "...",
                error=str(e),
                error_type=type(e).__name__,
            ).error("FCM notification failed")
            
            return PushResult(
                success=False,
                device_token=device_token,
                provider="fcm",
                error_message=str(e)
            )

    async def send_apns_notification(
        self,
        device_token: str,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        notification_id: Optional[str] = None,
    ) -> PushResult:
        """
        发送 APNs 推送（iOS）
        
        Args:
            device_token: 设备令牌
            title: 通知标题
            body: 通知内容
            data: 自定义数据
            notification_id: 可选的通知ID
            
        Returns:
            PushResult 对象
        """
        if not self._apns_enabled or not HTTPX_AVAILABLE:
            return PushResult(
                success=False,
                device_token=device_token,
                provider="apns",
                error_message="APNs not enabled or httpx not installed"
            )
        
        try:
            # 构建推送负载
            payload = {
                "aps": {
                    "alert": {
                        "title": title,
                        "body": body,
                    },
                    "sound": "default",
                    "badge": 1,
                }
            }
            
            # 添加自定义数据
            if data:
                payload.update(data)
            
            # 发送 APNs 推送
            if self._apns_production:
                url = f"https://api.push.apple.com/3/device/{device_token}"
            else:
                url = f"https://api.development.push.apple.com/3/device/{device_token}"
            
            headers = {
                "apns-topic": self._apns_bundle_id,
                "apns-push-type": "alert",
                "apns-id": notification_id or str(hash(f"{device_token}{title}{body}")),
                "content-type": "application/json",
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    apns_id = response.headers.get('apns-id')
                    logger.bind(
                        device_token=device_token[:20] + "...",
                        apns_id=apns_id,
                        title=title,
                    ).info("APNs notification sent successfully")
                    
                    return PushResult(
                        success=True,
                        device_token=device_token,
                        provider="apns",
                        message_id=apns_id
                    )
                else:
                    error_text = response.text
                    logger.bind(
                        device_token=device_token[:20] + "...",
                        status_code=response.status_code,
                        error=error_text,
                    ).error("APNs notification failed")
                    
                    return PushResult(
                        success=False,
                        device_token=device_token,
                        provider="apns",
                        error_message=f"HTTP {response.status_code}: {error_text}"
                    )
            
        except Exception as e:
            logger.bind(
                device_token=device_token[:20] + "...",
                error=str(e),
                error_type=type(e).__name__,
            ).error("APNs notification failed")
            
            return PushResult(
                success=False,
                device_token=device_token,
                provider="apns",
                error_message=str(e)
            )

    async def send_notification(
        self,
        device_token: str,
        platform: str,  # "android" or "ios"
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        notification_id: Optional[str] = None,
    ) -> PushResult:
        """
        根据平台自动选择推送服务
        
        Args:
            device_token: 设备令牌
            platform: 平台类型（"android" 或 "ios"）
            title: 通知标题
            body: 通知内容
            data: 自定义数据
            notification_id: 可选的通知ID
            
        Returns:
            PushResult 对象
        """
        if platform == "android":
            return await self.send_fcm_notification(
                device_token, title, body, data, notification_id
            )
        elif platform == "ios":
            return await self.send_apns_notification(
                device_token, title, body, data, notification_id
            )
        else:
            logger.bind(platform=platform).warning("Unsupported platform for push notification")
            return PushResult(
                success=False,
                device_token=device_token,
                provider="unknown",
                error_message=f"Unsupported platform: {platform}"
            )

    async def _init_firebase(self):
        """初始化 Firebase Admin SDK"""
        if self._firebase_app is not None:
            return
        
        try:
            if not self._fcm_credentials_path:
                raise ValueError("FCM_CREDENTIALS_PATH not configured")
            
            cred = credentials.Certificate(self._fcm_credentials_path)
            firebase_admin.initialize_app(cred)
            
            self._firebase_app = firebase_admin.get_app()
            
            logger.bind(credentials_path=self._fcm_credentials_path).info("Firebase Admin SDK initialized")
            
        except Exception as e:
            logger.bind(
                error=str(e),
                error_type=type(e).__name__,
                credentials_path=self._fcm_credentials_path,
            ).error("Failed to initialize Firebase Admin SDK")
            raise

    @property
    def _apns_bundle_id(self) -> str:
        """获取 APNs Bundle ID"""
        # 从配置获取，或者使用默认值
        return getattr(settings, "APNS_BUNDLE_ID", "com.hugme.app")


# 全局单例
_mobile_push_service: Optional[MobilePushService] = None


def get_mobile_push_service() -> MobilePushService:
    """获取移动端推送服务单例"""
    global _mobile_push_service
    if _mobile_push_service is None:
        _mobile_push_service = MobilePushService()
    return _mobile_push_service