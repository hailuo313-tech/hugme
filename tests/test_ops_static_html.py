"""GET /ops/*.html — 与 /docs（Swagger）分离的只读 HTML。"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    html = tmp_path / "x.html"
    html.write_text("<!DOCTYPE html><html><body>ok</body></html>", encoding="utf-8")
    monkeypatch.setenv("OPS_DOCS_DIR", str(tmp_path))
    import importlib

    import main as m

    importlib.reload(m)
    with TestClient(m.app) as c:
        yield c


def test_ops_serves_html(client: TestClient):
    r = client.get("/ops/x.html")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "ok" in r.text


def test_ops_non_html_404(client: TestClient):
    assert client.get("/ops/readme.md").status_code == 404
