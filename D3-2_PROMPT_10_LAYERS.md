# D3-2 10-Layer Prompt Structure

**Owner**: Cursor AI
**Branch**: `feature/d3-2-prompt-10-layers`
**Status**: implementation ready (RUNBOOK 已更，roadmap 待部署后打勾)

## Goal

把 LLM Orchestrator 的 prompt 从"一行 system + history"升级成显式的 10 层结构，
为后续 D3-3（记忆写入）/ D3-4（embedding queue）/ D4-1（Hybrid Retrieval）/
D4-2（记忆注入）/ D4-3（loneliness_score 实时调节）提供注入位。

## 10 Layers

| 层 | 名称 | 数据源 | D3-2 是否填实 |
|----|------|--------|---------------|
| L1 | SAFETY              | 静态常量 | ✅ |
| L2 | IDENTITY            | 静态常量 | ✅ |
| L3 | CHARACTER           | `characters` | ✅ |
| L4 | RELATIONSHIP        | `user_profiles.relationship_stage` + `.vip_level` | ✅ |
| L5 | USER_PROFILE        | `chat_style / interests / forbidden_topics / preferences.nickname` | ✅ |
| L6 | MEMORY              | retrieved memories (D4-1) | 占位（接口已开） |
| L7 | CONVERSATION_STATE  | `user_profiles.loneliness_score` 分段 | ✅（数值由 D4-3 实时算） |
| L8 | RECENT_CONTEXT      | Redis `ctx:{conv_id}` | ✅（走 messages 数组，不在 system） |
| L9 | FORMAT              | character.tone / reply_length / emoji_frequency | ✅ |
| L10 | ANCHOR              | 静态常量（注意力末端锚） | ✅ |

每层在 system content 里有 `## ===== Lx_NAME =====` 标签，便于：

- 线上 `docker logs ... | grep` 排查"为什么 AI 没用上画像"
- 自检脚本 / 单测做存在性断言
- 后续把某层灰度替换（如 L6 接 D4-1）只需改一个函数

## Files

```
app/services/prompt_builder.py       # 新增：10 层骨架
app/services/llm_orchestrator.py     # 改造：用 build_prompt + 加 db 入参 + assembled 日志
app/api/telegram.py                  # 改：generate_reply 传 db
app/api/conversations.py             # 改：generate_reply 传 db
tests/test_prompt_builder.py         # 新增：每层 + 兼容性 21 条用例
tests/test_llm_orchestrator.py       # 增 3 条：标签存在 / db 注入 / db 异常降级
RUNBOOK.md                           # 新增 "D3-2" 章节 + smoke
D3-2_PROMPT_10_LAYERS.md             # 本文件
eris-roadmap.html                    # D3-2 done:true
```

## Back-compat

`llm_orchestrator.DEFAULT_SYSTEM_PROMPT` 现在 = `build_prompt(空入参).system_content`。
原 8 条单测断言形如 `messages[0].content == DEFAULT_SYSTEM_PROMPT` 仍成立。

## Failure Modes & Fallback

| 故障 | 行为 |
|------|------|
| `db=None` | 不查 DB，L3/L4/L5/L7/L9 走默认；10 层结构仍渲染 |
| DB 抛异常 | 吞掉，logger.warning `orchestrator.db.*_load_failed`，对应层走默认 |
| Redis 抛异常 | 沿用 D2-2.1 行为，history=[] |
| LLM 失败 | 沿用 D2-2 fallback 链路：`LLMOrchestratorError` 或 `echo:` |

## Logging Additions

- `orchestrator.prompt.assembled` 必发，字段：
  - `layers`: 10 层名（恒定）
  - `layers_with_data`: 实际非空的层列表
  - `system_chars` / `estimated_tokens`
  - `has_character` / `has_profile`
- `orchestrator.db.character_load_failed` / `.profile_load_failed`：DB 失败时

## Not in scope (留给后续 PR)

- **D3-3**：记忆写入管线（规则预过滤 + LLM 重要性评分），会让 L6 真的有内容写。
- **D3-4**：异步 embedding queue + memories.embedding 字段写入。
- **D4-1**：Hybrid Retrieval（tag → pgvector TopK=30 → Rerank Top10），填 L6。
- **D4-2**：把 retrieved memories 按 memory_type 分组渲染（替换 `_render_memory`）。
- **D4-3**：loneliness_score 真算（当前 L7 只读取 user_profiles 已有列）。
- 多语言 prompt_en / prompt_es / prompt_fr / prompt_de：当前忽略，全部按中文渲染。

## Test Plan

1. `pytest tests/test_prompt_builder.py -v` — 21 条全过
2. `pytest tests/test_llm_orchestrator.py -v` — 老 8 条 + 新 3 条全过
3. 服务器 smoke：参见 RUNBOOK 「LLM Orchestrator: 10 层 Prompt 结构 (D3-2)」节。
4. 真发一条 TG 消息后看日志：

```bash
docker logs --tail 200 eris-api | grep "prompt.assembled" | head -1 | jq .
```

应至少看到 `"layers_with_data":["L1_SAFETY","L2_IDENTITY","L3_CHARACTER",...]`。

## PR Merge Order

按 roadmap 7 步走：当前合并顺序第 4 步「Memory + Score」入口，已等齐 D1+D2 主干。
建议合并后 review tag：`d3-prompt-baseline`，方便 D3-3 起回滚锚点。
