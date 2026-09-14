# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R7-D1 outcome](docs/JPL_R7_D1_DEPARTURE_ATTRIBUTION_OUTCOME_20260914.md)、[R8-C0 protocol](docs/JPL_R8_C0_HORIZON_ALIGNED_DEPARTURE_EXPOSURE_PROTOCOL_20260914.md) 和 [R8-C0 outcome](docs/JPL_R8_C0_HORIZON_ALIGNED_DEPARTURE_EXPOSURE_OUTCOME_20260914.md)。

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
```

Final holdout `2019-03/06/09/12` remains sealed. Closed stages must not be rerun unless a separately frozen repair protocol requires it.

## 2. R8-C0 formal identity

```text
R8-C0 status SHA256              5f69386c62bff1314cc16de94d1667421e872aada739194e41ab41c5f5e2a6fe
protocol merge                   de2ca2a0be462a85d61adb48f6b32c0ae9996c6d
reviewed executable              91ab4a18f776b33e00a439ab10c74fd42a04f9b5
implementation merge             e67dbac395a89155042dead07b441714b4ec4f12
launcher SHA256                  afa29c162dac6b8132dd6081a9a0cba9f64235362cba946a660f3d0190777777
source R7-D1 status SHA256       48247f4ef47415c65b080584e667e9b2dba9227271ad24d93da51800756b406b
source R7-D1 private manifest    0c816334d74173e16df6e58e55de90ca3ed5723a6775e0b6287749afa479e019
private manifest SHA256          ec11e3555727259960e355b12ac1867d14adef876fedf2d7580daaa3366ff2d2
fit_count                        275
holdout_accessed                 false
development_data_unchanged       true
reference_models_retrained       false
r7_d1_references_retrained       false
```

## 3. R8-C0 formal result

```text
Arrival MAE:
Base-M2                 23.1051516907 A
Departure-Availability  23.0557563709 A
Departure-Aug           22.7486906628 A
Horizon-Exposure        23.1408646361 A

Total MAE:
S1                      28.5948815297 A
Equal                   28.9172859886 A
TotalAvailability       28.4546589435 A
TotalDeparture          28.4354542901 A
TotalHorizonExposure    28.6358770531 A
```

Frozen support:

```text
component horizon wins vs Departure-Aug   0/5
component month wins vs Departure-Aug     1/4
component wins in {60,120,240}            0/3
total horizon wins vs TotalDeparture      2/5
total month wins vs TotalDeparture        1/4
component horizon wins vs Availability    2/5
total horizon wins vs Availability        0/5
max component degradation                 +5.288667%
max total degradation                     +2.986383%
```

Formal decision is `NO_STABLE_HORIZON_ALIGNED_ADVANTAGE`.

## 4. Interpretation boundary

R8 rejects only the compressed horizon-local count representation:

```text
observed_count
missing_count
overdue_count
due_within_current_horizon_count
```

It does not overturn R7-D1. Numerical requested-departure timing still carries stable incremental information beyond metadata availability, but that information is not preserved by the single `0 < d_i <= h` count.

Do not claim horizon alignment in general is useless, and do not rescue R8 by adding current/pilot/energy weights, ratios, gates, routers, feature search, attention, Transformer/Mamba or survival/TPP.

## 5. Only justified next representation question

A final narrow distribution-shape probe may be preregistered:

- use a fixed requested-departure histogram/CDF whose cut points are exactly the canonical forecast horizons `15/30/60/120/240 min`;
- preserve missing and overdue counts;
- no data-driven bins, no feature search, no weights;
- same HGB and exact frozen M2 horizon parameters;
- same rolling-origin rows and future-arrival target;
- reuse R7-D1 references read-only;
- final holdout stays sealed.

Scientific question:

> Does retaining the **full forecast-grid shape** of the issue-time requested-departure distribution recover the R7-D1 timing signal more faithfully than the failed single-horizon exposure count?

If this final distribution-shape probe fails, close departure-representation refinement and retain R7 Departure-Aug as the accepted development candidate. Do not continue feature-engineering rescues.

## 6. Repository and Actions hygiene

Preserve detached worktrees, status JSONs, private caches and historical outputs. Do not reset/clean/stash/force-push or automatically delete worktrees. Pure docs do not trigger full CI; code changes should be completed before one final PR/CI where possible.
