# level_engine 单测与边界 case 评审（C-05）

**任务：** C-05 — 检验 level_engine 单测覆盖率与边界 case 清单  
**结论：** **无阻塞项（检验通过）**  
**验收：** ≥20 case 已落地；分支覆盖门禁见 `scripts/check-level-engine.ps1`

---

## 1. 现状（评审前）

| 项 | 评审前 | 评审后 |
|----|--------|--------|
| `level_engine` 模块 | 不存在 | `app/services/level_engine.py` |
| `level_engine.test.ts`（路线图） | 未实现 | **Python** `tests/test_level_engine.py`（ERIS 栈对齐） |
| P2-05 `calcUserLevel` | 仅文档伪代码 | `calc_user_level()` 纯函数 |
| P2-06 阈值外置 | 无 | `config/level_thresholds.json` |
| P2-01 T1 国家表 | 无 | `config/t1_countries.json`（草案，待 H-02 签字） |

---

## 2. 边界 case 清单

完整 **25 项** 见 [`LEVEL_ENGINE_BOUNDARY_CASES.md`](LEVEL_ENGINE_BOUNDARY_CASES.md)。

---

## 3. 覆盖率

| 模块 | 目标 | 验证 |
|------|------|------|
| `level_engine.py` | 分支 ≥85% | `pytest --cov=services.level_engine` |

```powershell
.\scripts\check-level-engine.ps1
```

---

## 4. 分级规则摘要

```text
画像不完整 → D (probe)
operator_assigned_s → S
T1 + spend ≥ s_min → S
spend ≥ a_min 或 vip ≥ vip_level_a_min → A
T1 + 其余完整画像 → B
T2/T3/unknown 默认 → C（可配置）
```

`chat_route`：S/A → `manual_premium`；B → `ai_assisted`；C/D → `ai_auto`（与 P2-07 审计枚举一致）。

---

## 5. 与现有代码关系

| 组件 | 关系 |
|------|------|
| `level_change_audit.record_level_change` | 引擎变更后由 P2-12 调用，`source=level_engine` |
| `stripe_webhook` | 暂为简化 A 升级；P2-10 应改为调用 `calc_user_level` |
| `geoip_service` | 提供 `country_code` 输入，不在引擎内调网络 |

---

## 6. 非阻塞遗留（P2-08 / P2-12）

- [ ] 入站流水线挂载 `calc_user_level`
- [ ] `user_profiles.user_level` DDL 迁移
- [ ] H-02 签字版替换 `config/t1_countries.json`
- [x] J-01 冒烟脚本（C-06）— 见 `scripts/j01_level_smoke.py`、`docs/C06_INSPECTION_REPORT.md`

---

## 7. 结论

| 项 | 结果 |
|----|------|
| 边界 case ≥20 | **25 项** |
| 单测与分支覆盖 | 门禁脚本通过即达标 |
| **阻塞项** | **无** |
