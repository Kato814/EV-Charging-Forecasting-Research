# JPL/ACN R4-D2 query-geometry regime diagnostic protocol

Date: 2026-09-13
Status: frozen after the single formal R4-D1 run and before any R4-D2 data run.

## 1. Purpose

R4-D1 established two facts simultaneously:

1. M3 selects histories much closer in session-state geometry but much farther in instantaneous station-current level than Level-Control.
2. This aggregate geometry conflict does not by itself explain the horizon/month performance reversal. Geometry is nearly invariant across horizon, and the April/October reversal is much larger than their aggregate geometry difference.

R4-D2 asks one narrower question:

> Can a target-free, issue-time-only measure of the current-continuity versus session-state geometry conflict stratify when frozen M3 analogs have more or less future divergence than frozen Level analogs?

R4-D2 is a zero-fit/read-only diagnostic. It does not create a forecasting model, does not alter analog identities, and cannot change the formal R4-I0 decision.

## 2. Frozen source evidence

R4-D2 is bound to:

```text
R4 decision                    MIXED_STATE_ALIASING_SIGNAL
R4 source status SHA256        a8b7142e0361b5cd56e53c7de99d8e699a27e1aee78728810773c127f385823f
R4-D1 source status SHA256     522af0c71236ad3da7d8de006875394420f702aa650613660e619d8dd0048c94
R4-D1 reviewed executable      51048259f8d9c61f324db07e05ded0a3c2f9d48e
R4-D1 implementation merge    1a55796aa79ce976d115ac5b508ebb250a77c6a6
```

Development months remain `2019-01/04/07/10`. Final holdout `2019-03/06/09/12` remains sealed.

## 3. Exact replay requirement

Before publishing any R4-D2 quantity, the implementation must exact-replay R4-D1 using the same development data, supported rows, fold-local preprocessing and frozen Level/M2/M3 analog identities.

The recomputed R4-D1 aggregates must match the accepted R4-D1 status with `rtol=0`, `atol=1e-12` for:

- pooled overall;
- all 5 horizons;
- all 4 months;
- all 20 month × horizon cells;
- all D1 geometry means/medians, overlap summaries and future-divergence summaries.

A replay mismatch invalidates R4-D2. It does not authorize a new R4/D1 run or any threshold change.

## 4. Frozen per-query geometry quantities

For every supported query `i`, reuse the D1 quantities from the original frozen analog identities:

```text
C_Level(i), C_M3(i)       instantaneous standardized current-level gap
QE_Level(i), QE_M3(i)     M3 session-extension RMS geometry
Q3_Level(i), Q3_M3(i)     complete M3 RMS geometry
O_Level_M3(i)             neighbor overlap in {0,1,2,3}
```

No analog is added, removed, reordered or replaced.

## 5. Target-free geometry-conflict scores

Use fixed `eps = 1e-12` only to protect zero denominators.

### 5.1 Current-continuity loss

```text
S_current(i) = (C_M3(i) - C_Level(i)) / (C_M3(i) + C_Level(i) + eps)
```

Positive values mean M3 sacrifices instantaneous current similarity relative to Level.

### 5.2 Session-extension gain

```text
S_session(i) = (QE_Level(i) - QE_M3(i)) / (QE_Level(i) + QE_M3(i) + eps)
```

Positive values mean M3 gains session-extension similarity relative to Level.

### 5.3 Complete-state gain

```text
S_full(i) = (Q3_Level(i) - Q3_M3(i)) / (Q3_Level(i) + Q3_M3(i) + eps)
```

This is a secondary issue-time-only summary of total M3-geometry gain.

### 5.4 Primary balance score

The only primary regime score is frozen before R4-D2 is run:

```text
B(i) = S_session(i) - S_current(i)
```

Larger `B` means the normalized session-geometry gain is larger relative to the normalized current-continuity loss. `B` is computed without future targets and cannot use month/horizon-specific fitted weights.

## 6. Future diagnostic outcome

After `B` is fixed, reuse the original D1 future divergence:

```text
A(i,h) = D_Level(i,h) - D_M3(i,h)
```

Positive `A` means M3 analogs have less future divergence than Level analogs; negative `A` means Level analogs are better.

Also report the binary descriptive indicator `I[A>0]`. It is an outcome summary only and may not alter `B`, analog selection, support or row inclusion.

## 7. Frozen stratification

Compute the 25th, 50th and 75th percentiles of pooled `B` over all supported development records using NumPy quantiles with `method="higher"`. These three cut points are determined from issue-time geometry only; future targets are not used.

Use those same pooled cut points everywhere to form four ordered bins `Q1..Q4`. Do not recompute cut points separately by month or horizon.

For each bin report:

- record count;
- mean and median `B`;
- mean and median `S_current`, `S_session`, `S_full`;
- mean and median `A`;
- fraction with `A>0`;
- mean `O_Level_M3`.

## 8. Required aggregation and association

Report the four fixed `B` bins for:

- pooled overall;
- all 5 horizons;
- all 4 months;
- all 20 month × horizon cells.

Also report, without fitting any model:

- pooled Spearman rank correlation between `B` and `A`;
- Spearman correlation for each of 5 horizons and 4 months;
- pooled and grouped `Q4-Q1` difference in mean `A`;
- pooled and grouped `Q4-Q1` difference in `A>0` fraction.

No selected-hour, selected-day, selected-station, alternative quantile or favorable-subset analysis is allowed.

## 9. Interpretation boundary

R4-D2 has no forecasting PASS/MIXED/STOP decision and cannot modify R4-I0 or R4-D1.

It may support only bounded conclusions:

- whether an issue-time geometry-conflict score has monotonic association with M3-vs-Level future advantage;
- whether such association is stable or unstable across horizons/months;
- whether a later, separately preregistered adaptive two-branch forecasting method is scientifically justified for development.

A positive D2 pattern is not itself evidence that a gated predictor improves forecast accuracy. Any such method must be specified and evaluated separately.

## 10. Explicit prohibitions

R4-D2 must not:

- change K, same-clock candidates, q95 support or supported rows;
- construct new analogs or a hybrid/two-stage neighbor rule;
- learn weights for `B`;
- tune `eps`, quantile count or cut points using future targets;
- train a classifier, regressor, gate or forecasting model;
- use calendar month as a gating input;
- perform PCA, metric learning or feature selection;
- access final holdout;
- choose a favorable score after seeing results. `B` is the sole primary score.

## 11. Execution sequence

This protocol alone authorizes no local run.

Required sequence:

1. archive R4-D1 outcome and merge this R4-D2 protocol;
2. separate zero-fit R4-D2 implementation PR;
3. tests for exact D1 replay, score formulas, pooled target-blind quartiles and fixed-cutpoint grouped summaries;
4. full pytest/compileall/Ruff;
5. pinned development-only launcher;
6. exactly one R4-D2 run;
7. archive the diagnostic;
8. only then decide whether to preregister an adaptive Level/M3 forecasting model.
