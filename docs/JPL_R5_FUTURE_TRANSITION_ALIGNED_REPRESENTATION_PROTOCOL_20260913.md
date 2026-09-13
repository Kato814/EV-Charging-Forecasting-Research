# JPL/ACN R5 future-transition-aligned representation protocol

Date: 2026-09-13
Status: frozen before any R5 real-data model fit.

## 1. Scientific question

The accepted evidence chain is:

- S1 target decomposition is `MIXED_STRUCTURED_SIGNAL`;
- P1 continuation/count-mark mechanism is closed;
- R1 hand-designed joint summaries are MIXED and closed;
- R2 true higher-order session-set alignment is `STOP_HIGHER_ORDER_SET_ROUTE`, so larger Deep Sets / Set Transformer / attention rescue is not allowed;
- R3-C0 control-endogeneity route is closed;
- R4-I0 shows M3 contains stable incremental issue-time information beyond M2, but not a stable advantage over instantaneous-current continuity;
- R4-D1 shows raw M3 geometry is much closer in session-state space but farther in current-level space;
- R4-D2 shows a hand-built scalar geometry balance is not a stable routing variable.

The remaining question is therefore not which expert to select. It is:

> Can a single predictor learn a latent geometry of legal issue-time M3 states in which states that undergo similar future station-load transitions are close, and does explicitly aligning that geometry improve multi-horizon point forecasting beyond an identical direct neural predictor and the frozen strong baselines?

R5 is a forecasting-model experiment. It cannot change any prior formal decision.

## 2. Novelty boundary

R5 does **not** claim that contrastive learning, metric learning, MLPs, multi-output forecasting or representation learning are new. Generic EV-load Transformer, Mamba/state-space, Neural-ODE, MoE/gating, residual-hybrid and probabilistic architectures are already crowded prior art. R2 also prevents a post-hoc Set Transformer/attention rescue of the higher-order session-set route.

A targeted literature search on 2026-09-13 did not retrieve an EV charging-station load forecaster with the exact construction below: causal issue-time session-state representation trained so that latent pairwise geometry follows normalized *future transition-trajectory* geometry. This is negative search evidence only, not proof of first use.

The mechanism under test is specifically **future-transition-aligned issue-time state geometry**. If it does not show stable forecasting value under the frozen comparison, the route stops; it must not be rescued by adding a gate, attention block or larger backbone.

## 3. Data and causal boundary

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

The same accepted JPL development snapshots, local timezone, test-day boundary and daily rolling-origin chronology are used. No new data download is allowed.

For each local-midnight refit cutoff `c`, R5 training rows must satisfy:

```text
issue_time < c
issue_time + 240 min <= c
```

Thus every R5 training row has all five frozen future labels available before the refit cutoff. Test predictions are evaluated on the same causal OOS issue rows as the frozen development references for each horizon.

No test or future-holdout label may influence preprocessing, training, pair construction or optimization.

## 4. Input state

Both matched R5 arms use the exact canonical M3 issue-time feature block:

```text
311 raw M3 features
391 encoded coordinates after the accepted fold-local RidgePreprocessor
```

The preprocessor is fitted only on the R5 training rows of that refit. No feature selection, PCA, individual-session set encoder, added weather/price data, future session identity or realized future composition is allowed.

The raw issue-time station current `p_t` is read from the canonical M2/M3 shared `station_current_a` coordinate only for target re-expression and output reconstruction.

## 5. Future-transition target

The five official station-current targets remain:

```text
h = [15, 30, 60, 120, 240] min
```

For training row `i`, define the transition vector

```text
r_i,h = y_i,h - p_i
```

For each refit and horizon, compute a training-only robust scale

```text
m_h = median(r_i,h)
s_h = max(median(abs(r_i,h - m_h)), 1.0 A)
q_i,h = r_i,h / s_h
```

Both R5 arms predict the same normalized five-dimensional transition vector `q_i`. Published load forecasts are reconstructed as

```text
yhat_i,h = p_i + s_h * qhat_i,h
```

No clipping or nonnegative projection is applied to the primary result.

## 6. Matched network architecture

`R5-Direct` and `R5-FTAR` use identical architecture, initialization, batches and optimizer.

Encoder:

```text
Linear(391,128)
GELU
Linear(128,32)
```

Forecast head:

```text
Linear(32,64)
GELU
Linear(64,5)
```

There is no gate, expert router, attention, recurrent block, Transformer, Set Transformer, Mamba, Neural ODE, dropout or branch decomposition.

The 32-dimensional encoder output is the latent state `z_i` used by the FTAR geometry objective.

## 7. Direct prediction loss

Both arms use identical normalized transition prediction loss:

```text
L_pred = mean_h SmoothL1(qhat_i,h, q_i,h; beta=1.0)
```

`R5-Direct` optimizes `L_pred` only.

## 8. FTAR geometry objective

Within each training mini-batch, for all unordered row pairs `i<j`:

```text
D_future(i,j) = RMS(q_i - q_j)                 over 5 horizons
D_latent(i,j) = RMS(z_i - z_j)                 over 32 latent coordinates
```

For the vector of upper-triangle pair distances, independently standardize the two distance vectors using their batch mean and population standard deviation with `eps=1e-6`:

```text
Dtilde = (D - mean(D)) / (std(D) + 1e-6)
```

Then

```text
L_geo = mean((Dtilde_latent - Dtilde_future)^2)
```

`R5-FTAR` optimizes

```text
L_total = L_pred + 0.25 * L_geo
```

The weight `0.25` is frozen before the real-data run and receives no development-data tuning or sensitivity search in R5.

This objective uses future trajectories only inside historical training folds. At inference, the model receives issue-time M3 state only.

## 9. Training contract

Formal development training uses:

```text
Python           3.11.16
PyTorch          2.14.0+cu132
CUDA             13.2
formal device    NVIDIA GeForce RTX 5080 / cuda:0
optimizer        AdamW
learning rate    1e-3
weight decay     1e-4
epochs           80
batch size       256
shuffle          true
seed             20260913
```

No early stopping, scheduler, hyperparameter search, mixed precision or CPU fallback is allowed in the formal run. The launcher must fail before fitting if the approved CUDA device/environment is unavailable.

The two arms must receive the same deterministic row order and mini-batch partition for every refit.

## 10. Required strong baselines

R5 public aggregates must include the already frozen common-row predictions where available:

- M3 HGB;
- fixed `0.5*(M2+M3)` Equal baseline;
- accepted S1 structured baseline.

These references are read-only and must not be retrained or altered.

The primary mechanism comparison is `R5-FTAR vs R5-Direct`; strong-baseline comparisons establish practical value.

## 11. Held-out geometry audit

For OOS rows with all five future labels available, compute an offline diagnostic only:

- normalize transition vectors with the corresponding refit's training-only `s_h`;
- use a deterministic PCG64 seed `20260913` to draw at most 20,000 distinct unordered OOS row pairs per development month;
- compute Spearman correlation between latent RMS distance and future-transition RMS distance separately for Direct and FTAR.

Future OOS labels used in this audit never affect predictions or training. The audit is aggregate-only.

## 12. Required reporting

Report MAE primary, RMSE and WAPE secondary for:

- pooled overall;
- all 5 horizons;
- all 4 development months;
- complete month × horizon cells.

Also report:

- FTAR-vs-Direct MAE improvement;
- FTAR-vs-Equal and FTAR-vs-S1 improvement;
- horizon and month win counts;
- maximum horizon degradation vs Direct;
- held-out latent/future-transition Spearman for Direct and FTAR;
- exact model fit counts and elapsed runtime.

No row-level predictions, model objects, absolute paths or private cache identifiers are public.

## 13. Frozen decision

### `PASS_FUTURE_TRANSITION_GEOMETRY`

All must hold:

1. FTAR pooled MAE is lower than Direct;
2. FTAR pooled MAE is lower than both frozen Equal and S1;
3. FTAR beats Direct in at least 3/5 horizons;
4. FTAR beats Direct in at least 3/4 development months;
5. no horizon FTAR MAE degradation vs Direct exceeds 5%;
6. pooled held-out latent/future-transition Spearman is higher for FTAR than Direct.

A PASS only authorizes a later robustness/ablation stage. It does not authorize final holdout.

### `MIXED_FUTURE_TRANSITION_GEOMETRY`

FTAR improves pooled MAE over Direct and at least one frozen strong baseline but misses one or more stability/mechanism conditions. Only failure-source analysis is allowed; no larger backbone rescue.

### `STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`

Trigger if either:

- FTAR pooled MAE is not lower than Direct; or
- FTAR beats Direct in at most 1/5 horizons; or
- FTAR beats Direct in at most 1/4 months.

The route closes without attention/MoE/Set-Transformer enlargement.

## 14. Explicit prohibitions

R5 must not:

- access final holdout;
- change development months;
- tune the geometry-loss weight after seeing results;
- change the network width/depth after seeing results;
- use target-aware test-time matching or retrieval;
- train a gate, classifier or expert router;
- use calendar month as a model input;
- add individual-session set encoding;
- revive P1 survival/TPP or R2 set routes;
- add clipping/calibration/post-hoc residual correction;
- select favorable hours/days/cells for the formal decision.

## 15. Execution sequence

1. archive accepted D2 and merge this protocol;
2. implement Direct/FTAR in a separate PR;
3. add unit tests for causal rows, transition scaling, pairwise geometry loss, matched architecture, decision logic and holdout blocking;
4. full pytest/compileall/Ruff plus CUDA-environment launcher checks;
5. release one pinned development-only launcher;
6. run exactly one formal R5 development experiment;
7. archive the outcome before any further model modification.
