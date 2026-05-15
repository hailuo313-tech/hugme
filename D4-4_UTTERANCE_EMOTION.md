# D4-4：当前用户句情绪（关键词）并入孤独度

## 目标

在 D4-3 的「记忆 `emotion_tags`」之外，增加 **本条 `user_text`** 的轻量信号，使
`loneliness_score` 对当下情绪更敏感。**不调用 LLM**，仅用可维护的关键词子串表（中英）。

## 行为

| 项目 | 说明 |
|------|------|
| 入口 | `loneliness_updater.infer_utterance_emotion_tags(user_text)` |
| 标签集合 | 与 memory_writer / D4-3 一致：`lonely` `sad` `anxious` `angry` `happy` `calm` `excited` |
| 命中规则 | 子串匹配；纯 ASCII 关键词大小写不敏感；按预定义表顺序扫描，**最多 3 个不同标签** |
| 权重 | 与 `_TAG_WEIGHTS` 相同 |
| 并入方式 | `delta_utterance = sum(weights)` 后单独 clamp 到 **±`LONELINESS_UTTERANCE_MAX_DELTA`**（默认 10），再与 `delta_tags`、衰减相加 |
| 衰减 | 与 D4-3 相同：仅当 **既无**记忆侧非空 tag、**又无**推断出的当前句标签时，才向 `LONELINESS_BASELINE` 衰减 |

## 开关

| 环境变量 | 默认 | 含义 |
|----------|------|------|
| `LONELINESS_UTTERANCE_ENABLED` | true | 关闭则仅保留 D4-3 记忆路径 |
| `LONELINESS_UTTERANCE_MAX_DELTA` | 10 | 当前句对分数的最大绝对贡献 |

## 实现

- `app/services/loneliness_updater.py` — `infer_utterance_emotion_tags`、`compute_next_loneliness` 的 `utterance_tags` / `delta_utterance`、`refresh_loneliness_score(..., user_text=...)`
- `app/services/llm_orchestrator.py` — 调用刷新时传入 `user_text`

## 日志

`loneliness.refresh.ok` / `skip_unchanged` 的 meta 中含 `utterance_tags`、`delta_utterance`、`had_utterance_signal`（**不**记录完整用户原文，避免日志敏感内容）。

编排层 `orchestrator.prompt.assembled` 另带 `loneliness_utterance_tags`（与刷新内推断一致，便于 grep）。

## 局限与后续

- 关键词会有误报 / 漏报；后续可换 **小型分类模型** 或上游 NLU，仍通过同一 `utterance_tags` 接口并入。
- 未做分词；中文依赖子串，扩展词表时避免过短词根。

## Score worker（D4-4 剩余：initiation + trigger_threshold）

- **模块**：`app/services/profile_score_worker.py`（计算 + DB 写回）、`app/services/profile_score_scheduler.py`（APScheduler）。
- **开关**：`SCORE_WORKER_ENABLED`（默认 `false`）、`SCORE_WORKER_POLL_SECONDS` 等见 `app/core/config.py`。
- **initiation_score**：近 `SCORE_INITIATION_LOOKBACK_DAYS` 天 `sender_type='user'` 消息数 / `SCORE_INITIATION_CAP_MESSAGES` 饱和到 0–100。
- **trigger_threshold**：min-only 聚合 + 与 `LONELINESS_BASELINE` 对齐的 pivot 线性式；冷启动 `loneliness≈35` 且其余未建模为 0 时与 `init.sql` 默认 **65** 一致。
