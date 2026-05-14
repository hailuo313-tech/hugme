# D8 — Admin `basePath` 登录态与 401 跳转修复（PR 素材）

> 用途：发 PR 时复制 **标题 / 正文 / 验收**；合并后按 **部署** 一节上生产。  
> 关联：`D8-DEV-01`（运营后台体验）；对齐 `RUNBOOK.md` 公网域名 `https://hugme2.com` 与 `admin` 的 `basePath=/admin`。

---

## 建议分支名

`fix/d8-admin-basepath-auth-redirect`

---

## 建议 commit message（首行 ≤72 字符）

```
fix(admin): basePath login redirect and auth edge cases (D8)
```

**正文（可选）：**

- 401 时 `window.location` 从 `/login` 改为 `/admin/login`，避免跳到无路由白屏。
- 登录页：仅当 token 与 `eris_admin_operator` 同时存在才进首页；否则 `clearAuth()`。
- 首页：无 operator 时显示加载/跳转提示，避免 `return null` 白屏；token 无 operator 时清态回登录。

---

## PR 标题（GitHub）

**`fix(admin): basePath login redirect and auth edge cases (D8)`**

---

## PR 正文（复制到 GitHub）

### 关联任务

- [x] D8-DEV-01：运营后台体验与缺陷收敛（basePath / 401 / localStorage 边界）

### `git add` 建议范围（勿 `git add .` 除非确认无杂项）

- `admin/lib/auth.ts`
- `admin/app/login/page.tsx`
- `admin/app/page.tsx`
- `docs/D8_PR_ADMIN_BASEPATH.md`（本说明，便于评审与部署对照）

### 改动摘要

- `admin/lib/auth.ts`：增加 `ADMIN_BASE_PATH` / `LOGIN_PATH`；`apiFetch` 401 时跳转 `LOGIN_PATH`。
- `admin/app/login/page.tsx`：`isLoggedIn` 且 `getOperator()` 才 `router.replace("/")`；否则 `clearAuth()`。
- `admin/app/page.tsx`：挂载时校验 operator；缺失则清 auth；无 operator 时用加载文案替代空白渲染。

### 验收

- [ ] 本机 `cd admin && npm run build` 通过（Next 14）。
- [ ] 本机 `cd app && pytest -q` 通过（后端与 admin 无直接耦合，回归防回归）。
- [ ] 浏览器：`https://hugme2.com/admin/login` — 无 token 可见登录表单；过期 token 触发 401 后回到 `/admin/login` 而非全白。
- [ ] 浏览器：仅 `eris_admin_token`、无 `eris_admin_operator` 时不长期白屏，能回到可登录状态。

### 部署影响

- [ ] **需**在服务器 `cd /opt/eris && git pull` 后执行：`cd admin && npm ci && npm run build && pm2 restart eris-admin`（与 RUNBOOK「前端静态 + pm2」一致）。
- [ ] 无新增服务端环境变量；无 DB 迁移。
- [ ] 回滚：`git revert` 该合并提交后重新 `npm run build` + `pm2 restart eris-admin`。

### 备注

- 与 `AGENTS.md` 一致：**不在生产服务器用 `sed` 长期补丁**；以本 PR 为唯一真源。

---

## 维护者本地验证命令（发 PR 前在本机执行并填结果）

在仓库根目录 `C:\Users\13267\Desktop\产品\eris`：

```powershell
cd app
pytest -q
```

```powershell
cd ..\admin
npm run build
```

将终端中的 **通过/失败摘要** 贴在 PR 描述「验收」下作为评论即可。

---

## 与 RUNBOOK 的对应关系

| 主题 | RUNBOOK 位置 | 说明 |
|------|----------------|------|
| 公网健康检查 | `curl -i https://hugme2.com/health` | 与 admin 无关，发版后顺手执行。 |
| Admin 登录 smoke | `POST http://127.0.0.1:8000/api/v1/admin/login`（服务器本机） | 验 API；本 PR 修的是 **浏览器端** 跳转与壳子。 |
| 部署 | `admin/` 构建 + `pm2 restart eris-admin` | 见上「部署影响」。 |

---

## 与 Devin / Codex 任务卡的关系

| 任务卡 | 本 PR 覆盖情况 |
|--------|----------------|
| **D8-DEV-01** | 本 PR 实现其核心 **basePath / 401 / 半登录态** 部分；Devin 可继续在 **UI/接管流程** 上叠 PR。 |
| **D8-DEV-02** | 不覆盖；运营 Preflight 文档仍由 Devin 单独 PR。 |
| **D8-CODEX-01 / 02 / 03** | 不冲突；Codex 文档类任务可并行。 |
