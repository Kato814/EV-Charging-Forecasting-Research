# JPL/ACN R9-C0 forecast-grid requested-departure profile protocol

Date: 2026-09-14
Status: frozen before any R9-C0 real-data fit.

## 1. Scientific question

R7-D1 established `TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL`, while R8-C0 returned `NO_STABLE_HORIZON_ALIGNED_ADVANTAGE`: a single target-window count `0 < d_i <= h` did not preserve the useful timing signal.

R9-C0 asks the final narrow representation question:

> Does retaining the full issue-time requested-departure distribution shape over the fixed canonical forecast grid improve future-arrival current prediction relative to the accepted generic ten-stat Departure-Aug representation?

This is the final preregistered departure-representation refinement probe. It cannot access the final holdout and cannot reopen closed gate/MoE, survival/TPP, higher-order set, control-endogeneity, FTAR, Transformer/Mamba or feature-search routes.

## 2. Frozen source evidence

Formal R8-C0 status SHA256:

```text
5f69386c62bff1314cc16de94d1667421e872aada739194e41ab41c5f5e2a6fe
```

R8-C0 decision:

```text
NO_STABLE_HORIZON_ALIGNED_ADVANTAGE
```

R8-C0 private manifest SHA256:

```text
ec11e3555727259960e355b12ac1867d14adef876fedf2d7580daaa3366ff2d2
```

R8 reviewed executable:

```text
91ab4a18f776b33e00a439ab10c74fd42a04f9b5
```

Accepted R7-D1 source remains:

```text
status SHA256       48247f4ef47415c65b080584e667e9b2dba9227271ad24d93da51800756b406b
private manifest    0c816334d74173e16df6e58e55de90ca3ed5723a6775e0b6287749afa479e019
decision            TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL
```

Development months remain `2019-01/04/07/10`; final holdout `2019-03/06/09/12` remains sealed.

## 3. Rows, target and learner

Reuse the exact R7/R8 rolling-origin OOS rows and exact future-arrival current target.

Expected rows:

```text
2019-01 1305 per horizon
2019-04 1180 per horizon
2019-07 1294 per horizon
2019-10 1296 per horizon
pooled  5075 per horizon
all     25375 origin-horizon records
```

Only one new arm is fitted. Use:

- `HistGradientBoostingRegressor`;
- exact frozen horizon-specific M2 parameters;
- same-month daily rolling-origin;
- same target and OOS rows;
- native thread limit 1;
- no retuning, early model selection, clipping, calibration, nonnegative projection or feature search.

Expected new fits:

```text
275
```

## 4. Forecast-grid departure profile

Start from canonical M2. Using only issue-time-known `requested_departure_minutes_from_issue` for sessions connected at the issue time, append exactly nine nonnullable station-level count features:

```text
requested_departure_observed_count
requested_departure_missing_count
requested_departure_overdue_count
requested_departure_bin_0_15_count
requested_departure_bin_15_30_count
requested_departure_bin_30_60_count
requested_departure_bin_60_120_count
requested_departure_bin_120_240_count
requested_departure_beyond_240_count
```

Exact definitions for finite requested-departure offset `d_i` in minutes:

```text
overdue       d_i <= 0
bin_0_15      0 < d_i <= 15
bin_15_30     15 < d_i <= 30
bin_30_60     30 < d_i <= 60
bin_60_120    60 < d_i <= 120
bin_120_240   120 < d_i <= 240
beyond_240    d_i > 240
```

Required identities on every row:

```text
observed_count = overdue + bin_0_15 + bin_15_30 + bin_30_60
                 + bin_60_120 + bin_120_240 + beyond_240
connected_session_count = observed_count + missing_count
```

`observed_count` and `missing_count` must reproduce the accepted canonical requested-departure count/missing-count fields exactly.

All nine new features are integer-valued, nonnegative and nonnullable.

Exact feature width:

```text
201 M2 raw + 9 profile counts = 210 raw
210 raw + 3 fixed M2 missing indicators = 213 encoded
```

No departure mean/std/min/max/quantiles, ratios, proximity scores, current/pilot/energy weighting, data-driven bins, learned embedding or horizon-specific feature subset is allowed.

The same nine profile features are supplied to every horizon-specific HGB. The forecast grid itself defines the representation; there is no per-horizon feature search.

## 5. Read-only references

Replay from the exact accepted R8 private cache without retraining:

```text
Base-M2
Departure-Availability
Departure-Aug
Horizon-Exposure
S1
Equal
TotalAvailability
TotalDeparture
TotalHorizonExposure
```

Primary comparator is `Departure-Aug` for the arrival component and `TotalDeparture` after recombination. `Horizon-Exposure` is a secondary failed-R8 reference only.

## 6. Total recombination

Reuse frozen S1 existing-session prediction `E_hat_S1`:

```text
TotalForecastGridProfile = E_hat_S1 + A_hat_ForecastGridProfile
```

No existing-session model is retrained.

## 7. Required reporting

For Base-M2, Departure-Availability, Departure-Aug, Horizon-Exposure and Forecast-Grid Profile arrival predictions report MAE/RMSE/WAPE/negative-prediction count at:

- pooled overall;
- 5 horizons;
- 4 months;
- 20 month × horizon cells.

For S1, Equal, TotalAvailability, TotalDeparture, TotalHorizonExposure and TotalForecastGridProfile report the same.

Also report:

```text
ForecastGridProfile wins vs Departure-Aug: horizons / months
ForecastGridProfile wins within {60,120,240}
TotalForecastGridProfile wins vs TotalDeparture: horizons / months
secondary wins vs failed R8 Horizon-Exposure / TotalHorizonExposure
max horizon degradation vs Departure-Aug / TotalDeparture
pooled improvements vs Departure-Aug / TotalDeparture / S1 / Equal
```

## 8. Frozen decision

Three outcomes are exhaustive. Evaluate STOP first, then PASS, otherwise MIXED.

### `STOP_DEPARTURE_REPRESENTATION_REFINEMENT`

Applies if any of:

1. ForecastGridProfile wins against Departure-Aug in <=1/5 component horizons;
2. ForecastGridProfile wins against Departure-Aug in <=1/4 months;
3. both pooled ForecastGridProfile arrival MAE >= pooled Departure-Aug arrival MAE **and** pooled TotalForecastGridProfile MAE >= pooled TotalDeparture MAE.

Consequence: close departure-representation refinement. Retain accepted R7 Departure-Aug as the development candidate. Do not create additional engineered departure representations.

### `PASS_FORECAST_GRID_DEPARTURE_PROFILE`

Applies only if STOP does not apply and all conditions hold:

1. pooled ForecastGridProfile arrival MAE < pooled Departure-Aug arrival MAE;
2. component wins vs Departure-Aug in >=3/5 horizons;
3. component wins vs Departure-Aug in >=3/4 months;
4. component wins in `{60,120,240}` in >=2/3 horizons;
5. pooled TotalForecastGridProfile MAE < pooled TotalDeparture MAE;
6. total wins vs TotalDeparture in >=3/5 horizons;
7. total wins vs TotalDeparture in >=3/4 months;
8. pooled TotalForecastGridProfile MAE < S1 and < Equal;
9. maximum component and total horizon degradation vs Departure-Aug/TotalDeparture is <=5%.

Consequence: Forecast-Grid Profile becomes the preferred departure representation for the next robustness/holdout-readiness stage. This does not itself authorize final-holdout access.

### `MIXED_FORECAST_GRID_DEPARTURE_PROFILE_SIGNAL`

Applies otherwise.

Consequence: close departure-representation refinement and retain R7 Departure-Aug as the accepted development candidate. No further feature-engineering rescue is allowed.

Thresholds cannot change after results are observed.

## 9. Interpretation boundary

R9-C0 tests representation sufficiency, not causality. Requested departure is user-declared intended timing, not actual disconnect. The model may not use actual disconnect/doneCharging, future arrival identities, realized future occupancy/share, or future connector state as predictors.

Do not claim first use of departure time, remaining parking duration, active-session state or session decomposition. Existing EV scheduling and forecasting literature already uses those concepts. Current targeted literature search did not retrieve this exact fixed forecast-grid requested-departure histogram in online aggregate station-load forecasting; negative search evidence is not proof of novelty.

## 10. GitHub Actions conservation

Implement on an isolated branch. Perform static/manual/targeted review before opening the code PR. Use one full Actions run for the final candidate where possible; if a lint-only failure occurs, fix all lint issues in one commit before one rerun.
