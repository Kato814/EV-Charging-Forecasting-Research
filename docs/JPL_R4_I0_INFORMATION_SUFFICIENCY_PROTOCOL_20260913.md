# JPL/ACN R4-I0 information-sufficiency / state-aliasing protocol

## 1. Scientific question

R4-I0 is a development-only, zero-model-fit diagnostic. It asks:

> When two issue-time states are close under the frozen legal JPL feature representation, do their future aggregate station-current outcomes remain materially different, and does richer M3 state information reduce that future-outcome divergence beyond a simple current-load analog?

This is an empirical state-aliasing / information-sufficiency gate. It is **not** an information-theoretic impossibility proof, not a nearest-neighbor forecasting contribution, and not a generic probabilistic-forecasting novelty claim.

A positive aliasing result would only support a later, separately frozen uncertainty / external-information / target-design stage. It does not authorize final-holdout access.

## 2. Frozen data and target

Development months only:

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

Target remains:

```text
station_current_mean_a
unit = A
horizons = 15, 30, 60, 120, 240 min
```

No new data are downloaded. No reference forecast is fitted or retuned.

## 3. Frozen issue-time state tiers

R4-I0 uses the already canonical feature blocks without feature selection.

### Level-Control

Uses only the current `station_current_a` coordinate from M2 after the fold-local M2 Ridge preprocessing described below.

### M2-State

Uses the complete canonical M2 block:

```text
raw width = 201
encoded Ridge width = 204
```

### M3-State

Uses the complete canonical M3 block:

```text
raw width = 311
encoded Ridge width = 391
```

No issue timestamp, row identity, anonymous session identity, future current, future arrival, realized departure, future control path, future composition, future delivered energy or forecast error is added to the state.

M3 is the primary rich-state arm. M2 is a secondary representation control. Level-Control is the primary matched baseline.

## 4. Rolling causal eligibility

The existing development rolling-origin protocol remains authoritative.

For each development month, local test day and horizon `h`:

1. test rows are the frozen OOS rows on that local day;
2. historical rows are eligible only when their issue time precedes the test-day midnight and their `h`-minute target is already available by that midnight;
3. no row from the current test day or a later day may enter preprocessing, analog selection or support calibration;
4. future labels are never used to select analogs.

This is the same label-availability causality used by the frozen development experts.

## 5. Historical-only preprocessing

For each month × local test day × horizon, separately fit the existing repository `RidgePreprocessor` on the horizon-eligible historical rows for M2 and M3.

The preprocessing contract is therefore frozen to the existing implementation:

- training-only median imputation;
- canonical nullable indicators;
- training-only mean/std standardization;
- no PCA, learned embedding, target supervision, weighting or feature selection.

The transformed M2/M3 test vectors are generated with those historical-only preprocessing statistics.

R4-I0 does not instantiate Ridge regression or any other estimator. Model fit count must remain zero.

## 6. Same-clock historical candidate pool

For every OOS test issue `i`, define its local 15-minute clock slot in `America/Los_Angeles`.

For each horizon, its candidate pool contains only eligible historical rows from the **same development month** and the **exact same local 15-minute clock slot** as `i`.

This restriction is fixed before seeing R4 outcomes. Its purpose is to remove the dominant intraday cycle without using future information or an optimized time window.

Minimum candidate count:

```text
MIN_CANDIDATES = 10
```

If fewer than 10 same-clock eligible historical rows exist, the test issue is unsupported for R4-I0.

## 7. Frozen analog distances

Set:

```text
K = 3 analogs
```

### 7.1 Level-Control distance

Let `z_level` be the standardized `station_current_a` coordinate produced by the fold-local M2 RidgePreprocessor.

```text
d_level(i,j) = abs(z_level_i - z_level_j)
```

### 7.2 M2-State distance

For the 204-dimensional encoded M2 vectors:

```text
d_M2(i,j) = sqrt(mean((z_M2_i - z_M2_j)^2))
```

### 7.3 M3-State distance

For the 391-dimensional encoded M3 vectors:

```text
d_M3(i,j) = sqrt(mean((z_M3_i - z_M3_j)^2))
```

Using RMS rather than raw Euclidean norm avoids a purely dimensional scale multiplier between M2 and M3. No feature weights or learned metric are allowed.

For each arm, select the three smallest-distance candidates. Ties are broken by earlier issue time. No target value or target error participates in ranking.

## 8. Historical support calibration

The phrase “similar state” must itself be supported by historical feature geometry.

For each test issue's same-clock candidate pool, use **M3 distance only** to calibrate support:

1. for every historical candidate row, compute its third-nearest M3 distance to the other rows in that candidate pool;
2. define the historical support threshold as the empirical 95th percentile of those third-nearest distances, using the `higher` quantile rule;
3. compute the test issue's third-nearest M3 distance;
4. the issue is in-support only when that test third-nearest distance is no greater than the historical threshold.

Thus support uses only historical and current issue-time features. Future targets do not enter support calibration.

The same supported test-row set is then used for Level-Control, M2-State and M3-State comparisons.

Report, but do not tune on:

- third-neighbor M3 distance;
- historical 95th-percentile threshold;
- their ratio;
- candidate count.

## 9. Frozen future-outcome divergence metric

Only **after** analog identities are frozen, use the already available historical and OOS target labels.

For test issue `i`, horizon `h`, and arm `a` with three analog rows `N_a(i)`:

```text
D_a(i,h) = mean_j | y(i,h) - y(j,h) |,  j in N_a(i)
```

This is an analog future-outcome divergence diagnostic, not a fitted forecast.

Aggregate by pooled records, horizon, month and month × horizon using equal weight per supported origin-horizon record.

For each aggregate group report:

```text
G_level = mean(D_level)
G_M2    = mean(D_M2)
G_M3    = mean(D_M3)
Y_scale = mean(abs(y))
```

Primary rich-state skill:

```text
skill_M3_vs_Level = 1 - G_M3 / G_level
```

Secondary incremental skill:

```text
skill_M3_vs_M2 = 1 - G_M3 / G_M2
skill_M2_vs_Level = 1 - G_M2 / G_level
```

Positive skill means the richer state selects historical analogs with more similar future outcomes.

Material aliasing magnitude:

```text
normalized_M3_divergence = G_M3 / Y_scale
```

If an aggregate denominator is non-positive or non-finite, the run is invalid rather than patched.

## 10. Frozen support gate

R4-I0 support passes only if all conditions hold:

1. pooled supported origin-horizon fraction >= 0.70;
2. every one of the 20 month × horizon cells has supported fraction >= 0.50;
3. every month × horizon cell has at least 250 supported origin-horizon records.

Support is evaluated before scientific effect criteria.

If support fails, the formal result is:

```text
STOP_STATE_ALIASING_ROUTE
reason = INSUFFICIENT_ANALOG_SUPPORT
```

No relaxation of `MIN_CANDIDATES`, `K`, the same-clock rule or the 95th-percentile M3 support threshold is allowed after observing results.

## 11. Frozen scientific decisions

### 11.1 PASS_STATE_ALIASING_SIGNAL

All conditions must hold:

1. support gate passes;
2. pooled `normalized_M3_divergence >= 0.10`;
3. at least 3/5 horizons have `normalized_M3_divergence >= 0.08`;
4. pooled `skill_M3_vs_Level <= 0.05`;
5. pooled `skill_M3_vs_M2 <= 0.02`;
6. at most 1/5 horizons have `skill_M3_vs_Level >= 0.10`;
7. at most 1/4 months have `skill_M3_vs_Level >= 0.10`;
8. 60-min `skill_M3_vs_Level <= 0.05`;
9. 60-min `normalized_M3_divergence >= 0.10`.

Interpretation: even among historically supported, same-clock close states, the complete frozen M3 representation does not materially reduce future-outcome divergence beyond current-load analogs, while remaining future divergence is operationally nontrivial. This is evidence of empirical state aliasing under the frozen metric.

PASS does **not** prove irreducible uncertainty and does not authorize final holdout. It only permits a separately frozen uncertainty/external-information/target-design stage.

### 11.2 STOP_STATE_ALIASING_ROUTE

After support passes, STOP is triggered if either route below holds.

#### A. Rich state materially resolves divergence

All must hold:

1. pooled `skill_M3_vs_Level >= 0.10`;
2. at least 3/5 horizons have `skill_M3_vs_Level >= 0.05`;
3. at least 3/4 months have `skill_M3_vs_Level >= 0.05`;
4. 60-min `skill_M3_vs_Level >= 0.05`.

Interpretation: the legal issue-time state contains material deterministic information that the simple level analog misses. An information-limit explanation is not supported; any next stage must focus on extracting existing information more effectively rather than claiming state insufficiency.

#### B. Future divergence is intrinsically small under M3 analogs

All must hold:

1. pooled `normalized_M3_divergence < 0.05`;
2. at least 4/5 horizons have `normalized_M3_divergence < 0.08`.

Interpretation: close M3 states already have close future outcomes; material state aliasing is not demonstrated.

### 11.3 MIXED_STATE_ALIASING_SIGNAL

If support passes and neither PASS nor STOP condition is fully satisfied, the formal result is:

```text
MIXED_STATE_ALIASING_SIGNAL
```

MIXED permits only a separately preregistered read-only failure analysis. It does not authorize metric learning, PCA, alternate K, alternate time windows, feature selection or new forecasting models.

## 12. Required outputs

Public aggregate output must contain:

- status and frozen code identity;
- fit_count = 0;
- model_fit_attempted = false;
- final holdout accessed = false;
- support counts/fractions overall and for all 20 month-horizon cells;
- `G_level`, `G_M2`, `G_M3`, `Y_scale`;
- the three skill metrics;
- normalized M3 divergence;
- by-horizon and by-month summaries;
- formal PASS/MIXED/STOP decision and reason;
- distance-support summaries without row IDs or absolute local paths.

Private row-level analog identities may be stored locally for audit but never committed to Git.

## 13. Prohibited post-result actions

The first R4-I0 run must not be rescued by:

- changing K from 3;
- widening/narrowing the same-clock candidate window;
- changing the 10-candidate floor;
- replacing the historical 95th-percentile M3 support rule;
- PCA, metric learning, feature weighting or feature selection;
- target-informed distance;
- deleting dates/hours/horizons;
- threshold tuning;
- switching to another deterministic backbone;
- accessing final holdout.

## 14. Novelty boundary

R4-I0 does not claim first EV charging predictability analysis, first nearest-neighbor/similar-day method, first probabilistic EV load forecast or first uncertainty quantification.

Direct/adjacent prior art already covers user-level charging predictability heterogeneity, site/horizon-dependent EV forecastability, similar-day EV load forecasting, and probabilistic multi-horizon EV charging forecasts.

The narrow contribution boundary is the **empirical information-sufficiency test of this project's frozen causal JPL issue-time state after a sequence of failed richer deterministic representations**. Any later paper claim must remain within that evidence.

## 15. Execution authorization

This protocol document alone authorizes **no local run**.

Required sequence:

1. protocol PR full CI/review/merge;
2. separate zero-fit implementation PR;
3. regression tests for causality, support, distances and decisions;
4. full pytest/compileall/Ruff;
5. pinned one-time development launcher;
6. exactly one formal R4-I0 development run;
7. decision by the rules above.

Final holdout remains sealed regardless of the first R4-I0 result.
