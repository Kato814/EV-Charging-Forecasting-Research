# JPL/ACN R2 higher-order origin-active session-set probe protocol

Date: 2026-09-12

Status: **frozen before any R2 model fit**. This protocol follows the completed R1 `MIXED_JOINT_STATE_SIGNAL` diagnostic. It does not reopen P1/R1 tuning, does not authorize a Set Transformer or MoE, and does not authorize final-holdout access.

## 1. Scientific question

R1 showed that 55 matched pairwise Pearson features carry some predictive signal beyond a same-width availability control, but the signal is not stable enough to beat Equal/S1 overall. Pearson correlations are only low-order summaries and can discard higher-order nonlinear structure of the simultaneously connected session population.

R2 asks:

> Does the higher-order nonlinear joint configuration of the origin-active charging-session population contain stable issue-time predictive information beyond exactly the same per-field marginals, and can that information improve direct aggregate multi-horizon station-current forecasts?

R2 is a **representation probe**. Deep Sets is prior art and is not itself the claimed innovation.

## 2. Frozen target, months and horizons

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

Frozen development snapshot SHA256 values:

```text
2019-01 e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12
2019-04 f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299
2019-07 9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2
2019-10 e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296
```

Horizons:

```text
15 / 30 / 60 / 120 / 240 min
```

Use the exact accepted same-month daily rolling-origin OOS issue rows. For a test day cutoff, training rows must satisfy the already frozen baseline causality rule, including `issue < cutoff` and `issue + horizon <= cutoff`. No cross-month training or future-day borrowing.

## 3. Legal issue-time station context

Both R2 arms use the exact frozen **M2 raw FeatureBlock** as station context:

```text
raw width = 201
```

It contains the frozen 24 h station-current history, corresponding observation masks, calendar variables and six current station-state features. No M3 pooled session features are concatenated; the session population is supplied separately as a set.

The canonical M2 feature names/order and nullable mask are inherited unchanged from `acn_jpl_gate1_features.py`. The fixed M2 nullable mask adds missing indicators only at the three canonical nullable state columns. Historical-current missingness is already accompanied by its frozen 96 observation-mask columns.

No future variable, realized composition, session identifier, test error or offline outcome may enter the station context.

## 4. Legal origin-active session element

At each issue time, the set consists only of sessions present in the accepted M3 issue-time group. For each connected session use exactly the 11 frozen legal M3 fields:

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

For neural input, each field is represented as:

```text
standardized numeric value + observed/not-missing bit
```

so each session element has exactly 22 inputs.

`anonymous_session_index` may be used **only** internally to establish a deterministic canonical preprocessing order. It is forbidden as a model input, target, public output or grouping feature.

No post-issue sample, realized departure, future current, future arrival identity/count or final delivered kWh is allowed as a predictor.

## 5. Fold-local numeric preprocessing

All preprocessing parameters are fitted on the current rolling-origin training fold only and then frozen for that fold.

### 5.1 M2 context

For each of the 201 raw M2 columns:

- compute mean and population standard deviation from finite training-row values only;
- if no finite training value exists, use mean `0` and scale `1`;
- if standard deviation is non-finite or `< 1e-12`, use scale `1`;
- transform finite values as `(x - mean) / scale`;
- transform missing numeric values to `0` in standardized space;
- append the fixed three M2 nullable indicators defined by the canonical FeatureBlock metadata.

Resulting context width:

```text
201 + 3 = 204
```

The already present 96 historical observation-mask columns remain ordinary M2 inputs; no extra data-driven indicator discovery is allowed.

### 5.2 Session fields

For each of the 11 session fields, compute mean/std from **all finite training-session values in the fold** using the same `1e-12` scale rule. Missing session-field values become standardized zero and have observed bit `0`; finite values have observed bit `1`.

Preprocessing is identical between Joint and Permuted arms. Test values never affect mean/std.

## 6. Matched representations

### 6.1 R2-Joint

Use the true unordered set of same-session 22-dimensional elements at each issue time. The set cardinality is exactly the number of accepted origin-active M3 rows.

### 6.2 R2-Permuted — marginal-preserving counterfactual control

R2-Permuted uses:

- the exact same M2 context;
- the exact same issue times and target;
- the exact same number of session elements;
- for each of the 11 fields, exactly the same multiset of numeric values and missing/observed states as R2-Joint;
- the exact same neural architecture and optimization.

The only difference is same-session cross-field alignment.

Construction at one issue time:

1. Canonically order the M3 rows by `anonymous_session_index` ascending. This private ordinal is not exposed to the learner.
2. For each field `j`, treat `(raw value, observed bit)` as one indivisible field item.
3. Independently permute that field's items across the `n` session positions.
4. Use a deterministic NumPy `PCG64` permutation. Its seed is derived from SHA256 of the ASCII payload:

```text
R2_PERMUTED_V1|20260912|<issue_time_utc_s>|<field_index_0_to_10>
```

and the first 16 digest bytes interpreted as an unsigned big-endian integer.
5. For `n <= 1`, the only possible ordering is retained.

Thus each field's observed/missing multiset and marginal values are preserved exactly while real tuple alignment is removed stochastically but reproducibly. The same deterministic control is used for training and OOS rows. No result-dependent permutation selection or multiple-control search is allowed.

The control is a scientific counterfactual only; it is not a deployable forecast feature transformation.

## 7. Fixed model architecture

Both R2 arms use the exact same small Deep-Sets-style network.

### 7.1 Session encoder `phi`

```text
22 -> 32 -> 32
Linear -> ReLU -> Linear -> ReLU
```

Apply independently to every padded session element. Multiply by the valid-element mask and use **sum pooling** across sessions. Empty sets map to an all-zero 32-dimensional embedding.

No attention, recurrent layer, normalization layer, dropout or learned pooling is allowed.

### 7.2 M2 context encoder

```text
204 -> 64 -> 32
Linear -> ReLU -> Linear -> ReLU
```

### 7.3 Forecast head

Concatenate the 32-dimensional pooled session embedding and 32-dimensional context embedding:

```text
64 -> 32 -> 1
Linear -> ReLU -> Linear
```

The scalar output is unconstrained; no non-negative activation or prediction clipping is allowed.

All `Linear` weights use Xavier-uniform initialization and all biases are initialized to zero.

Parameter count and architecture must be identical for Joint and Permuted.

## 8. Horizon and fold structure

Train five separate horizon-specific models. Do not use a shared multi-output model, horizon token, horizon query or horizon-conditioned gate during R2.

For each development month, test day and horizon, train Joint and Permuted on the exact same rolling-origin training rows and evaluate on the exact same OOS rows.

The model initialization seed and minibatch order seed must be identical between the two arms for a given fold/horizon. Derive the fold seed from SHA256 of:

```text
R2_MODEL_V1|20260912|<month>|<horizon_minutes>|<local_test_date>
```

using the first 8 digest bytes as an unsigned integer reduced modulo `2**31 - 1`.

## 9. Fixed optimization

No hyperparameter search is permitted.

Formal training parameters:

```text
loss              = mean absolute error (L1Loss)
optimizer         = AdamW
learning_rate     = 0.001
weight_decay      = 0.0001
batch_size        = 256
epochs            = 30
early_stopping    = false
scheduler         = none
dropout           = 0
precision         = float32
AMP               = false
torch.compile     = false
```

Training examples are shuffled each epoch using the deterministic fold generator. Joint and Permuted receive the same batch row order for each fold.

No validation-selected epoch, learning-rate tuning, gradient clipping, output clipping or calibration is allowed.

## 10. GPU and environment contract

R2 must use a **separate environment** from the accepted `evcf-gate1-pilot` environment. Do not upgrade or mutate the accepted environment.

Formal local training environment target:

```text
environment = evcf-r2-set
Python      = 3.11.16
PyTorch     = 2.14.0
CUDA wheel  = cu132
formal run device = NVIDIA GeForce RTX 5080 / cuda:0
```

PyTorch 2.14 officially publishes CUDA 13.2 binaries. Before any R2 fit, a separate environment-preflight step must verify:

- exact Python/PyTorch/data-package pins;
- `torch.cuda.is_available() == True`;
- selected device is `cuda:0`;
- device name contains `RTX 5080`;
- a small float32 forward/backward smoke test succeeds.

The formal launcher must **fail closed before fitting** if the CUDA device contract is not satisfied; it must not silently fall back to CPU. CI may run CPU-only unit tests, but CI is not the formal development experiment.

Use `torch.use_deterministic_algorithms(True)` and deterministic padded-tensor sum pooling. No mixed precision is used in R2.

The launcher must print device, month, horizon, arm, fold/day and coarse epoch progress in real time. At minimum it must report total fit count and emit epoch progress every 5 epochs, plus actual elapsed time. PowerShell delivery remains one line.

## 11. Frozen comparison set

Primary scientific comparison:

```text
R2-Joint vs R2-Permuted
```

Required practical references on identical OOS rows:

```text
M2
M3
Equal
S1
R1-Joint
```

Do not retrain those frozen references. Reuse accepted prediction caches and verify common truth/row identity.

P1 remains a stopped historical route and is not a model to rescue.

## 12. Metrics

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
- month × horizon;
- fit count and actual runtime.

07:00/09:00 or turnover slices may be reported only after the frozen primary decision is computed. They cannot alter PASS/MIXED/STOP.

## 13. Frozen decision rules

Define `BetterBaseline(h)` as the lower MAE of frozen Equal and frozen S1 at horizon `h`.

### `PASS_HIGHER_ORDER_SET_SIGNAL`

All conditions must hold:

1. pooled R2-Joint MAE < pooled R2-Permuted MAE;
2. pooled R2-Joint MAE < pooled Equal MAE;
3. pooled R2-Joint MAE < pooled S1 MAE;
4. pooled R2-Joint MAE < pooled R1-Joint MAE;
5. R2-Joint beats R2-Permuted on at least 3/5 horizons;
6. R2-Joint beats R2-Permuted on at least 3/4 development months;
7. R2-Joint beats Equal on at least 3/5 horizons;
8. R2-Joint beats Equal on at least 3/4 development months;
9. R2-Joint beats S1 on at least 3/5 horizons;
10. R2-Joint beats S1 on at least 3/4 development months;
11. 60-min R2-Joint MAE < 60-min Equal MAE;
12. no horizon degrades by more than 5% relative to `BetterBaseline(h)`.

Meaning only:

- true higher-order same-session alignment contains stable development-set signal beyond exactly matched per-field marginals; and
- the fixed low-capacity representation is practically competitive enough to justify a separately preregistered seed-robustness / method-freeze stage.

A PASS does **not** authorize final-holdout access and does not establish Deep Sets as a novel architecture.

### `MIXED_HIGHER_ORDER_SET_SIGNAL`

Use MIXED only when:

- pooled R2-Joint MAE < pooled R2-Permuted MAE; and
- R2-Joint beats R2-Permuted on at least 2/5 horizons; and
- R2-Joint beats R2-Permuted on at least 2/4 development months; and
- one or more PASS conditions fail.

Meaning: higher-order alignment has some reproducible signal but the fixed representation is not stable/practical enough. Next action is failure-source analysis only. Do not enlarge the network, add attention, tune the permutation, or open the holdout.

### `STOP_HIGHER_ORDER_SET_ROUTE`

Use STOP when **any** holds:

- pooled R2-Joint MAE >= pooled R2-Permuted MAE; or
- R2-Joint beats R2-Permuted on at most 1/5 horizons; or
- R2-Joint beats R2-Permuted on at most 1/4 development months.

Meaning: the controlled higher-order set hypothesis lacks enough development evidence. Close this joint-set route as the current core method; do not rescue it with Set Transformer/MoE after seeing the result.

## 14. Explicitly forbidden during R2

- final holdout access;
- M2/M3/Equal/S1/R1 retuning;
- changing the 11 session fields;
- using session identifiers as predictors;
- future arrivals, realized departures or future composition predictors;
- changing the deterministic permutation after seeing results;
- multiple permutation search / best-control selection;
- session or row deletion;
- prediction clipping/calibration;
- early stopping or validation-selected epochs;
- hyperparameter search;
- Set Transformer or attention pooling;
- MoE / horizon routing / time-of-day gate;
- P1 survival/TPP rescue;
- session generation or replay;
- residual stacking on S1/R1 during this probe.

## 15. Engineering and audit requirements before local fit

Implementation must be isolated in a separate code PR after this protocol merges. Tests must verify at least:

1. R2-Joint is invariant to arbitrary input-session row order;
2. R2-Permuted is reproducible from the frozen seed construction;
3. for every issue time and every field, Joint and Permuted have exactly the same value multiset and missing/observed multiset;
4. the Permuted arm changes only cross-field tuple alignment;
5. `anonymous_session_index` never reaches model inputs or public output;
6. fold preprocessing uses training rows/sessions only;
7. Joint and Permuted model architecture/parameter count/initial weights and minibatch row order match per fold;
8. empty/single-session sets are handled without row deletion;
9. final-holdout paths are rejected;
10. full repository pytest / compileall / Ruff pass;
11. GPU preflight fails closed without the approved RTX 5080 CUDA device;
12. private row/session predictions remain outside Git.

No user local fit is authorized until the implementation PR and separate GPU/environment preflight pass review/CI and a pinned launcher is released.

## 16. Interpretation boundary

R2 does not test whether “Deep Sets is better than HGB” in general. Its primary matched comparison tests whether **real same-session field alignment** improves forecasting relative to a counterfactual with identical station context, set size, field marginals and missingness but destroyed tuple alignment.

If R2 passes, the next step is seed-robustness/method freezing under a separate protocol, not automatic Set Transformer escalation or holdout access. If R2 is mixed, only bounded failure analysis is allowed. If R2 stops, the current higher-order joint-set route is closed.
