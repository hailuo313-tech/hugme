# C-14 全量上线前代码审查 + 架构一致性终检

**任务：** C-14 — 全量上线前代码审查 + 架构一致性终检  
**验收：** 终检报告无阻塞项  
**基线：** [`docs/REPO_LAYOUT.md`](REPO_LAYOUT.md)、[`AGENTS.md`](../AGENTS.md)

---

## 1. 审查范围

| 维度 | 内容 |
|------|------|
| 架构 | ERIS MVP 目录约定；禁止 `gateway/` `ws/` `worker/` `dashboard/` 顶层目录 |
| CI | `pr-required-gates.yml` 三 job；`nightly-e2e-ci.yml` + C-12 稳定 3 天 |
| Cursor 交付 | C-01～C-13 检验报告 / 契约 / 门禁脚本 |
| 监控 | C-13：14 告警 + Grafana MVP 11 面板 |
| 部署边界 | 源码仅 Git；生产 `/opt/eris` 非 git 克隆（见 RUNBOOK） |

---

## 2. 门禁命令

```powershell
.\scripts\check-c14-prelaunch-final.ps1
```

```bash
bash scripts/check-c14-prelaunch-final.sh
```

---

## 3. 人工终检（生产）

| # | 项 | 结果 |
|---|-----|------|
| 1 | `https://hugme2.com/health/detail` 200 | ☐ |
| 2 | Admin `/admin` 登录 + WS | ☐ |
| 3 | Nightly E2E 最近 run 绿 | ☐ |
| 4 | `business-flow.html` 与 main 同步（scp） | ☐ |
| 5 | 问题单 PL-01 部署计划确认 | ☐ |

---

## 4. 签字

| 角色 | 姓名 | 日期 |
|------|------|------|
| 终检 | | |
| 运维 | | |

**结论：** ☐ 通过　☐ 不通过
