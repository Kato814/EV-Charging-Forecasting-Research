# JPL/ACN R11-P1 horizon-targeted privileged-arrival supervision protocol

Date: 2026-09-15  
Status: **PROTOCOL FROZEN / implementation not yet authorized**.

## 1. Trigger and scope

R11-S0 completed all `68/68` frozen fits and returned:

```text
STOP_DEEP_CORE_ROUTE
selected_backbone = null
```

The same-information Station-HGB anchor achieved pooled MAE `25.8731522189 A`. The closest deep candidate, TCN, achieved pooled MAE `26.9086600381 A` and failed the frozen eligibility gates. Therefore the original plan of selecting one end-to-end deep backbone and then launching R11-M1 is closed.

R11-S0 nevertheless exposed a diagnostic horizon asymmetry that is consistent with the earlier R6 mechanism evidence:

```text
TCN vs Station-HGB MAE
15 min   +49.36%
30 min   +11.87%
60 min    -2.22%
120 min   -1.01%
240 min   -3.35%
```

Earlier R6-O0 independently showed that the larger removable error source changes between 30 and 60 min: issue-time existing-session evolution dominates at 15–30 min, while future-arrival uncertainty dominates at 60–240 min.

This new protocol treats those two already-observed development signals only as motivation for a **new, separately frozen hypothesis**. It does not modify, rescue or reinterpret the R11-S0 decision.

Final JPL holdout `2019-03/06/09/12` remains sealed.

## 2. Methodological review and design correction

A direct `Station-HGB + neural residual correction` design was considered and rejected as the primary experiment carrier.

Reason: a leakage-free residual target `Y - HGB(X)` for the residual learner would require nested chronological cross-fitting of the HGB base on every residual-training row. Using in-sample HGB residuals would create a stacking leakage mismatch, while nested cross-fitting would add substantial implementation complexity and make it harder to isolate the scientific effect of privileged supervision.

The cleaner carrier is therefore a **fixed horizon-gated hybrid**:

```text
15 / 30 min      -> frozen same-information Station-HGB
60 / 120 / 240   -> station-only TCN branch
```

The horizon split is fixed before R11-P1 execution. It is not learned from test performance and is not changed after seeing R11-P1 results.

The TCN branch is not claimed as novel. It is only the carrier used to test training-only privileged supervision where S0 already showed that deep temporal modeling is at least competitive with HGB.

## 3. Literature subtraction / novelty boundary

Targeted literature review establishes that the following ideas are already occupied and cannot be claimed as the contribution:

- Learning Using Privileged Information (LUPI) in forecasting generally, including PV power forecasting and multi-step tourism/carbon-price forecasting;
- multi-task learning in EV charging-demand prediction;
- hybrid boosting + deep-learning EV load forecasting;
- decomposition-driven EV load forecasting;
- residual/error-correction neural forecasting;
- existing-session / future-arrival modeling as a conceptual decomposition;
- future-session generation or session-aware probabilistic EV forecasting.

Relevant examples include:

- `10.1016/j.ins.2022.11.046` — privileged-information PV forecasting;
- `10.1016/j.eswa.2022.118502` — LUPI for multi-step tourism demand;
- `10.1016/j.eswa.2024.124825` — time-series privileged information for multi-step carbon-price prediction;
- `10.1016/j.apenergy.2025.125460` — EV charging-demand multi-task learning;
- `10.1109/TITS.2026.3704750` — EVCha multi-task EV charging-demand prediction;
- `10.1038/s41598-025-29739-z` — XGBoost–BiLSTM EVCS hybrid forecasting;
- `10.1016/j.apenergy.2024.124308` — EV multi-step forecasting with an error-correction block;
- `10.1109/TSG.2026.3677496` — decomposition + stacked meta-learning for EV load forecasting;
- SessionFlow, SSRN 7316940 — explicit origin-active / future-session probabilistic forecasting.

The targeted search did **not** return a direct match for the exact combination below:

> session-resolved future-arrival contribution labels, used only during training as an auxiliary supervision signal, to improve an aggregate-only station-level forecaster whose deployment input remains aggregate history/calendar and which does not require session data at inference.

This is negative search evidence only, not proof of first publication.

Therefore the only defensible candidate novelty is **cross-granularity, training-only future-arrival supervision under an aggregate-only deployment contract**, not TCN, horizon gating, multi-task learning or LUPI by themselves.

## 4. Scientific question

Primary question:

> For 60–240 min EV charging-station forecasting, can future-arrival contribution labels reconstructed from session-rich source data improve a station-only temporal representation when those labels are available only during training and no session information is available at inference?

Secondary engineering question:

> Does combining a short-horizon Station-HGB expert with the long-horizon station-only branch produce a practically stronger five-horizon aggregate forecaster than Station-HGB alone without changing the deployment input contract?

## 5. Data identity and chronology

R11-P1 reuses only the already-designated development months:

```text
2019-01 / 2019-04 / 2019-07 / 2019-10
```

Final holdout remains:

```text
2019-03 / 2019-06 / 2019-09 / 2019-12
```

R11-P1 uses the exact R11-S0 chronological folds:

```text
train       all earlier development months + current month days 1-14
validation  current month days 15-17
test        current month day >=18 on exact frozen origins
```

Frozen test origins remain:

```text
2019-01 1305
2019-04 1180
2019-07 1294
2019-10 1296
pooled  5075 origins
```

No test row may be removed, reweighted or filtered based on outcome values.

## 6. Inference contract

At deployment, all R11-P1 predictive outputs may depend only on:

```text
96 x 15-min station aggregate current history
96-bin validity mask
issue-time calendar context
target-time calendar context / horizon
```

Prohibited at inference:

```text
session IDs
requested departure
requested energy
per-session pilot/current
existing-session truth
future-arrival truth
future sessions
```

No weather/traffic/price variable is added in R11-P1.

## 7. Targets and privileged label

Main target:

```text
Y(t,h) = station_current_mean_a at horizon h
h in {60,120,240} min
```

Training-only privileged label:

```text
A(t,h) = aggregate current contribution at t+h from sessions that were not connected at issue time t
```

`A(t,h)` must come from the previously accepted offline issue-time decomposition logic. It is not an inference feature.

Before any fit, the training-label QA must verify for every eligible row/horizon:

```text
Y(t,h) = E(t,h) + A(t,h)
A(t,h) >= 0
E(t,h) >= 0
finite values only
exact issue-time alignment
```

Rows failing the accepted source snapshot/decomposition identity cause fail-closed execution; they are not silently removed.

## 8. Model carrier

### 8.1 Short-horizon expert

For `15/30 min`, final predictions are the frozen same-information Station-HGB predictions under the accepted chronological evaluation logic.

### 8.2 Long-horizon station-only TCN

For `60/120/240 min`, use the same TCN encoder family frozen in R11-S0:

```text
5 causal residual blocks
channels 64
kernel 3
dilations 1,2,4,8,16
two convolutions per block
station-only 96 x 2 history input
same issue/target calendar context
float32
```

Only the output task set changes from five horizons to the preregistered long-horizon set `{60,120,240}`.

The shared encoder produces latent representation `z_t`. Two horizon-conditioned heads are instantiated:

```text
total head    -> Y_hat(t,h)
arrival head  -> A_hat(t,h)
```

Both arms use the **same architecture**, including the arrival head. In the control arm the arrival-loss weight is exactly zero. This keeps implementation identity paired while ensuring the deployed total predictor has the same inference structure.

The arrival head is discarded at deployment.

## 9. Experimental arms

### Arm A — Station-HGB anchor

```text
15/30/60/120/240 min -> Station-HGB
```

No privileged supervision.

### Arm B — horizon-gated hybrid, total-only training

```text
15/30 min       -> Station-HGB
60/120/240 min  -> TCN total head
training loss   -> total-load loss only
arrival weight  -> 0
```

### Arm C — horizon-gated hybrid, privileged-arrival training

```text
15/30 min       -> Station-HGB
60/120/240 min  -> same TCN total head
training loss   -> total-load + arrival auxiliary loss
arrival weight  -> 0.5
```

Arm B and Arm C must use the same train/validation/test rows, architecture, optimizer, early stopping, seeds and initialization policy.

## 10. Losses and normalization

For each fold, normalization statistics are computed from training rows only.

Main total target uses the same train-only scalar standardization policy as R11-S0, restricted to `{60,120,240}`.

Arrival labels use a separate train-only scalar mean/std over the same three horizons.

Both losses use SmoothL1 with `beta=1.0` in standardized space:

```text
L_Y = SmoothL1(Y_hat_std, Y_std)
L_A = SmoothL1(A_hat_std, A_std)
```

Frozen objectives:

```text
Arm B: L = L_Y
Arm C: L = L_Y + 0.5 * L_A
```

No lambda search is allowed in R11-P1. `0.5` is fixed to make the auxiliary task a bounded representation regularizer rather than a co-primary objective.

No consistency loss is added in R11-P1. This is deliberate: the experiment isolates whether the privileged arrival label improves the shared station-only representation without introducing another coupling term.

## 11. Training policy

Reuse the R11-S0 deep-training policy unless explicitly changed here:

```text
optimizer        AdamW
learning rate    1e-3
weight decay     1e-4
batch size       256
max epochs       120
patience         12
min val improve  1e-4 standardized MAE
grad clip        1.0
scheduler        none
AMP              disabled
deterministic    required
CPU fallback     prohibited
```

Seeds:

```text
2026091401
2026091402
2026091403
```

Early stopping is determined **only by total-load validation MAE**, not the auxiliary arrival loss. This prevents the privileged task from selecting a checkpoint that is worse on the deployment task.

## 12. Evaluation metrics

### Primary comparison

Arm C vs Arm B on total-load prediction over pooled long horizons `{60,120,240}`.

Primary metric:

```text
MAE in A
```

Report additionally:

```text
RMSE
WAPE
by horizon
by month
paired seed results
local-day MAE deltas
negative prediction counts
```

### Secondary absolute comparison

Arm C hybrid vs Arm A Station-HGB over all five horizons.

No clipping, calibration, ensemble weighting or non-negative projection is allowed.

## 13. Frozen decision rule

### PASS_PRIVILEGED_ARRIVAL_SUPERVISION

All conditions must hold:

1. median-seed pooled long-horizon MAE improvement of Arm C over Arm B is **>= 1.0%**;
2. Arm C beats Arm B in **at least 2/3** long horizons;
3. no long horizon degrades by more than **1.0%** versus Arm B;
4. Arm C beats Arm B in long-horizon pooled MAE in **at least 3/4 months**;
5. Arm C beats Arm B in **at least 2/3 paired seeds** on pooled long-horizon MAE;
6. Arm C pooled seed spread is **<= 3.0%**;
7. Arm C long-horizon pooled MAE is better than Station-HGB long-horizon pooled MAE;
8. the complete five-horizon Arm C hybrid is better than Arm A Station-HGB in pooled MAE;
9. all folds/seeds complete and no frozen test rows are removed.

### MIXED_PRIVILEGED_ARRIVAL_SIGNAL

Use only when Arm C improves Arm B by a positive median pooled amount but one or more PASS stability/absolute-value conditions fail.

### STOP_PRIVILEGED_SUPERVISION_ROUTE

Use when Arm C does not improve Arm B in median pooled long-horizon MAE, or execution integrity fails.

These outcomes are exhaustive. No threshold may be relaxed after result inspection.

## 14. Fit ceiling

Deep fits:

```text
Arm B: 4 folds x 3 seeds = 12
Arm C: 4 folds x 3 seeds = 12
Total deep fits = 24
```

Station-HGB anchor may be deterministically replayed under the already frozen parameter/chronology contract if row-level predictions are needed locally. Such replay is not hyperparameter search.

No third neural arm, extra seed, fifth architecture, lambda sweep or horizon-boundary sweep is allowed in R11-P1.

## 15. Interpretation boundaries

If PASS:

Allowed development-stage statement:

> On the frozen JPL development protocol, session-resolved future-arrival contribution labels used only during training improve the aggregate-only long-horizon station forecaster relative to the same station-only model trained on total load alone, without requiring session information at inference.

Still not allowed:

- final generalization claim;
- first use of LUPI, multi-task learning, TCN or hybrid EV forecasting;
- claim that future-arrival truth is available online;
- causal claim about arrival behavior;
- final-holdout claim.

If MIXED:

Treat the privileged label as a mechanism signal, not a robust algorithmic gain. Do not tune lambda or architecture inside R11-P1.

If STOP:

Close the training-only privileged-supervision algorithm route on JPL. Do not rescue it with another backbone or auxiliary weight search.

## 16. Post-R11-P1 requirement

Even a PASS remains development evidence because the JPL development months have supported an adaptive research sequence.

Before any strong paper-level generalization claim, the method must be tested under a preregistered independent deployment setting or source/site where the deployed model sees only aggregate station data.

The sealed JPL final holdout is not opened by this protocol.
