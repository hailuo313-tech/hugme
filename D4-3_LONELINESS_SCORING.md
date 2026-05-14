# D4-3：loneliness_score 实时更新

## 目标

在每次 AI 回复前，用近期 **结构化记忆** 上的 `emotion_tags`（D4-3）及 **当前用户句**
关键词命中（D4-4，无 LLM）更新 `user_profiles.loneliness_score`（0–100），使 **L7_CONVERSATION_STATE**
与情绪元数据更一致。D4-4 详见 **`D4-4_UTTERANCE_EMOTION.md`**。
分段逻辑不变，仍由 `prompt_builder._loneliness_band` 定义：

| 区间 | 标签 |
|------|------|
| &lt; 35 | low |
| 35–54.9 | mid |
| 55–74.9 | high |
| ≥ 75 | critical |

## 信号与窗口

| 项目 | 默认 | 说明 |
|------|------|------|
| 数据源 | `memories` | `is_active = true` |
| 当前句（D4-4） | `user_text` 关键词 | 无 LLM；开关 `LONELINESS_UTTERANCE_ENABLED` |
| 时间窗 | 30 天 | `LONELINESS_LOOKBACK_DAYS`（仅记忆） |
| 条数上限 | 40 | `LONELINESS_MEMORY_CAP`，按 `created_at` 新→旧 |
| 每条 tag 数 | ≤3 | 与 `memory_writer` 一致 |

## 标签权重（小写匹配）

**升高**：lonely +10，anxious +9，sad +8，angry +3  

**降低**：happy −8，calm −6，excited −4  

未列出的字符串标签 **忽略**（不推分）。

## 聚合与衰减

1. 对每条记忆：标签加权和 → clamp 到 **±`LONELINESS_PER_MEMORY_CLAMP`**（默认 12）。
2. 跨记忆求和 → clamp 到 **±`LONELINESS_GLOBAL_DELTA_CLAMP`**（默认 20），得到 `delta_tags`。
3. **若窗口内没有任何非空 `emotion_tag`，且 D4-4 未推断出当前句标签**：施加向 **`LONELINESS_BASELINE`**（默认 35，与 DB default 一致）的衰减：  
   `(baseline - old_score) * LONELINESS_DECAY_FACTOR`（默认 0.08）。
4. 若记忆侧存在非空 tag（即使全为未知标签）：**不**施加上述衰减（`delta_tags` 可能为 0）。
5. `new = clamp(0, 100, old + delta_tags + delta_utterance + decay)`（`delta_utterance` 为 D4-4，无当前句信号时为 0），保留两位小数。
6. 若 `|new - old| < LONELINESS_MIN_UPDATE_DELTA`（默认 0.05），跳过 `UPDATE`（减写放大）。

## 更新频率

在 `generate_reply(..., db=session)` 中、**加载 profile 之后**、**调用 `memory_retriever.retrieve`（D4-2）之前**、组装 prompt 之前执行；与 D4-2 同频（每条触发回复的用户消息最多一次）。无后台 cron。

**D4-4**：在同一次刷新中增加当前 `user_text` 关键词推断，详见 **`D4-4_UTTERANCE_EMOTION.md`**。

## 开关与环境变量

| 变量 | 默认 | 含义 |
|------|------|------|
| `LONELINESS_REFRESH_ENABLED` | true | 关则完全不跑 D4-3 |
| `LONELINESS_LOOKBACK_DAYS` | 30 | 回溯天数 |
| `LONELINESS_MEMORY_CAP` | 40 | 最多扫描记忆条数 |
| `LONELINESS_PER_MEMORY_CLAMP` | 12 | 单条记忆 tag 和 clamp |
| `LONELINESS_GLOBAL_DELTA_CLAMP` | 20 | 全局 tag delta clamp |
| `LONELINESS_DECAY_FACTOR` | 0.08 | 无 tag 时向 baseline 拉回比例 |
| `LONELINESS_BASELINE` | 35 | 衰减目标，与 schema default 对齐 |
| `LONELINESS_UTTERANCE_ENABLED` | true | D4-4：是否启用当前句关键词 |
| `LONELINESS_UTTERANCE_MAX_DELTA` | 10 | D4-4：当前句对分数的最大绝对贡献 |

## 实现位置

- `app/services/loneliness_updater.py` — 查询、纯函数计算、`UPDATE user_profiles`
- `app/services/llm_orchestrator.py` — 编排调用与日志字段 `loneliness_score`

## 日志

- `loneliness.refresh.ok` — 成功写库（含 old/new、`delta_tags`、`delta_utterance`、`utterance_tags`、
`had_utterance_signal`、decay、扫描条数）
- `loneliness.refresh.skip_unchanged` — 变化低于阈值
- `loneliness.sql.fetch_failed` / `loneliness.sql.update_failed` — 降级不抛

## 后续可做

- 按 `importance_score` 或向量相似度加权记忆（当前每条等权）。
- 用小型分类模型 / NLU 替换关键词表，仍输出同一套标准 `emotion_tags` 再并入。
