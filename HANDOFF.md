# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R7 outcome](docs/JPL_R7_C0_DEPARTURE_STATE_ARRIVAL_OUTCOME_20260914.md)、[R7-D1 protocol](docs/JPL_R7_D1_DEPARTURE_ATTRIBUTION_PROTOCOL_20260914.md) 和 [R7-D1 outcome](docs/JPL_R7_D1_DEPARTURE_ATTRIBUTION_OUTCOME_20260914.md)。

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
```

Final holdout `2019-03/06/09/12` remains sealed. Do not rerun closed S1–R7-D1 stages unless a separately frozen repair protocol explicitly requires it.

## 2. R7-D1 formal identity

```text
source R7 status SHA256          deb7fc1700fccd3eb53616bbe2e65de0941b6294d60aec58e4f63953b576bce0
source R7 private manifest       172c69c71e6baef689f65ad0169b3440947675f462dd1bc9b72479e11bad6967
R7-D1 status SHA256              48247f4ef47415c65b080584e667e9b2dba9227271ad24d93da51800756b406b
protocol commit                  5532e2f9aca90e03c580d0203aec6b193b71cda3
reviewed executable              2a2384781eeccf122ef43116b604f319e5637bdc
implementation merge             992a611d8c3223b895818df984fc6e4f6b4521af
launcher SHA256                  80242a597b5dd25b3eea5d36f1b26119ef4a7044589aca6e4fbe9b7e1573f2a4
private manifest SHA256          0c816334d74173e16df6e58e55de90ca3ed5723a6775e0b6287749afa479e019
fit_count                        275
holdout_accessed                 false
development_data_unchanged       true
reference_models_retrained       false
r7_departure_retrained           false
```

## 3. R7-D1 formal result

Arrival component:

```text
Base-M2                 23.1051516907 A
Departure-Availability  23.0557563709 A
Departure-Aug           22.7486906628 A

Availability vs Base-M2        +0.213785%
Departure-Aug vs Availability  +1.331840%
Departure-Aug vs Base-M2       +1.542777%
```

Total load:

```text
S1                  28.5948815297 A
Equal               28.9172859886 A
TotalAvailability   28.4546589435 A
TotalDeparture      28.4354542901 A

TotalAvailability vs S1        +0.490377%
TotalDeparture vs Availability +0.067492%
TotalDeparture vs S1           +0.557538%
```

Frozen support counts:

```text
Availability component wins vs Base-M2       4/5 horizons, 3/4 months
Availability total wins vs S1                 5/5 horizons, 3/4 months
Departure-Aug component wins vs Availability  3/5 horizons, 3/4 months
Departure-Aug total wins vs Availability      3/5 horizons, 3/4 months
max Departure component degradation           +0.3915%
max Departure total degradation               +1.4584%
```

All preregistered `TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL` conditions were satisfied.

## 4. Horizon and month structure

Departure-Aug relative to Departure-Availability:

```text
horizon   arrival change   total change
15 min       +2.4918%        +0.5303%
30 min       -0.3915%        -0.5086%
60 min       +4.5427%        +2.6429%
120 min      +1.9216%        +0.4012%
240 min      -0.2361%        -1.4584%
```

The timing signal is strongest at 60 min. It is positive at 15 and 120 min, but reverses at 30 and 240 min.

By month, Departure-Aug beats Availability in January, April and July and worsens in October. The month heterogeneity therefore remains part of the formal interpretation.

## 5. Interpretation boundary

Accepted claim:

> Numerical requested-departure timing values of currently connected sessions contain stable incremental predictive information for future-arrival current beyond declaration availability/missingness alone, and part of that information survives total-load recombination.

This rules out the narrow hypothesis that R7-C0 was only a metadata-presence effect.

Do not claim that requested departure causes future arrivals or connector release. Requested departure is user-declared intended timing, not realized disconnect time. The 30/240-min horizon reversals and October reversal show that the signal is not uniformly beneficial.

## 6. Required next step

Per the frozen R7-D1 consequence boundary, the next permissible stage is a **horizon-aligned scheduled-departure exposure representation** based only on issue-time-known requested-departure information.

Before implementation:

1. review current literature specifically for session-level requested-departure/departure-time information in aggregate EV charging forecasting;
2. freeze one narrow development-only protocol;
3. preserve the existing-session / future-arrival component decomposition and exact rolling OOS rows;
4. keep the final holdout sealed;
5. benchmark against frozen Base-M2, Departure-Aug, S1 and Equal references;
6. do not add a gate, MoE, TPP, survival model, attention, Set Transformer or larger generic backbone merely for novelty.

The intended scientific question is whether **forecast-horizon-aligned departure timing exposure** can capture the supported timing information more directly and more consistently than the generic ten-stat Departure-Aug pool.

## 7. Closed routes remain closed

Do not return to:

- Level/M3 gate, learned gate, month/horizon router or MoE;
- P1 survival/TPP/count-mark escalation;
- R2 Deep Sets / Set Transformer / attention rescue;
- R3 control-endogeneity route;
- R5 larger backbone or geometry-loss tuning.

R7-D1 does not reopen any of them.

## 8. GitHub Actions conservation

Full CI runs only on code/config/workflow PRs. Pure documentation and result archival do not trigger full CI. Development should use local/static checks first; one final code candidate should consume the next Actions run where possible.

Preserve all detached worktrees, status JSONs, private caches and historical outputs. Do not reset/clean/stash/force-push or automatically delete worktrees.
