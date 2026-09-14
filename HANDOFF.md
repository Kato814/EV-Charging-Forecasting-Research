# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R9-C0 outcome](docs/JPL_R9_C0_FORECAST_GRID_DEPARTURE_PROFILE_OUTCOME_20260914.md) 和此前 R7/R8 协议与 outcome。

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
```

Final holdout `2019-03/06/09/12` remains sealed.

## 2. R9-C0 formal identity

```text
R9-C0 status SHA256            d3ce58b4272e0b3fea4f11c9774c7b61a11fae443cfbb4f09210e8e22bea6d98
protocol merge                 35ed40105faaa82f0c9d7e6a96f805ffdf4aea35
reviewed executable            c60ed89f522bc3f9df30f10093e1216a9a9f6b2f
implementation merge           b7e2da489db13523c8d7fe46bff4799a63a64ba7
launcher SHA256                0efb11b2e2484ccae8c0af3ea0664ec5aaf771402621000b643894cebb143c6c
private manifest SHA256        a94de82891c821600f81adcaaa6c948a2bb90afc8e5c40ad2bfbcbdaabf744f1
fit_count                      275
holdout_accessed               false
development_data_unchanged     true
```

## 3. R9-C0 formal result

```text
Arrival pooled MAE:
Departure-Aug           22.7486906628 A
ForecastGridProfile     22.8459204443 A
Horizon-Exposure        23.1408646361 A

Total pooled MAE:
S1                      28.5948815297 A
Equal                   28.9172859886 A
TotalDeparture          28.4354542901 A
TotalForecastGridProfile 28.4001928133 A
```

Frozen support:

```text
component horizon wins vs Departure-Aug   3/5
component month wins vs Departure-Aug     1/4
component long-horizon wins               2/3
total horizon wins vs TotalDeparture      3/5
total month wins vs TotalDeparture        2/4
pooled arrival improvement                -0.427408%
pooled total improvement                  +0.124005%
```

Formal STOP is triggered by the preregistered cross-month condition `component month wins <=1/4`. Do not reinterpret the slight total pooled gain as PASS.

## 4. Departure route closure

R7-D1 remains the accepted evidence that numerical requested-departure timing contains incremental information beyond metadata availability. R8 and R9 show that neither a single horizon-local count nor a fixed forecast-grid histogram provides a stable replacement for the generic ten-stat Departure-Aug representation.

Therefore:

- retain R7 Departure-Aug as the accepted development candidate;
- no more engineered departure representations;
- no bin tuning, horizon/month selection, weighting, ratios, embeddings or feature search;
- do not reopen gate/MoE, survival/TPP, Deep Sets/attention, FTAR enlargement, Transformer/Mamba or control-endogeneity rescue.

## 5. Next authorized scientific step

The next step is a **zero-fit development robustness / holdout-readiness audit** of the accepted R7 candidate, using frozen private row predictions only.

It should answer whether the total-level improvement is broadly distributed across local days or concentrated in a small number of days/cells. Appropriate diagnostics include paired local-day MAE differences, day-level win rates, month-balanced summaries, block/bootstrap uncertainty or equivalent preregistered descriptive stability checks. No model retraining, no feature search and no final-holdout access.

Only after that audit is frozen and completed may a separate holdout-access decision be considered.

## 6. Repository hygiene

Preserve all detached worktrees, status JSONs and private caches. No reset/clean/stash/force-push/automatic deletion. Pure docs remain CI-free; do not spend Actions on archival work.
