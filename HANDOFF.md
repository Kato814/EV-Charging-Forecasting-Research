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
R10-R0 = robustness/holdout-readiness protocol FROZEN, NOT RUN
```

Final holdout `2019-03/06/09/12` remains sealed.

## 2. R9-C0 closure

```text
R9-C0 status SHA256             d3ce58b4272e0b3fea4f11c9774c7b61a11fae443cfbb4f09210e8e22bea6d98
private manifest                a94de82891c821600f81adcaaa6c948a2bb90afc8e5c40ad2bfbcbdaabf744f1
reviewed executable             c60ed89f522bc3f9df30f10093e1216a9a9f6b2f
implementation merge            b7e2da489db13523c8d7fe46bff4799a63a64ba7
fit_count                       275
holdout_accessed                false
development_data_unchanged      true
```

R9 formal decision is `STOP_DEPARTURE_REPRESENTATION_REFINEMENT`. ForecastGridProfile beats Departure-Aug in 3/5 component horizons but only 1/4 months. STOP condition is therefore met before PASS is considered. The slightly better pooled recombined total does not change the route decision.

Accepted development candidate remains R7 `Departure-Aug` with TotalDeparture MAE `28.4354542901 A`, about 0.5576% better than S1 and 1.6662% better than Equal.

No further departure bins/weights/ratios/embeddings/feature search are allowed.

## 3. R10-R0 protocol identity

```text
protocol commit  05dc342d376425c13f09ee68356583223203aae3
```

R10-R0 is a zero-fit, read-only audit of accepted R7 predictions. It uses the exact R7-D1 private cache:

```text
status SHA256       48247f4ef47415c65b080584e667e9b2dba9227271ad24d93da51800756b406b
private manifest    0c816334d74173e16df6e58e55de90ca3ed5723a6775e0b6287749afa479e019
reviewed executable 2a2384781eeccf122ef43116b604f319e5637bdc
```

Primary candidate = `TotalDeparture`; primary references = `S1` and `Equal`.

Required checks:

- exact pooled replay;
- paired local-day pooled-over-horizon MAE and win rate;
- per-month daily stability;
- leave-one-month-out row-pooled comparisons;
- leave-one-horizon-out row-pooled comparisons;
- original month/horizon wins and worst-month degradation;
- 10,000-replicate deterministic PCG64 month-stratified day bootstrap for descriptive uncertainty only.

No model fit/refit is allowed: `fit_count=0`.

## 4. Frozen R10 decisions

```text
FRAGILE_DEVELOPMENT_SIGNAL
READY_FOR_SINGLE_SHOT_HOLDOUT_PROTOCOL
MIXED_DEVELOPMENT_ROBUSTNESS
```

FRAGILE is evaluated first; READY next; otherwise MIXED. READY requires pooled superiority over S1/Equal, stable original month/horizon wins, >=50% local-day win rates vs both, 4/4 leave-one-month-out wins vs both, >=4/5 leave-one-horizon-out wins vs both, and <=5% worst-month degradation.

READY still does not authorize final holdout. Any holdout access requires a separate frozen protocol, explicit user authorization and a new pinned launcher.

## 5. Closed routes and hygiene

Do not return to departure feature engineering, gate/MoE, survival/TPP, Deep Sets/attention, control-endogeneity rescue, FTAR enlargement, Transformer/Mamba or post-hoc feature search. Preserve all worktrees/status/private caches; no reset/clean/stash/force-push/automatic deletion.

Pure docs remain CI-free. If R10 needs code, complete and statically review it before one final PR/CI where possible.
