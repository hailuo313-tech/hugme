"""D6-3 调度器单元测试：``services.silent_reactivation_scheduler``。

不启动真 APScheduler 后台线程；通过 patch 把 scheduler 类替换成 MagicMock，
聚焦于 ``start_scheduler / shutdown_scheduler / _run_scan_job`` 的分支覆盖。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import silent_reactivation_scheduler as sched
from services.silent_reactivation_scheduler import (
    JOB_ID,
    _run_scan_job,
    shutdown_scheduler,
    start_scheduler,
)


# ── 共用：在每个用例前重置模块级单例 ───────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton():
    sched._scheduler = None
    yield
    sched._scheduler = None


# ── start_scheduler ─────────────────────────────────────────────


def test_start_scheduler_disabled_when_flag_off():
    with patch.object(sched.settings, "SILENT_REACTIVATION_ENABLED", False):
        out = start_scheduler()
    assert out is None
    assert sched._scheduler is None


def test_start_scheduler_returns_existing_singleton():
    fake = MagicMock(name="existing")
    sched._scheduler = fake
    with patch.object(sched.settings, "SILENT_REACTIVATION_ENABLED", True):
        out = start_scheduler()
    assert out is fake  # 不会重新创建


def test_start_scheduler_handles_invalid_cron():
    with patch.object(sched.settings, "SILENT_REACTIVATION_ENABLED", True), patch.object(
        sched.settings, "SILENT_REACTIVATION_CRON", "not a cron"
    ):
        out = start_scheduler()
    assert out is None
    assert sched._scheduler is None


def test_start_scheduler_happy_path_adds_job():
    fake_scheduler = MagicMock(name="scheduler")
    with patch.object(sched.settings, "SILENT_REACTIVATION_ENABLED", True), patch.object(
        sched.settings, "SILENT_REACTIVATION_CRON", "0 2 * * *"
    ), patch.object(sched, "AsyncIOScheduler", return_value=fake_scheduler):
        out = start_scheduler()
    assert out is fake_scheduler
    fake_scheduler.add_job.assert_called_once()
    # 校验 job 配置
    kwargs = fake_scheduler.add_job.call_args.kwargs
    assert kwargs["id"] == JOB_ID
    assert kwargs["max_instances"] == 1
    assert kwargs["coalesce"] is True
    fake_scheduler.start.assert_called_once()


# ── shutdown_scheduler ─────────────────────────────────────────


def test_shutdown_scheduler_no_op_when_not_started():
    # _scheduler 已被 fixture 置 None
    shutdown_scheduler()  # 不应抛
    assert sched._scheduler is None


def test_shutdown_scheduler_calls_shutdown_and_clears_singleton():
    fake = MagicMock(name="scheduler")
    sched._scheduler = fake
    shutdown_scheduler()
    fake.shutdown.assert_called_once_with(wait=False)
    assert sched._scheduler is None


def test_shutdown_scheduler_swallows_exception():
    fake = MagicMock(name="scheduler")
    fake.shutdown.side_effect = RuntimeError("boom")
    sched._scheduler = fake
    shutdown_scheduler()  # 不应抛
    assert sched._scheduler is None


# ── _run_scan_job ──────────────────────────────────────────────


def _make_session_mock(*, got_lock: bool):
    """模拟 ``async with AsyncSessionLocal() as session``。

    pg_try_advisory_lock 返回 got_lock；后续 unlock 同样 mock。
    """
    session = MagicMock()
    lock_res = MagicMock()
    lock_res.scalar = MagicMock(return_value=got_lock)
    session.execute = AsyncMock(return_value=lock_res)
    session.commit = AsyncMock(return_value=None)

    # async context manager
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx, session


async def test_run_scan_job_runs_when_lock_acquired():
    ctx, session = _make_session_mock(got_lock=True)
    runner_mock = AsyncMock(return_value=None)
    with patch.object(sched, "AsyncSessionLocal", return_value=ctx), patch.object(
        sched, "run_silent_reactivation_scan", runner_mock
    ):
        await _run_scan_job()
    runner_mock.assert_awaited_once()
    # 释放锁的 execute 也被调用过（至少 2 次：try_lock + unlock）
    assert session.execute.await_count >= 2


async def test_run_scan_job_skips_when_lock_not_acquired():
    ctx, session = _make_session_mock(got_lock=False)
    runner_mock = AsyncMock(return_value=None)
    with patch.object(sched, "AsyncSessionLocal", return_value=ctx), patch.object(
        sched, "run_silent_reactivation_scan", runner_mock
    ):
        await _run_scan_job()
    runner_mock.assert_not_awaited()


async def test_run_scan_job_swallows_runner_exception():
    ctx, session = _make_session_mock(got_lock=True)
    runner_mock = AsyncMock(side_effect=RuntimeError("boom"))
    with patch.object(sched, "AsyncSessionLocal", return_value=ctx), patch.object(
        sched, "run_silent_reactivation_scan", runner_mock
    ):
        # 不应抛
        await _run_scan_job()
    runner_mock.assert_awaited_once()


async def test_run_scan_job_swallows_outer_exception():
    """AsyncSessionLocal 抛错（例如 DB 挂） → 也不应冒泡。"""
    with patch.object(
        sched, "AsyncSessionLocal", side_effect=RuntimeError("db down")
    ):
        await _run_scan_job()  # 不应抛
