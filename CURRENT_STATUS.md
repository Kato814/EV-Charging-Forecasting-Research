# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R10-R0 正式结果见 [R10-R0 outcome](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_OUTCOME_20260914.md)，冻结协议见 [R10-R0 protocol](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_PROTOCOL_20260914.md)，R10 后科学路线筛选见 [Post-R10 screening](docs/JPL_POST_R10_METHOD_SCREENING_20260914.md)，论文可行性与创新性综合判断见 [Post-R10 paper-viability synthesis](docs/JPL_POST_R10_PAPER_VIABILITY_NOVELTY_SYNTHESIS_20260914.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`；R5=`STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`；R6-O0=`MIXED_COMPONENT_ORACLE_SIGNAL`；R7-C0=`PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL`；R7-D1=`TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL`；R8-C0=`NO_STABLE_HORIZON_ALIGNED_ADVANTAGE`；R9-C0=`STOP_DEPARTURE_REPRESENTATION_REFINEMENT`；R10-R0=`MIXED_DEVELOPMENT_ROBUSTNESS`, COMPLETE；Post-R10 paper viability=`CONDITIONAL_MECHANISM_PAPER_VIABILITY`。当前方法线冻结，不授权新的预测模型实验；final holdout 2019-03/06/09/12 继续封存。**

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

## 4. Scientific result retained after R10

The pooled gain is not driven by a single development month or horizon: the candidate wins all 4/4 leave-one-month-out and all 5/5 leave-one-horizon-out aggregates against both references.

The limiting evidence is day-level breadth versus S1:

```text
mean daily delta vs S1       -0.16134 A
median daily delta vs S1     +0.05723 A
top-5 gain share vs S1        60.66%
```

Per-month daily win rate vs S1 is 35.71% / 76.92% / 57.14% / 21.43% for 2019-01/04/07/10 respectively.

The accepted scientific chain is now:

1. future load composition shifts from issue-time connected sessions toward future arrivals as horizon increases;
2. R4 shows richer legal issue-time state is informative but does not remove substantial future-state ambiguity;
3. R6 shows the larger removable error source changes from existing-session evolution at 15–30 min to future-arrival error at 60–240 min;
4. R7/R7-D1 show requested-departure timing of current sessions provides incremental predictive information for the future-arrival component beyond declaration availability;
5. R8/R9 close further departure representation engineering;
6. R10 shows the resulting small total-load gain is reproducible in month/horizon deletion tests but not broad enough across days for holdout readiness.

## 5. Paper-viability / novelty decision

Formal synthesis decision:

```text
CONDITIONAL_MECHANISM_PAPER_VIABILITY
```

The current evidence does **not** support positioning R7 as a major new forecasting algorithm. The ten-stat `Departure-Aug` representation is simple, total-load improvement over S1 is only `+0.5575%`, and R10 is MIXED.

The remaining publishable candidate is instead a bounded forecasting-problem result:

> the dominant station-current forecast-error source changes with horizon under a fixed issue-time information boundary; existing-session evolution is the larger removable source at 15–30 min, future arrivals at 60–240 min, while current-session requested-departure timing provides a measurable but bounded information channel for the arrival component.

Nearest-neighbor review removes several broader novelty claims:

- horizon-dependent accuracy is already established in EV charging forecasting;
- present/future EV populations and their different uncertainty are established in scheduling;
- active-session information in station forecasting is prior art;
- SessionFlow already explicitly models origin-active and future served sessions probabilistically;
- component decomposition plus learned fusion is already represented in recent EV-load forecasting;
- requested departure is a standard ACN user-input field used in prior EV studies.

Targeted review did **not** retrieve an exact match for the full JPL evidence chain above. This is negative search evidence, not proof of absence.

## 6. Evidence limitation

The four JPL development months have supported an adaptive sequence from S1 through R10. R10 is a strong zero-fit robustness audit on those same development data, but it is not an independent validation set.

Therefore:

```text
algorithm superiority claim       NOT READY
generalization claim              NOT ESTABLISHED
mechanism/problem paper           CONDITIONAL
```

A development-only paper could be written only as a bounded case study. A stronger manuscript requires independent mechanism replication.

## 7. Holdout and route boundary

Final JPL holdout `2019-03/06/09/12` remains sealed.

Do not:

- create a final-holdout launcher;
- access any final-holdout month;
- tune/refit R7 or references;
- optimize directly against the observed R10 day-win shortfall;
- return to departure bins/ratios/weights/embeddings;
- select favorable days/months/horizons;
- add gate/MoE/router, learned reconciliation, probabilistic-model or deep-backbone rescue.

R9 and R10 route closures remain binding.

## 8. Selected next action

The next selected stage is **R11-V0: independent mechanism-replication feasibility and protocol design**. No model run or data acquisition is authorized yet.

The immediate task is an unused-source/site audit and protocol freeze. Repository-tracked formal configs are JPL-specific (`acn_jpl_*`); the current main tree contains no Caltech or Office1 configuration. The official ACN schema indicates that Caltech/JPL/Office1 expose the same session schema, including `requestedDeparture`, pilot and charging-current time series, but user-input coverage must be verified before any source is selected.

R11-V0 must first determine:

1. whether a candidate site/source is genuinely untouched by this research line;
2. whether required issue-time fields have sufficient support without favorable filtering;
3. whether the existing/future decomposition and fixed five horizons can be reproduced;
4. whether a no-tuning replication protocol can be frozen before examining outcomes.

The later decisive test, if authorized, is replication of the **mechanism evidence**, not reproduction of the exact `+0.5575%` JPL score. If independent replication materially contradicts the mechanism, archive this line rather than rescue it with another architecture.
