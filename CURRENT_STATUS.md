# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R9-C0 正式结果见 [R9-C0 outcome](docs/JPL_R9_C0_FORECAST_GRID_DEPARTURE_PROFILE_OUTCOME_20260914.md)，下一阶段冻结协议见 [R10-R0 protocol](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_PROTOCOL_20260914.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`；R5=`STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`；R6-O0=`MIXED_COMPONENT_ORACLE_SIGNAL`；R7-C0=`PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL`；R7-D1=`TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL`；R8-C0=`NO_STABLE_HORIZON_ALIGNED_ADVANTAGE`；R9-C0=`STOP_DEPARTURE_REPRESENTATION_REFINEMENT`；R10-R0 稳健性/holdout-readiness 协议已冻结，尚未执行。final holdout 2019-03/06/09/12 继续封存。**

## 1. R9-C0 formal result

```text
status                         COMPLETE
decision                       STOP_DEPARTURE_REPRESENTATION_REFINEMENT
R9-C0 status SHA256            d3ce58b4272e0b3fea4f11c9774c7b61a11fae443cfbb4f09210e8e22bea6d98
protocol merge                 35ed40105faaa82f0c9d7e6a96f805ffdf4aea35
reviewed executable            c60ed89f522bc3f9df30f10093e1216a9a9f6b2f
implementation merge           b7e2da489db13523c8d7fe46bff4799a63a64ba7
launcher SHA256                0efb11b2e2484ccae8c0af3ea0664ec5aaf771402621000b643894cebb143c6c
private manifest SHA256        a94de82891c821600f81adcaaa6c948a2bb90afc8e5c40ad2bfbcbdaabf744f1
fit_count                      275
holdout accessed               false
development data unchanged     true
```

Arrival-component pooled MAE:

```text
Departure-Aug           22.7486906628 A
ForecastGridProfile     22.8459204443 A
Horizon-Exposure        23.1408646361 A
```

Total pooled MAE:

```text
S1                          28.5948815297 A
Equal                       28.9172859886 A
TotalDeparture              28.4354542901 A
TotalForecastGridProfile    28.4001928133 A
```

R9 is STOP because the frozen component month-stability condition triggers: ForecastGridProfile beats Departure-Aug in only `1/4` months. The slight pooled total improvement cannot override STOP.

## 2. Accepted development candidate

Departure-representation refinement is closed. Retain R7 `Departure-Aug`:

```text
Arrival MAE        22.7486906628 A
Total MAE          28.4354542901 A
vs S1 total        +0.5576% improvement
vs Equal total     +1.6662% improvement
```

No further departure bins, weights, ratios, embeddings, feature selection or horizon/month routing are allowed.

## 3. R10-R0 frozen robustness audit

Protocol commit:

```text
05dc342d376425c13f09ee68356583223203aae3
```

R10-R0 is zero-fit and read-only. It replays the accepted R7-D1 private cache and evaluates TotalDeparture against S1 and Equal using:

- pooled replay;
- paired local-day pooled-over-horizon MAE differences/win rates;
- per-month daily stability;
- leave-one-month-out aggregates;
- leave-one-horizon-out aggregates;
- original month/horizon stability;
- a 10,000-replicate month-stratified day bootstrap for descriptive uncertainty only.

Frozen decisions:

```text
FRAGILE_DEVELOPMENT_SIGNAL
READY_FOR_SINGLE_SHOT_HOLDOUT_PROTOCOL
MIXED_DEVELOPMENT_ROBUSTNESS
```

`READY_FOR_SINGLE_SHOT_HOLDOUT_PROTOCOL` still does **not** authorize holdout access. A separate frozen holdout protocol, explicit user authorization and a new pinned launcher would still be required.

## 4. Closed routes and GitHub Actions

Final holdout remains sealed. Do not return to departure feature engineering, gate/MoE, survival/TPP, Deep Sets/attention, control-endogeneity rescue, FTAR enlargement, Transformer/Mamba or post-hoc feature search. Pure documentation/result archival remains CI-free; R10 implementation should be zero-fit and use Actions only for its final code candidate if code changes are needed.
