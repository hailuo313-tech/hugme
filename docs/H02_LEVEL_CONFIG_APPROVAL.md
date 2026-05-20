# H-02 Level Configuration Approval

Status: signed
Task: H-02 - 审定 T1 国家名单与分级金额阈值
Signed on: 2026-05-20

## Signed Config Files

The signed configuration files for phase 02 grading are:

- `config/t1_countries.json`
- `config/level_thresholds.json`

Both files contain `status: "approved"` and an `approval` block for H-02.

## T1 Country List

The approved T1 country list uses ISO-3166 alpha-2 country codes:

| Code | Market |
|---|---|
| `US` | United States |
| `CA` | Canada |
| `GB` | United Kingdom |
| `AU` | Australia |
| `DE` | Germany |
| `FR` | France |
| `JP` | Japan |
| `KR` | South Korea |
| `SG` | Singapore |
| `HK` | Hong Kong |

## Amount Thresholds

Amounts are based on `lifetime_spend_usd` and use USD.

| Rule | Approved value | Result |
|---|---:|---|
| Incomplete profile | n/a | `D` |
| Operator assigned S | n/a | `S` |
| T1 high spend | `>= 500.00` | `S` |
| Spend threshold | `>= 99.00` | `A` |
| VIP threshold | `vip_level >= 1` | `A` |
| Complete T1 below A threshold | `>= 0.00` | `B` |
| T2 default | n/a | `C` |
| T3 default | n/a | `C` |
| Unknown country default | n/a | `C` |

## Level Engine Alignment

`app/services/level_engine.py` reads:

- T1 countries from `config/t1_countries.json`;
- thresholds from `config/level_thresholds.json`.

The current C-06 / J-01 smoke fixture already exercises the signed values,
including T1 high spend, T1 A threshold, T1 default B, T2/T3 default C, unknown
country default C, and non-T1 high spend not becoming S.

## Change Control

Any future change to the T1 country list, amount thresholds, VIP threshold, or
default country-tier mapping requires a new signed config revision and a level
engine smoke/regression run.

## Acceptance

- [x] T1 country list is signed.
- [x] Amount thresholds are signed.
- [x] Config files are the source of truth for P2-01/P2-05/P2-06.
- [x] Changes are traceable through Git history.
