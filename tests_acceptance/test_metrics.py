from fastapi.testclient import TestClient

from main import app


def test_metrics_endpoint_returns_prometheus_text():
    client = TestClient(app)
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "# HELP" in response.text
