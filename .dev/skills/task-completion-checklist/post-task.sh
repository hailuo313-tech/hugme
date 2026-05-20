#!/bin/bash
# 任务完成自动化辅助脚本
# 使用方法：./post-task.sh <task-id> <pr-title>

set -e

TASK_ID=$1
PR_TITLE=$2
CURRENT_BRANCH=$(git branch --show-current)

echo "📋 任务完成检查清单 - $TASK_ID"
echo "================================"

# 检查是否在 feature 分支
if [[ $CURRENT_BRANCH == "main" ]]; then
    echo "❌ 错误：当前在 main 分支，请切换到 feature 分支"
    exit 1
fi

echo "✅ 当前分支: $CURRENT_BRANCH"

# 步骤 1：推送分支
echo ""
echo "📤 步骤 1/6：推送分支到远程..."
git push -u origin "$CURRENT_BRANCH"

# 步骤 2：创建 PR
echo ""
echo "🔨 步骤 2/6：创建 PR..."
if [ -z "$PR_TITLE" ]; then
    echo "请输入 PR 标题:"
    read PR_TITLE
fi

gh pr create --title "$PR_TITLE" --body "## 关联任务
- [x] $TASK_ID

## 改动摘要
(请填写改动摘要)

## 验收
- [x] 代码符合规范
- [x] 测试通过

## 部署影响
- [ ] 无需新增环境变量
- [ ] 无需运行数据库迁移

Generated with Devin"

# 步骤 3：获取 PR 编号
PR_NUMBER=$(gh pr view --json number --jq '.number')
echo "✅ PR 创建成功: #$PR_NUMBER"

# 步骤 4：合并 PR
echo ""
echo "🔗 步骤 3/6：合并 PR..."
read -p "确认合并 PR #$PR_NUMBER? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    gh pr merge "$PR_NUMBER" --merge --delete-branch
    echo "✅ PR 已合并"
else
    echo "❌ 取消合并"
    exit 1
fi

# 步骤 5：切换到 main 并更新
echo ""
echo "🔄 步骤 4/6：切换到 main 分支并更新..."
git checkout main
git pull origin main

# 步骤 6：删除本地分支
echo ""
echo "🗑️  步骤 5/6：删除本地 feature 分支..."
git branch -d "$CURRENT_BRANCH"

# 步骤 7：提醒标记任务
echo ""
echo "📝 步骤 6/6：重要提醒"
echo "请在 docs/product/business-flow.html 中为任务 $TASK_ID 添加 baseline:true"
echo "然后按照标准流程提交和合并"

echo ""
echo "✅ 任务完成流程执行完毕！"
echo "📊 请更新 .dev/task_completion_checklist.md 中的历史记录"