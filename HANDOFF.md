# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R9-C0 outcome](docs/JPL_R9_C0_FORECAST_GRID_DEPARTURE_PROFILE_OUTCOME_20260914.md) 和 [R10-R0 protocol](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_PROTOCOL_20260914.md)。

## 1. Frozen scientific state

```text
S1    = MIXED_STRUCTURED_SIGNAL, CLOSED
P1    = STOP_MECHANISM_ROUTE, CLOSED
R1    = MIXED_JOINT_STATE_SIGNAL, CLOSED
R2    = STOP_HIGHER_ORDER_SET_ROUTE, CLOSED
R3-C0 = STOP_CONTROL_ENDOGENEITY_ROUTE, CLOSED
R4-I0 = MIXED_STATE_ALIASING_SIGNAL
R4-D1/R4-D2 = COMPLETE diagnostics
R5    = STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE, CLOSED
R6-O0 = MIXED_COMPONENT_ORACLE_SIGNAL, COMPLETE
R7-C0 = PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL, COMPLETE
R7-D1 = TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL, COMPLETE
R8-C0 = NO_STABLE_HORIZON_ALIGNED_ADVANTAGE, COMPLETE
R9-C0 = STOP_DEPARTURE_REPRESENTATION_REFINEMENT, COMPLETE
R10-R0 = READY; formal zero-fit audit NOT RUN
```

Final holdout `2019-03/06/09/12` remains sealed.

## 2. Accepted development candidate

R9 formally closed departure-representation refinement. The accepted candidate remains R7 `Departure-Aug` / `TotalDeparture`:

```text
Arrival MAE        22.7486906628 A
Total MAE          28.4354542901 A
S1 total           28.5948815297 A
Equal total        28.9172859886 A
```

No further engineered departure representation is authorized.

## 3. R10-R0 frozen identity

```text
protocol commit                 05dc342d376425c13f09ee68356583223203aae3
reviewed executable             753f9adc5c5bd28022d6c1ce3e4c54fb3f76c3e0
implementation merge            062fb6cee5a14a0cd5a09bf3a4e41f80cc797f9f
final CI                        1241 passed, 2 skipped
compileall                      PASS
Ruff                            PASS
launcher filename               evcf_r10_r0_launcher_v1.py
launcher SHA256                 e4d247424274c926a07dcdee9e99eab0f3f88f5cdd1e7efec06de231ac0c6949
fit_count                       0
```

Exact accepted R7-D1 cache:

```text
status SHA256       48247f4ef47415c65b080584e667e9b2dba9227271ad24d93da51800756b406b
private manifest    0c816334d74173e16df6e58e55de90ca3ed5723a6775e0b6287749afa479e019
reviewed executable 2a2384781eeccf122ef43116b604f319e5637bdc
```

## 4. R10-R0 audit contents

R10 does not train/refit any model and creates no new prediction cache. It reads only the exact R7-D1 private cache and reports:

- pooled replay of TotalDeparture, S1 and Equal;
- paired local-day pooled-over-horizon MAE deltas and win rates;
- per-month daily stability;
- leave-one-month-out robustness;
- leave-one-horizon-out robustness;
- original 4-month / 5-horizon stability and worst-month degradation;
- deterministic 10,000-replicate PCG64 month-stratified complete-day bootstrap, descriptive only.

The external launcher verifies the exact reviewed worktree, frozen protocol blob, exact R7-D1 private manifest and every declared private task hash, then verifies the cache is unchanged after execution. It skips all final-holdout month directories during source discovery.

## 5. Frozen decision

```text
FRAGILE_DEVELOPMENT_SIGNAL
READY_FOR_SINGLE_SHOT_HOLDOUT_PROTOCOL
MIXED_DEVELOPMENT_ROBUSTNESS
```

FRAGILE is evaluated first. READY requires pooled superiority over S1 and Equal, >=3/4 original month wins vs both, >=3/5 original horizon wins vs both, >=50% local-day win rate vs both, 4/4 leave-one-month-out wins vs both, >=4/5 leave-one-horizon-out wins vs both, and <=5% worst-month degradation vs both.

READY does not itself authorize final holdout. If READY occurs, freeze a separate single-shot holdout protocol first and obtain explicit user authorization before any holdout access.

## 6. Next action

Run the pinned R10-R0 launcher exactly once on the user machine and upload only the newest `evcf_r10_r0_status_*.json`, whether COMPLETE or INCOMPLETE. Do not debug or rerun before inspecting that status.

## 7. Hygiene

Preserve all worktrees/status/private caches; no reset/clean/stash/force-push/automatic deletion. Do not return to closed model/feature routes. Pure docs remain CI-free; no GitHub Actions are required for the formal R10 audit.