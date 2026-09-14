# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。当前入口为本文件与 [HANDOFF](HANDOFF.md)。正式 R7-C0 结果见 [R7 outcome](docs/JPL_R7_C0_DEPARTURE_STATE_ARRIVAL_OUTCOME_20260914.md)，R7-D1 冻结协议见 [R7-D1 protocol](docs/JPL_R7_D1_DEPARTURE_ATTRIBUTION_PROTOCOL_20260914.md)，正式 R7-D1 结果见 [R7-D1 outcome](docs/JPL_R7_D1_DEPARTURE_ATTRIBUTION_OUTCOME_20260914.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`；R5=`STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`；R6-O0=`MIXED_COMPONENT_ORACLE_SIGNAL`；R7-C0=`PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL`；R7-D1=`TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL`。final holdout 2019-03/06/09/12 继续封存。**

## 1. R7-D1 formal result

```text
status                         COMPLETE
decision                       TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL
R7-D1 status SHA256            48247f4ef47415c65b080584e667e9b2dba9227271ad24d93da51800756b406b
reviewed executable            2a2384781eeccf122ef43116b604f319e5637bdc
implementation merge           992a611d8c3223b895818df984fc6e4f6b4521af
launcher SHA256                80242a597b5dd25b3eea5d36f1b26119ef4a7044589aca6e4fbe9b7e1573f2a4
private manifest SHA256        0c816334d74173e16df6e58e55de90ca3ed5723a6775e0b6287749afa479e019
fit_count                      275
holdout accessed               false
development data unchanged     true
reference models retrained     false
R7 Departure-Aug retrained     false
```

Frozen decision support:

```text
Availability component wins vs Base-M2       4/5 horizons, 3/4 months
Availability total wins vs S1                 5/5 horizons, 3/4 months
Departure-Aug component wins vs Availability  3/5 horizons, 3/4 months
Departure-Aug total wins vs Availability      3/5 horizons, 3/4 months
max Departure component degradation           +0.3915%
max Departure total degradation               +1.4584%
```

All preregistered conditions for `TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL` are satisfied.

## 2. Main R7-D1 finding

Arrival-component pooled MAE:

```text
Base-M2                 23.1051516907 A
Departure-Availability  23.0557563709 A
Departure-Aug           22.7486906628 A
```

Relative improvement:

```text
Availability vs Base-M2        +0.213785%
Departure-Aug vs Availability  +1.331840%
Departure-Aug vs Base-M2       +1.542777%
```

Total pooled MAE:

```text
Equal               28.9172859886 A
S1                  28.5948815297 A
TotalAvailability   28.4546589435 A
TotalDeparture      28.4354542901 A
```

Availability/missingness alone explains only a small part of the R7 component gain. The numerical requested-departure timing distribution contributes the larger incremental component improvement.

## 3. Horizon and month structure

Departure-Aug relative to Departure-Availability:

```text
horizon   arrival change   total change
15 min       +2.4918%        +0.5303%
30 min       -0.3915%        -0.5086%
60 min       +4.5427%        +2.6429%
120 min      +1.9216%        +0.4012%
240 min      -0.2361%        -1.4584%
```

The timing signal is strongest at 60 min and is positive at 15 and 120 min; it reverses at 30 and 240 min.

By month, Departure-Aug beats Availability in January, April and July and worsens in October. The month heterogeneity remains material.

## 4. Interpretation boundary

Accepted bounded claim:

> Numerical requested-departure timing values of currently connected sessions contain stable incremental predictive information for future-arrival current beyond declaration availability/missingness alone, and part of that information survives recombination into total station-current forecasts.

Do **not** claim:

- requested departure equals actual disconnect time;
- connector release causally drives future arrivals;
- the signal is uniformly beneficial at all horizons/months;
- R7-D1 solves the 240-min arrival problem.

R7-D1 rules out only the narrow explanation that R7-C0 was driven merely by metadata presence.

## 5. Next permitted method step

Per the frozen R7-D1 protocol, the next permissible step is to design and preregister a **horizon-aligned scheduled-departure exposure representation** using only issue-time-known requested-departure information.

The next design must remain narrow:

- preserve the accepted existing-session / future-arrival component decomposition;
- align departure timing features explicitly to each forecast horizon;
- keep development-only model selection and final holdout sealed;
- compare against frozen Base-M2, Departure-Aug, S1 and Equal references;
- do not add a gate, MoE, survival/TPP, attention, Set Transformer or generic larger backbone as a rescue mechanism;
- do not claim causality.

Before freezing that protocol, check current literature specifically for session-level requested-departure / departure-time use in aggregate EV charging forecasting so the method contribution is framed against existing work rather than model novelty alone.

## 6. Closed routes remain closed

Do not return to:

- Level/M3 gate, learned gate, month/horizon router or MoE;
- P1 survival/TPP/count-mark escalation;
- R2 Deep Sets / Set Transformer / attention rescue;
- R3 control-endogeneity route;
- R5 larger backbone or geometry-loss tuning.

R7-D1 does not reopen any of them.

## 7. GitHub Actions policy

Full CI only runs on pull requests touching code/scripts/pyproject/workflow/MANIFEST. Pure documentation/result archival does not trigger full CI. New code should be statically/locally checked first and use Actions only for the final candidate.
