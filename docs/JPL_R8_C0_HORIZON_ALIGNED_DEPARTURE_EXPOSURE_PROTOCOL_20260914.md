# JPL/ACN R8-C0 horizon-aligned requested-departure exposure protocol

Date: 2026-09-14
Status: frozen before any R8-C0 real-data fit.

## 1. Scientific question

R7-C0 established `PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL`. R7-D1 then established `TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL`: numerical requested-departure timing values carry incremental predictive information beyond declaration availability/missingness alone.

R8-C0 asks one narrower method question:

> Can the same issue-time requested-departure information be represented more effectively by aligning current-session departure exposure directly to each forecast horizon, improving future-arrival prediction and total station-current forecasting relative to the accepted generic ten-stat Departure-Aug representation?

R8-C0 is a representation probe. It does not alter R7-C0 or R7-D1 decisions and does not authorize final-holdout access.

## 2. Literature collision boundary

The method contribution must not be framed as the first use of EV departure time, remaining parking duration, active-session information, or session decomposition.

Relevant neighboring work already includes:

- forecasting EV session characteristics such as arrival/departure time and charging demand for aggregated charging/scheduling;
- prediction of plug-in duration / parking duration and charging demand;
- real-time time-to-departure modeling;
- online/session-replayable forecasting that distinguishes origin-active sessions from future sessions.

The current targeted literature check did not identify an exact construction that maps issue-time user-declared requested-departure values of currently connected sessions into forecast-horizon-specific station-level exposure for an aggregate future-arrival component. This is negative search evidence only, not a novelty or first-use claim.

Any later paper claim must therefore be bounded to the specific representation and evidence obtained here, not to departure-time use or session-aware forecasting in general.

## 3. Frozen evidence identity

Formal R7-D1 source status SHA256:

```text
48247f4ef47415c65b080584e667e9b2dba9227271ad24d93da51800756b406b
```

R7-D1 decision:

```text
TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL
```

R7-D1 private manifest SHA256:

```text
0c816334d74173e16df6e58e55de90ca3ed5723a6775e0b6287749afa479e019
```

R7-D1 reviewed executable:

```text
2a2384781eeccf122ef43116b604f319e5637bdc
```

R7-D1 implementation merge:

```text
992a611d8c3223b895818df984fc6e4f6b4521af
```

Upstream R7-C0 private manifest SHA256:

```text
172c69c71e6baef689f65ad0169b3440947675f462dd1bc9b72479e11bad6967
```

Development months remain:

```text
2019-01 / 2019-04 / 2019-07 / 2019-10
```

Final holdout remains sealed:

```text
2019-03 / 2019-06 / 2019-09 / 2019-12
```

## 4. Frozen rows and target

Reuse the exact accepted R7/R7-D1 rolling-origin rows and the exact future-arrival current target.

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

Forecast horizons are fixed at:

```text
15 / 30 / 60 / 120 / 240 min
```

## 5. Legal issue-time source

For each canonical issue time, use only current-session M3 records that were legally visible at that issue time. The only session field used to construct the new exposure variables is:

```text
requested_departure_minutes_from_issue
```

This value must be the user-declared requested-departure state available by the issue time under the existing verified M3 construction.

Prohibited as predictors include actual disconnect time, retrospective done-charging time, post-issue updates, future arrivals, realized future occupancy, or any future-session identity.

## 6. Frozen R8-C0 feature representation

For a forecast issued at time `t` with horizon `h`, let `d_i` be the issue-time-known requested-departure minutes from issue for currently connected session `i`. Missing requested-departure values remain missing and are counted separately.

Construct exactly four nonnullable station-level raw features:

```text
requested_departure_observed_count
requested_departure_missing_count
requested_departure_overdue_count
requested_departure_due_within_horizon_count
```

Definitions:

```text
observed_count = number of current sessions with finite d_i
missing_count  = number of current sessions with missing d_i
overdue_count  = number of finite d_i <= 0
due_within_horizon_count = number of finite d_i satisfying 0 < d_i <= h
```

For audit only, derive:

```text
due_after_horizon_count = observed_count - overdue_count - due_within_horizon_count
```

and require it to be a nonnegative integer for every row.

The first two features must reproduce the canonical requested-departure `count` and `missing_count` used by R7-D1 Departure-Availability on every common row. Any mismatch is a hard failure.

No mean/std/min/max/sum/quantile, proximity weighting, current weighting, pilot weighting, energy weighting, ratio, learned embedding, interaction search, or additional departure feature is allowed in R8-C0.

Because canonical M2 has 201 raw columns and three fixed nullable indicators, the exact new arm width is:

```text
201 M2 raw + 4 nonnullable horizon-exposure raw = 205 raw
205 raw + 3 M2 missing indicators               = 208 encoded
```

The horizon `h` changes the value of `due_within_horizon_count`; therefore the new feature block is horizon-specific. The horizon itself is a fixed known forecast-task parameter and is not future information.

## 7. Arms

### 7.1 Base-M2 — read-only

Reuse exact accepted R7-D1 Base-M2 arrival predictions. No fit.

### 7.2 Departure-Availability — read-only

Reuse exact accepted R7-D1 Departure-Availability predictions. No fit.

### 7.3 Departure-Aug — read-only primary reference

Reuse exact accepted R7/R7-D1 full ten-stat requested-departure predictions. No fit.

### 7.4 Horizon-Exposure — only newly fitted arm

Use canonical M2 plus exactly the four features in Section 6.

No other feature or model change is permitted.

## 8. Learner and OOS protocol

Only Horizon-Exposure is newly fitted.

Use:

- `HistGradientBoostingRegressor`;
- exact frozen horizon-specific M2 parameter set used in R7-C0/R7-D1;
- same-month daily rolling-origin;
- same future-arrival target and test rows;
- native thread limit 1 where applicable;
- no early stopping or retuning beyond the already-frozen estimator behavior;
- no feature search, hyperparameter search, clipping, calibration, nonnegative projection, or post-hoc model selection.

Expected new fits:

```text
275
```

## 9. Total recombination

Reuse the frozen accepted S1 existing-session prediction `E_hat_S1` from the R7-D1 private cache.

```text
TotalHorizonExposure = E_hat_S1 + A_hat_HorizonExposure
```

Read-only total references are:

```text
S1
Equal
TotalAvailability
TotalDeparture
```

No existing-session model is retrained.

## 10. Required reporting

For arrival components report MAE/RMSE/WAPE/negative prediction count for:

```text
Base-M2
Departure-Availability
Departure-Aug
Horizon-Exposure
```

For total station current report the same metrics for:

```text
S1
Equal
TotalAvailability
TotalDeparture
TotalHorizonExposure
```

Report at:

- pooled overall;
- all 5 horizons;
- all 4 development months;
- all 20 month×horizon cells.

Also report:

```text
Horizon-Exposure component wins vs Departure-Aug: horizons / months
Horizon-Exposure total wins vs TotalDeparture:    horizons / months
Horizon-Exposure component wins within {60,120,240}
Horizon-Exposure component/total wins vs Availability
max horizon degradation vs Departure-Aug, component and total
```

## 11. Frozen decision

Evaluate `PASS` first, then `NO_STABLE_ADVANTAGE`, else `MIXED`. Thresholds cannot change after results are observed.

### `PASS_HORIZON_ALIGNED_DEPARTURE_EXPOSURE`

All must hold:

1. pooled Horizon-Exposure arrival MAE < pooled Departure-Aug arrival MAE;
2. Horizon-Exposure arrival wins vs Departure-Aug in >=3/5 horizons;
3. Horizon-Exposure arrival wins vs Departure-Aug in >=3/4 months;
4. Horizon-Exposure arrival wins vs Departure-Aug in >=2/3 of `{60,120,240}` min;
5. pooled TotalHorizonExposure MAE < pooled TotalDeparture MAE;
6. TotalHorizonExposure wins vs TotalDeparture in >=3/5 horizons;
7. TotalHorizonExposure wins vs TotalDeparture in >=3/4 months;
8. pooled TotalHorizonExposure MAE < pooled S1 MAE and < pooled Equal MAE;
9. no horizon component degradation vs Departure-Aug exceeds 5%;
10. no horizon total degradation vs TotalDeparture exceeds 5%.

Interpretation: explicit horizon alignment improves both the targeted future-arrival representation and practical total forecast relative to the accepted generic departure pool.

### `NO_STABLE_HORIZON_ALIGNED_ADVANTAGE`

Applies if all hold:

1. pooled Horizon-Exposure arrival MAE >= pooled Departure-Aug arrival MAE;
2. pooled TotalHorizonExposure MAE >= pooled TotalDeparture MAE;
3. Horizon-Exposure arrival wins vs Departure-Aug in <=2/5 horizons and <=2/4 months;
4. TotalHorizonExposure wins vs TotalDeparture in <=2/5 horizons and <=2/4 months.

Interpretation: the tested four-feature horizon-aligned representation does not provide stable advantage over the accepted generic Departure-Aug representation. This stops this representation only; it does not overturn the R7-D1 timing-information result.

### `MIXED_HORIZON_ALIGNED_DEPARTURE_EXPOSURE_SIGNAL`

Applies otherwise.

Interpretation: some evidence favors horizon alignment, but practical or stability evidence is insufficient for promotion. Only bounded failure-source analysis is allowed; no larger backbone, gate, or feature-search rescue is authorized.

The three labels are exhaustive.

## 12. Consequence boundary

If `PASS_HORIZON_ALIGNED_DEPARTURE_EXPOSURE`:

- archive the result;
- permit a later robustness/ablation stage on the same development protocol;
- do not open final holdout yet;
- do not immediately add neural/attention/gating complexity.

If `NO_STABLE_HORIZON_ALIGNED_ADVANTAGE`:

- retain Departure-Aug as the accepted requested-departure representation;
- stop further handcrafted horizon-exposure rescue unless a new independent scientific hypothesis is frozen first.

If `MIXED`:

- perform at most one read-only or low-cost failure-source diagnostic;
- do not search feature variants or model families.

## 13. Prohibitions

R8-C0 must not:

- access final holdout;
- retrain Base-M2, Departure-Availability, Departure-Aug, S1 or Equal references;
- use actual disconnect or doneCharging times as predictors;
- use future arrival identities, realized future occupancy, realized arrival share, or future connector state;
- add current/pilot/energy weighting to departure exposure;
- use session-level identifiers or user IDs;
- retune HGB;
- fit neural, TPP, survival, gate, MoE, Set Transformer, attention, Transformer or Mamba models;
- drop hard cells or negative predictions;
- reinterpret the decision thresholds after observing results;
- claim causality or first use.

## 14. GitHub Actions conservation

Implement in an isolated branch. Perform static and targeted checks before opening the code PR. Open only one code PR after the implementation, CLI and tests are complete. Use full GitHub Actions only for the final candidate where possible. Pure protocol/status/outcome documentation must not trigger full CI.
