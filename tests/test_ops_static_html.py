"""GET /ops/*.html — 与 /docs（Swagger）分离的只读 HTML。"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import types

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    html = tmp_path / "x.html"
    html.write_text("<!DOCTYPE html><html><body>ok</body></html>", encoding="utf-8")
    monkeypatch.setenv("OPS_DOCS_DIR", str(tmp_path))
    if importlib.util.find_spec("prometheus_fastapi_instrumentator") is None:
        fake_metrics = types.ModuleType("prometheus_fastapi_instrumentator")
        fake_metrics.Instrumentator = _NoopInstrumentator
        monkeypatch.setitem(sys.modules, "prometheus_fastapi_instrumentator", fake_metrics)
    _install_worker_stubs(monkeypatch)
    monkeypatch.delitem(sys.modules, "main", raising=False)

    import main as m

    importlib.reload(m)
    monkeypatch.setattr(m, "init_db", _noop_async)
    monkeypatch.setattr(m, "start_silent_reactivation_scheduler", _noop)
    monkeypatch.setattr(m, "start_embedding_worker", _noop)
    monkeypatch.setattr(m, "start_profile_score_scheduler", _noop)
    monkeypatch.setattr(m, "start_notification_sender_worker", _noop)
    monkeypatch.setattr(m, "start_message_schedule_scheduler", _noop)
    monkeypatch.setattr(m, "start_auto_delivery_worker", _noop)
    monkeypatch.setattr(m, "start_archive_worker", _noop)
    monkeypatch.setattr(m, "shutdown_archive_worker", _noop)
    monkeypatch.setattr(m, "shutdown_auto_delivery_worker", _noop)
    monkeypatch.setattr(m, "shutdown_message_schedule_scheduler", _noop)
    monkeypatch.setattr(m, "shutdown_profile_score_scheduler", _noop)
    monkeypatch.setattr(m, "shutdown_notification_sender_worker", _noop)
    monkeypatch.setattr(m, "shutdown_embedding_worker", _noop)
    monkeypatch.setattr(m, "shutdown_silent_reactivation_scheduler", _noop)
    with TestClient(m.app) as c:
        yield c


async def _noop_async():
    return None


def _noop():
    return None


class _NoopInstrumentator:
    def instrument(self, app):
        return self

    def expose(self, app, **kwargs):
        return app


def _install_worker_stubs(monkeypatch):
    for module_name in (
        "services.silent_reactivation_scheduler",
        "services.embedding_worker",
        "services.profile_score_scheduler",
        "services.notification_sender_worker",
        "services.message_schedule_service",
        "services.auto_delivery_worker",
        "services.archive_service",
    ):
        fake_module = types.ModuleType(module_name)
        fake_module.start_scheduler = _noop
        fake_module.shutdown_scheduler = _noop
        fake_module.run_one_tick = _noop_async
        fake_module.get_scheduler_status = lambda: {"running": False}
        fake_module.add_scheduled_message = _return_id_async
        fake_module.reinit_account_pool = _return_true_async
        fake_module.archive_message_async = _return_false_async
        fake_module.get_conversation_script_hits = _return_empty_async
        fake_module.get_premium_chat_trace = _return_none_async
        monkeypatch.setitem(sys.modules, module_name, fake_module)


async def _return_id_async(*args, **kwargs):
    return "test-id"


async def _return_true_async(*args, **kwargs):
    return True


async def _return_false_async(*args, **kwargs):
    return False


async def _return_empty_async(*args, **kwargs):
    return []


async def _return_none_async(*args, **kwargs):
    return None


def test_ops_serves_html(client: TestClient):
    r = client.get("/ops/x.html")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "ok" in r.text


def test_ops_non_html_404(client: TestClient):
    assert client.get("/ops/readme.md").status_code == 404
