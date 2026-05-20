# C-11 坐席看板 UI/UX 走查

**任务：** C-11 — 优先级、弹窗、断线提示  
**页面：** https://hugme2.com/admin  

---

## 走查项（8/8）

| ID | 验证步骤 | 期望 |
|----|----------|------|
| C11-01 | 登录后看列表「等级」列 | S/A/B/C 彩色徽章 |
| C11-02 | 点击「待接管」 | 筛选 `WAITING_OPERATOR`，行琥珀色高亮 |
| C11-03 | 看右上角任务流状态 | 绿点「已连接」 |
| C11-04 | 断网或停 WS 服务 | 显示「已断开」+ 重连按钮 |
| C11-05 | 详情里填草稿后点 ✕ 或遮罩 | 浏览器确认框 |
| C11-06 | 模拟 API 失败 | 红色条 + 重试 |
| C11-07 | AI 辅助失败 | 重试链接（原有） |
| C11-08 | 打开/关闭详情抽屉 | 遮罩点击可关 |

---

## 部署后验证

```bash
cd /opt/eris/admin && npm ci && npm run build
pkill -f next-server
PORT=3000 nohup npm start >> /var/log/eris-admin.log 2>&1 &
```

浏览器 **Ctrl+Shift+R** 强刷。

---

## 问题单

见 [`C11_UX_ISSUES.md`](C11_UX_ISSUES.md) — 全部 **已关闭/豁免**。
