# level_engine 边界 case 清单（C-05 / P2-08）

实现：`app/services/level_engine.py`  
测试：`tests/test_level_engine.py`（**≥20 case**，见下表 ID）

| ID | 分类 | 输入要点 | 期望 |
|----|------|----------|------|
| BC-01 | geo | US | T1 |
| BC-02 | geo | us 小写 | T1 |
| BC-03 | geo | BR | T2 |
| BC-04 | geo | ZZ | T3 |
| BC-05 | geo | 空串 | unknown |
| BC-06 | geo | None | unknown |
| BC-07 | route | S | manual_premium |
| BC-08 | route | A | manual_premium |
| BC-09 | route | B | ai_assisted |
| BC-10 | route | C | ai_auto |
| BC-11 | route | D | ai_auto |
| BC-12 | probe | 画像不完整 + 高消费 | D |
| BC-13 | override | operator_assigned_s | S |
| BC-14 | spend | T1 + spend=500 | S |
| BC-15 | spend | T1 + spend=499.99 | A（非 S） |
| BC-16 | spend | spend=99 | A |
| BC-17 | spend | spend=98.99 + T2 | C |
| BC-18 | vip | vip_level=1 无消费 | A |
| BC-19 | tier | T1 + spend=0 | B |
| BC-20 | tier | country=None | C + unknown |
| BC-21 | tier | T3 (ZZ) | C |
| BC-22 | edge | 负消费 | 按 0 处理 → B@T1 |
| BC-23 | config | 加载 t1_countries / thresholds | 不抛错 |
| BC-24 | spend | T2 + spend=1000 | A（非 S，因非 T1） |
| BC-25 | invariant | 任意合法输入 | chat_route 合法 |

## 分支覆盖目标

- `calc_user_level` / `country_tier` / `level_to_chat_route`：**行覆盖 ≥90%，分支覆盖 ≥85%**（`scripts/check-level-engine.ps1` 门禁）

## 未纳入本阶段（P2-12 集成）

- 入站流水线实时调用
- `user_profiles.user_level` 列迁移
- 与 GeoIP 服务异步联调（仅单元测试注入 country_code）
