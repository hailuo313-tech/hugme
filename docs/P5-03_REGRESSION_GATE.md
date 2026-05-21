# P5-03 Level / Intent Regression Gate

Task: P5-03  
Acceptance: regression has 0 failures

## Scope

P5-03 maintains the Phase 02 level engine and Phase 03 intent classifier
regression fixtures as one release gate.

## Fixtures

- `config/level_regression_set.json`
  - 20 level cases covering profile completeness, T1/T2/T3/unknown country tiers,
    signed S/A thresholds, VIP promotion, operator S override, and route mapping.
- `config/intent_regression_set.json`
  - Existing labeled intent set with 50+ examples.

## Gate

The gate runs both suites and fails if any case fails:

```powershell
python scripts/run_p5_03_regression.py --json
```

Output fields:

- `status`: `passed` only when all suites have zero failures.
- `total`: total cases across level and intent suites.
- `failed`: total failed cases. P5-03 requires this to be `0`.
- `suites`: per-suite totals and failure details.

## CI Tests

`tests/test_p5_03_regression_gate.py` enforces:

- Level regression set has at least 20 cases and 0 failures.
- Intent regression set has at least 50 cases and 0 failures.
- Combined P5-03 gate has 0 failures.
- `docs/product/business-flow.html` marks P5-03 as completed.

## Maintenance Rule

When signed thresholds, T1 countries, intent taxonomy, or classifier behavior
changes, update the corresponding fixture in the same PR. Do not relax the
P5-03 zero-failure gate; add accepted alternates only when product taxonomy
explicitly allows the alternate intent.
