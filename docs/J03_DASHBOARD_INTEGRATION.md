# J-03 看板联调检验（C-10）

**目标：** 坐席看板（Admin 会话列表 + 详情 + Handoff + WebSocket）满足 **3s 接管** 产品 SLA。  
**实现：** `admin/app/page.tsx`、`app/api/admin.py`、`app/api/handoff.py`、`app/api/realtime.py`

---

## 3s 接管定义

| 阶段 | 预算 | 说明 |
|------|------|------|
| 任务可见 | ≤ 2s | WS `task.snapshot` / `task.upsert`（轮询 1s + 网络） |
| 坐席点击接管 | ≤ 3s | `POST /api/v1/handoff/{id}/lock` 端到端（含 DB） |
| **合计 SLA** | **3s** | 从任务出现在看板到 `HUMAN_LOCKED` |

录屏验收：WAITING_OPERATOR 会话出现在列表首屏 → 打开详情 → Lock → 状态变 `HUMAN_LOCKED`，墙钟 **< 3s**。

---

## API 联调清单

| ID | 步骤 | 端点 / 行为 | 通过 |
|----|------|-------------|------|
| J03-01 | Admin 登录 | `POST /api/v1/admin/login` → JWT | ☐ |
| J03-02 | 会话列表 | `GET /api/v1/admin/conversations` | ☐ |
| J03-03 | 待接管置顶 | `WAITING_OPERATOR` + 高 VIP/S 在前 | ☐ |
| J03-04 | 会话详情 | `GET /admin/conversations/{id}` + 消息 | ☐ |
| J03-05 | AI 辅助 | `POST /ops-ai/.../assist` | ☐ |
| J03-06 | 接管锁 | `POST /handoff/{id}/lock` | ☐ |
| J03-07 | 坐席回复 | `POST /handoff/{id}/reply` | ☐ |
| J03-08 | WS 任务流 | `wss://.../ws/operators/tasks` | ☐ |
| J03-09 | 3s 接管 | 录屏计时 < 3s | ☑ |
| J03-10 | 归档 | 录屏 + 签字页存档 | ☑ |

签字页：[`C10_DASHBOARD_CHECKLIST_SIGNOFF.md`](C10_DASHBOARD_CHECKLIST_SIGNOFF.md)

---

## 列表排序（后端）

`admin_list_conversations` 使用：

1. `WAITING_OPERATOR` → `HUMAN_LOCKED` → 其它  
2. `vip_level` 降序（S/A 代理）  
3. `last_message_at` 降序  

纯函数单测：`sort_conversations_for_dashboard()` + `fixtures/j03_dashboard_smoke.json`

---

## 门禁

```powershell
.\scripts\check-j03-dashboard-smoke.ps1
```

---

## 非阻塞遗留

- [ ] Admin 页内嵌 WebSocket 客户端（当前需独立联调 WS）
- [ ] `users.user_level` 列入库后替换 VIP 代理排序
- [ ] C-11 UI/UX 走查（断线提示、弹窗）
