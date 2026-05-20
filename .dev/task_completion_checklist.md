# 任务完成标准流程

> **重要提醒**：每次完成任何任务后，必须严格按照以下流程执行，不得跳过任何步骤。

---

## 任务完成后必须执行的三个步骤

### 1. 创建 PR、合并 PR、删除分支

```bash
# 1.1 确保当前在 feature 分支上
git status  # 确认在正确的 feature 分支

# 1.2 推送分支到远程
git push -u origin <feature-branch-name>

# 1.3 创建 PR（使用 gh cli）
gh pr create --title "<commit-message>" --body "<PR-description>"

# 1.4 合并 PR（自动删除远程分支）
gh pr merge --merge --delete-branch

# 1.5 切换回 main 分支并更新
git checkout main
git pull origin main

# 1.6 删除本地 feature 分支
git branch -d <feature-branch-name>
```

**注意事项**：
- PR 标题应该与 commit message 保持一致
- PR 描述应该包含：关联任务、改动摘要、验收标准、部署影响、备注
- 确保合并前代码已通过所有检查
- 如果遇到认证问题，先执行 `gh auth login`

---

### 2. 在任务列表页标记任务完成

**文件位置**：`docs/product/business-flow.html`

**操作步骤**：
1. 找到对应的任务（例如 P2-11）
2. 在任务对象中添加 `baseline:true` 属性
3. 示例：
   ```javascript
   { id:"P2-11", phase:"02", owner:"devin", w:1, week:"W4", dep:"P1-07,P2-09", desc:"USER_UPGRADED WebSocket 推送", acc:"看板收到升级事件", baseline:true },
   ```

**注意事项**：
- 只有任务真正完成并合并后才添加 `baseline:true`
- 不要为未完成的任务添加此标记
- 保持文件格式的一致性

---

### 3. 本地更新和同步

```bash
# 3.1 确保在 main 分支
git checkout main

# 3.2 拉取最新代码
git pull origin main

# 3.3 检查状态
git status

# 3.4 清理未提交的更改（如果有）
git restore <files>  # 或 git stash
```

**注意事项**：
- 确保本地 main 分支与远程保持同步
- 清理所有未提交的更改
- 确认工作目录干净

---

## 执行检查清单

每次任务完成后，按顺序检查：

- [ ] PR 已创建并成功合并
- [ ] 远程 feature 分支已自动删除
- [ ] 本地 feature 分支已删除
- [ ] `docs/product/business-flow.html` 中任务已添加 `baseline:true`
- [ ] 本地 main 分支已更新到最新
- [ ] 工作目录干净，无未提交更改

---

## 常见问题处理

### GitHub CLI 认证失败
```bash
gh auth login -h github.com
# 然后在浏览器中完成授权
```

### 分支冲突
```bash
# 如果遇到 "no history in common" 错误
git checkout main
git pull origin main
git checkout -b feature/<new-branch-name>
# 然后 cherry-pick 相关提交
```

### 文件格式问题
```bash
# 如果遇到 CRLF/LF 行尾符问题
git config core.autocrlf true
git restore <files>
```

---

## 记录历史

| 任务编号 | 完成日期 | PR编号 | 分支名称 | 状态 |
|---------|---------|--------|----------|------|
| P2-11 | 2026-05-19 | #116 | feature/p2-11-user-upgrade | ✅ 完成 |
| 基础设施 | 2026-05-19 | #117 | feature/add-task-checklist | ✅ 完成 |
| 基础设施 | 2026-05-19 | #118 | feature/update-task-history | ✅ 完成 |
| 技能系统 | 2026-05-19 | #119 | feature/add-task-checklist-skill | ✅ 完成 |
| 文档更新 | 2026-05-19 | #120 | feature/update-skill-readme | ✅ 完成 |