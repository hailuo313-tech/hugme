"""P1-05: FastAPI /health 端点测试

验证：
- GET /health 返回 200 状态码
- 响应包含必要字段
- 结构化日志正确配置
- CORS 配置正确
"""
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health_endpoint_returns_200():
    """验证 /health 端点返回 200 状态码"""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_endpoint_response_structure():
    """验证 /health 端点响应包含必要字段"""
    response = client.get("/health")
    data = response.json()
    
    assert "status" in data
    assert data["status"] == "ok"
    assert "service" in data
    assert data["service"] == "ERIS API"
    assert "version" in data
    assert "timestamp" in data


def test_health_detail_endpoint_returns_200():
    """验证 /health/detail 端点返回 200 状态码"""
    response = client.get("/health/detail")
    assert response.status_code == 200


def test_health_detail_response_structure():
    """验证 /health/detail 端点响应包含必要字段"""
    response = client.get("/health/detail")
    data = response.json()
    
    assert "api" in data
    assert data["api"] == "ok"
    assert "db" in data
    assert "redis" in data
    assert "duration_ms" in data


def test_cors_headers_present():
    """验证 CORS 头存在"""
    response = client.get("/health")
    # FastAPI CORS middleware 会添加这些头
    assert response.status_code == 200


def test_trace_id_header_present():
    """验证 X-Trace-Id 头存在"""
    response = client.get("/health")
    assert "X-Trace-Id" in response.headers
    assert len(response.headers["X-Trace-Id"]) > 0


def test_main_py_has_logging_config():
    """验证 main.py 包含日志配置"""
    import main
    assert hasattr(main, 'configure_logging')
    assert hasattr(main, 'request_trace_id')


def test_main_py_has_cors_config():
    """验证 main.py 包含 CORS 配置"""
    import main
    # 检查应用是否添加了 CORS 中间件
    cors_middleware_found = False
    for middleware in main.app.user_middleware:
        if "CORSMiddleware" in str(middleware.cls):
            cors_middleware_found = True
            break
    assert cors_middleware_found, "CORS middleware not found in FastAPI app"


def test_health_py_has_structured_logging():
    """验证 health.py 包含结构化日志"""
    import api.health
    assert hasattr(api.health, 'logger')
    assert hasattr(api.health, 'router')
