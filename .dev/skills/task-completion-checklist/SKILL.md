# Task Completion Checklist Skill

确保所有 AI 在完成任务后都按照标准流程执行，保证项目的一致性和可追溯性。

## 触发时机

- **自动触发**：每次开始任何任务前自动执行
- **手动触发**：可通过 `skill invoke task-completion-checklist` 手动调用

## 功能

1. **任务前提醒**：提醒 AI 任务完成后的标准流程
2. **任务检查清单**：提供详细的完成步骤
3. **自动执行辅助**：提供标准化命令和脚本
4. **历史记录**：维护任务完成历史

## 任务完成标准流程

### 步骤 1：创建 PR、合并 PR、删除分支

```bash
# 1.1 确保当前在 feature 分支上
git status

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

### 步骤 2：在任务列表页标记任务完成

**文件位置**：`docs/product/business-flow.html`

**操作**：在对应任务中添加 `baseline:true` 属性

```javascript
// 示例
{ id:"P2-11", phase:"02", owner:"devin", w:1, week:"W4", dep:"P1-07,P2-09", desc:"USER_UPGRADED WebSocket 推送", acc:"看板收到升级事件", baseline:true },
```

### 步骤 3：本地更新和同步

```bash
# 3.1 确保在 main 分支
git checkout main

# 3.2 拉取最新代码
git pull origin main

# 3.3 检查状态
git status

# 3.4 清理未提交的更改
git restore <files>  # 或 git stash
```

## 执行检查清单

每次任务完成后，按顺序确认：

- [ ] PR 已创建并成功合并
- [ ] 远程 feature 分支已自动删除
- [ ] 本地 feature 分支已删除
- [ ] `docs/product/business-flow.html` 中任务已添加 `baseline:true`
- [ ] 本地 main 分支已更新到最新
- [ ] 工作目录干净，无未提交更改

## 常见问题处理

### GitHub CLI 认证失败
```bash
gh auth login -h github.com
```

### 分支冲突
```bash
git checkout main
git pull origin main
git checkout -b feature/<new-branch-name>
# 然后 cherry-pick 相关提交
```

### 文件格式问题
```bash
git config core.autocrlf true
git restore <files>
```

## 历史记录

任务完成历史记录在 `.dev/task_completion_checklist.md` 文件中。

## AI 使用指南

### 开始任务前
1. 自动执行此技能获取提醒
2. 了解任务完成后的标准流程
3. 按照流程执行任务

### 完成任务后
1. 严格按照三个步骤执行
2. 更新历史记录
3. 确保所有检查项都已完成

## 注意事项

- 不得跳过任何步骤
- 遇到问题及时记录在历史中
- 保持文档的更新
- 确保分支命名规范