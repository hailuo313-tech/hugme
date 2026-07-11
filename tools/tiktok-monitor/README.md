# TikTok 直播监测（精简版）

旧版「作品播放量 / 粉丝数 / 2144 作品抓取」已全部清理归档。  
当前版本只保留：

1. **账号添加 / 删除**（`config.json` + SQLite 同步）
2. **直播监测数据表**（`live_sessions` / `live_viewer_samples`）
3. **Web 面板**（`/tiktok-monitor/`）

## 直播判定与人工触发

- 不运行自动直播检测或自动直播采样。
- 运营人员进入“直播中”页面，点击“立即检测全部账号”后才执行一次全量检测，默认 8 路有限并发。
- `tiktok-live-probe.timer` 与 `tiktok-live-sample.timer` 必须保持 disabled；每日封号巡检可继续自动运行。
- SIGI 只作为候选信号，必须再由 Webcast 接口或实际视频流返回可播放数据确认。
- 启用专业 LIVE API 后，仅把本地强信号候选提交给付费 API；两边必须同为直播才显示“确认直播”，避免对全部账号产生高额调用费。
- 两个来源冲突、HTTP 超时、限流或无法解析均记为 `unknown`（待确认），不会显示在“直播中”，也不会结束直播场次。
- 明确连续 2 次离线后才结束场次。
- 临时网络错误自动重试 1 次，并使用短指数退避。
- Apify 每日硬限额 700 个结果：600 个用于直播复核、100 个用于新候选和结束确认，最高估算费用 `$2.80/天`。
- 新账号候选必须连续两次出现本地强直播信号；已确认直播的 Apify 复核间隔最少 15 分钟，并按同时直播数自动延长。
- 每次人工检测仍受 Apify 每日预算和最短复核间隔约束；额度耗尽后只显示“待确认”。

账号表保存最后检测时间、检测来源、状态与错误；面板会分别显示确认直播、确认离线、待确认和数据过期数量。

### 专业 LIVE API

在 `config.json` 的 `live_api` 中启用，密钥建议只通过服务环境变量提供：

```bash
TIKTOK_LIVE_API_ENABLED=true
TIKTOK_LIVE_API_KEY=replace-me
```

`provider=apify` 时默认使用
`unseenuser/tiktok-live-status-scraper` 的同步批量 Actor，只提交本地已验证的直播候选，
`TIKTOK_LIVE_API_ENDPOINT` 可留空。

其他供应商可另外设置 `TIKTOK_LIVE_API_ENDPOINT`。自定义批量端点接收
`POST {"usernames":["account"]}`，响应可为
`{"data":[{"username":"account","is_live":true,"room_id":"..."}]}`。
也支持包含 `{username}` 的单账号 GET 端点。可通过 `auth_header` 和
`auth_scheme` 适配供应商鉴权；密钥不要提交到仓库。

## 目录

| 文件 | 说明 |
|------|------|
| `web_app.py` | Web 服务（8766） |
| `accounts_store.py` | 账号 CRUD |
| `live_db.py` | 直播 SQLite 表结构 |
| `config.json` | 账号列表（服务器） |
| `data/tiktok_live.sqlite` | 直播数据库 |

## 本地

```powershell
cd E:\eris\tools\tiktok-monitor
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy config.example.json config.json
python web_app.py
```

## 服务器

- 路径：`/opt/eris-TIKTOK`
- 服务：`systemctl restart tiktok-monitor`
- 清理归档：`archive/pre-live-cleanup-*`

## 已删除（归档）

- `monitor.py`（1600 行作品抓取）
- `tiktok_metrics.sqlite`、`*metrics*.csv`
- 7 日粉丝/作品/播放量页面
- 手动 poll 日志
