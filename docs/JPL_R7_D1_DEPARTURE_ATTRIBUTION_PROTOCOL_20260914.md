# JPL/ACN R7-D1 departure attribution ablation protocol

Date: 2026-09-14
Status: frozen before any R7-D1 real-data fit.

## 1. Scientific question

R7-C0 established `PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL`, but the primary Departure-Aug feature block contained both requested-departure timing statistics and declaration-availability statistics (`count`, `missing_count`).

R7-D1 asks:

> Does the numerical requested-departure timing distribution carry stable incremental predictive information for future-arrival current beyond declaration availability alone?

This is an attribution ablation. It cannot alter the formal R7-C0 PASS decision and cannot authorize final-holdout access.

## 2. Frozen evidence identity

Formal R7-C0 source status SHA256:

```text
deb7fc1700fccd3eb53616bbe2e65de0941b6294d60aec58e4f63953b576bce0
```

R7-C0 decision:

```text
PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL
```

R7-C0 private manifest SHA256:

```text
172c69c71e6baef689f65ad0169b3440947675f462dd1bc9b72479e11bad6967
```

Accepted S1 private manifest SHA256:

```text
562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1
```

Accepted baseline private manifest SHA256:

```text
2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd
```

R7 reviewed executable:

```text
24e9e69413cb4b224bd1c59cdd3725b352bd27ed
```

Development months remain `2019-01/04/07/10`; final holdout `2019-03/06/09/12` remains sealed.

## 3. Frozen rows and target

Reuse exact R7/S1 rolling-origin rows and exact future-arrival current target.

Expected rows per horizon/month:

```text
2019-01 1305
2019-04 1180
2019-07 1294
2019-10 1296
pooled  5075 per horizon
all     25375 origin-horizon records
```

No row may be dropped.

## 4. Arms

### 4.1 Base-M2 — read-only reference

Reuse frozen S1 arrival predictions. No fit.

### 4.2 Departure-Availability — only newly fitted arm

Start from canonical M2 and append exactly two canonical departure-pool raw statistics:

```text
m3_requested_departure_minutes_from_issue_count
m3_requested_departure_minutes_from_issue_missing_count
```

Both are nonnullable canonical pool fields. Canonical M2 already contains three nullable indicators, therefore exact width is:

```text
201 M2 raw + 2 availability raw + 3 M2 indicators = 206 encoded
```

No timing sum/mean/std/min/max/quantiles are included.

### 4.3 Departure-Aug — read-only R7 reference

Reuse the exact accepted R7-C0 private predictions for the full ten-stat departure pool. Do not retrain.

## 5. Learner and OOS protocol

Only Departure-Availability is newly fitted.

Use:

- `HistGradientBoostingRegressor`;
- exact frozen horizon-specific M2 parameter set used in R7-C0;
- same-month daily rolling-origin;
- same target and test rows;
- native thread limit 1 where applicable;
- no retuning, feature search, clipping, calibration, nonnegative projection or post-hoc model selection.

Expected new fits:

```text
275
```

## 6. Total recombination

Reuse frozen S1 existing-session prediction `E_hat_S1`.

```text
TotalAvailability = E_hat_S1 + A_hat_Availability
TotalDeparture    = frozen accepted R7-C0 total departure prediction
```

Frozen references remain S1 and Equal.

## 7. Required reporting

For Base-M2, Departure-Availability and Departure-Aug arrival components report MAE/RMSE/WAPE/negative prediction count at:

- pooled overall;
- 5 horizons;
- 4 months;
- 20 month×horizon cells.

For S1, Equal, TotalAvailability and TotalDeparture report the same.

Also report:

```text
Availability component wins vs Base-M2: horizons / months
Availability total wins vs S1:          horizons / months
Departure-Aug wins vs Availability:      horizons / months, component and total
max horizon degradation of Departure-Aug vs Availability, component and total
```

## 8. Frozen descriptive decision

R7-D1 does not change R7-C0 PASS. It produces one attribution label.

### `TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL`

All must hold:

1. pooled Departure-Aug arrival MAE < pooled Departure-Availability arrival MAE;
2. Departure-Aug arrival wins vs Availability in >=3/5 horizons;
3. Departure-Aug arrival wins vs Availability in >=3/4 months;
4. pooled TotalDeparture MAE < pooled TotalAvailability MAE;
5. TotalDeparture wins vs TotalAvailability in >=3/5 horizons;
6. TotalDeparture wins vs TotalAvailability in >=3/4 months;
7. no horizon component or total degradation of Departure-Aug vs Availability exceeds 5%.

Interpretation: numerical requested-departure timing distribution carries stable incremental information beyond declaration availability alone.

### `AVAILABILITY_PROXY_SUFFICIENT_SIGNAL`

Applies when `TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL` is not met, and Availability itself satisfies all of:

1. pooled Availability arrival MAE < Base-M2 arrival MAE;
2. Availability arrival wins vs Base-M2 in >=3/5 horizons and >=3/4 months;
3. pooled TotalAvailability MAE < S1 and < Equal;
4. TotalAvailability wins vs S1 in >=3/5 horizons and >=3/4 months;
5. no horizon component or total degradation exceeds 5% relative to Base-M2/S1 respectively.

Interpretation: declaration availability/missingness is sufficient to reproduce the stable R7 predictive signal; a timing/release mechanism is not established.

### `MIXED_DEPARTURE_ATTRIBUTION_SIGNAL`

Applies otherwise.

Interpretation: R7 remains formally PASS, but attribution between declaration availability and numerical timing is unresolved or unstable.

The three labels are exhaustive and thresholds cannot change after results are observed.

## 9. Consequence boundary

- If `TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL`: a later horizon-aligned scheduled-departure exposure representation may be designed and preregistered.
- If `AVAILABILITY_PROXY_SUFFICIENT_SIGNAL`: do not promote a connector-release/departure-time mechanism; treat R7 as a metadata-availability or user/session-regime proxy signal.
- If MIXED: do not escalate model complexity; keep the attribution bounded.

## 10. Prohibitions

R7-D1 must not:

- access final holdout;
- retrain Base-M2, S1 or accepted R7 Departure-Aug references;
- use actual disconnect or doneCharging times as predictors;
- use future arrival identities or realized arrival share;
- retune HGB;
- fit neural, TPP, survival, gate, MoE, Set Transformer or attention models;
- drop hard cells or negative predictions;
- claim causality.

## 11. GitHub Actions conservation

Implement in an isolated branch. Perform static/targeted checks before opening the code PR. Reserve one full Actions run for the final candidate where possible; if lint-only failures occur, fix all in one commit before a single rerun.
