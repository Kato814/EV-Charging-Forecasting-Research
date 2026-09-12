# JPL/ACN R1 joint-session-state representation probe protocol

Date: 2026-09-12

Status: **frozen before any R1 model fit**. This protocol follows the completed P1 `STOP_MECHANISM_ROUTE` outcome and the post-P1 method screening. It does not reopen P1, does not authorize final-holdout access, and does not authorize a learned Deep Sets / Set Transformer model.

## 1. Scientific question

The frozen M3 representation pools each legal connected-session field independently, so it preserves marginal distributions but discards which field values belong to the same connected session. The next low-complexity question is therefore:

> Does the within-session joint alignment of legal issue-time session states contain stable horizon-dependent information for direct aggregate charging-current forecasting beyond what is available from the same marginal pools and the same joint-feature availability pattern?

R1 tests this question directly. It does **not** claim that pairwise correlation is a new architecture, and it does not claim that a set model is novel.

## 2. Frozen data boundary

Target:

```text
station_current_mean_a
unit = A
```

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

Frozen development snapshot SHA256 values remain unchanged:

```text
2019-01 e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12
2019-04 f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299
2019-07 9eea83e13ea6fbe5fef694c5de93b5bc4a82f7efe00e90e4fadd6d0b9e9ff2
2019-10 e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296
```

Forecast horizons remain:

```text
15 / 30 / 60 / 120 / 240 min
```

All comparisons use the exact same rolling-origin OOS issue rows already used by the accepted development experts, S1 and P1.

## 3. Legal issue-time session state

R1 uses exactly the 11 legal M3 connected-session fields already frozen in the repository:

1. `elapsed_connection_s`
2. `elapsed_charging_time_proxy_s`
3. `current_current_a`
4. `recent_current_mean_a`
5. `recent_current_peak_a`
6. `recent_current_observed_ratio`
7. `cumulative_current_ah`
8. `cumulative_current_observed_ratio`
9. `current_pilot_a`
10. `requested_departure_minutes_from_issue`
11. `known_kwh_requested`

No session identifier is a predictor. No field measured after the issue time is allowed. No realized future composition, future-arrival count, future session identity, future departure realization or future current is allowed as a predictor.

## 4. Frozen base context

Both R1 representations start from the exact frozen M3 raw feature vector:

```text
M3 raw width = 311
```

This contains:
- 24 h station-current history / observation masks / calendar context;
- the six M2 current station-state features;
- the existing 110 independent marginal session-pool features.

R1 appends exactly 55 pair features, one for every unordered pair among the 11 legal session fields:

```text
C(11, 2) = 55
R1 raw width = 311 + 55 = 366
```

The same 55 pair positions and the same nullable mask are used for both representations.

## 5. Pairwise-complete availability rule

For one issue time and one field pair `(j, k)`, define the pairwise-complete connected-session subset as sessions for which both field values are finite.

A pair feature is **defined** only when:
- at least 2 pairwise-complete sessions exist; and
- both fields have strictly positive finite sample variance on that pairwise-complete subset.

Otherwise the pair feature is `NaN` in **both** R1-Control and R1-Joint.

This makes the missing/availability pattern identical between the matched representations. The existing preprocessing therefore exposes the same missingness indicator to both models.

No minimum-count threshold may be changed after observing R1 results.

## 6. Matched representations

### 6.1 R1-Control — marginal-pool matched control

For every defined pair position:

```text
pair_value = 0.0
```

For every undefined pair position:

```text
pair_value = NaN
```

Thus R1-Control receives:
- all frozen M3 information;
- the exact same 55 pair-feature availability/missingness pattern as R1-Joint;
- no within-session cross-field alignment value.

### 6.2 R1-Joint — joint-session-state probe

For every defined pair position, compute the ordinary pairwise-complete Pearson correlation over the currently connected sessions:

```text
pair_value(j,k) = corr(x_j, x_k)
```

The value is structurally bounded to `[-1, 1]`. Undefined pairs remain `NaN` under the identical rule above.

R1-Joint therefore differs from R1-Control only in the **within-session joint alignment value**. It does not add future information, additional session fields, session IDs or a different missingness pattern.

## 7. Learner and capacity matching

No new hyperparameter search is allowed.

For each horizon, both R1-Control and R1-Joint use:
- the same frozen M3 HistGradientBoosting learner family;
- the exact same accepted M3 horizon-specific hyperparameters and parameter SHA identities;
- the same preprocessing logic as the accepted development experts;
- the same random-state/determinism settings;
- the same rolling-origin fitting rows;
- the same OOS issue rows;
- the same target.

The 55 added raw columns are marked nullable for both representations so preprocessing width is identical.

No model is allowed to know whether it is the control or joint arm except through the values in those 55 matched positions.

## 8. Rolling-origin rule

Use the already accepted development-expert daily rolling-origin protocol without modification.

For a forecast issued on local day `d`, training data must satisfy the same cutoff rule already frozen for M2/M3. Test rows, day boundaries and horizon-target construction must match the accepted baseline cache exactly.

No cross-month training, no future-day borrowing and no test-selected refit schedule are allowed.

## 9. Frozen comparison set

Primary matched comparison:

```text
R1-Joint vs R1-Control
```

Required external references on identical OOS rows:

```text
M2
M3
Equal
S1
```

P1 is reported only as a historical stopped route and is not a benchmark to beat or rescue.

## 10. Metrics

Primary metric:

```text
MAE in A
```

Secondary reporting:
- RMSE in A;
- WAPE ratio;
- negative prediction count;
- pooled overall;
- pooled by horizon;
- pooled by development month;
- month × horizon table.

The previously identified 07:00 / 09:00 turnover cells may be reported descriptively, but they are not allowed to define or alter the decision after results are seen.

Realized future arrival share remains diagnostic-only and is forbidden from the R1 prediction path and decision rule.

## 11. Frozen decision rules

### `PASS_JOINT_STATE_SIGNAL`

All conditions must hold:

1. pooled R1-Joint MAE < pooled R1-Control MAE;
2. pooled R1-Joint MAE < pooled Equal MAE;
3. R1-Joint beats R1-Control on at least 3/5 horizons;
4. R1-Joint beats R1-Control on at least 3/4 development months;
5. R1-Joint beats Equal on at least 3/5 horizons;
6. R1-Joint beats Equal on at least 3/4 development months;
7. 60-min R1-Joint MAE < 60-min Equal MAE;
8. no horizon degrades by more than 5% relative to Equal.

Meaning only:
- the preserved within-session joint state has stable development-set predictive signal beyond the matched marginal/availability control; and
- the low-order joint representation is strong enough to justify a separately preregistered learned session-set model.

A PASS does **not** authorize final-holdout access and does not prove that Set Transformer / Deep Sets is novel.

### `MIXED_JOINT_STATE_SIGNAL`

Use this decision only when:
- pooled R1-Joint MAE < pooled R1-Control MAE; and
- R1-Joint beats R1-Control on at least 2/5 horizons and at least 2/4 months; and
- one or more PASS conditions fail.

Meaning:
- there is some joint-state signal, but it is not yet stable/practically sufficient.

Next action is failure-source analysis only. A learned Set Transformer, MoE or horizon gate is not automatically authorized.

### `STOP_JOINT_STATE_ROUTE`

Use this decision when **any** of the following holds:
- pooled R1-Joint MAE >= pooled R1-Control MAE; or
- R1-Joint beats R1-Control on at most 1/5 horizons; or
- R1-Joint beats R1-Control on at most 1/4 months.

Meaning:
- this low-order joint-alignment probe does not provide enough development evidence to continue the session-set route as the current core method.

A STOP cannot be rescued by post-hoc pair selection, dropping bad rows, changing minimum session counts, changing the correlation estimator or jumping directly to a larger Set Transformer.

## 12. Explicitly forbidden during R1

- final holdout access;
- M2/M3 retuning;
- pair-feature selection after seeing OOS errors;
- Spearman/Kendall/covariance replacement after seeing results;
- row deletion, including the pathological P1 rows;
- prediction clipping or calibration;
- reliability/composition gates;
- realized future composition predictors;
- future-session generation;
- survival/TPP rescue;
- Deep Sets / Set Transformer training;
- MoE / horizon routing;
- hyperparameter search.

## 13. Engineering / audit requirements

Before local execution:
- implementation must be isolated in a dedicated branch/PR;
- unit tests must verify permutation invariance of the pair features;
- tests must verify identical availability masks between Control and Joint;
- tests must verify that independent per-field session permutations leave M3 marginals unchanged but may change R1-Joint correlations;
- tests must verify no final-holdout path is accepted;
- full repository pytest / compileall / Ruff must pass;
- the launcher must bind to the CI-passed reviewed head;
- private row-level outputs must remain outside the repository.

The public status must report code identity, data identities, fit counts, decision support and integrity flags without private session identifiers.

## 14. Interpretation boundary

R1 is a **representation probe**, not the final paper method.

If R1 passes, the defensible next question is whether a learned permutation-invariant session-population representation can exploit more than pairwise joint alignment under the same causal boundary. If R1 is mixed, only targeted failure analysis is allowed. If R1 stops, the current session-set route is not escalated merely because a larger neural model might fit better.
