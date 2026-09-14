# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。当前入口为本文件与 [HANDOFF](HANDOFF.md)。正式 R7-D1 结果见 [R7-D1 outcome](docs/JPL_R7_D1_DEPARTURE_ATTRIBUTION_OUTCOME_20260914.md)，R8-C0 协议见 [R8-C0 protocol](docs/JPL_R8_C0_HORIZON_ALIGNED_DEPARTURE_EXPOSURE_PROTOCOL_20260914.md)，正式 R8-C0 结果见 [R8-C0 outcome](docs/JPL_R8_C0_HORIZON_ALIGNED_DEPARTURE_EXPOSURE_OUTCOME_20260914.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`；R5=`STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`；R6-O0=`MIXED_COMPONENT_ORACLE_SIGNAL`；R7-C0=`PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL`；R7-D1=`TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL`；R8-C0=`NO_STABLE_HORIZON_ALIGNED_ADVANTAGE`。final holdout 2019-03/06/09/12 继续封存。**

## 1. R8-C0 formal result

```text
status                         COMPLETE
decision                       NO_STABLE_HORIZON_ALIGNED_ADVANTAGE
R8-C0 status SHA256            5f69386c62bff1314cc16de94d1667421e872aada739194e41ab41c5f5e2a6fe
protocol merge                 de2ca2a0be462a85d61adb48f6b32c0ae9996c6d
reviewed executable            91ab4a18f776b33e00a439ab10c74fd42a04f9b5
implementation merge           e67dbac395a89155042dead07b441714b4ec4f12
launcher SHA256                afa29c162dac6b8132dd6081a9a0cba9f64235362cba946a660f3d0190777777
private manifest SHA256        ec11e3555727259960e355b12ac1867d14adef876fedf2d7580daaa3366ff2d2
fit_count                      275
holdout accessed               false
development data unchanged     true
reference models retrained     false
```

## 2. Main R8 finding

Arrival-component pooled MAE:

```text
Base-M2                 23.1051516907 A
Departure-Availability  23.0557563709 A
Departure-Aug           22.7486906628 A
Horizon-Exposure        23.1408646361 A
```

Total pooled MAE:

```text
Equal                   28.9172859886 A
S1                      28.5948815297 A
TotalAvailability       28.4546589435 A
TotalDeparture          28.4354542901 A
TotalHorizonExposure    28.6358770531 A
```

Horizon-Exposure is worse than Departure-Aug at all 5 component horizons and in 3/4 months; it is also worse than Departure-Availability at pooled component/total level and worse than S1 at pooled total level.

Frozen support:

```text
component wins vs Departure-Aug      0/5 horizons, 1/4 months
long-horizon component wins          0/3
component wins vs Availability       2/5 horizons, 1/4 months
total wins vs TotalDeparture         2/5 horizons, 1/4 months
total wins vs TotalAvailability      0/5 horizons, 1/4 months
max component horizon degradation    +5.288667%
max total horizon degradation        +2.986383%
```

## 3. Interpretation

Accepted bounded conclusion:

> The R7-D1 requested-departure timing signal cannot be reduced to a single `0 < d_i <= h` exposure count plus overdue/availability counts. The useful signal depends on richer timing-distribution structure.

R8 does not invalidate R7-C0 or R7-D1. It rejects only this compressed four-count horizon-local representation.

Do not rescue R8 with current/pilot/energy weighting, ratios, learned gates, feature search, attention, Transformer/Mamba, survival/TPP or month/horizon routing.

## 4. Next scientific step

One final narrow representation question remains justified before closing departure-representation refinement:

> Is the useful information the **shape of the requested-departure distribution across the full canonical forecast grid**, rather than the count inside only the target horizon?

If pursued, the next probe must use one fixed forecast-grid histogram/CDF representation determined solely by canonical horizons `{15,30,60,120,240}`; same HGB, same frozen M2 parameters, same rolling OOS rows, same future-arrival target, and read-only R7-D1 references. No feature search or weighting.

If that final distribution-shape probe fails, close the departure-representation refinement route and retain R7 Departure-Aug as the accepted development candidate.

## 5. Holdout and closed routes

Final holdout remains sealed. Do not return to gate/MoE, P1 survival/TPP, R2 Deep Sets/attention, R3 control-endogeneity rescue, R5 geometry enlargement, Transformer/Mamba, or post-hoc feature search.

## 6. GitHub Actions policy

Pure documentation/result archival does not trigger full CI. New code should be statically reviewed before the final PR and full Actions should be reserved for the final candidate only.
