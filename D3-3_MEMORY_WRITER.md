# D3-3 Memory Writer Pipeline

**Owner**: Cursor AI
**Branch**: `feature/d3-3-memory-writer`
**Builds on**: D2-1 (OpenRouter client) + D3-1 (characters table) + D3-2 (prompt L6 placeholder)
**Unblocks**: D3-4 (embedding queue), D4-1 (Hybrid Retrieval), D4-2 (memory injection into L6)

## Goal

让 ERIS 真的开始"记得你"。每条用户消息走三阶段过滤后，把有价值的事实写入
`memories` 表，供 D4-1 之后做向量检索 + 注入 L6。

## Architecture

```
[telegram/webhook]            [POST /messages/inbound]
        │                              │
        ▼                              ▼
  persist user msg               persist user msg
  push Redis ctx                 push Redis ctx
        │                              │
        └──────────┬───────────────────┘
                   ▼
       asyncio.create_task(maybe_write_memory(...))
                   │  (fire-and-forget; user reply 不被阻塞)
                   ▼
   ┌──────────────────────────────────────────┐
   │  Phase 1 · Rule prefilter (sync, free)   │
   │    - len < 10                            │
   │    - acknowledgements 词库              │
   │    - emoji / 标点 only                   │
   │    - 24h dedup (Redis SET)               │
   └──────────────────────────────────────────┘
                   │ pass
                   ▼
   ┌──────────────────────────────────────────┐
   │  Phase 2 · LLM importance scoring        │
   │    - services.llm.chat(force_model=...)  │
   │    - JSON: {is_memory_worthy, type,      │
   │             content, importance, ...}    │
   │    - whitelist memory_type               │
   │    - importance >= threshold             │
   └──────────────────────────────────────────┘
                   │ pass
                   ▼
   ┌──────────────────────────────────────────┐
   │  Phase 3 · Persist                       │
   │    INSERT INTO memories (...)            │
   │    embedding = NULL  (D3-4 fills)        │
   │    source_message_id 用于回溯            │
   │    自带 AsyncSessionLocal (不复用请求    │
   │    session — 请求结束 session 已关闭)    │
   └──────────────────────────────────────────┘
                   │ ok
                   ▼
       Redis SADD dedup:mem:{user_id}  (TTL 24h)
```

## Why fire-and-forget

LLM 评分 + DB INSERT 同步加进用户回复路径会加 1~3s 延迟。背景任务保证：
- 用户感受不到差别（telegram 回 200 OK 之前不等记忆写完）
- 一条失败不影响下一条
- 失败完全静默：所有日志化，**绝不抛异常到上游**

## Why a new DB session

`get_db()` 是 FastAPI request-scoped，请求结束就 `session.close()`。
后台任务可能比请求活得长。复用会撞到 `Connection is closed`。
所以 `maybe_write_memory` 内部用 `AsyncSessionLocal()` 开自己的 session，
和请求生命周期解耦。

## Skipped paths

| 场景 | 跳过原因 | 阶段 |
|------|---------|------|
| MEMORY_WRITE_ENABLED=False | disabled_by_flag | flag check (在 prefilter 前) |
| Onboarding 进行中 | onboarding | flag check |
| 太短 (<10 字符) | too_short | Phase 1 |
| 寒暄 (ok/嗯/谢谢) | acknowledgement | Phase 1 |
| 全 emoji / 标点 | emoji_or_punct_only | Phase 1 |
| 24h 内重复 | duplicate_24h | Phase 1 |
| LLM 评 is_memory_worthy=false | below_threshold | Phase 2 |
| LLM 评 importance < 5 | below_threshold | Phase 2 |
| LLM 调用失败 / JSON 解析失败 | llm.failed | Phase 2 |

## Files

```
app/services/memory_writer.py            新增（约 410 行）
app/core/config.py                       +3 字段：MEMORY_WRITE_ENABLED /
                                                  LLM_MEMORY_MODEL /
                                                  MEMORY_IMPORTANCE_THRESHOLD
app/api/telegram.py                      +asyncio.create_task wire-in
app/api/messages.py                      +asyncio.create_task wire-in
tests/test_memory_writer.py              新增（13 条用例）
RUNBOOK.md                               +"Memory Writer (D3-3)" 章节
D3-3_MEMORY_WRITER.md                    本文件
```

## .env.example additions

```
MEMORY_WRITE_ENABLED=true
LLM_MEMORY_MODEL=openai/gpt-4o-mini
MEMORY_IMPORTANCE_THRESHOLD=5
```

## Test Plan

1. `pytest tests/test_memory_writer.py -v` — 13 条全过
2. Python 3.9 语法 sanity（吸取 #19 教训）:
   ```bash
   python -m py_compile app/services/memory_writer.py
   ```
3. 服务器 smoke：参见 RUNBOOK 「Memory Writer: 三阶段记忆写入 (D3-3)」节。
4. 真实链路（onboarding 完成的账号）：
   - 发 `"嗯"` → 日志应见 `prefilter_skip reason=too_short` / `acknowledgement`
   - 发 `"我从小在上海长大，家里有只叫橘子的猫"` → 应见
     `llm.scored importance=8 type=fact` → `persisted memory_id=...`
   - `psql ... SELECT FROM memories ORDER BY created_at DESC LIMIT 5` 看到记录

## Cost / Latency Profile

- 主对话路径：**0 ms 增量**（背景任务）
- 每条 user message：~1 次 gpt-4o-mini 调用（≈ $0.0001 / 条）
- Phase 1 通过率约 20–30%，所以平均成本 ≈ $0.00003 / 条
- 月活 1000 人 × 每天 20 条 → 月成本 ~$18

## Not in scope (留给下一 PR)

- **D3-4**：异步 embedding worker（消费 `memories.embedding IS NULL` 的行）
- **D4-1**：tag filter → pgvector TopK=30 → Rerank Top10（消费 memories 表）
- **D4-2**：把 retrieved memories 注入 L6（修改 prompt_builder._render_memory）
- **D4-3**：loneliness_score 实时计算（消费 memories.emotion_tags + 频次）
- 记忆"被遗忘"机制（importance 衰减 / is_active=false）：D8 性能阶段再做
