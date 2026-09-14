# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R10-R0 outcome](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_OUTCOME_20260914.md)、[Post-R10 paper-viability synthesis](docs/JPL_POST_R10_PAPER_VIABILITY_NOVELTY_SYNTHESIS_20260914.md)、[R11 direction screening](docs/JPL_R11_STATION_LEVEL_DEEP_METHOD_SCREENING_20260914.md) 和最新 [R11-S0 protocol](docs/JPL_R11_S0_STATION_LEVEL_DEEP_BACKBONE_SCREENING_PROTOCOL_20260914.md)。

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
R11 direction = portable station-level deep method
R11-S0 protocol = FROZEN; implementation pending; no real fit authorized
```

Final JPL holdout `2019-03/06/09/12` remains sealed.

## 2. Closed R7 line remains unchanged

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

## 3. R10 frozen identity and result

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

R10 is MIXED because the local-day win rate against S1 is `26/55 = 47.27%`, below the frozen 50% READY threshold. All other READY conditions pass. This result must not be retuned away.

## 4. User-confirmed algorithm objective

The project is continuing algorithm exploration, but the final forecasting core must remain usable on datasets that contain only station-level load time series.

Required at inference:

```text
- station-level historical load/current
- timestamp/calendar context
- optional station-level exogenous covariates only in later studies when available
```

Not required at inference:

```text
- session IDs
- requested departure
- per-session pilot/current
- per-session energy request
- existing/arrival truth labels
- realized future sessions
```

Multi-horizon forecasting is the task; session resolution is optional training information, not the deployment data format.

## 5. Selected research hypothesis

The selected method line is:

> **station-level multi-horizon forecasting with session-resolved training-only auxiliary supervision.**

This is a Learning Using Privileged Information / multi-task setup.

On ACN source data, later R11-M1 may use:

```text
Y(t,h) = total station current
E(t,h) = contribution from sessions already connected at issue time
A(t,h) = contribution from sessions arriving after issue time
```

as training labels. The deployed encoder and forecast head still receive only station-level predictors.

Generic multi-scale encoding, Transformer/PatchTST/TCN choice, multi-horizon forecasting and knowledge distillation are not novelty claims.

## 6. R11-S0 frozen input/data contract

Target:

```text
station_current_mean_a (A)
```

Development only:

```text
2019-01 / 2019-04 / 2019-07 / 2019-10
```

Final holdout stays sealed:

```text
2019-03 / 2019-06 / 2019-09 / 2019-12
```

History/horizons:

```text
history window = 96 x 15-min bins = 24 h
horizons       = 15 / 30 / 60 / 120 / 240 min
```

Historical sequence channels:

```text
standardized aggregate station current
history-validity mask
```

Generic issue/target calendar sin/cos + weekend + normalized horizon are allowed. No session-derived station count/pilot/departure field is allowed.

Formal test origins must match the exact common frozen OOS set:

```text
2019-01 1305
2019-04 1180
2019-07 1294
2019-10 1296
pooled  5075 origins = 25375 origin-horizon records
```

A mismatch fails before fitting.

## 7. R11-S0 chronological folds

For each target development month:

```text
training:
- all eligible earlier development months
- target-month local days 1-14

validation:
- target-month local days 15-17

test:
- target-month local day >=18
- exact frozen common OOS origins only
```

No random train/test split. Validation is only for early stopping and is not merged back into training.

## 8. Frozen deep candidates

### GRU

```text
2 layers
hidden 96
dropout 0.10
```

### TCN

```text
5 causal residual blocks
channels 64
kernel 3
dilations 1 / 2 / 4 / 8 / 16
2 convs per block
dropout 0.10
```

### N-HiTS

```text
3 stacks
pool factors 1 / 4 / 16
1 block per stack
2 hidden MLP layers
width 128
```

### PatchTST control

```text
context 96
patch 16
stride 8
d_model 64
heads 4
layers 2
FFN 128
dropout 0.10
RevIN disabled
```

Target trainable parameter band:

```text
50k <= params <= 250k
```

Only width-only correction before real-label fitting is permitted if a shape-only parameter preflight finds a frozen arm outside this band. Final widths/counts must be committed before the formal run.

## 9. Station-only reference and training budget

Reference:

```text
Station-HGB
```

It uses the same 96-bin station history/mask + calendar information and frozen M2 HGB hyperparameters per horizon; it uses none of M2's session-derived fields.

Deep common training:

```text
optimizer    AdamW
lr           1e-3
weight_decay 1e-4
batch        256
max epochs   120
patience     12
min delta    1e-4 standardized MAE
grad clip    1.0
loss         mean SmoothL1 across 5 standardized targets
float32      yes
AMP          no
formal GPU   RTX 5080 / cuda:0
```

Frozen seeds:

```text
2026091401
2026091402
2026091403
```

Fit ceiling:

```text
4 architectures x 3 seeds x 4 folds = 48 deep fits
Station-HGB: 4 folds x 5 horizons     = 20 fits
formal total                          = 68 fits
```

No ensemble is allowed.

## 10. Frozen R11-S0 decisions

Eligibility for R11-M1 carrier selection, using median-of-three-seed deep metrics:

```text
pooled MAE <= 1.02 * Station-HGB
worst horizon degradation <= 10%
worst month degradation   <= 10%
pooled seed spread        <= 3%
all four folds complete
```

Decisions:

```text
SELECT_STATION_BACKBONE
MIXED_STATION_BACKBONE
STOP_DEEP_CORE_ROUTE
```

If multiple arms are eligible, select the lowest median pooled MAE. If top two differ by <0.25% relative pooled MAE, choose the lower trainable-parameter count.

`MIXED` means no automatic R11-M1. `STOP` means do not rescue with Mamba, a larger Transformer or a fifth architecture inside R11-S0.

S1/Equal/R7 may be shown only as richer-information context and are not the S0 eligibility anchor.

## 11. Planned R11-M1

Only after `SELECT_STATION_BACKBONE` may a separate protocol test:

```text
Arm 1: station-level input + total supervision only
Arm 2: same input/backbone + training-only E/A auxiliary supervision
```

Inference remains station-only. If privileged supervision does not improve total-load prediction stably, close the route rather than adding session predictors to deployment.

## 12. Immediate next action

There is still **no authorized real-data R11 fit**.

Next work is implementation only:

1. isolated R11 code branch;
2. station-only dataset builder and chronological folds;
3. Station-HGB + GRU/TCN/N-HiTS/PatchTST implementations;
4. tests for no-session contract, common-row identity, chronology, missing-history masks and five-output shapes;
5. shape-only parameter-count preflight;
6. CUDA/RTX 5080 preflight, no CPU fallback for formal run;
7. static/targeted tests first;
8. one final code PR / one full CI where possible;
9. freeze reviewed executable and pinned launcher;
10. only then run the formal 68-fit screen once.

## 13. Prohibited actions

- no JPL final-holdout access/preparation;
- no informal R11 fits before executable freeze;
- no R7 rescue or new departure feature engineering;
- no session fields as R11 inference inputs;
- no post-result tuning of context length, architecture depth, patch length, dilation pattern, LR/dropout or seeds;
- no fifth backbone after observing S0;
- no ensemble/clipping/calibration rescue;
- no favorable day/month/horizon/dataset selection;
- no generic backbone/multi-scale/multi-horizon/KD novelty claim.

Preserve all historical worktrees/status/private caches. No reset/clean/stash/force-push/automatic deletion. Continue GitHub Actions conservation.
