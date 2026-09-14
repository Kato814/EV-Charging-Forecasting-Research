# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R10-R0 正式结果见 [R10-R0 outcome](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_OUTCOME_20260914.md)，冻结协议见 [R10-R0 protocol](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_PROTOCOL_20260914.md)，R10 后科学路线筛选见 [Post-R10 screening](docs/JPL_POST_R10_METHOD_SCREENING_20260914.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`；R5=`STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`；R6-O0=`MIXED_COMPONENT_ORACLE_SIGNAL`；R7-C0=`PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL`；R7-D1=`TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL`；R8-C0=`NO_STABLE_HORIZON_ALIGNED_ADVANTAGE`；R9-C0=`STOP_DEPARTURE_REPRESENTATION_REFINEMENT`；R10-R0=`MIXED_DEVELOPMENT_ROBUSTNESS`, COMPLETE。Post-R10 screening 已完成：当前方法线冻结，不授权新的模型实验；final holdout 2019-03/06/09/12 继续封存。**

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

## 5. Post-R10 route screening

The R10 result must not be converted into a tuning target. Post-R10 screening rejects as immediate routes:

- optimizing specifically to move the R10 day-win rate above 50%;
- further requested-departure bins/ratios/weights/embeddings or horizon/month routing;
- generic probabilistic EV-load forecasting as novelty by itself;
- learned component fusion/reconciliation as a post-hoc rescue;
- standard weather/traffic/tariff covariates as the central novelty;
- gate/MoE/router or a larger backbone.

Recent literature already covers probabilistic EV-load forecasting, component-specific decomposition/fusion, online probabilistic adaptation, and active/future-session probabilistic generation. SessionFlow is especially close to any attempt to claim existing/future-session decomposition plus probabilistic session generation as novelty.

The current method line is therefore **frozen for contribution synthesis** rather than extended by another model experiment.

## 6. Holdout and route boundary

Final holdout `2019-03/06/09/12` remains sealed.

Do not:

- create a single-shot final-holdout launcher;
- access any final-holdout month;
- return to departure bins/ratios/weights/embeddings;
- tune/refit R7 or references;
- optimize directly against the observed R10 day-win shortfall;
- select favorable days/months/horizons;
- add gate/MoE/router, learned reconciliation, probabilistic-model or deep-backbone rescue.

R9 route closure remains binding.

## 7. Next action

The next authorized task is **paper-viability / novelty synthesis using frozen evidence and current literature only**. No model fitting or final-holdout access is authorized.

The contribution to evaluate is the evidence chain around a **horizon-dependent observability transition**:

> short horizons are governed mainly by evolution of sessions already connected at issue time; future-arrival uncertainty becomes the dominant removable error source from 60 min onward; issue-time requested-departure timing provides a measurable but bounded incremental signal for that future-arrival component.

The synthesis must determine whether this problem-level contribution is sufficiently distinct from SessionFlow and other recent EV forecasting work, whether R7 is more than a feature ablation when coupled to R4/R6 evidence, and whether the current development-only evidence is publishable without violating the sealed-holdout protocol.

If that synthesis is negative, archive the current line rather than rescue it with another architecture.
