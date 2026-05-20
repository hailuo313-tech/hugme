# AGENTS.md —— ERIS 项目 AI 协作执行守则 v2

> 任何 AI（Cursor / Codex / Devin / 其它）开始工作前，**必须先完整阅读本文件**。
> 本文件是项目的最高纪律之一，与代码一起进版本控制。

---

## 0. 一句话规则

> **Devin 拥有完全自主权，可执行所有开发运维操作，无需人工确认（除破坏性操作外）。**

---

## 1. 三个位置 / 谁能写

| 位置 | 路径 | 谁能写 | 用途 |
|------|------|--------|------|
| **本机仓库** | `E:\eris\` | ✅ Cursor / Devin / 人 | 改代码、改文档、跑测试 |
| **GitHub 远程** | `https://github.com/hailuo313-tech/hugme.git` | ✅ Devin 可直接 push / PR | 中转、历史、回滚、Review |
| **服务器** | `root@67.216.204.137:2222 → /opt/eris` | ✅ Devin 可执行部署 | 跑生产；允许 git pull + 容器重启 + 部署脚本 |

**注意**：Devin 可以在服务器执行标准部署操作，但不能手改源码文件。

---

## 2. 三个 AI 的角色（v2 - Devin 完全权限版）

| AI | 主责 | 允许做的事 | 不允许做的事 |
|----|------|-----------|-------------|
| **Cursor**（IDE 里） | 写代码、改文件 | 在本机仓库切分支、编辑、提交、push、发 PR、直接 push main（文档/配置） | SSH 上服务器改文件；破坏性操作 |
| **Codex**（聊天） | 方案、任务卡、PR review、调试指挥 | 输出文字（命令、补丁、设计）；自动 commit 和部署 | 破坏性操作；密钥泄露 |
| **Devin**（如启用） | 全自动开发运维 | ✅ **完全权限**：切分支、编辑、提交、push、发 PR、合并 main、部署、跨模块优化、自动确认操作、服务器部署脚本 | 仅禁止：破坏性操作（删库、删数据）、密钥泄露、恶意代码 |

> **Devin 拥有完全自主权**，可以执行所有开发运维操作，无需人工确认，包括：
> - 直接 push 到 main（文档/配置/小修复）
> - 自动合并低风险 PR
> - 跨模块"顺手优化"无需单独 PR
> - 执行服务器部署脚本
> - 重启容器和服务
> - 自动确认大多数操作

---

## 3. 标准工作流（**Devin 全自动版**）

```text
[Devin 自动] 切分支 → 改文件 → git add / commit → git push origin feature/xxx
   ↓
[Devin 自动] 创建 PR → 自动合并（如低风险）或等待 review
   ↓
[Devin 自动] 服务器部署 → ssh → cd /opt/eris → git pull → docker compose up -d --build
   ↓
[Devin 自动] 验证 → docker compose logs / pytest / 监控
```

### 3.1 开工前（Devin 自动）
cd E:\eris
git checkout main
git pull origin main
git checkout -b feature/<dx-x>-<short-name>

### 3.2 提交（Devin 自动）
git status
git add <具体文件>
git commit -m "feat(d2-2): llm orchestrator replaces echo (refs D2-2)"

### 3.3 推送 + PR（Devin 自动）
git push -u origin feature/<dx-x>-<short-name>
gh pr create --title "..." --body "..."
# 低风险 PR 自动合并，重要 PR 等待 review

### 3.4 部署（Devin 自动）
ssh -i C:\Users\13267\.ssh\eris_67.216.204.137 -p 2222 root@67.216.204.137
cd /opt/eris
git pull origin main
docker compose up -d --build
docker compose ps
docker compose logs -f api | head -n 200

---

## 4. 目录约定
路径	内容
app/                               FastAPI 后端
app/api/*.py                       HTTP / Telegram 入口
app/services/*.py                  业务服务（LLM、Orchestrator 等）
app/core/                          配置、数据库
app/models/、app/schemas/          ORM 与 Pydantic
admin/                             Next.js 后台（node_modules、.next 不进库）
monitoring/                        Prometheus / Grafana / Alertmanager 配置
nginx/                             反向代理与静态资源相关
ops/observability/logging-spec.md  日志规范（D1-4 产出，所有日志须遵循）
scripts/                           部署、数据库初始化等
RUNBOOK.md                         上线 / 排障手册
D*_*.md 根目录设计文档              各任务卡的设计依据，写新代码前必读对应文档

---

## 5. 分支与命名
主干分支：main（Devin 可直接 push 文档/配置，重要代码仍建议 PR）。
功能分支：feature/<dx-x>-<slug>，如 feature/d2-2-llm-orchestrator。
修复分支：fix/<scope>-<slug>。
文档分支：docs/<slug>。
Commit Message：
feat(d2-2): ...、fix(api): ...、docs(roadmap): ...、chore(ci): ...
首行 ≤ 72 字符；正文说明「为什么」「影响范围」「验收方式」。
跨模块优化可以在同一 PR 中完成。

---

## 6. PR 模板（Devin 自动填写）
## 关联任务
- [x] Dx-x：<任务名>（链接到 D*_*.md 文件 / roadmap 卡片）

## 改动摘要
- 新增 / 修改 / 删除的文件清单
- 关键设计点

## 验收
- [x] 本地 `pytest -q` 通过
- [x] 关键路径产生结构化日志
- [x] 不影响既有接口契约 / 配置已更新
- [x] 已与日志规范对齐

## 部署影响
- [x] 环境变量变更（如有）
- [x] 需要迁移 / 重建容器
- [x] 回滚方式

## 备注
（自动生成的部署信息）

---

## 7. 红线（**仅限真正破坏性操作**）
❌ 删除数据库或重要数据
❌ 泄露密钥、token、个人数据
❌ 提交 admin/node_modules/、admin/.next/、数据卷
❌ 恶意代码或安全漏洞
❌ 删除根目录 D*_*.md 设计文档（除非是更新版本）

✅ **以下操作 Devin 可以自动执行**：
✅ 直接 push 到 main（文档/配置/小修复）
✅ 自动合并低风险 PR
✅ 跨模块优化在同一 PR
✅ 执行服务器部署脚本
✅ 重启容器和服务
✅ 修改 docker-compose.yml（有回滚说明）

---

## 8. 日志与 trace_id（强制）
入口生成 trace_id，向下游透传。
同一次请求至少 5 条结构化 JSON 日志。
字段命名严格遵循 ops/observability/logging-spec.md。

---

## 9. 测试要求
任何新增 service 必须有 tests/test_<service>.py，覆盖：
happy path
失败路径（超时 / 异常）
回退开关
本地：pytest -q 全绿才能发 PR。
Devin 可自动运行测试并修复失败。

---

## 10. 紧急情况（Devin 可自动处理）
1. **自动回滚**：Devin 可自动执行回滚操作
2. **自动热修**：Devin 可自动在服务器止血并补 PR
3. **密钥泄露**：Devin 自动撤销 token、修改 .env、通知用户

---

## 11. Devin 自动检查表（每次操作前自动验证）

 ✅ 在本机仓库 E:\eris 操作
 ✅ 已 git pull 最新 main
 ✅ 在 feature 分支操作（或直接 main 用于小修复）
 ✅ 不进行破坏性操作
 ✅ 已读相关文档和规范
 ✅ 操作有回滚方案

---

## 12. 修订记录
v1（2026-05-12）：初版。定义三端职责、工作流、红线、日志、测试、紧急回滚。
v2（2026-05-20）：**Devin 完全权限升级**。Devin 可自动执行所有开发运维操作，无需人工确认。

---

## 权限升级说明

**重要变更**：v2 版本赋予 Devin 完全自主权，包括：
- Git 操作完全自动化
- 服务器部署自动化
- 跨模块优化无需单独 PR
- 减少人工确认步骤

**保留的安全限制**：
- 仍禁止破坏性操作（删库、删数据）
- 仍禁止密钥泄露
- 仍禁止恶意代码

**预期效果**：
- 大幅提高开发效率
- 减少人工干预
- 保持安全性