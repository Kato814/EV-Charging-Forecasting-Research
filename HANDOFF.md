# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R10-R0 outcome](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_OUTCOME_20260914.md)、[R10-R0 protocol](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_PROTOCOL_20260914.md) 和 [Post-R10 screening](docs/JPL_POST_R10_METHOD_SCREENING_20260914.md)。

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
R10-R0 = MIXED_DEVELOPMENT_ROBUSTNESS, COMPLETE
Post-R10 = method line frozen for contribution synthesis; no model run authorized
```

Final holdout `2019-03/06/09/12` remains sealed.

## 2. Accepted development candidate

The accepted development-stage candidate remains R7 `Departure-Aug / TotalDeparture`:

```text
Arrival MAE        22.7486906628 A
Total MAE          28.4354542901 A
S1 total           28.5948815297 A
Equal total        28.9172859886 A
vs S1              +0.5576% improvement
vs Equal           +1.6662% improvement
```

R9 permanently closed further departure-representation refinement. R10 does not reverse that closure.

## 3. R10-R0 frozen identity and outcome

```text
status file                    evcf_r10_r0_status_20260914T124334Z.json
status SHA256                  058ec6b1196c76e884973e36f851e5c05831bb16fc6533b240d445c4dd82dda8
protocol commit                05dc342d376425c13f09ee68356583223203aae3
reviewed executable            753f9adc5c5bd28022d6c1ce3e4c54fb3f76c3e0
implementation merge           062fb6cee5a14a0cd5a09bf3a4e41f80cc797f9f
launcher SHA256                e4d247424274c926a07dcdee9e99eab0f3f88f5cdd1e7efec06de231ac0c6949
fit_count                      0
status                         COMPLETE
decision                       MIXED_DEVELOPMENT_ROBUSTNESS
holdout accessed               false
```

Source R7-D1:

```text
status SHA256       48247f4ef47415c65b080584e667e9b2dba9227271ad24d93da51800756b406b
private manifest    0c816334d74173e16df6e58e55de90ca3ed5723a6775e0b6287749afa479e019
reviewed executable 2a2384781eeccf122ef43116b604f319e5637bdc
```

R7-D1 private-cache integrity before/after R10 was identical. No model was fit or retrained and no network data were acquired.

## 4. Why R10 is MIXED

Frozen decision support:

```text
                                        vs S1          vs Equal
pooled improvement                      +0.5575%       +1.6662%
original month wins                     3/4            3/4
original horizon wins                   4/5            4/5
local-day win rate                      47.27%         56.36%
leave-one-month-out wins                4/4            4/4
leave-one-horizon-out wins              5/5            5/5
worst original-month degradation        1.004%         1.675%
```

FRAGILE does not apply because pooled performance is better than both references, leave-one-month-out is 4/4 vs both, and both local-day win rates exceed 40%.

READY fails the required `>=50%` local-day win rate versus S1. Observed is `26/55 = 47.27%`; all other frozen READY conditions pass.

Therefore the preregistered result is `MIXED_DEVELOPMENT_ROBUSTNESS`.

## 5. Scientific reading

The pooled gain survives deletion of any single development month and any single horizon, so it is not a one-month or one-horizon artifact.

The weakness is day-level coverage versus S1. Mean daily delta is favorable (`-0.16134 A`) but median daily delta is slightly unfavorable (`+0.05723 A`), and the top five favorable days contribute about 60.66% of positive daily gain.

Supported claim: requested-departure timing has reproducible incremental predictive information and a small pooled total-load development gain, but total-load improvement is not broad enough across development days for holdout readiness.

## 6. Post-R10 scientific-route decision

Do **not** respond to the R10 shortfall by tuning toward the 50% threshold. The following immediate rescue classes remain closed or are rejected as novelty cores:

- new departure features/bins/ratios/weights/embeddings;
- month/horizon routing, gate or MoE;
- robust/day-weighted loss chosen after R10;
- generic probabilistic EV forecasting;
- component-fusion/reconciliation added only to recover total-load MAE;
- generic weather/traffic/tariff feature addition;
- Transformer/Mamba/attention or another larger backbone.

The closest 2026 literature already includes EV-specific probabilistic multi-horizon forecasting, component-specific decomposition/fusion, online probabilistic adaptation, and SessionFlow-style origin-active/future-session probabilistic generation. Those concepts cannot be promoted to novelty simply because the current point forecast is MIXED.

The current method line is therefore frozen for contribution synthesis.

## 7. Next action

There is **no authorized model run** at this point.

The next task is a **paper-viability / novelty synthesis** based only on frozen evidence plus current literature. It must evaluate whether the following problem-level contribution is sufficiently distinct and substantial:

> short-horizon forecast error is governed mainly by evolution of sessions already connected at issue time; future-arrival uncertainty becomes the dominant removable error source from 60 min onward; requested-departure timing of currently connected sessions carries measurable but bounded issue-time information about that future-arrival component.

The synthesis must explicitly compare this claim against SessionFlow and other current EV forecasting work, judge whether R7 is more than a feature ablation when tied to R4/R6, and judge whether the development-only evidence can support publication while final holdout remains sealed.

If the synthesis is negative, archive this method line. Do not rescue it with another model.

Do not:

- rerun R10;
- open final holdout;
- create a holdout launcher;
- tune/refit models;
- optimize directly for the observed R10 day-win threshold;
- add new departure representations;
- add gate/MoE/router/probabilistic/reconciliation/deep-model rescue;
- delete/select favorable days, months or horizons.

## 8. Hygiene

Preserve all worktrees, status files and private caches. No reset/clean/stash/force-push/automatic deletion. Pure documentation updates remain CI-free where repository workflow filters allow.
