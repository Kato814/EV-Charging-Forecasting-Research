# JPL/ACN R6-O0 component-oracle replacement protocol

Date: 2026-09-14
Status: frozen before any R6-O0 execution.

## 1. Scientific question

The accepted evidence chain is now:

- S1 = `MIXED_STRUCTURED_SIGNAL`;
- P1 = `STOP_MECHANISM_ROUTE`, closed;
- R1 = `MIXED_JOINT_STATE_SIGNAL`, closed;
- R2 = `STOP_HIGHER_ORDER_SET_ROUTE`, closed;
- R3-C0 = `STOP_CONTROL_ENDOGENEITY_ROUTE`, closed;
- R4-I0 = `MIXED_STATE_ALIASING_SIGNAL`;
- R4-D1/R4-D2 = COMPLETE diagnostics;
- R5 = `STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`, closed.

R5 showed that future-transition-aligned latent geometry can be learned, but that geometry improvement did not produce stable or competitive point forecasts. Before another forecasting model is proposed, R6-O0 asks a narrower information question:

> In the accepted S1 decomposition, how much total OOS error would disappear if either the future contribution of sessions already connected at issue time or the future contribution of sessions arriving after issue time were replaced by its realized truth, while the other frozen S1 branch prediction is left unchanged?

R6-O0 is read-only, zero-fit and descriptive. It cannot change any prior formal decision and cannot authorize final-holdout access.

## 2. Data source and immutable identity

R6-O0 uses only the accepted S1 private OOS cache from the four development months:

```text
2019-01
2019-04
2019-07
2019-10
```

Final holdout remains sealed:

```text
2019-03
2019-06
2019-09
2019-12
```

Accepted S1 private manifest SHA-256:

```text
562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1
```

Accepted S1 protocol SHA-256:

```text
74af85044d12f3c68fe4156e6ad1ae67b6e5486b47aecd5637cd67d6539c1902
```

Expected private-cache schema:

```text
evcf-jpl-structured-s1-private-cache/v1
```

Expected files are exactly the 20 month-horizon files for horizons `15/30/60/120/240` min plus `private_manifest.json`.

Accepted OOS row counts are also frozen:

```text
2019-01: 1305 rows per horizon
2019-04: 1180 rows per horizon
2019-07: 1294 rows per horizon
2019-10: 1296 rows per horizon
pooled per horizon: 5075 rows
pooled origin-horizon records: 25375
```

Any count drift fails closed. R6-O0 does not read raw ACN/JPL data, processed feature arrays, metadata, R5 predictions or final-holdout files.

## 3. Required row-level identities

Each accepted S1 task file must contain exactly:

```text
issue_times
day_start_utc_s
y_true
existing_truth
arrival_truth
existing_predictions
arrival_predictions
structured_predictions
```

For every task file, all arrays must be one-dimensional, equal-length and finite, with strictly increasing `issue_times` and the exact month-specific row count from Section 2.

The following identities must hold within absolute tolerance `1e-6 A`:

```text
existing_truth + arrival_truth = y_true
existing_predictions + arrival_predictions = structured_predictions
```

No row may be dropped after cache validation. No clipping, calibration or favorable-cell filtering is allowed.

## 4. Oracle-replacement constructions

For every OOS row define:

```text
E_truth = existing_truth
A_truth = arrival_truth
E_hat   = existing_predictions
A_hat   = arrival_predictions

S1              = E_hat   + A_hat
OracleExisting  = E_truth + A_hat
OracleArrival   = E_hat   + A_truth
Truth           = E_truth + A_truth
```

The component errors are:

```text
e_E     = E_hat - E_truth
e_A     = A_hat - A_truth
e_total = e_E + e_A
```

The primary component-oracle replacement gains are:

```text
G_existing = MAE(S1) - MAE(OracleExisting)
G_arrival  = MAE(S1) - MAE(OracleArrival)
```

Interpretation:

- positive `G_existing`: replacing the existing-session branch by truth reduces total MAE;
- positive `G_arrival`: replacing the future-arrival branch by truth reduces total MAE;
- negative gain is possible and means the frozen branch errors were providing beneficial cancellation.

These quantities are **not** called value of perfect information (VPI), because the fixed error in the unreplaced branch can interact with the replaced branch through cancellation/reinforcement.

Also report normalized gains:

```text
g_existing = G_existing / MAE(S1)
g_arrival  = G_arrival  / MAE(S1)
```

when `MAE(S1) > 0`.

## 5. Error interaction diagnostics

For each row classify component-error interaction using tolerance `eps=1e-12 A`:

```text
reinforcement: e_E and e_A have the same nonzero sign
cancellation:  e_E and e_A have opposite nonzero signs
zero_involved: abs(e_E)<=eps or abs(e_A)<=eps
```

Define row cancellation amount:

```text
C_i = abs(e_E) + abs(e_A) - abs(e_total)
```

Numerically enforce `C_i >= -1e-10 A`; values within that tolerance are clipped to zero for aggregate reporting only.

Required interaction aggregates:

- reinforcement/cancellation/zero-involved row counts and fractions;
- mean and median `C_i`;
- total cancellation share

```text
sum(C_i) / sum(abs(e_E)+abs(e_A))
```

when the denominator is positive;
- mean absolute existing-branch error `mean(abs(e_E))`;
- mean absolute arrival-branch error `mean(abs(e_A))`;
- Pearson correlation between `e_E` and `e_A` as a descriptive aggregate only.

No causal interpretation is permitted.

## 6. Required reporting levels

For `S1`, `OracleExisting` and `OracleArrival`, report MAE primary plus RMSE and WAPE at:

1. pooled overall;
2. all 5 horizons;
3. all 4 development months;
4. all 20 month × horizon cells.

At the same levels report:

- `G_existing`, `G_arrival`;
- normalized gains;
- interaction diagnostics from Section 5.

Also report direction counts:

```text
arrival_gain_gt_existing_gain_horizons / 5
arrival_gain_gt_existing_gain_months   / 4
existing_gain_gt_arrival_gain_horizons / 5
existing_gain_gt_arrival_gain_months   / 4
positive_arrival_gain_horizons         / 5
positive_arrival_gain_months           / 4
positive_existing_gain_horizons        / 5
positive_existing_gain_months          / 4
```

Ties are not wins for either component.

## 7. Frozen descriptive classification

R6-O0 is not a forecasting-model gate, so its outcome codes are descriptive and do not modify S1–R5 decisions.

Evaluate in the following order.

### `ARRIVAL_COMPONENT_ORACLE_DOMINANT`

All must hold:

1. pooled `G_arrival > G_existing`;
2. pooled `G_arrival > 0`;
3. `G_arrival > G_existing` in at least 4/5 horizons;
4. `G_arrival > G_existing` in at least 3/4 development months;
5. `G_arrival > 0` in at least 4/5 horizons and at least 3/4 months.

Interpretation: the larger stable removable error under the S1 decomposition is associated with the future-arrival branch. This does not prove irreducibility; it only states where the accepted branch decomposition places the larger stable oracle-replacement headroom.

### `EXISTING_COMPONENT_ORACLE_DOMINANT`

Symmetric conditions:

1. pooled `G_existing > G_arrival`;
2. pooled `G_existing > 0`;
3. `G_existing > G_arrival` in at least 4/5 horizons;
4. `G_existing > G_arrival` in at least 3/4 months;
5. `G_existing > 0` in at least 4/5 horizons and at least 3/4 months.

### `CANCELLATION_DOMINATED_COMPONENT_ERRORS`

Use only if neither dominance code applies and both pooled gains are non-positive:

```text
G_existing <= 0
G_arrival  <= 0
```

This means replacing either branch by truth, while freezing the other branch prediction, does not improve pooled MAE because cross-branch error cancellation dominates the isolated replacement.

### `MIXED_COMPONENT_ORACLE_SIGNAL`

All remaining valid outcomes.

This includes cases with positive headroom in one or both components but insufficient cross-horizon/month stability for a dominance statement.

The four codes are exhaustive.

## 8. Consequences for later method selection

R6-O0 does not itself authorize a model.

If `ARRIVAL_COMPONENT_ORACLE_DOMINANT`, the next method review must focus on what forecast-time information can legally reduce uncertainty in future arrivals (for example externally known future covariates or a probabilistic formulation). It must not return to larger current-session encoders as the default response.

If `EXISTING_COMPONENT_ORACLE_DOMINANT`, there is stable headroom in currently connected-session evolution, but any next mechanism must be distinct from the already closed P1 and R2 routes.

If `CANCELLATION_DOMINATED_COMPONENT_ERRORS`, branchwise replacement/modeling is structurally suspect because aggregate accuracy depends strongly on compensating branch errors.

If `MIXED_COMPONENT_ORACLE_SIGNAL`, no new model is authorized until the instability source is analyzed without post-hoc cell selection.

## 9. Explicit prohibitions

R6-O0 must not:

- fit or retrain any model;
- access raw or processed ACN/JPL data;
- access final holdout;
- use R5 private predictions;
- alter S1 predictions or labels;
- clip/calibrate/project predictions;
- remove negative predictions;
- select favorable hours, days, months, horizons or cells;
- interpret oracle truth as a legal forecast-time feature;
- change the frozen classification after seeing results;
- call the replacement gains information-theoretic irreducibility or VPI.

## 10. Implementation and execution sequence

1. merge the R5 outcome archive;
2. merge this R6-O0 protocol before execution;
3. implement a read-only diagnostic in a separate PR;
4. add unit tests for exact private-cache identity, row reconstruction, oracle formulas, cancellation arithmetic, aggregation, exhaustive classification and holdout blocking;
5. run full pytest / compileall / Ruff;
6. release one pinned local launcher if private-cache access is required;
7. run exactly one R6-O0 diagnostic;
8. archive the aggregate outcome before any further method design.

No user-side command is authorized by this protocol alone.