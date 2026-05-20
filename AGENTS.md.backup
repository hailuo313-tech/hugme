# AGENTS.md —— ERIS 项目 AI 协作执行守则 v1

> 任何 AI（Cursor / Codex / Devin / 其它）开始工作前，**必须先完整阅读本文件**。
> 本文件是项目的最高纪律之一，与代码一起进版本控制。

---

## 0. 一句话规则

> **所有代码修改都在「本机仓库」里发生；GitHub 只是中转；服务器只用来 `git pull` 和重启容器，禁止在服务器上手改源码。**

---

## 1. 三个位置 / 谁能写

| 位置 | 路径 | 谁能写 | 用途 |
|------|------|--------|------|
| **本机仓库** | `E:\eris\` | ✅ Cursor / Devin / 人 | 改代码、改文档、跑测试 |
| **GitHub 远程** | `https://github.com/hailuo313-tech/hugme.git` | ⚠️ 仅通过 `git push` / PR | 中转、历史、回滚、Review |
| **服务器** | `root@67.216.204.137:2222 → /opt/eris` | ❌ 任何 AI 都**禁止直接编辑文件** | 跑生产；只允许 `git pull` + 容器重启 |

**违反这条 = 项目最严重的错误**。原因：服务器手改 → 下次 `git pull` 冲突 / 覆盖 → 线上和仓库不一致 → 排障时无法用 git 历史复现。

---

## 2. 三个 AI 的角色

| AI | 主责 | 允许做的事 | 不允许做的事 |
|----|------|-----------|-------------|
| **Cursor**（IDE 里） | 写代码、改文件 | 在本机仓库切分支、编辑、提交、push、发 PR | 直接 push 到 `main`（必须走 PR）；SSH 上服务器改文件 |
| **Codex**（聊天） | 方案、任务卡、PR review、调试指挥 | 输出文字（命令、补丁、设计） | 在用户没确认前直接帮其它 AI commit；改服务器 |
| **Devin**（如启用） | 中长任务、跑测试、出 PR | 在本机仓库或自己的工作区开 feature 分支、push、发 PR | 直接合并 `main`；改服务器；越权改未指派的模块 |

> 任何 AI 都**只针对当前任务卡涉及的文件**做修改；与任务无关的“顺手优化”一律单独 PR。

---

## 3. 标准工作流（**唯一允许的循环**）

```text
[本机] 切分支 → 改文件 → git add / commit → git push origin feature/xxx
   ↓
[GitHub] PR → 人 / Codex review → 合并到 main
   ↓
[服务器] ssh → cd /opt/eris → git pull origin main → docker compose up -d --build
   ↓
[验证] docker compose logs / pytest / 监控

3.1 开工前（每次都要做）
cd E:\eris
git checkout main
git pull origin main
git checkout -b feature/<dx-x>-<short-name>

3.2 提交
git status
git add <具体文件，不要 git add .  除非确认全是任务相关>
git commit -m "feat(d2-2): llm orchestrator replaces echo (refs D2-2)"

3.3 推送 + 发 PR
git push -u origin feature/<dx-x>-<short-name>
到 GitHub 网页发 PR，标题与首行 commit 一致，正文按 §6 模板。

3.4 部署（由人执行，不让 AI 自动登服务器）
ssh -i C:\Users\13267\.ssh\eris_67.216.204.137 -p 2222 root@67.216.204.137
cd /opt/eris
git pull origin main
docker compose up -d --build
docker compose ps
docker compose logs -f api | head -n 200

4. 目录约定

> **C-01 验收**：以 `docs/REPO_LAYOUT.md` 为准。原计划 `gateway/ws/worker/dashboard` 四目录 **不采用**；能力映射见该文档「对应原计划名称」列。

| 路径 | 内容 |
|------|------|
| `app/` | FastAPI 后端（含 HTTP、Telegram、WebSocket、进程内 Worker） |
| `app/api/*.py` | 路由入口（含 `realtime.py` WebSocket） |
| `app/services/*.py` | 业务服务（LLM、embedding_worker 等） |
| `app/core/` | 配置、数据库 |
| `app/models/`、`app/schemas/` | ORM 与 Pydantic |
| `admin/` | Next.js 运营看板（= 原计划 dashboard） |
| `docker-compose.yml` | api + postgres + redis |
| `monitoring/` | Prometheus / Grafana / Alertmanager |
| `ops/observability/logging-spec.md` | 日志规范 |
| `scripts/` | 部署、迁移、E2E |
| `docs/REPO_LAYOUT.md` | 仓库目录约定（C-01） |
| `docs/PR_GATES_D8.md` | PR 合并门禁说明（C-02） |
| `pyproject.toml` | Ruff + Mypy 配置（C-02） |
| `.github/workflows/pr-required-gates.yml` | CI：lint / 类型检查 / 测试 |
| `RUNBOOK.md` | 上线 / 排障 |
| `D*_*.md`（根目录） | 各阶段设计文档 |

5. 分支与命名
主干分支：main（只能通过 PR 合并，不允许直接 push）。
功能分支：feature/<dx-x>-<slug>，如 feature/d2-2-llm-orchestrator。
修复分支：fix/<scope>-<slug>。
文档分支：docs/<slug>。
Commit Message：
feat(d2-2): ...、fix(api): ...、docs(roadmap): ...、chore(ci): ...
首行 ≤ 72 字符；正文说明「为什么」「影响范围」「验收方式」。
同一 PR 不混合无关改动。

6. PR 模板（请按此填写）
## 关联任务
- [ ] Dx-x：<任务名>（链接到 D*_*.md 文件 / roadmap 卡片）

## 改动摘要
- 新增 / 修改 / 删除的文件清单（≤ 10 行）
- 关键设计点（1–3 条）

## 验收
- [ ] 本地 `pytest -q` 通过
- [ ] 关键路径产生 ≥ 5 条同 `trace_id` 的结构化日志（如适用）
- [ ] 不影响既有接口契约 / 数据库迁移已写 / 配置项已更新 `.env.example`
- [ ] 已与 `ops/observability/logging-spec.md` 对齐

## 部署影响
- [ ] 是否需新增环境变量？默认值是什么？
- [ ] 是否需运行迁移 / 重建容器？
- [ ] 回滚方式：`git revert <sha>` 后 `git pull` 即可，是 / 否

## 备注
（必要时附截图 / 日志片段）

7. 红线（任何 AI 都不许跨越）
❌ SSH 上服务器后用 vim、nano、sed -i 等修改源码。
❌ 在服务器执行 git commit / git push（服务器只 pull）。
❌ 直接 push 到 main（除非是 typo / docs 且经过人同意）。
❌ 把 .env、密钥、token、个人数据写进 commit。
❌ 提交 admin/node_modules/、admin/.next/、数据卷、转储文件。
❌ 重写本任务以外的模块（即使代码丑也先记 TODO，单独 PR）。
❌ 删除根目录 D*_*.md 设计文档（它们是验收依据）。
❌ 在没有 LLM_ECHO_FALLBACK 等开关的情况下，去掉关键回退逻辑。
❌ 改 docker-compose.yml 的端口 / volume 时不在 PR 中说明回滚方式。
❌ 假装某条 roadmap 已 done 而不交付代码与测试。

8. 日志与 trace_id（强制）
入口（Telegram / HTTP）生成 trace_id（UUID v4 短串即可），向下游所有调用 透传。
同一次请求至少 5 条结构化 JSON 日志： ingress.received → orchestrator.dispatch → llm.request.start → llm.request.success|failure → ingress.replied
字段命名严格遵循 ops/observability/logging-spec.md。

9. 测试要求
任何新增 service 必须有 tests/test_<service>.py，覆盖：
happy path
一种失败路径（超时 / 异常）
回退开关（如 LLM_ECHO_FALLBACK=1）
本地：pytest -q 全绿才能发 PR。
服务器上若有 e2e smoke，PR 描述里写手动验证步骤。

10. 紧急情况（仅在生产已坏的前提下）
1.回滚优先：服务器执行
cd /opt/eris
git log --oneline -n 5
git checkout <上一个稳定 sha>
docker compose up -d --build
事后立刻在仓库发一个 revert PR，让 main 回到稳定点；不要把服务器留在「游离 HEAD」状态过夜。
2.临时热修：若必须在服务器改一行止血，改完 10 分钟内：
在本机把同样改动落到 feature 分支、push、merge；
服务器 git pull 覆盖临时改动；
在 PR 里注明「先服务器止血、再补 PR」。
3.密钥泄露：立刻在 GitHub 撤销对应 token；改 .env（仍不进库）；通知人。

11. 新 AI 上工的 30 秒检查表

 我在 本机仓库 C:\Users\13267\Desktop\产品\eris\ 里改文件，对吗？

 我已经 git pull 了 main，对吗？

 我已经切到 feature/... 分支，对吗？

 我没有打开任何 SSH 会话编辑服务器文件，对吗？

 我读过对应任务的 D*_*.md 文档与 ops/observability/logging-spec.md，对吗？
四个「对」都满足，再开始写代码。

12. 修订记录
v1（2026-05-12）：初版。定义三端职责、工作流、红线、日志、测试、紧急回滚。

---

## 怎么提交它（你来做，命令贴下面）

```powershell
cd E:\eris
# 把上面整段 Markdown 保存为 AGENTS.md（用记事本 / VSCode / Cursor 都行）
git checkout main
git pull origin main
git add AGENTS.md
git commit -m "docs(agents): add execution rules for Cursor/Codex/Devin"
git push origin main
服务器同步（只是为了让仓库一致，服务器不需要读它来运行）：
ssh -i C:\Users\13267\.ssh\eris_67.216.204.137 -p 2222 root@67.216.204.137
cd /opt/eris
git pull origin main
ls AGENTS.md
exit
