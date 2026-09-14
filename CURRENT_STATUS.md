# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R10-R0 正式结果见 [R10-R0 outcome](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_OUTCOME_20260914.md)，冻结协议见 [R10-R0 protocol](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_PROTOCOL_20260914.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`；R5=`STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`；R6-O0=`MIXED_COMPONENT_ORACLE_SIGNAL`；R7-C0=`PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL`；R7-D1=`TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL`；R8-C0=`NO_STABLE_HORIZON_ALIGNED_ADVANTAGE`；R9-C0=`STOP_DEPARTURE_REPRESENTATION_REFINEMENT`；R10-R0=`MIXED_DEVELOPMENT_ROBUSTNESS`, COMPLETE。final holdout 2019-03/06/09/12 继续封存。**

## 1. Accepted development candidate

Departure-representation refinement remains closed. Retain R7 `Departure-Aug / TotalDeparture` as the accepted development-stage candidate:

```text
Arrival MAE        22.7486906628 A
Total MAE          28.4354542901 A
S1 total           28.5948815297 A
Equal total        28.9172859886 A
vs S1              +0.5576% improvement
vs Equal           +1.6662% improvement
```

R10 does not revoke the R7 development signal, but it does not qualify the candidate for final holdout.

## 2. R10-R0 formal result

```text
status                         COMPLETE
decision                       MIXED_DEVELOPMENT_ROBUSTNESS
status SHA256                  058ec6b1196c76e884973e36f851e5c05831bb16fc6533b240d445c4dd82dda8
protocol commit                05dc342d376425c13f09ee68356583223203aae3
reviewed executable            753f9adc5c5bd28022d6c1ce3e4c54fb3f76c3e0
implementation merge           062fb6cee5a14a0cd5a09bf3a4e41f80cc797f9f
launcher SHA256                e4d247424274c926a07dcdee9e99eab0f3f88f5cdd1e7efec06de231ac0c6949
fit_count                      0
holdout accessed               false
R7 private cache unchanged     true
```

Exact pooled replay passed.

## 3. Frozen decision support

```text
                                        vs S1          vs Equal
pooled improvement                      +0.5575%       +1.6662%
original month wins                     3/4            3/4
original horizon wins                   4/5            4/5
local-day wins                          26/55          31/55
local-day win rate                      47.27%         56.36%
leave-one-month-out wins                4/4            4/4
leave-one-horizon-out wins              5/5            5/5
worst original-month degradation        1.004%         1.675%
```

FRAGILE does not apply. READY fails only the frozen `>=50%` local-day win-rate requirement versus S1: observed `26/55 = 47.27%`. Therefore the exhaustive preregistered decision is `MIXED_DEVELOPMENT_ROBUSTNESS`.

## 4. Stability interpretation

The pooled gain is not driven by a single development month or horizon: the candidate wins all 4/4 leave-one-month-out and all 5/5 leave-one-horizon-out aggregates against both references.

The limiting evidence is day-level breadth versus S1:

```text
mean daily delta vs S1       -0.16134 A
median daily delta vs S1     +0.05723 A
top-5 gain share vs S1        60.66%
```

Per-month daily win rate vs S1 is 35.71% / 76.92% / 57.14% / 21.43% for 2019-01/04/07/10 respectively.

The deterministic result therefore supports a small, reproducible development-stage average gain, but not sufficiently broad day-level improvement for holdout readiness.

## 5. Bootstrap context

Frozen 10,000-replicate month-stratified complete-day bootstrap:

```text
             q05          q50          q95          fraction(delta < 0)
vs S1       -0.7507 A    -0.1543 A    +0.3878 A    0.6790
vs Equal    -1.6314 A    -0.5442 A    +0.4399 A    0.8154
```

Descriptive only; it does not change the deterministic decision.

## 6. Holdout and route boundary

Final holdout `2019-03/06/09/12` remains sealed.

Do not:

- create a single-shot final-holdout launcher;
- access any final-holdout month;
- return to departure bins/ratios/weights/embeddings;
- tune/refit R7 or references;
- select favorable days/months/horizons;
- add gate/MoE/router, survival/TPP, Transformer/Mamba/attention rescue.

R9 route closure remains binding.

## 7. Next action

R10-R0 is closed. The next action is a **documentation and scientific-route review using the frozen evidence only**. No additional model experiment is authorized by R10-R0.

The immediate question is no longer whether R7 has a pooled development gain; it does. The question is whether the paper/research contribution should retain R7 as a bounded development finding or whether a future, separately preregistered methodological route is scientifically justified. Until that decision is frozen, do not run another experiment.
