# D8：memories 性能索引（D8-1 / D8-2）

## D8-1 — B-tree / 部分索引

**目的**：加速非向量或向量路径上的 **筛选 + 排序** 前缀，与当前代码一致。

| 索引名 | 定义要点 | 主要受益查询 |
|--------|-----------|----------------|
| `idx_memories_user_active_created_at` | `(user_id, created_at DESC) WHERE is_active` | `loneliness_updater` 按用户 + 时间窗拉 `emotion_tags` |
| `idx_memories_user_active_importance_created` | `(user_id, importance_score DESC, created_at DESC) WHERE is_active` | `memory_retriever` 无向量时的 `ORDER BY importance_score DESC, created_at DESC` |

**交付**：已写入 `scripts/init.sql`（新库）；存量库用 `scripts/migrations/d8-1_memories_btree_indexes.sql`（`CONCURRENTLY`）。

## D8-2 — IVFFLAT（cosine）

**目的**：加速 `ORDER BY embedding <=> query_vector`（D4-1 hybrid retrieval）。

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS memories_embedding_ivfflat
    ON memories USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

**何时建**

- 已有一定量 **非空** `embedding` 行后再建，IVFFLAT 才有稳定收益；行数极少时顺序扫描也可能更快。
- 调整 `lists`：常见经验 `lists ≈ sqrt(行数)` 作起点，结合 `EXPLAIN (ANALYZE)` 与延迟再调。

**交付**：`scripts/migrations/d8-2_memories_embedding_ivfflat.sql`（勿与事务块一起执行）。

## 运维注意

- `CREATE INDEX CONCURRENTLY` 在 PostgreSQL 中 **不能** 包在普通多语句事务里；用 `psql -f` 单文件或 autocommit 连接执行。
- 每次大变更后执行 `ANALYZE memories;`。
