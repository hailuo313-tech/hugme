# C-10 看板联调检验清单（签字页）

**任务：** C-10 — J-03 看板联调（3s 接管）  
**录屏文件：** _（填写路径或链接）_  
**检验日期：** _2026-05-__  
**检验人：** _________________  

---

## 自动门禁（CI / 本地）

- [ ] `.\scripts\check-j03-dashboard-smoke.ps1` 通过

---

## 人工联调（须录屏）

| # | 项 | 结果 | 备注 |
|---|-----|------|------|
| 1 | 登录 Admin，列表加载 | ☐ PASS ☐ FAIL | |
| 2 | 筛选 `WAITING_OPERATOR` | ☐ PASS ☐ FAIL | |
| 3 | 待接管行在首屏可见（≤2s） | ☐ PASS ☐ FAIL | |
| 4 | 打开会话详情 + 消息历史 | ☐ PASS ☐ FAIL | |
| 5 | Ops AI 辅助生成回复 | ☐ PASS ☐ FAIL | |
| 6 | Handoff Lock → `HUMAN_LOCKED` | ☐ PASS ☐ FAIL | |
| 7 | Handoff Reply 发出 | ☐ PASS ☐ FAIL | |
| 8 | WS 收到 `task.upsert` / `user.upgraded` | ☐ PASS ☐ FAIL | |
| 9 | **墙钟接管 < 3s**（录屏打点） | ☐ PASS ☐ FAIL | |
| 10 | 录屏已归档 | ☐ PASS ☐ FAIL | |

---

## 签字

| 角色 | 姓名 | 日期 |
|------|------|------|
| 检验（Cursor/QA） | | |
| 产品确认 | | |

**结论：** ☐ 通过进入 C-11 / W9 关口　☐ 不通过（问题单：____）
