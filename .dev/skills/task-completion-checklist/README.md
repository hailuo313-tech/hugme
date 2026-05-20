# Task Completion Checklist Skill

## 概述

这个技能确保所有 AI（Cursor、Codex、Devin）在完成任务后都按照统一的标准流程执行，保证项目的一致性和可追溯性。

## 使用方法

### 方式 1：直接阅读文档（当前推荐）

**注意**：由于当前环境技能系统的限制，`skill invoke` 命令暂时无法识别自定义技能。

AI 可以直接阅读以下文档获取标准流程：

- **技能定义**：`.dev/skills/task-completion-checklist/SKILL.md`
- **使用说明**：本文档
- **原始检查清单**：`.dev/task_completion_checklist.md`

### 方式 2：手动调用（未来支持）

当技能系统完全支持自定义技能后，可以通过以下方式调用：

```bash
skill invoke task-completion-checklist
```

### 方式 3：使用自动化脚本

对于重复性任务，可以使用提供的自动化脚本：

```bash
# 使用方法
./.dev/skills/task-completion-checklist/post-task.sh <task-id> <pr-title>

# 示例
./.dev/skills/task-completion-checklist/post-task.sh "P2-11" "feat(p2-11): implement USER_UPGRADED WebSocket push"
```

## 标准流程

### 1. 创建 PR、合并 PR、删除分支
- 推送 feature 分支到远程
- 使用 `gh pr create` 创建 PR
- 使用 `gh pr merge --merge --delete-branch` 合并
- 切换回 main 分支并更新
- 删除本地 feature 分支

### 2. 标记任务完成
- 在 `docs/product/business-flow.html` 中为任务添加 `baseline:true`

### 3. 本地更新和同步
- 确保在 main 分支
- 拉取最新代码
- 清理未提交的更改

## 检查清单

每次任务完成后，确认以下项：

- [ ] PR 已创建并成功合并
- [ ] 远程 feature 分支已自动删除
- [ ] 本地 feature 分支已删除
- [ ] 任务列表中已添加 `baseline:true`
- [ ] 本地 main 分支已更新
- [ ] 工作目录干净

## 文件结构

```
.dev/skills/task-completion-checklist/
├── SKILL.md           # 技能定义文件
├── README.md          # 使用说明
└── post-task.sh       # 自动化脚本
```

## AI 集成

### 当前状态（重要）
由于技能系统限制，当前所有 AI 都需要通过**直接阅读文档**的方式使用此检查清单。

### Cursor
- 在 IDE 中可以看到技能文件
- 可以手动执行脚本
- 建议在开始任务前阅读 `.dev/skills/task-completion-checklist/SKILL.md`

### Codex
- 可以通过文件读取工具查看技能内容
- 可以调用自动化脚本
- 建议在任务开始前请求读取相关文档

### Devin
- 可以读取技能文档内容
- 可以执行自动化脚本
- 建议在每次任务开始前自动读取并遵循检查清单

### 未来改进
当技能系统支持自定义技能后，所有 AI 都可以通过 `skill invoke` 命令自动调用此检查清单。

## 历史记录

任务完成历史记录在 `.dev/task_completion_checklist.md` 文件中，每次完成任务后需要更新。

## 故障排除

### GitHub CLI 认证失败
```bash
gh auth login -h github.com
```

### 脚本执行权限
```bash
chmod +x .dev/skills/task-completion-checklist/post-task.sh
```

### 分支冲突
参考 SKILL.md 中的常见问题处理部分

## 维护

- 定期更新历史记录
- 根据项目需要调整流程
- 保持文档的准确性
- 收集反馈并改进

## 版本

- v1.1 (2026-05-19): 更新版本
- 添加技能系统限制说明
- 提供文档阅读作为主要使用方式
- 保留自动化脚本支持
- v1.0 (2026-05-19): 初始版本
- 包含基本的三步流程
- 提供自动化脚本
- 尝试集成到项目技能系统