# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。当前入口为本文件与 [HANDOFF](HANDOFF.md)。正式 R6-O0 结果见 [R6 outcome](docs/JPL_R6_O0_COMPONENT_ORACLE_OUTCOME_20260914.md)，R7-C0 协议见 [R7 protocol](docs/JPL_R7_C0_DEPARTURE_STATE_ARRIVAL_PROTOCOL_20260914.md)，正式 R7-C0 结果见 [R7 outcome](docs/JPL_R7_C0_DEPARTURE_STATE_ARRIVAL_OUTCOME_20260914.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`；R5=`STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`；R6-O0=`MIXED_COMPONENT_ORACLE_SIGNAL`；R7-C0=`PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL`。final holdout 2019-03/06/09/12 继续封存。**

## 1. R7-C0 formal result

```text
status                         COMPLETE
decision                       PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL
source status SHA256           deb7fc1700fccd3eb53616bbe2e65de0941b6294d60aec58e4f63953b576bce0
reviewed executable            24e9e69413cb4b224bd1c59cdd3725b352bd27ed
implementation merge           78e51d98d476e30098a19b67121c0658a4c848b4
launcher SHA256                f1dbaf035055038f337f0207baba8ae0ef884ca0118c16a87ef75d7178f822e9
fit_count                      550
holdout accessed               false
development data unchanged     true
reference models retrained     false
```

Frozen PASS support:

```text
pooled arrival improvement vs Base-M2      +1.542777%
component horizon wins                      5/5
component month wins                        3/4
wins within {60,120,240}                    3/3
pooled total improvement vs S1              +0.557538%
pooled total improvement vs Equal           +1.666241%
total horizon wins vs S1                    4/5
total month wins vs S1                      3/4
max total horizon degradation vs S1         +0.568377%
```

All preregistered primary PASS conditions are satisfied.

## 2. Main R7 finding

Arrival-component pooled MAE:

```text
Base-M2        23.1051516907 A
Departure-Aug  22.7486906628 A
Full-M3        22.5561552852 A
```

Total pooled MAE:

```text
Equal           28.9172859886 A
S1              28.5948815297 A
TotalDeparture  28.4354542901 A
TotalFullM3     28.2945240071 A
```

Departure-Aug improves the arrival component at all 5 horizons. After recombination it beats S1 at 15/30/60/120 min and slightly worsens at 240 min (+0.568%). The strongest practical gain is around 60 min; the 240-min future-arrival bottleneck remains largely unresolved.

Month stability is 3/4: January/April/July improve; October worsens.

Secondary Full-M3 label is `FULL_M3_INCREMENTAL_SIGNAL`: current-session state beyond M2 contains additional arrival information, but Full-M3 total gain is less stable across horizons/months than Departure-Aug.

## 3. Interpretation boundary

Accepted bounded claim:

> Issue-time requested-departure state of currently connected sessions provides stable incremental predictive information for the future-arrival current component beyond frozen M2, and part of that gain survives recombination into total station-current forecasts.

Do **not** yet claim:

- actual departure time is known;
- connector release causally drives the improvement;
- requested-departure timing values alone explain the gain;
- R7 solves the long-horizon arrival problem.

The canonical ten-stat departure pool contains both timing statistics and declaration-availability information (`count`, `missing_count`).

## 4. Next required attribution step: R7-D1

Before a horizon-aligned departure/release method is designed, isolate whether the R7 signal comes from actual requested-departure timing or mainly from declaration availability/missingness.

Planned narrow ablation:

```text
Base-M2                 frozen S1 arrival, read-only
Departure-Availability  M2 + requested-departure observed-count/missing-count only
Departure-Aug           frozen R7 prediction, read-only
```

Use identical HGB class, frozen M2 parameters, rolling-origin rows, arrival truth and total recombination. Only the new Availability arm is fitted; expected new fits = 275.

If full Departure-Aug stably beats Availability, actual timing-distribution information is supported. If Availability captures the gain, R7 must be interpreted as a declaration/missingness proxy rather than a departure-time mechanism. No holdout, retuning, gate or neural rescue is authorized.

## 5. Closed routes remain closed

Do not return to:

- Level/M3 gate, learned gate, month/horizon router or MoE;
- P1 survival/TPP/count-mark escalation;
- R2 Deep Sets / Set Transformer / attention rescue;
- R3 control-endogeneity route;
- R5 larger backbone or geometry-loss tuning.

R7 PASS does not reopen any of them.

## 6. GitHub Actions policy

Full CI only runs on pull requests touching code/scripts/pyproject/workflow/MANIFEST. Pure documentation/result archival does not trigger full CI; duplicate push-triggered runs remain removed; `cancel-in-progress` remains enabled. New code should be statically/locally checked first and use Actions only for the final candidate.
