# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R9-C0 正式结果见 [R9-C0 outcome](docs/JPL_R9_C0_FORECAST_GRID_DEPARTURE_PROFILE_OUTCOME_20260914.md)，R10-R0 冻结协议见 [R10-R0 protocol](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_PROTOCOL_20260914.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`；R5=`STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`；R6-O0=`MIXED_COMPONENT_ORACLE_SIGNAL`；R7-C0=`PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL`；R7-D1=`TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL`；R8-C0=`NO_STABLE_HORIZON_ALIGNED_ADVANTAGE`；R9-C0=`STOP_DEPARTURE_REPRESENTATION_REFINEMENT`；R10-R0 协议、实现与 pinned launcher 已冻结，正式零训练审计尚未执行。final holdout 2019-03/06/09/12 继续封存。**

## 1. Accepted development candidate

Departure-representation refinement is closed. Retain R7 `Departure-Aug`:

```text
Arrival MAE        22.7486906628 A
Total MAE          28.4354542901 A
S1 total           28.5948815297 A
Equal total        28.9172859886 A
vs S1              +0.5576% improvement
vs Equal           +1.6662% improvement
```

No further departure bins, weights, ratios, embeddings, feature selection or horizon/month routing are allowed.

## 2. R10-R0 scientific purpose

R10-R0 is a zero-fit, read-only robustness and holdout-readiness audit. It does not create new forecasts and does not access the final holdout.

It replays the exact accepted R7-D1 private cache and evaluates `TotalDeparture` against `S1` and `Equal` using:

- exact pooled replay;
- paired local-day pooled-over-horizon MAE differences and win rates;
- per-month daily stability;
- leave-one-month-out row-pooled comparisons;
- leave-one-horizon-out row-pooled comparisons;
- original month/horizon wins and worst-month degradation;
- 10,000-replicate deterministic PCG64 month-stratified complete-day bootstrap for descriptive uncertainty only.

## 3. R10-R0 frozen identities

```text
protocol commit                 05dc342d376425c13f09ee68356583223203aae3
reviewed executable             753f9adc5c5bd28022d6c1ce3e4c54fb3f76c3e0
implementation merge            062fb6cee5a14a0cd5a09bf3a4e41f80cc797f9f
final code CI                   1241 passed, 2 skipped; compileall PASS; Ruff PASS
launcher SHA256                 e4d247424274c926a07dcdee9e99eab0f3f88f5cdd1e7efec06de231ac0c6949
fit_count                       0
formal audit                    NOT RUN
```

Source R7-D1:

```text
status SHA256       48247f4ef47415c65b080584e667e9b2dba9227271ad24d93da51800756b406b
private manifest    0c816334d74173e16df6e58e55de90ca3ed5723a6775e0b6287749afa479e019
reviewed executable 2a2384781eeccf122ef43116b604f319e5637bdc
```

R10 launcher reads only that exact cache, verifies its content before/after execution, creates no prediction cache and performs no network data acquisition.

## 4. Frozen R10 decisions

```text
FRAGILE_DEVELOPMENT_SIGNAL
READY_FOR_SINGLE_SHOT_HOLDOUT_PROTOCOL
MIXED_DEVELOPMENT_ROBUSTNESS
```

FRAGILE is evaluated first; READY next; otherwise MIXED. READY requires pooled superiority over S1/Equal, stable original month/horizon wins, >=50% local-day win rates vs both, 4/4 leave-one-month-out wins vs both, >=4/5 leave-one-horizon-out wins vs both, and <=5% worst-month degradation.

`READY_FOR_SINGLE_SHOT_HOLDOUT_PROTOCOL` still does **not** authorize holdout access. A separate frozen single-shot holdout protocol, explicit user authorization and a new pinned launcher would still be required.

## 5. Execution and hygiene

```text
R10-R0 protocol             FROZEN / MERGED
R10-R0 implementation       CI PASS / MERGED
R10-R0 pinned launcher      READY
R10-R0 formal audit         NOT RUN
final holdout               SEALED
```

Do not return to departure feature engineering, gate/MoE, survival/TPP, Deep Sets/attention, control-endogeneity rescue, FTAR enlargement, Transformer/Mamba or post-hoc feature search. Pure documentation/result archival remains CI-free.