# Script Match 全链路钩子（8 hooks）

| Hook | 流程位置 | P3-20 状态 |
|------|----------|------------|
| `inbound` | ① 入站 | stub |
| `consumption` | ② 消费 | stub |
| `probe` | ③ 探测 | stub |
| `grading` | ④ 分级 | stub |
| `reply` | ⑤ 回复 | stub |
| `operator` | ⑥ 坐席 | stub |
| `outbound` | ⑦ 出站 | stub |
| `archive` | ⑧ 归档 | stub |

实现：`app/services/script_match_hooks.py`  
C-07 验收：每钩子至少 1 个契约用例（`tests/test_c07_script_hooks.py`）。
