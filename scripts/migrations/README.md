# 一次性 SQL 迁移（D8 性能）

在 **已有生产/预发库** 上执行；新库若全量跑 `scripts/init.sql`，已含 **D8-1**  btree 索引，无需再跑 `d8-1`（重复执行也安全）。

## 执行方式

使用 **autocommit** 会话（`psql` 默认单条语句即提交即可）。**不要**把含 `CREATE INDEX CONCURRENTLY` 的脚本包在显式 `BEGIN … COMMIT` 里。

```bash
# 例：在 API 容器外对 Postgres 执行
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/migrations/d8-1_memories_btree_indexes.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/migrations/d8-2_memories_embedding_ivfflat.sql
```

Docker 示例见 `RUNBOOK.md`「D8：memories 索引」节。

## 顺序

1. **D8-1** — B-tree / 部分索引，冷启动成本低，可随时加。  
2. **D8-2** — `embedding` 上 IVFFLAT（cosine）。建议在 **embedding 已批量回填**、行数较多后再建；`lists` 需按体量调优（见 `docs/D8_PERFORMANCE_INDEXES.md`）。
