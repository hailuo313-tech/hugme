# D4-1 · Hybrid Memory Retrieval

## Why

D3-3 把"值得记住的"消息写入 `memories`，D3-4 把 embedding 填实。
D4-1 是"让 Aria 真的想起来"的那一步：给一段当前对话上下文，把这个用户最相关的
≤10 条 memories 返回出来，供 D4-2 的 prompt builder 注入到 system prompt 的
`L6_MEMORY` 层。

纯 vector 检索的两个老问题这套设计同时解决：
- **跨用户 / 跨 character 串味**：SQL `WHERE user_id = ... AND character_id ...` 硬过滤。
- **语义召回 + 时间衰减 / 重要度**：cosine `<=>` 拿候选，rerank 用加权综合分。

## API

`POST /api/v1/users/{user_id}/memories/retrieve`

```jsonc
{
  "query": "她女朋友最喜欢什么颜色？",   // 当前对话上下文/最后一句用户话
  "k": 10,                                 // 1..50；默认 10
  "k_candidates": 30,                      // 1..200；默认 30
  "memory_types": ["preference","goal"],   // 可选；ANY(:types)
  "min_importance": 0.0,                   // 默认 0；调 3.0 可过滤琐碎
  "character_id": null,                    // 提供则只回该角色+global
  "include_global": true
}
```

响应：

```jsonc
{
  "embedding_used": true,
  "fallback_reason": null,                 // "4xx:401" / "no_vector" / "sql:..." 等
  "candidates_scanned": 27,                // SQL 实际返回了 27 行
  "latency_ms": 312.4,
  "hits": [
    {
      "id": "uuid",
      "content": "用户的女朋友最喜欢蓝色",
      "memory_type": "preference",
      "importance_score": 8.0,
      "confidence_score": 0.92,
      "emotion_tags": ["calm"],
      "created_at": "2026-05-10T...",
      "last_used_at": null,
      "similarity": 0.871,                  // 1 - cosine_distance
      "final_score": 0.781                  // rerank 加权后
    }
  ]
}
```

## Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│ POST /memories/retrieve                                     │
│  1. services.embedder.embed([query])  ← 复用 D3-4 的模块    │
│     失败 → 降级到 importance 排序，结果仍非空                │
│  2. tag-filter SQL:                                         │
│       WHERE user_id, is_active, importance >= :min,         │
│             memory_type = ANY(:types),                      │
│             character_id rules                              │
│     ORDER BY embedding <=> :qvec  (cosine, asc)             │
│     LIMIT :k_candidates                                     │
│  3. Python rerank：                                         │
│       final = 0.55·sim + 0.25·(imp/10)                      │
│             + 0.15·recency(30d half-life) + 0.05·conf       │
│  4. sort desc → 截 k_final                                  │
│  5. asyncio.create_task: UPDATE memories.last_used_at=NOW() │
│     fire-and-forget；不阻塞响应                              │
└─────────────────────────────────────────────────────────────┘
```

## 关键设计决策

### 1. 复用 D3-4 的 embedder

`services.embedder.embed()` 已封装好 OpenAI `text-embedding-3-small`、超时重试、
4xx/5xx 区分。query 走同一条路保证向量空间一致（同模型嵌入），
也共用 `OPENAI_API_KEY` 一个 secret。

### 2. cosine `<=>` 而不是 L2 `<->`

text-embedding-3-small 输出已 L2-normalized，两者排序等价；
cosine 语义更直观，`similarity = 1 - distance ∈ [-1, 1]`，方便讲故事
（"sim=0.87 表示87%相似"虽然不严谨但易解释）。

### 3. tag filter 不靠索引也够用

memories 表当前**没有** IVFFLAT / HNSW 索引；几千行规模 seq scan + `<=>`
排序毫秒级完成。当 row count 突破 ~50k/用户、或多用户合查时再加：

```sql
CREATE INDEX memories_embedding_ivfflat
ON memories USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
ANALYZE memories;
```

留到 D8-2 性能调优阶段，不预先优化。

### 4. embed 失败必须降级，不能空

LLM 调 OpenAI 是网络操作，会偶发 5xx / 4xx / 超时；如果 D4-2 等着我们返回
"AI 该想起什么"，**返回空集会让 prompt 第 6 层退化为占位**，体验崩塌。
所以：

- 没向量 → SQL 改用 `importance DESC, created_at DESC` 取 top k；
- `embedding_used=False` + `fallback_reason="4xx:401"` 同时返回，
  调用方可决定是否再 retry / 告警。

### 5. rerank 权重不是写死真理

| 权重 | 来源 | 后续可调 |
|---|---|---|
| 0.55 · similarity | 语义相关性是首要 | A/B 时可推到 0.7 看是否更稳 |
| 0.25 · importance/10 | D3-3 LLM 评分 | 不同 character preset 可不同 |
| 0.15 · recency (30 天半衰) | 旧事实降权但不踢出 | 半衰期可由用户活跃度反推 |
| 0.05 · confidence | D3-3 自评信心 | 一般在 0.7–1.0，影响小 |

设计成模块顶部常量便于实验；将来可挂在 `characters.config` 或
`user_profiles.preferences` 上做个人化。

### 6. side-effect：异步 touch last_used_at

这条数据对未来的"哪些记忆该退役 / 哪些该 boost"很有用，但**绝不能**
阻塞 retrieve 的响应。`asyncio.create_task` fire-and-forget；
即使 UPDATE 失败也只 log warning。

## 失败模式 / 降级

| 场景 | 表现 | 自愈 |
|---|---|---|
| OpenAI key 失效 | `embedding_used=False`, importance 排序 fallback | 换 key 后自动恢复 |
| embedding_worker 还没追平积压 | 该用户 embedding IS NULL 的行被 WHERE 过滤掉 | worker 跑完后自动可见 |
| `query` 为空字符串 | 直接返回空 hits + `fallback_reason="empty_query"` | 调用方应避免 |
| memories 表全空 | hits=[], candidates_scanned=0 | N/A |
| pgvector 维度错配（schema vs 模型）| SQL 报错 → `fallback_reason="sql:..."` | 需 migrate schema |

## 性能预估

- query embedding：OpenAI text-embedding-3-small ≈ 100–250ms
- SQL `<=>` 排序 + LIMIT 30，行数 ≤10k：< 30ms
- Python rerank + 序列化：< 5ms
- **典型端到端 P50 ≈ 200ms，P95 ≈ 400ms**；超过 600ms 应告警

## Roll-out

1. 合并 PR + 部署
2. 服务器若尚未配 `OPENAI_API_KEY`，先配；否则该接口走 fallback 排序也能用
3. Smoke：
   ```bash
   TOKEN=$(...)  # operator JWT，参考 D5-2 章节
   USER_ID=$(... pick a real user with memories ...)
   curl -s -X POST "http://127.0.0.1:8000/api/v1/users/$USER_ID/memories/retrieve" \
     -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"query":"我喜欢什么音乐","k":5}' | python -m json.tool
   ```
   预期 `embedding_used=true`，hits[0].similarity > hits[-1].similarity。
4. roadmap D4-1 打勾。

## 下一步（D4-2）

`prompt_builder.py` 的 `L6_MEMORY` 层目前是占位。D4-2 会在 orchestrator 调用
prompt 之前，先调 retrieve，把 hits 按 `memory_type` 分组渲染进去：

```
## ===== L6_MEMORY =====
关于用户：
- [偏好] 爵士乐 / 蓝色
- [目标] 三个月内瘦 5kg
- [事实] 妹妹叫 Maya，10 岁
```

为了让 D4-2 干净，D4-1 的接口已经设计成**纯函数式 + 完整结构化返回**，
不需要 D4-2 再做额外查询。
