#!/usr/bin/env python3
"""TikTok live monitor dashboard — account CRUD + live sessions."""

from __future__ import annotations

import html
import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from accounts_store import (
    GROUP_INTERCEPT,
    GROUP_LABELS,
    GROUP_OWN,
    add_account,
    add_accounts_from_text,
    delete_account,
    list_accounts as list_config_accounts,
    normalize_group,
    parse_account_input,
)
from live_db import (
    audit_in_progress,
    cleanup_stale_jobs,
    get_active_probe_run,
    init_db,
    list_accounts as list_db_accounts,
    list_live_sessions,
    list_removed_accounts,
    managed_budget_stats,
    managed_recheck_overview,
    probe_in_progress,
    stats,
    sync_accounts,
)
from job_lock import cleanup_stale_lock, is_job_running
from managed_live import managed_api_enabled

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
DB_PATH = ROOT / "data" / "tiktok_live.sqlite"
WORKER_PATH = ROOT / "live_worker.py"

TABS_WITH_GROUP = {"accounts", "live", "history", "removed"}


def esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def parse_group(raw: str) -> str:
    return normalize_group(raw, default=GROUP_INTERCEPT)


def page_url(*, tab: str, group: str = GROUP_INTERCEPT, msg: str = "") -> str:
    url = f"/tiktok-monitor/?tab={quote(tab)}&group={quote(group)}"
    if msg:
        url += f"&msg={quote(msg)}"
    return url


def ensure_runtime() -> None:
    init_db(DB_PATH)
    cleanup_stale_jobs(DB_PATH)
    cleanup_stale_lock(ROOT, "probe")
    cleanup_stale_lock(ROOT, "audit")
    sync_accounts(DB_PATH, list_config_accounts(CONFIG_PATH))


def hybrid_mode_note() -> str:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        config = {}
    live_api = config.get("live_api") if isinstance(config.get("live_api"), dict) else {}
    if managed_api_enabled(live_api):
        return "混合严格模式：专业 LIVE API 与本地 Webcast/视频流必须一致才确认直播。"
    return "严格本地模式：已禁止 SIGI 单独确认；专业 LIVE API 尚未启用，启用后自动执行双源一致判定。"


class Handler(BaseHTTPRequestHandler):
    server_version = "TikTokLiveMonitor/2.1"

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.client_address[0]} - {fmt % args}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/tiktok-monitor", "/tiktok-monitor/"}:
            qs = parse_qs(parsed.query)
            tab = (qs.get("tab") or ["live"])[0]
            group = parse_group((qs.get("group") or [GROUP_INTERCEPT])[0])
            msg = (qs.get("msg") or [""])[0]
            self._html(200, render_page(tab=tab, group=group, message=msg))
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        form = {k: v[0] for k, v in parse_qs(raw).items()}
        group = parse_group(form.get("group", GROUP_OWN))

        if parsed.path == "/tiktok-monitor/add-account":
            account_raw = form.get("account", "")
            name = form.get("name", "")
            try:
                acc = parse_account_input(account_raw, name=name, group=group)
                ok = add_account(CONFIG_PATH, acc)
                ensure_runtime()
                msg = f"已添加账号 @{acc.username}" if ok else f"账号 @{acc.username} 已存在"
            except ValueError as exc:
                msg = str(exc)
            self._redirect(page_url(tab="accounts", group=group, msg=msg))
            return

        if parsed.path == "/tiktok-monitor/add-accounts":
            text = form.get("accounts", "")
            added = add_accounts_from_text(CONFIG_PATH, text, group=group)
            ensure_runtime()
            msg = f"批量导入完成，新增 {added} 个账号"
            self._redirect(page_url(tab="accounts", group=group, msg=msg))
            return

        if parsed.path == "/tiktok-monitor/delete-account":
            username = form.get("username", "")
            removed = delete_account(CONFIG_PATH, username)
            ensure_runtime()
            msg = f"已删除账号 @{username.lstrip('@')}" if removed else "未找到该账号"
            self._redirect(page_url(tab="accounts", group=group, msg=msg))
            return

        if parsed.path == "/tiktok-monitor/run-probe":
            total = len(list_config_accounts(CONFIG_PATH))
            eta_min = max(1, int(total * 0.8 / 60) + 1)
            if is_job_running(ROOT, "probe"):
                msg = f"检测任务正在运行中，约 {eta_min} 分钟完成，请稍后刷新页面"
            else:
                ok = run_worker_async("probe")
                msg = (
                    f"已启动直播检测（共 {total} 个账号，约需 {eta_min} 分钟）。"
                    f"检测完成后请刷新本页查看结果；若无账号在播，列表仍为空属正常"
                    if ok
                    else "启动检测失败"
                )
            self._redirect(page_url(tab="live", group=group, msg=msg))
            return

        if parsed.path == "/tiktok-monitor/run-audit":
            total = len(list_config_accounts(CONFIG_PATH))
            eta_min = max(1, int(total * 1.0 / 60) + 1)
            if is_job_running(ROOT, "audit"):
                msg = f"封号巡检正在运行中，约 {eta_min} 分钟完成，请稍后刷新"
            else:
                ok = run_worker_async("audit")
                msg = (
                    f"已启动封号巡检（共 {total} 个账号，约需 {eta_min} 分钟），完成后请刷新"
                    if ok
                    else "启动巡检失败"
                )
            self._redirect(page_url(tab="removed", group=group, msg=msg))
            return

        self.send_error(404)

    def _html(self, code: int, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()


def run_worker_async(command: str) -> bool:
    if not WORKER_PATH.exists():
        return False
    try:
        subprocess.Popen(
            [sys.executable, str(WORKER_PATH), command],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except OSError:
        return False


REASON_LABEL = {
    "banned": "被封禁",
    "not_found": "不存在/已注销",
    "unavailable": "不可用",
    "error": "检测失败",
}


def reason_label(code: str) -> str:
    return REASON_LABEL.get(str(code or ""), str(code or "-"))


PROBE_STATUS_LABELS = {
    "live": "确认直播",
    "offline": "确认离线",
    "unknown": "待确认",
}


def probe_status_html(row) -> str:
    status = str(row["last_probe_status"] or "pending")
    label = PROBE_STATUS_LABELS.get(status, "等待检测")
    error = str(row["last_probe_error"] or "").strip()
    detail = f"<div class='probe-error'>{esc(error[:160])}</div>" if error else ""
    return f"<span class='status status-{esc(status)}'>{esc(label)}</span>{detail}"


def session_row_html(row) -> str:
    live_url = f"https://www.tiktok.com/@{row['username']}/live"
    enter_now = row["last_enter_count"] if row["last_enter_count"] is not None else "-"
    delta = row["last_enter_delta"] if row["last_enter_delta"] is not None else "-"
    if isinstance(delta, int) and delta >= 0:
        delta_text = f"+{delta}" if delta > 0 else "0"
    else:
        delta_text = str(delta)
    return (
        "<tr>"
        f"<td><a href='{esc(live_url)}' target='_blank' rel='noopener'>@{esc(row['username'])}</a></td>"
        f"<td>{esc(row['title'] or '-')}</td>"
        f"<td>{esc(enter_now)}</td>"
        f"<td>{esc(delta_text)}</td>"
        f"<td>{esc(row['sample_count'])}</td>"
        f"<td>{esc(row['started_at'])}</td>"
        f"<td>{esc(row['ended_at'] or '-')}</td>"
        f"<td>{probe_status_html(row)}</td>"
        f"<td>{esc(row['last_probe_at'] or '-')}<div class='note'>{esc(row['last_probe_source'] or '-')}</div></td>"
        "</tr>"
    )


def render_group_tabs(*, tab: str, group: str) -> str:
    if tab not in TABS_WITH_GROUP:
        return ""
    parts = []
    for key in (GROUP_INTERCEPT, GROUP_OWN):
        active = "active" if group == key else ""
        href = page_url(tab=tab, group=key)
        parts.append(f"<a class='subtab {active}' href='{href}'>{esc(GROUP_LABELS[key])}</a>")
    return f"<div class='subtabs'>{''.join(parts)}</div>"


def render_page(*, tab: str, group: str = GROUP_INTERCEPT, message: str = "") -> str:
    ensure_runtime()
    tab = tab if tab in {"accounts", "live", "history", "removed"} else "live"
    group = parse_group(group)
    counts = stats(DB_PATH, group=group)
    budget = managed_budget_stats(DB_PATH)
    recheck = managed_recheck_overview(DB_PATH)
    total_accounts = stats(DB_PATH).get("account_count", counts["account_count"])
    group_label = GROUP_LABELS[group]

    accounts = list_db_accounts(DB_PATH, group=group)
    live_sessions = list_live_sessions(DB_PATH, status="live", group=group)
    history_sessions = list_live_sessions(DB_PATH, status="ended", group=group, limit=200)
    removed_rows_db = list_removed_accounts(DB_PATH, group=group, limit=200)

    account_rows = []
    for row in accounts:
        account_rows.append(
            "<tr>"
            f"<td>@{esc(row['username'])}</td>"
            f"<td>{esc(row['display_name'])}</td>"
            f"<td>{probe_status_html(row)}</td>"
            f"<td>{esc(row['last_probe_at'] or '-')}</td>"
            f"<td><a href='{esc(row['profile_url'])}' target='_blank' rel='noopener'>主页</a></td>"
            f"<td>{esc(row['updated_at'])}</td>"
            f"<td>"
            f"<form method='post' action='/tiktok-monitor/delete-account' "
            f"onsubmit=\"return confirm('确认删除 @{esc(row['username'])} ？');\">"
            f"<input type='hidden' name='username' value='{esc(row['username'])}'>"
            f"<input type='hidden' name='group' value='{esc(group)}'>"
            f"<button type='submit' class='danger'>删除</button>"
            f"</form>"
            f"</td>"
            "</tr>"
        )

    live_rows = [session_row_html(row) for row in live_sessions]
    history_rows = [session_row_html(row) for row in history_sessions]
    removed_rows = []
    for row in removed_rows_db:
        removed_rows.append(
            "<tr>"
            f"<td>@{esc(row['username'])}</td>"
            f"<td>{esc(row['display_name'] or '-')}</td>"
            f"<td>{esc(reason_label(row['reason']))}</td>"
            f"<td>{esc(row['status_code'] if row['status_code'] is not None else '-')}</td>"
            f"<td>{esc(row['detail'] or '-')}</td>"
            f"<td>{esc(row['removed_at'])}</td>"
            "</tr>"
        )

    msg_html = f"<div class='alert alert-success'><strong>✓</strong> {esc(message)}</div>" if message else ""
    active_probe = get_active_probe_run(DB_PATH)
    probe_running = is_job_running(ROOT, "probe") or active_probe is not None
    audit_running = is_job_running(ROOT, "audit") or audit_in_progress(DB_PATH)
    eta_min = max(1, int(total_accounts / 8 * 1.5 / 60) + 1)
    if probe_running and active_probe:
        checked = int(active_probe["accounts_checked"] or 0)
        progress = f"已检测 {checked}/{total_accounts} 个账号"
        if checked <= 0:
            progress = f"正在启动，共 {total_accounts} 个账号"
        probe_running_html = (
            f"<div class='alert alert-warning'><strong>⏳ 直播检测进行中</strong>"
            f" — {progress}，预计总耗时约 {eta_min} 分钟。"
            f" 页面每 15 秒自动刷新。</div>"
        )
    elif probe_running:
        probe_running_html = (
            f"<div class='alert alert-warning'><strong>⏳ 直播检测进行中</strong>"
            f" — 共 {total_accounts} 个账号，预计约 {eta_min} 分钟。</div>"
        )
    else:
        probe_running_html = ""
    refresh_ms = 15000 if probe_running or audit_running else 60000
    auto_refresh = f"<script>setTimeout(function(){{location.reload();}},{refresh_ms});</script>"
    probe_note = counts.get("last_probe_at") or "尚未执行"
    probe_live = counts.get("last_probe_live", 0)
    audit_note = counts.get("last_audit_at") or "尚未执行"
    audit_removed = counts.get("last_audit_removed", 0)
    group_tabs = render_group_tabs(tab=tab, group=group)

    def tab_href(name: str) -> str:
        return page_url(tab=name, group=group)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TikTok 直播监测</title>
  <style>
    :root {{
      --bg:#0b1020; --card:#121a2e; --line:#24304d; --text:#e8eefc; --muted:#8ea0c8;
      --accent:#3b82f6; --danger:#ef4444; --ok:#22c55e;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:"Segoe UI","PingFang SC",sans-serif; background:var(--bg); color:var(--text); }}
    .wrap {{ max-width:1100px; margin:0 auto; padding:24px; }}
    h1 {{ margin:0 0 8px; font-size:28px; }}
    .sub {{ color:var(--muted); margin-bottom:20px; }}
    .cards {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:20px; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; }}
    .card .n {{ font-size:28px; font-weight:700; }}
    .card .l {{ color:var(--muted); font-size:12px; margin-top:6px; }}
    .tabs {{ display:flex; gap:8px; margin-bottom:10px; flex-wrap:wrap; }}
    .tab {{ padding:10px 16px; border-radius:8px; border:1px solid var(--line); color:var(--muted); text-decoration:none; }}
    .tab.active {{ background:var(--accent); border-color:var(--accent); color:#fff; }}
    .subtabs {{ display:flex; gap:8px; margin-bottom:16px; flex-wrap:wrap; }}
    .subtab {{ padding:8px 14px; border-radius:999px; border:1px solid var(--line); color:var(--muted); text-decoration:none; font-size:13px; }}
    .subtab.active {{ background:rgba(59,130,246,.18); border-color:var(--accent); color:#fff; }}
    .panel {{ background:var(--card); border:1px solid var(--line); border-radius:12px; overflow:hidden; }}
    .panel h2 {{ margin:0; padding:16px 18px; border-bottom:1px solid var(--line); font-size:16px; }}
    .panel-body {{ padding:18px; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th, td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
    th {{ color:var(--muted); font-weight:600; }}
    table a {{ color:#fff; text-decoration:none; font-weight:500; }}
    table a:hover {{ color:var(--accent); text-decoration:underline; }}
    input, textarea {{ width:100%; padding:10px 12px; border-radius:8px; border:1px solid var(--line); background:#0a1224; color:var(--text); }}
    textarea {{ min-height:120px; }}
    .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
    button, .button {{ padding:10px 14px; border:none; border-radius:8px; background:var(--accent); color:#fff; cursor:pointer; font-size:14px; font-weight:600; }}
    button:disabled, .btn-running {{ background:#475569 !important; color:#e2e8f0 !important; cursor:not-allowed !important; }}
    .danger {{ background:var(--danger); }}
    .alert {{ margin-bottom:16px; padding:14px 16px; border-radius:10px; font-size:15px; line-height:1.5; border:2px solid transparent; }}
    .alert-success {{ background:#166534; border-color:#22c55e; color:#fff; }}
    .alert-warning {{ background:#9a3412; border-color:#fb923c; color:#fff; }}
    .msg {{ margin-bottom:16px; padding:12px 14px; border-radius:8px; background:rgba(59,130,246,.12); border:1px solid rgba(59,130,246,.35); }}
    .empty {{ color:var(--muted); padding:24px 0; text-align:center; }}
    .note {{ color:var(--muted); font-size:12px; line-height:1.6; }}
    .status {{ display:inline-block; padding:3px 8px; border-radius:999px; font-size:12px; font-weight:600; }}
    .status-live {{ background:rgba(34,197,94,.18); color:#86efac; }}
    .status-offline {{ background:rgba(100,116,139,.22); color:#cbd5e1; }}
    .status-unknown {{ background:rgba(239,68,68,.18); color:#fca5a5; }}
    .status-pending {{ background:rgba(59,130,246,.18); color:#93c5fd; }}
    .probe-error {{ color:#fca5a5; font-size:11px; margin-top:4px; max-width:300px; word-break:break-word; }}
    @media (max-width:800px) {{ .cards,.grid2 {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>TikTok 直播监测</h1>
    <p class="sub">直播检测仅在人工点击“立即检测全部账号”后执行 · 不自动检测 · 封号巡检每天 03:00 UTC<br>
    当前视图：{esc(group_label)} · 上次直播检测 {esc(probe_note)}（{probe_live} 个在播）· 上次封号巡检 {esc(audit_note)}（清理 {audit_removed} 个，累计记录 {counts.get('removed_total', 0)} 个）</p>
    {msg_html}
    {probe_running_html}
    <div class="cards">
      <div class="card"><div class="n">{counts['account_count']}</div><div class="l">监控账号（{esc(group_label)}）</div></div>
      <div class="card"><div class="n">{counts['live_now']}</div><div class="l">正在直播（{esc(group_label)}）</div></div>
      <div class="card"><div class="n">{counts['offline_count']}</div><div class="l">确认离线（{esc(group_label)}）</div></div>
      <div class="card"><div class="n">{counts['unknown_count']}</div><div class="l">待确认（{esc(group_label)}）</div></div>
      <div class="card"><div class="n">{counts['stale_count']}</div><div class="l">超过 3 分钟未确认</div></div>
      <div class="card"><div class="n">{counts['session_total']}</div><div class="l">历史场次（{esc(group_label)}）</div></div>
      <div class="card"><div class="n">{budget['used']}/{budget['limit']}</div><div class="l">今日 Apify 调用（UTC）</div></div>
      <div class="card"><div class="n">${budget['estimated_cost_usd']:.3f}</div><div class="l">今日预计费用（硬上限 ${budget['max_cost_usd']:.2f}）</div></div>
      <div class="card"><div class="n">{budget['remaining']}</div><div class="l">今日剩余付费额度</div></div>
      <div class="card"><div class="n">{recheck['interval_minutes']} 分钟</div><div class="l">Apify 再次付费复核的最短间隔</div></div>
    </div>
    <div class="tabs">
      <a class="tab {'active' if tab == 'live' else ''}" href="{tab_href('live')}">直播中</a>
      <a class="tab {'active' if tab == 'history' else ''}" href="{tab_href('history')}">历史记录</a>
      <a class="tab {'active' if tab == 'removed' else ''}" href="{tab_href('removed')}">清理记录</a>
      <a class="tab {'active' if tab == 'accounts' else ''}" href="{tab_href('accounts')}">账号管理</a>
    </div>
    {group_tabs}
    {render_accounts_tab(account_rows, group) if tab == 'accounts' else ''}
    {render_live_tab(live_rows, group, probe_running=probe_running) if tab == 'live' else ''}
    {render_history_tab(history_rows, group) if tab == 'history' else ''}
    {render_removed_tab(removed_rows, group, audit_running=audit_running) if tab == 'removed' else ''}
  </div>
  {auto_refresh}
</body>
</html>"""


def render_accounts_tab(rows: list[str], group: str) -> str:
    group_label = GROUP_LABELS[parse_group(group)]
    body = "".join(rows) if rows else f"<tr><td colspan='7' class='empty'>暂无{esc(group_label)}，请在下方添加</td></tr>"
    return f"""
    <div class="panel">
      <h2>{esc(group_label)} · 账号列表</h2>
      <div class="panel-body">
        <table>
          <thead><tr><th>用户名</th><th>备注</th><th>检测状态</th><th>最后检测</th><th>链接</th><th>更新时间</th><th>操作</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </div>
    <div class="grid2" style="margin-top:16px">
      <div class="panel">
        <h2>单个添加 · {esc(group_label)}</h2>
        <div class="panel-body">
          <form method="post" action="/tiktok-monitor/add-account">
            <input type="hidden" name="group" value="{esc(group)}">
            <p class="note">支持 @username 或 TikTok 主页链接，将归入「{esc(group_label)}」</p>
            <p><input name="account" placeholder="@username 或 https://www.tiktok.com/@username" required></p>
            <p><input name="name" placeholder="备注名（可选）"></p>
            <button type="submit">添加账号</button>
          </form>
        </div>
      </div>
      <div class="panel">
        <h2>批量添加 · {esc(group_label)}</h2>
        <div class="panel-body">
          <form method="post" action="/tiktok-monitor/add-accounts">
            <input type="hidden" name="group" value="{esc(group)}">
            <p class="note">一行一个账号，# 开头为注释，将归入「{esc(group_label)}」</p>
            <p><textarea name="accounts" placeholder="@user1&#10;https://www.tiktok.com/@user2"></textarea></p>
            <button type="submit">批量导入</button>
          </form>
        </div>
      </div>
    </div>"""


def render_live_tab(rows: list[str], group: str, *, probe_running: bool = False) -> str:
    group_label = GROUP_LABELS[parse_group(group)]
    disabled_attr = " disabled" if probe_running else ""
    btn_label = "⏳ 检测进行中…" if probe_running else "立即检测全部账号"
    btn_class = "btn-running" if probe_running else ""
    body = "".join(rows) if rows else (
        f"<tr><td colspan='9' class='empty'>当前无{esc(group_label)}在直播</td></tr>"
    )
    return f"""
    <div class="panel">
      <h2>{esc(group_label)} · 正在直播</h2>
      <div class="panel-body">
        <form method="post" action="/tiktok-monitor/run-probe" style="margin-bottom:14px">
          <input type="hidden" name="group" value="{esc(group)}">
          <button type="submit" class="{btn_class}"{disabled_attr}>{btn_label}</button>
          <span class="note" style="margin-left:10px">检测范围：全部账号 · 本页仅显示{esc(group_label)} · 只在点击按钮后执行，不自动检测</span>
        </form>
        <p class="note">{esc(hybrid_mode_note())} 冲突、超时、限流或预算耗尽统一显示“待确认”，不会误报为直播。每次点击执行一次完整检测；Apify 只复核连续强信号候选，并受最短复核间隔和每日预算限制。</p>
        <p class="note">累计进入 = 本场总进入人次（只增不减）；较上次增加 = 距上一次采样新增的人次。TikTok 未登录接口无法读取 App 内实时在线人数。</p>
        <table>
          <thead><tr><th>账号</th><th>标题</th><th>累计进入</th><th>较上次增加</th><th>采样次数</th><th>开播时间</th><th>结束时间</th><th>确认状态</th><th>最后确认/来源</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </div>"""


def render_history_tab(rows: list[str], group: str) -> str:
    group_label = GROUP_LABELS[parse_group(group)]
    body = "".join(rows) if rows else f"<tr><td colspan='9' class='empty'>暂无{esc(group_label)}直播历史</td></tr>"
    return f"""
    <div class="panel">
      <h2>{esc(group_label)} · 直播历史</h2>
      <div class="panel-body">
        <table>
          <thead><tr><th>账号</th><th>标题</th><th>累计进入</th><th>较上次增加</th><th>采样次数</th><th>开播</th><th>结束</th><th>最终状态</th><th>最后确认/来源</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </div>"""


def render_removed_tab(rows: list[str], group: str, *, audit_running: bool = False) -> str:
    group_label = GROUP_LABELS[parse_group(group)]
    disabled_attr = " disabled" if audit_running else ""
    btn_label = "⏳ 巡检进行中…" if audit_running else "立即执行封号巡检"
    btn_class = "btn-running" if audit_running else ""
    body = "".join(rows) if rows else f"<tr><td colspan='6' class='empty'>暂无{esc(group_label)}清理记录</td></tr>"
    return f"""
    <div class="panel">
      <h2>{esc(group_label)} · 封号 / 不可用账号清理记录</h2>
      <div class="panel-body">
        <form method="post" action="/tiktok-monitor/run-audit" style="margin-bottom:14px">
          <input type="hidden" name="group" value="{esc(group)}">
          <button type="submit" class="{btn_class}"{disabled_attr}>{btn_label}</button>
          <span class="note" style="margin-left:10px">巡检范围：全部账号 · 本页仅显示{esc(group_label)} · 自动任务每天 03:00</span>
        </form>
        <table>
          <thead><tr><th>用户名</th><th>备注</th><th>原因</th><th>状态码</th><th>说明</th><th>清理时间</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </div>"""


def main() -> None:
    ensure_runtime()
    server = ThreadingHTTPServer(("127.0.0.1", 8766), Handler)
    print("TikTok live monitor listening on http://127.0.0.1:8766/tiktok-monitor/")
    server.serve_forever()


if __name__ == "__main__":
    main()
