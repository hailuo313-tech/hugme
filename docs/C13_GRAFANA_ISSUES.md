# C-13 走查问题单

| ID | 优先级 | 问题 | 处理 | 状态 |
|----|--------|------|------|------|
| GR-01 | P1 | Grafana 大盘缺 LLM 面板 | 新增 LLM Request Rate / LLM p95 Latency | **已关闭** |
| GR-02 | P2 | 部分 `eris_*` 应用指标尚未在运行时导出 | 依赖指标埋点落地；告警规则已就绪 | **豁免** |
| GR-03 | P2 | Alertmanager Discord 需生产 `.env` 配置 | `DISCORD_WEBHOOK_URL` 仅服务器配置 | **豁免** |
| GR-04 | P2 | 监控栈默认未随主 compose 启动 | 按 `docker-compose.monitoring.yml` 按需启用 | **豁免** |
| GR-05 | P1 | 走查签字页待人工 | `C13_GRAFANA_WALKTHROUGH.md` | **待签字** |
