# JPL/ACN R10-R0 accepted-R7 robustness and holdout-readiness audit protocol

Date: 2026-09-14
Status: frozen before any R10-R0 computation.

## 1. Purpose

R9-C0 formally returned `STOP_DEPARTURE_REPRESENTATION_REFINEMENT`. Departure feature engineering is closed and R7 `Departure-Aug` remains the accepted development-stage candidate.

R10-R0 is a zero-fit, read-only robustness audit. It asks:

> Is the accepted R7 total-load gain broadly distributed across development days/months/horizons, or is the small pooled improvement driven by a narrow subset of the development sample?

R10-R0 is not a new forecasting method and cannot alter the R7 model, features, hyperparameters or predictions. It cannot access the final holdout.

## 2. Frozen source identities

Accepted R7-D1 private cache:

```text
status SHA256       48247f4ef47415c65b080584e667e9b2dba9227271ad24d93da51800756b406b
private manifest    0c816334d74173e16df6e58e55de90ca3ed5723a6775e0b6287749afa479e019
reviewed executable 2a2384781eeccf122ef43116b604f319e5637bdc
```

R9 route-closure evidence:

```text
status SHA256       d3ce58b4272e0b3fea4f11c9774c7b61a11fae443cfbb4f09210e8e22bea6d98
decision            STOP_DEPARTURE_REPRESENTATION_REFINEMENT
```

Development months remain `2019-01/04/07/10`. Final holdout `2019-03/06/09/12` remains sealed.

## 3. Read-only models

Primary accepted candidate:

```text
TotalDeparture = frozen S1 existing-session prediction + frozen Departure-Aug arrival prediction
```

Primary references:

```text
S1
Equal
```

Secondary component context may report `Departure-Aug` vs `Base-M2` and `Departure-Availability`, but no component result can replace the total-load readiness decision.

No model may be retrained. `fit_count` must equal zero.

## 4. Common-row requirement

Use only the exact common R7-D1 OOS rows already stored in the accepted private cache.

Expected counts:

```text
2019-01 1305 rows per horizon
2019-04 1180 rows per horizon
2019-07 1294 rows per horizon
2019-10 1296 rows per horizon
5075 rows per horizon
25375 origin-horizon records total
```

Issue times and local-day assignments must exactly match the frozen cache. No row deletion or favorable-cell selection is allowed.

## 5. Required deterministic robustness summaries

### 5.1 Replay

Reproduce exact accepted pooled MAE values:

```text
S1               28.594881529741027 A
Equal            28.91728598859252 A
TotalDeparture   28.435454290098633 A
```

Any mismatch fails closed.

### 5.2 Local-day paired audit

For each development local day, pool all five horizons for that day and compute:

```text
MAE_day(candidate)
MAE_day(S1)
MAE_day(Equal)
delta_day_vs_S1    = MAE_day(candidate) - MAE_day(S1)
delta_day_vs_Equal = MAE_day(candidate) - MAE_day(Equal)
```

Negative delta is better.

Report:

- number of local test days;
- candidate day-win count/rate vs S1;
- candidate day-win count/rate vs Equal;
- median and mean paired daily delta;
- per-month daily win counts/rates and mean deltas;
- positive-gain concentration: share of total positive daily gain contributed by the five largest-gain days (descriptive only).

No single day may be removed.

### 5.3 Leave-one-month-out robustness

For each one of the four development months, remove that month and recompute row-pooled total MAE for candidate, S1 and Equal over the remaining three months.

Report candidate improvement direction for all four leave-one-month-out aggregates.

### 5.4 Leave-one-horizon-out robustness

For each of the five horizons, remove that horizon and recompute row-pooled total MAE for candidate, S1 and Equal over the remaining four horizons.

Report candidate improvement direction for all five leave-one-horizon-out aggregates.

### 5.5 Existing month/horizon stability

Report candidate wins and relative degradation vs S1 and Equal for the original four month aggregates and five horizon aggregates. Do not alter the accepted R7 result.

## 6. Stratified day bootstrap (descriptive only)

Use deterministic PCG64 seed `20260914` and `10000` replicates.

Within each month independently, resample complete local days with replacement. A sampled day carries all five horizons together. For each replicate:

1. compute mean daily pooled-over-horizon delta within each month;
2. average the four monthly means with equal month weight;
3. do this separately for candidate-vs-S1 and candidate-vs-Equal.

Report 5th/50th/95th percentiles and fraction of replicates with delta < 0.

Bootstrap quantities are descriptive and are not used to change the deterministic decision thresholds below.

## 7. Frozen decision

Three outcomes are exhaustive. Evaluate FRAGILE first, then READY, otherwise MIXED.

### `FRAGILE_DEVELOPMENT_SIGNAL`

Applies if any of:

1. pooled TotalDeparture MAE is not lower than S1 or is not lower than Equal;
2. candidate wins against S1 in <=2/4 leave-one-month-out aggregates;
3. candidate wins against Equal in <=2/4 leave-one-month-out aggregates;
4. local-day pooled-over-horizon win rate is <40% against S1 or <40% against Equal.

Consequence: do not authorize final-holdout access. The accepted R7 candidate remains a development finding only.

### `READY_FOR_SINGLE_SHOT_HOLDOUT_PROTOCOL`

Applies only if FRAGILE does not apply and all conditions hold:

1. pooled TotalDeparture MAE < S1 and < Equal;
2. original month wins are >=3/4 vs S1 and >=3/4 vs Equal;
3. original horizon wins are >=3/5 vs S1 and >=3/5 vs Equal;
4. local-day pooled-over-horizon win rate is >=50% vs S1 and >=50% vs Equal;
5. candidate wins all 4/4 leave-one-month-out aggregates vs S1 and all 4/4 vs Equal;
6. candidate wins >=4/5 leave-one-horizon-out aggregates vs S1 and >=4/5 vs Equal;
7. worst original-month relative MAE degradation is <=5% vs S1 and <=5% vs Equal.

Consequence: the candidate is eligible for a separately frozen **single-shot final-holdout protocol**. This label does not itself authorize holdout access; explicit user authorization and a new pinned launcher are still required.

### `MIXED_DEVELOPMENT_ROBUSTNESS`

Applies otherwise.

Consequence: do not access final holdout yet. Review the stability evidence, but do not tune the model, alter features, select favorable cells, or add another representation rescue.

## 8. Prohibited actions

R10-R0 forbids:

- any model fit or refit;
- hyperparameter/feature search;
- clipping or calibration;
- new departure features or binning;
- excluding days/months/horizons;
- gate/MoE/router selection;
- survival/TPP/Transformer/Mamba/attention rescue;
- access to 2019-03/06/09/12;
- use of actual disconnect/doneCharging or future-session information as predictors.

## 9. Publication boundary

R10-R0 may support a statement about development robustness or fragility only. It cannot establish final generalization because the final holdout remains sealed.

All outputs should remain aggregate-only. Row-level predictions and local paths remain private.
