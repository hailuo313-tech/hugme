# D3-4 · Async Embedding Worker

## Why

D3-3 已经把"值得记住的"用户消息写入 `memories` 表，但 `embedding vector(1536)`
字段还是 `NULL`，下一步 D4-1 检索阶段无法用 pgvector 做语义召回。

把 embedding 计算放在用户回复的同步链路上会再叠加 0.3–0.8s LLM 调用，
显著拖慢"用户发消息 → 看到回复"的体感。所以单独做一个 **异步 backfill worker**，
和主请求路径解耦。

## What

- 新建 `app/services/embedder.py`：封装 OpenAI `/v1/embeddings` 调用，
  默认 `text-embedding-3-small`（1536 维，与表定义对齐）。
- 新建 `app/services/embedding_worker.py`：APScheduler IntervalTrigger 每 30s
  扫一次 `memories WHERE embedding IS NULL`，批量调 embedder，写回。
- `app/main.py` lifespan 启动 / 关闭 worker scheduler（沿用 `silent_reactivation_scheduler` 的范式）。
- 新增配置：
    - `EMBEDDING_WORKER_ENABLED`（默认 `true`）
    - `OPENAI_API_KEY`（必填；没填 worker 自动 disable）
    - `EMBEDDING_MODEL` = `text-embedding-3-small`
    - `EMBEDDING_BATCH_SIZE` = 32
    - `EMBEDDING_POLL_SECONDS` = 30
- 16 个新单测（embedder 8 + worker 8），全部 stub HTTP + DB，零外部依赖。

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI lifespan (single AsyncIOScheduler per worker process)  │
│                                                                 │
│   start_embedding_worker()                                      │
│        │                                                        │
│        ▼                                                        │
│   IntervalTrigger every EMBEDDING_POLL_SECONDS (default 30s)    │
│        │                                                        │
│        ▼                                                        │
│   run_one_tick():                                               │
│     1. pg_try_advisory_lock(6_300_410)  ← 跨进程/跨 pod 互斥    │
│     2. SELECT id, content FROM memories                         │
│        WHERE is_active = true AND embedding IS NULL             │
│        ORDER BY created_at ASC                                  │
│        LIMIT batch_size                                         │
│        FOR UPDATE SKIP LOCKED          ← 行级互斥               │
│     3. embedder.embed(contents)        ← 一次 HTTP，N 条        │
│     4. UPDATE memories                                          │
│        SET embedding = CAST(:vec AS vector), updated_at = NOW() │
│        WHERE id = :id AND embedding IS NULL   (双重幂等)        │
│     5. pg_advisory_unlock + commit                              │
└─────────────────────────────────────────────────────────────────┘
```

## 关键设计决策

### 1. 直连 OpenAI，不复用 OpenRouter

OpenRouter 当前对 `/embeddings` 路由的兼容性不稳定（部分模型 404 / 未列入路由）。
单独配 `OPENAI_API_KEY` 比和 OpenRouter chat 路由的稳定性绑死要安全得多。
代价：多一个 secret；但它只在 D3-4 + D4-1 两处使用，可控。

### 2. APScheduler 而不是后台协程

- 已经引入 `apscheduler==3.10.4`（D6-3 silent_reactivation 在用），不增加依赖。
- IntervalTrigger 自带 `coalesce` / `max_instances=1`，避免任务堆积。
- 集成 FastAPI lifespan，重启时自动 graceful shutdown。

### 3. pg_advisory_lock + `FOR UPDATE SKIP LOCKED` 双保险

- **advisory lock**：保证同一时刻只有一个 tick 在跑（多 worker 进程 / 多 pod）。
- **SKIP LOCKED**：即使 advisory lock 失效（assertion bug 等），行级锁也能保证
  同一行不会被两个 UPDATE 同时改。
- UPDATE 条件里再加 `AND embedding IS NULL`，做最后一层幂等。

### 4. pgvector 写回用字符串字面量

`'[1.0, 2.0, ...]'::vector` 是 pgvector 接受的标准格式。
不引入 `pgvector.sqlalchemy` 适配器是因为项目目前用 asyncpg + 裸 SQL，
保持一致性。`_vector_literal()` 用 `:.7f` 精度，避免科学计数被 pgvector 解析失败。

### 5. embed 失败 ≠ 行失败

embedder 4xx / 5xx → 整批跳过，下个 tick 重试。memories 行本身在 D3-3 已经入库，
不受 embedding 失败影响。这意味着：

- LLM key 临时过期 → 失败积压；切回好 key 后 5–30 分钟内自动追平。
- 模型切换（换 1536 维以外的模型）→ 需要先迁移 schema，否则 UPDATE 会报错。

### 6. 启动短路

- `EMBEDDING_WORKER_ENABLED=False` → no-op（演示 / 离线开发）。
- `OPENAI_API_KEY` 缺失 → no-op + warning log（用户回复仍照常，只是没法做语义检索）。

## 失败模式 / 降级

| 场景                          | 影响                            | 自愈?                  |
|-------------------------------|---------------------------------|------------------------|
| OpenAI key 失效               | 行积压；user 体感无影响         | 是，换 key 后自动追平 |
| OpenAI 5xx 持续               | 同上                            | 是                     |
| schema 维度不匹配             | UPDATE 报错；tick stats.error 非空 | 否，需 schema 迁移   |
| Postgres advisory lock 竞争   | 部分 tick skip                  | 是                     |
| 单条 content 超 8191 token    | 整批 4xx（极少见）              | 需要应用层切片         |

## Roll-out

1. 合并 PR → 部署
2. 服务器 `.env` 添加 `OPENAI_API_KEY=sk-...`（找 OpenAI 控制台拿）
3. `docker compose up -d --build api`
4. 30s 后看日志：`embedding_worker.scheduler.started` + `embedding_worker.tick.*`
5. 验证：
   ```sql
   SELECT COUNT(*) AS total,
          COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS embedded
   FROM memories WHERE is_active = true;
   ```
   `embedded` 应在数十秒内追平 `total`。
6. roadmap D3-4 打勾。
