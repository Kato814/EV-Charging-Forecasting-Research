# JPL/ACN R7-C0 current-session departure-state → future-arrival protocol

Date: 2026-09-14
Status: frozen before any R7-C0 real-data fit.

## 1. Scientific question

R6-O0 established a stable horizon transition in removable S1 error: existing-session evolution dominates 15–30 min, while future-arrival contribution dominates 60–240 min across all four development months.

R7-C0 asks one narrower question:

> Does the issue-time requested-departure distribution of sessions already connected at the station provide stable incremental predictive information for the future-arrival current component beyond the frozen M2 arrival predictor, and does any component improvement survive recombination into total station-current forecasts?

This is a development-only predictive mechanism probe. It does not make a causal connector-capacity claim and cannot alter prior S1–R6 decisions.

## 2. Frozen evidence identity

Source R6-O0 status SHA256:

```text
52bf3d7753b095a0faf39bc9aaefbd07b2c11f406ab05abd4bd1534e921dacce
```

Source R6-O0 decision:

```text
MIXED_COMPONENT_ORACLE_SIGNAL
```

Accepted S1 private manifest SHA256:

```text
562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1
```

Accepted baseline M2/M3 private manifest SHA256:

```text
2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd
```

Accepted source expert protocol SHA256:

```text
02c7809f1113aeaf20723030c96006ee0831b20ff219106da7d6968df535d71a
```

Accepted S1 protocol SHA256:

```text
74af85044d12f3c68fe4156e6ad1ae67b6e5486b47aecd5637cd67d6539c1902
```

Development months and processed snapshots remain:

```text
2019-01 e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12
2019-04 f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299
2019-07 9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2
2019-10 e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296
```

Final holdout remains sealed:

```text
2019-03 / 2019-06 / 2019-09 / 2019-12
```

No new data acquisition is authorized.

## 3. Frozen rows and targets

All causal and OOS rules inherit the accepted development-expert/S1 protocols:

- timezone: `America/Los_Angeles`;
- local test days start at day 18;
- refit at local midnight daily;
- same-month history only;
- fit issue rule: `issue_time < refit_cutoff`;
- fit label rule: `issue_time + horizon <= refit_cutoff`;
- test rule: all formal rows on the local test day;
- horizons: `15/30/60/120/240 min`.

The future-arrival target is the exact frozen S1 `arrival_truth`:

```text
y_arrival(t,h) = current contribution in [t+h-15min, t+h)
                 from sessions with connectionTime > t
```

The total truth is the exact frozen S1 `y_true`.

Expected OOS rows per horizon and month are fixed:

```text
2019-01  1305
2019-04  1180
2019-07  1294
2019-10  1296
pooled   5075 per horizon
all      25375 origin-horizon records
```

Candidate predictions must align exactly with frozen S1 issue times/truth. No row may be dropped.

## 4. Frozen feature arms

### 4.1 Base-M2 reference

Use the already accepted frozen S1 arrival predictions. Do not retrain the reference for headline comparison.

Canonical M2 is 201 raw / 204 encoded dimensions.

### 4.2 Departure-Aug — primary arm

Start with canonical M2 and append only the ten canonical M3 raw pooled features for:

```text
requested_departure_minutes_from_issue
```

in the frozen order:

```text
count
sum
mean
std
minimum
maximum
p25
p50
p75
missing_count
```

The canonical pool nullable mask is:

```text
False, False, True, True, True, True, True, True, True, False
```

Therefore seven fixed missing-indicator columns are appended for the nullable departure statistics.

The exact Departure-Aug width is:

```text
201 M2 raw + 10 departure raw + 3 M2 indicators + 7 departure indicators = 221
```

No `known_kwh_requested`, elapsed/current/pilot/cumulative-current session pool, individual session tuples, pairwise features or future-derived quantities are allowed in this primary arm.

### 4.3 Full-M3 — secondary attribution arm

Use the complete canonical M3 encoding (311 raw / 391 encoded dimensions).

This arm is secondary. Its result cannot change the primary Departure-Aug PASS/MIXED/STOP code and cannot justify Set Transformer/attention/MLP rescue.

## 5. Matched learner and hyperparameters

Both newly fitted arms use the exact same model class and horizon-specific parameter set:

```text
learner = sklearn HistGradientBoostingRegressor
parameters = frozen source M2 selected parameters for the same horizon
native_thread_limit = 1 where applicable
```

Frozen source M2 selected-parameter SHA256 values:

```text
15   92b00c5e34dddd323774012fddbc1a63d1c953b9abd79fdf071f26aa92553fff
30   a7405c4486297b12f246c39592d536818fda29d187c99a63876f97dd696ece1a
60   1e99af2c4d2ac923bcd6cb6f6e5991380aef1161b5f4295af23edc450feace48
120  a7405c4486297b12f246c39592d536818fda29d187c99a63876f97dd696ece1a
240  9b92e929ae0566dd606ef7ae464df81be87712cff7ff31c89acf15b047ee58ac
```

No hyperparameter search, early stopping selected from test results, feature selection, calibration, clipping, nonnegative projection or branch-specific retuning is allowed.

The same M2 parameterization is deliberately used for Departure-Aug and Full-M3 so the experimental variable is input information rather than learner tuning.

## 6. Training-label construction and reuse

Training arrival labels may be reconstructed only through the already accepted S1 component-label logic from the frozen development interim/processed artifacts.

Required checks before any fit:

- development snapshot SHA identity;
- cleaned-session counts match the frozen S1 protocol;
- `existing_truth + arrival_truth = total_truth` within `1e-6 A`;
- no final-holdout path is traversed;
- accepted S1 and baseline private caches pass exact manifest/file hash checks.

No S1/M2/M3 reference model is retrained.

## 7. Candidate total forecasts

Let the frozen S1 existing prediction be `E_hat_S1`.

For each new arrival arm:

```text
Total_Departure = E_hat_S1 + A_hat_Departure
Total_FullM3    = E_hat_S1 + A_hat_FullM3
```

The frozen total references are:

```text
S1
Equal = 0.5*(M2 + M3)
```

This recombination is mandatory because R6 measured material cross-branch cancellation. Component improvement is not assumed to imply total improvement.

## 8. Required metrics

For Base-M2, Departure-Aug and Full-M3 arrival components, report:

- MAE primary;
- RMSE;
- WAPE;
- negative prediction count.

For S1, Equal, Total_Departure and Total_FullM3, report the same metrics.

Aggregation levels:

1. pooled overall;
2. all 5 horizons;
3. all 4 development months;
4. all 20 month × horizon cells.

No favorable-cell selection.

Also report:

```text
Departure component wins vs Base-M2: horizons / months
Departure total wins vs S1:          horizons / months
Full-M3 component wins vs Base-M2:   horizons / months
Full-M3 total wins vs S1:            horizons / months
Departure wins within {60,120,240}:  0..3
max horizon component degradation vs Base-M2
max horizon total degradation vs S1
```

## 9. Frozen primary decision

The primary decision is based only on Departure-Aug.

### `PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL`

All must hold:

1. pooled Departure-Aug arrival MAE < frozen Base-M2/S1-arrival MAE;
2. Departure-Aug arrival MAE wins in at least 3/5 horizons;
3. Departure-Aug arrival MAE wins in at least 3/4 development months;
4. Departure-Aug wins in at least 2/3 R6 arrival-dominant horizons `{60,120,240}`;
5. no horizon arrival-component MAE degrades more than 5% vs Base-M2;
6. pooled `Total_Departure` MAE < pooled S1 MAE;
7. pooled `Total_Departure` MAE < pooled Equal MAE;
8. `Total_Departure` wins vs S1 in at least 3/5 horizons;
9. `Total_Departure` wins vs S1 in at least 3/4 development months;
10. no horizon total MAE degrades more than 5% vs S1.

Interpretation: planned departure state contains stable incremental arrival information and the gain survives aggregate recombination.

### `MIXED_DEPARTURE_STATE_ARRIVAL_SIGNAL`

Applies when PASS is not met but either:

- pooled Departure-Aug arrival MAE improves vs Base-M2; or
- pooled Total_Departure MAE improves vs S1.

Interpretation: some predictive signal exists, but either component stability or total-forecast utility is insufficient.

### `STOP_DEPARTURE_STATE_ARRIVAL_ROUTE`

Applies when PASS is not met and neither pooled component nor pooled total MAE improves.

The three codes are exhaustive. Thresholds must not be changed after results are observed.

## 10. Secondary Full-M3 interpretation

Full-M3 never changes the primary R7 code.

Report one secondary label:

- `FULL_M3_INCREMENTAL_SIGNAL` if its pooled arrival MAE improves vs Base-M2 and it wins >=3/5 horizons and >=3/4 months;
- otherwise `NO_STABLE_FULL_M3_INCREMENT`.

If Full-M3 is stable while Departure-Aug is not, the only allowed conclusion is that some current-session state beyond M2 is informative for arrival prediction; planned departure is not isolated as the mechanism.

## 11. Explicit prohibitions

R7-C0 must not:

- access final holdout;
- download new data;
- retune HGB;
- use M3 selected parameters in either newly fitted arm;
- fit a neural network, TPP, survival model, gate, MoE, Set Transformer or attention model;
- use realized future arrival share or future session identity as predictors;
- use actual disconnect/doneCharging times at prediction issue;
- clip/calibrate/project outputs;
- drop negative predictions or difficult cells;
- reinterpret requested departure as actual departure;
- claim causality from predictive improvement;
- claim requested-departure use itself as novelty.

## 12. Engineering and Actions policy

Implementation must be written in one isolated code branch after this protocol is committed.

To conserve GitHub Actions:

1. perform targeted syntax/unit checks locally or through static review while developing;
2. avoid iterative code pushes solely for formatting;
3. open one code PR when implementation/tests are complete;
4. run the full GitHub Actions suite once on that final candidate head where possible;
5. if CI reports only lint/formatting, fix all reported style issues in one commit before one final rerun.

A pinned local launcher is released only after a reviewed CI-passed executable head exists.
