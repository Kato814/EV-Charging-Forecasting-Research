# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R10-R0 outcome](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_OUTCOME_20260914.md)、[Post-R10 screening](docs/JPL_POST_R10_METHOD_SCREENING_20260914.md) 和 [Post-R10 paper-viability synthesis](docs/JPL_POST_R10_PAPER_VIABILITY_NOVELTY_SYNTHESIS_20260914.md)。

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
Post-R10 paper viability = CONDITIONAL_MECHANISM_PAPER_VIABILITY
```

Final JPL holdout `2019-03/06/09/12` remains sealed.

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

R9 permanently closed further departure-representation refinement. R10 does not reverse that closure and does not authorize the final holdout.

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

R7-D1 private-cache integrity before/after R10 was identical. No model was fit or retrained and no final-holdout data were accessed.

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

FRAGILE does not apply. READY fails only the frozen `>=50%` local-day win-rate requirement versus S1. Observed is `26/55 = 47.27%`. Therefore the preregistered result is `MIXED_DEVELOPMENT_ROBUSTNESS`.

## 5. Contribution synthesis result

The paper-viability review is complete with decision:

```text
CONDITIONAL_MECHANISM_PAPER_VIABILITY
```

### Not supported as the main claim

Do not frame the current work as:

- a new generic forecasting architecture;
- first active-session-aware station forecast;
- first existing/future-session decomposition;
- first use of requested departure;
- first probabilistic EV forecast;
- a major point-forecast accuracy improvement.

Nearest-neighbor work already covers forecast-horizon accuracy effects, current/future EV uncertainty, active-session station forecasting, component decomposition/fusion and explicit origin-active/future-session probabilistic generation (SessionFlow).

### Remaining candidate contribution

The defensible problem-level contribution is the frozen evidence chain:

> under a fixed issue-time information boundary, the dominant removable forecast-error source changes with horizon: evolution of already-connected sessions is larger at 15–30 min, while future-arrival error is larger at 60–240 min; current-session requested-departure timing contains incremental predictive information for that future-arrival component beyond declaration availability, but the total-load benefit remains bounded.

Key internal support:

```text
R4-I0 normalized M3 divergence     0.297930
R4-I0 M3 vs M2 skill               +8.19% pooled

R6 G_existing / G_arrival (A)
15 min       4.63784 /  1.15816
30 min       5.69349 /  4.38389
60 min       6.12154 / 12.10481
120 min      6.80800 / 23.16122
240 min      4.18779 / 38.21044

R7-D1 Departure-Aug vs Availability arrival improvement  +1.3318%
R7-D1 TotalDeparture vs S1 total improvement              +0.5575%
```

The targeted literature review did not retrieve an exact paper matching this full mechanism/attribution chain. This is negative search evidence only, not proof of first use or absence of prior art.

## 6. Evidence limitation

The same JPL development months `2019-01/04/07/10` have supported an adaptive sequence from S1 through R10. R10 is a rigorous zero-fit audit on those data but not an independent confirmation.

Thus:

```text
algorithm superiority      NOT READY
generalization             NOT ESTABLISHED
mechanism paper            CONDITIONAL
```

A stronger manuscript requires independent replication of the mechanism on an untouched source/site. Do not open the sealed JPL final holdout to compensate for this limitation because R10 did not grant readiness.

## 7. Next selected stage: R11-V0

`R11-V0` means **independent mechanism-replication feasibility and protocol design**. It is currently a design/audit stage only.

No local command is authorized yet. Do not download another ACN site or run a model until an unused-source/site audit and replication protocol are frozen.

Repository-tracked formal configs are currently JPL-specific (`acn_jpl_*`). The main tree contains no recorded Caltech or Office1 configuration. Official ACN documentation indicates that Caltech, JPL and Office1 share session records with user-input fields including `requestedDeparture` plus pilot/current time series, but user-input coverage is incomplete and must be audited before source selection.

R11-V0 must first resolve:

1. candidate source/site has not participated in prior local/public development decisions;
2. required legal issue-time fields have enough coverage without outcome-based filtering;
3. target remains station current in A and the existing/future split is physically reconstructible;
4. 15/30/60/120/240-min horizons and 15-min grid can remain fixed;
5. replication evaluation and STOP/PASS logic are frozen before result inspection.

If a later independent replication is authorized, it should test the mechanism evidence rather than tune for the exact JPL improvement. A material replication failure should archive this method line instead of triggering another architecture rescue.

## 8. Prohibited actions

Until an R11-V0 protocol is frozen:

- do not rerun R10;
- do not open JPL final holdout;
- do not create a final-holdout launcher;
- do not download/select an external site based on favorable prediction results;
- do not tune/refit R7 or references;
- do not optimize the observed R10 day-win threshold;
- do not add new departure features/bins/ratios/weights/embeddings;
- do not add gate/MoE/router, learned reconciliation, probabilistic or deep-model rescue;
- do not delete/select favorable days, months or horizons.

## 9. Hygiene

Preserve all worktrees, status files and private caches. No reset/clean/stash/force-push/automatic deletion. Continue the GitHub Actions conservation policy; pure documentation updates remain CI-free where workflow filters allow.
