# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R10-R0 outcome](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_OUTCOME_20260914.md)、[Post-R10 paper-viability synthesis](docs/JPL_POST_R10_PAPER_VIABILITY_NOVELTY_SYNTHESIS_20260914.md) 和 [R11 algorithm-direction screening](docs/JPL_R11_STATION_LEVEL_DEEP_METHOD_SCREENING_20260914.md)。

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
R11 direction = portable station-level deep method; protocol design only
```

Final JPL holdout `2019-03/06/09/12` remains sealed.

## 2. Accepted development candidate from the closed R7 line

R7 `Departure-Aug / TotalDeparture` remains the accepted development-stage candidate for the old structured line:

```text
Arrival MAE        22.7486906628 A
Total MAE          28.4354542901 A
S1 total           28.5948815297 A
Equal total        28.9172859886 A
vs S1              +0.5576% improvement
vs Equal           +1.6662% improvement
```

R9 permanently closed further departure-representation refinement. R10 does not reverse that closure and does not authorize final holdout access.

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

R7-D1 private-cache integrity before/after R10 was identical. No final-holdout data were accessed.

## 4. Why R10 is MIXED

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

FRAGILE does not apply. READY fails only the frozen `>=50%` local-day win-rate requirement versus S1. Observed is `26/55 = 47.27%`. Therefore the frozen result remains `MIXED_DEVELOPMENT_ROBUSTNESS`.

## 5. User-confirmed algorithm objective after R10

The user clarified that the project should continue algorithm exploration and that the final method should not depend on session-level inputs, because future datasets may contain only station-level load time series.

Therefore the current objective is **not** to convert the old R7 line into a session-only neural model.

The new minimum deployment contract is:

```text
required at inference:
- station-level historical load/current
- timestamp/calendar context
- optional station-level exogenous covariates when available

not required at inference:
- session IDs
- requested departure
- per-session pilot/current
- per-session energy request
- realized future sessions
```

Multi-horizon forecasting remains the task; session-level data becomes optional fine-grained supervision rather than mandatory input.

## 6. Literature collision boundary for the new algorithm line

Do not claim the following as novel by themselves:

- Transformer/PatchTST/TCN/GRU backbone choice;
- generic multi-scale temporal encoding;
- generic horizon-conditioned decoding;
- generic multi-horizon EV charging forecasting;
- generic knowledge distillation.

Recent EV-specific work already includes MFT multi-scale Transformer, ATF-PatchTST, TCN-LSTM, multiple-time-scale expert systems, multi-step Autoformer variants and multi-horizon TFT. `PhysDistill-EV` (IEEE Access, 2026, DOI `10.1109/ACCESS.2026.3726060`) already uses knowledge distillation for EV demand forecasting/edge deployment.

Thus the next method must exploit a more specific charging-data problem rather than rename a generic backbone.

## 7. Selected R11 hypothesis

The selected direction for protocol design is:

> **station-level multi-horizon forecasting with session-resolved training-only auxiliary supervision.**

This is a Learning Using Privileged Information / multi-task setup, not a session-input deployment model.

On the rich ACN source, the shared station-level encoder may be supervised by:

```text
Y(t,h) = total station current
E(t,h) = contribution from sessions already connected at issue time
A(t,h) = contribution from sessions arriving after issue time
```

The encoder and all forecast heads still receive only station-level predictors. Session-resolved data provide labels/supervision during source training.

Candidate source objective to be frozen later:

```text
L = L_total + lambda_E * L_existing + lambda_A * L_arrival + lambda_C * L_consistency
```

where `L_consistency` enforces compatibility between total and component predictions if that term survives protocol design.

On a station-level-only target dataset, training/fine-tuning can fall back to `L_total` without changing the inference feature contract.

Generic knowledge distillation is not the novelty claim. The only candidate novelty is cross-granularity privileged supervision for portable station-level forecasting, subject to a fresh nearest-neighbor and empirical test.

## 8. Next stage: R11-S0

`R11-S0` = **station-level deep-backbone screening protocol design**.

No model run is authorized yet.

Candidate backbone families to control in the protocol:

```text
GRU
TCN
N-HiTS
PatchTST
```

The backbone winner is an engineering carrier, not the paper contribution. Mamba/SSM or larger models are deferred unless lower-complexity families establish a clear need.

R11-S0 must use only station-level predictors and must freeze before any real-data fit:

1. common station-level feature set;
2. history window and fixed horizons `15/30/60/120/240 min`;
3. development chronology and validation rule;
4. exact candidate model definitions;
5. matched parameter/training budgets where practical;
6. optimizer, random-seed and early-stopping policy;
7. fit-count ceiling;
8. MAE/RMSE/WAPE plus month/horizon/day stability summaries;
9. backbone selection/STOP criteria;
10. explicit no-holdout guard.

## 9. Planned next stage if R11-S0 succeeds

`R11-M1` should compare, on identical station-level inputs and the chosen backbone:

```text
Arm 1: total-load supervision only
Arm 2: total-load + training-only existing/arrival auxiliary supervision
```

The primary scientific test is whether fine-grained source supervision improves total station-level forecasts without fine-grained inference inputs.

If this effect is absent or unstable, close the privileged-supervision route. Do not respond by adding session predictors to the deployment model or by changing backbones after seeing the result.

A later cross-dataset test must hide or lack session information at deployment and compare normal station-only training against privileged-source initialization/pretraining.

## 10. Prohibited actions

Until the R11-S0 protocol is frozen:

- do not rerun R10;
- do not open or prepare the JPL final holdout;
- do not create a final-holdout launcher;
- do not start architecture fits informally;
- do not use session fields as inference predictors in the new core;
- do not tune R7 or reopen departure representation engineering;
- do not select a target dataset after viewing favorable model results;
- do not claim generic multi-scale/horizon-aware/KD/backbone ideas as new;
- do not delete/select favorable days, months or horizons.

## 11. Hygiene

Preserve all historical worktrees, status files and private caches. No reset/clean/stash/force-push/automatic deletion. Continue the GitHub Actions conservation policy; pure documentation updates remain CI-free where workflow filters allow.
