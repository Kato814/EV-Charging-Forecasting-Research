# JPL structured mechanism probe protocol

Frozen: 2026-09-11

## 1. Purpose

This protocol is the sole authorized next scientific step after the completed S1 `MIXED_STRUCTURED_SIGNAL` failure diagnosis. It does not change the frozen S1 decision and does not authorize final-holdout access.

The diagnostic evidence shows that S1 failure is not explained by a single binary future-arrival gate or by a monotone composition rule. The reproducible weakness is a horizon-conditioned session-turnover regime: at 30 min the 25-50% realized arrival-share bin is worse than Equal in all four development months; at 60 min the 50-75% bin is worse in all four months, while the 0-25% bin is better in all four months. Local-hour diagnostics also show a reproducible sign reversal: 30/60/120 min are consistently weak near 07:00 across all development months and consistently stronger around 09:00 for the same horizons.

Therefore the next step is a low-complexity mechanism probe, not a deep-model search.

## 2. Frozen data boundary

Target remains `station_current_mean_a` in A.

Development months only:
- 2019-01
- 2019-04
- 2019-07
- 2019-10

Final holdout remains sealed:
- 2019-03
- 2019-06
- 2019-09
- 2019-12

Development processed snapshots:

```text
2019-01 e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12
2019-04 f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299
2019-07 9eea83e13ea6fbe5fef694c5de93b5bc4a82f7efe00e90e4fadd6d0b9e9ff2
2019-10 e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296
```

Source expert protocol SHA256:
`02c7809f1113aeaf20723030c96006ee0831b20ff219106da7d6968df535d71a`

Accepted baseline private manifest SHA256:
`2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd`

Accepted S1 private manifest SHA256:
`562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1`

All rolling-origin boundaries, common test rows, target windows and causal observability rules inherit the accepted development-expert / S1 protocols.

## 3. Frozen reference models

Reference forecasts remain:
- M2
- M3
- Equal = `0.5*M2 + 0.5*M3`
- S1 = direct existing-session HGB + direct future-arrival HGB

S1 remains formally `MIXED_STRUCTURED_SIGNAL`; this protocol does not reinterpret it as PASS.

## 4. Probe E: current-session continuation

### 4.1 Scientific question

Can the future contribution of sessions already connected at issue time be represented more robustly as a continuation/termination process than as direct aggregate-current regression?

### 4.2 Legal predictors

Only issue-time information may be used. Session-level predictors are restricted to the already legal M3 session fields plus calendar variables:

- `elapsed_connection_s`
- `elapsed_charging_time_proxy_s`
- `current_current_a`
- `recent_current_mean_a`
- `recent_current_peak_a`
- `recent_current_observed_ratio`
- `cumulative_current_ah`
- `cumulative_current_observed_ratio`
- `current_pilot_a`
- `requested_departure_minutes_from_issue`
- `known_kwh_requested`
- issue quarter-hour index / day of week / weekend

No disconnect time, future pilot/current, realized future composition, future-arrival identity, or other future-derived variable may enter predictors.

### 4.3 Low-complexity model

The primary continuation model is a discrete-time logistic hazard model implemented with scikit-learn only. No new dependency is authorized.

Fixed settings:
- 15-min person-period bins through 240 min;
- standardization fitted on each rolling-origin training fold only;
- L2 logistic regression;
- `C=1.0`;
- `solver=lbfgs`;
- `max_iter=1000`;
- no class weighting;
- no hyperparameter search.

The hazard is converted to horizon survival/continuation probability by cumulative product. This probability is a mechanism variable, not a reliability gate.

For the first probe, aggregate existing-session reconstruction uses survival-weighted issue-time current as the fixed mark. A positive-current magnitude learner is not added in P1-E; this deliberately isolates whether continuation modeling itself carries stable value.

### 4.4 Evaluation

Report by horizon, month and pooled:
- continuation Brier score;
- continuation log loss where defined;
- calibration by probability decile;
- reconstructed existing-component MAE/RMSE/WAPE;
- comparison with the frozen S1 existing branch.

## 5. Probe A: future-arrival count × mark

### 5.1 Scientific question

Is future-arrival contribution better represented as an event-count/intensity process times a positive current mark than as one direct aggregate-current regression target?

### 5.2 Offline targets

For each issue time and horizon on the exact S1 rows:
- `N_h`: number of sessions that arrive after issue time and contribute positive current in the target window;
- `M_h`: mean current contribution per contributing future-arrival session when `N_h > 0`;
- identity check: `N_h * M_h` must reconstruct `arrival_truth` within the frozen numerical tolerance when `N_h > 0`, and must be zero when `N_h = 0`.

These are supervised labels only. Future arrival/session identity is never a prediction-time feature.

### 5.3 Legal predictors

Use the frozen M2 feature tier only: 24-h station history/calendar plus legal current aggregate station state. No M3 future information and no realized composition share may be used.

### 5.4 Low-complexity models

No neural TPP is authorized in P1-A.

Fixed models:
- count/intensity: `PoissonRegressor(alpha=1.0, max_iter=1000)`;
- positive mark: `GammaRegressor(alpha=1.0, max_iter=1000)` on `N_h > 0` training rows only;
- standardization fitted inside each rolling-origin training fold;
- no hyperparameter search;
- arrival forecast = predicted count × predicted positive mark.

The purpose is to test target structure, not to maximize model capacity.

### 5.5 Evaluation

Report by horizon, month and pooled:
- count MAE and Poisson deviance;
- positive-mark MAE;
- reconstructed arrival-component MAE/RMSE/WAPE;
- comparison with the frozen S1 arrival branch.

## 6. Total forecast variants

Three variants are predeclared for attribution; no post-hoc best-of-three headline is allowed:

- `P1-Eonly` = Probe-E existing + frozen S1 arrival;
- `P1-Aonly` = frozen S1 existing + Probe-A arrival;
- `P1-EA` = Probe-E existing + Probe-A arrival.

`P1-EA` is the sole primary candidate. Eonly/Aonly are attribution diagnostics.

Primary comparisons: M3, Equal and S1 on identical OOS rows.

## 7. Frozen decision rules

### 7.1 Branch signal

A branch is `STABLE_COMPONENT_SIGNAL` only if all are true:
1. pooled component MAE is lower than the corresponding frozen S1 branch;
2. at least 3/5 horizons have lower component MAE;
3. at least 3/4 development months have lower pooled-over-horizon component MAE.

Otherwise that branch is `MIXED_COMPONENT_SIGNAL` if pooled MAE improves but stability conditions fail, and `NO_COMPONENT_SIGNAL` if pooled component MAE does not improve.

### 7.2 Primary P1-EA decision

`PASS_MECHANISM_PROBE` requires all:
1. pooled total MAE < Equal;
2. pooled total MAE < S1;
3. at least 3/5 horizons have MAE < Equal;
4. at least 3/4 months have pooled-over-horizon MAE < Equal;
5. no horizon degrades more than 5% relative to Equal;
6. 60-min pooled MAE < Equal, because 60 min is the pre-identified principal S1 weakness.

`MIXED_MECHANISM_PROBE` applies if P1-EA improves pooled MAE versus S1 or Equal but misses one or more stability criteria, or if exactly one branch shows a stable component signal.

`STOP_MECHANISM_ROUTE` applies if neither branch shows pooled component improvement and P1-EA beats neither S1 nor Equal pooled. In that case survival/event-process decomposition is not promoted as the core forecasting route.

Thresholds must not be changed after observing P1 results.

## 8. Mechanism validation diagnostics

These are secondary explanatory diagnostics, not optimization targets and not prediction-time oracle features:
- realized offline arrival-share bins;
- month × horizon × local-hour errors;
- special reporting at 07:00 and 09:00 for 30/60/120 min;
- negative prediction incidence;
- continuation calibration.

No realized future composition share may be used as a model input or gate.

## 9. Explicitly not authorized in P1

- final holdout access;
- pycox / DeepSurv / neural survival models;
- EasyTPP / RMTPP / NHP / THP;
- Transformer/Mamba/diffusion/state-space replacement;
- reliability gate or composition gate;
- HSMM;
- branch-specific hyperparameter search;
- calibration or clipping selected from observed test results;
- development-month reselection;
- deletion/reset/cleaning of historical worktrees, failed statuses or private caches.

## 10. Open-source boundary

Open-source implementations remain references, not novelty claims. `pycox` is a later survival benchmark candidate; `EasyTemporalPointProcess` is a later event-process benchmark candidate. ACN Portal already provides stochastic session generation based on arrival time, duration and energy demand, so joint session-event modeling itself is not novel here.

If P1 demonstrates stable signal, later method innovation may focus on an empirically supported horizon-dependent session-turnover mechanism that couples current-session continuation with future-arrival intensity/mark. If P1 does not demonstrate stable signal, this structured route must be downgraded rather than rescued by a larger neural backbone.
