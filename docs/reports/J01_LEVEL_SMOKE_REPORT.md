# J-01 分级冒烟报告

**生成时间：** 2026-05-20（C-06 交付）  
**结果：** 10/10 fixture 通过  
**脚本：** `scripts/j01_level_smoke.py`  
**夹具：** `fixtures/j01_level_smoke.json`

## 汇总

| 结果 | 数量 |
|------|------|
| PASS | 10 |
| FAIL | 0 |

## 明细

| ID | 场景 | 结果 | level | chat_route | reason |
|----|------|------|-------|------------|--------|
| J01-01 | 画像不完整 — 探测 D 级 | PASS | D | ai_auto | profile_incomplete_probe |
| J01-02 | T1 高消费 — S 级 | PASS | S | manual_premium | t1_high_spend |
| J01-03 | T1 达 A 门槛消费 | PASS | A | manual_premium | spend_or_vip_a |
| J01-04 | T1 零消费完整画像 — B 级 | PASS | B | ai_assisted | t1_default_b |
| J01-05 | T2 国家默认 — C 级 | PASS | C | ai_auto | tier_default_t2 |
| J01-06 | T3 国家默认 — C 级 | PASS | C | ai_auto | tier_default_t3 |
| J01-07 | VIP 达标 — A 级 | PASS | A | manual_premium | spend_or_vip_a |
| J01-08 | 坐席指定 — S 级 | PASS | S | manual_premium | operator_assigned_s |
| J01-09 | 未知国家 — C 级 | PASS | C | ai_auto | tier_default_unknown |
| J01-10 | T2 高消费不升 S — A 级 | PASS | A | manual_premium | spend_or_vip_a |

## 结论

**10/10 通过** — 可进入 C-06 关口验收与 AI 主链路并行准备。
