# R11 algorithm-direction screening — portable station-level deep forecasting

Date: 2026-09-14  
Status: direction screening complete; **no training run is authorized by this document alone**.

## 1. Why the post-R10 direction is being revised

The previous post-R10 synthesis prioritized independent mechanism replication. The user clarified a broader research objective: the project should continue toward a genuinely useful forecasting algorithm, and the core model should remain usable when a future dataset contains only station-level load rather than session-resolved records.

This changes the design requirement.

The final method must not require ACN-specific session fields at inference. Session-resolved data may be used for mechanism discovery, source-side auxiliary supervision or ablation, but the deployed forecasting core must accept ordinary station-level time series.

Multi-horizon prediction and session-level data are therefore separated conceptually:

- **multi-horizon** is the forecasting task: predict several future lead times;
- **session-level** is one optional data granularity available in ACN;
- a portable method must preserve the first without requiring the second.

Final JPL holdout `2019-03/06/09/12` remains sealed.

## 2. Literature collision check after the user clarification

A generic claim of "multi-scale + multi-horizon deep learning" is no longer sufficient novelty. Recent EV charging-load literature already contains:

- Multi-scale Fusion Transformer for EV charging-station load prediction (Scientific Reports, 2026);
- adaptive time-frequency fusion PatchTST for EV charging load forecasting (2026);
- TCN-LSTM EV charging-load forecasting with similar-day identification (Applied Energy, 2025);
- Multiple Time Scale Deep Expert System for EV charging stations (IEEE Transactions on Smart Grid, 2025);
- TCN/DCT/Autoformer multi-step EV charging-load forecasting (Applied Energy, 2024);
- multi-horizon TFT EV charging-load forecasting with environmental features (2026).

Therefore multi-scale encoding, horizon-aware decoding, Transformer/PatchTST/TCN replacement, or another hybrid stack cannot be the contribution by itself.

Knowledge distillation also cannot be claimed as new by itself. `PhysDistill-EV: Physics-Augmented Aggregation-Based Knowledge Distillation for Edge EV Demand Forecasting` (IEEE Access, 2026, DOI `10.1109/ACCESS.2026.3726060`) already occupies EV-demand knowledge distillation for deployment. Any later use of distillation here must solve a different scientific problem.

## 3. Candidate directions screened

### A. Generic multi-scale horizon-conditioned network

**Disposition: baseline/backbone idea only; rejected as the core novelty.**

Advantages:

- fully station-level;
- portable across datasets;
- natural for 15/30/60/120/240-min prediction.

Problem:

- direct collision with recent EV-specific multi-scale and horizon-aware models;
- difficult to distinguish from MFT, ATF-PatchTST, TCN-LSTM and multiple-time-scale expert systems.

### B. Session-input deep dual branch

**Disposition: rejected as the portable core.**

A model that requires individual session tokens, requested departure or pilot/current traces at inference would be useful on ACN but would fail structurally on station-level-only datasets.

Session inputs may remain an optional enhancement experiment, but they cannot define the model's minimum input contract.

### C. Station-level continuity / innovation residual architecture

**Disposition: retained as a secondary architecture hypothesis, not selected as the main novelty.**

A station-level model can explicitly separate recent-load continuity from future innovation/ramp dynamics. This is portable and consistent with the JPL mechanism evidence, but persistence-residual and ramp-aware forecasting are already established adjacent routes. It may be useful as an internal module or ablation, not as the sole contribution.

### D. Station-level core with session-resolved **training-only auxiliary supervision**

**Disposition: selected for protocol design.**

This direction uses standard `Learning Using Privileged Information` / auxiliary-task learning principles, but applies them to the granularity mismatch specific to charging forecasting:

- model input at both training and inference remains station-level history/context;
- when a rich source dataset such as ACN provides session-resolved labels, those labels supervise auxiliary tasks during source training;
- session fields are not required by the deployed model;
- on a station-level-only target dataset, the same core model can run and can be fine-tuned using only aggregate-load loss.

The candidate scientific question is:

> Can session-resolved charging information, used only as privileged training supervision, improve the representation learned by an aggregate station-level multi-horizon forecaster and transfer useful structure to settings where session data are unavailable at inference?

This is distinct from edge-model compression. If pursued, the contribution must be cross-granularity privileged supervision, not "knowledge distillation" as a generic technique.

## 4. Proposed model contract

### 4.1 Minimum deployable input

The core input must be available in ordinary station-level datasets:

```text
historical aggregate station load/current
issue timestamp / calendar variables
optional station-level exogenous variables when available
```

No individual session ID, requested departure, per-session pilot/current, energy request or future-session information is required at inference.

### 4.2 Multi-horizon core

The core forecasts the fixed development horizons:

```text
15 / 30 / 60 / 120 / 240 min
```

A shared station-level encoder produces a latent state `z_t`. Horizon-specific or horizon-conditioned heads map that representation to the five forecasts. The exact backbone is deliberately **not frozen yet**.

### 4.3 Privileged source-side auxiliary tasks

On ACN/JPL source development data only, the existing accepted offline decomposition can provide training labels:

```text
existing-session contribution E(t,h)
future-arrival contribution   A(t,h)
total load/current            Y(t,h) = E(t,h) + A(t,h)
```

A source-training objective may therefore contain:

```text
L_total      = loss(Y_hat, Y)
L_existing   = loss(E_hat, E)
L_arrival    = loss(A_hat, A)
L_consistency= loss(Y_hat, E_hat + A_hat)
```

with a weighted multi-task objective to be preregistered before execution.

The important constraint is that `E_hat` and `A_hat` are inferred from station-level inputs only. Session-resolved information supplies **labels/supervision**, not deployment features.

After source pretraining, a station-level-only target dataset can use `L_total` alone for fine-tuning or evaluation.

## 5. Backbone policy

Transformer is not assumed to be the final backbone.

The next screening should compare several families under matched station-level inputs and controlled parameter/training budgets:

- GRU — recurrent reference;
- TCN — efficient causal local/multi-scale temporal encoder;
- N-HiTS — hierarchical basis/residual forecasting reference;
- PatchTST — strong modern sequence baseline and explicit collision control.

Optional later candidates such as Mamba/SSM are not justified until these lower-complexity families establish the basic station-level ceiling.

The scientific contribution cannot be "the winning backbone". Backbone screening only selects a carrier for the later privileged-supervision test.

## 6. Selected next stage: R11-S0

`R11-S0` = **station-level deep-backbone screening protocol design**.

R11-S0 will use only station-level inputs. It must not use session fields as predictors. Its role is to identify a stable core architecture before testing privileged supervision.

The protocol must freeze before any real fit:

1. common input window and station-level feature set;
2. common five-horizon target rows;
3. train/validation/test chronology within the existing development months;
4. candidate backbone definitions and comparable capacity/training budgets;
5. optimizer, seed policy, early-stopping rule and fit-count ceiling;
6. headline metrics and stability criteria;
7. explicit rule preventing selection based only on one favorable month/horizon;
8. no access to `2019-03/06/09/12`.

R11-S0 is architecture screening, not a publication claim.

## 7. Planned stage after R11-S0: R11-M1

Only if R11-S0 identifies a stable station-level core should `R11-M1` test the actual scientific hypothesis:

```text
same station-level model inputs
same backbone
same train/test rows

Arm 1: total-load supervision only
Arm 2: total-load + privileged existing/arrival auxiliary supervision
```

Primary question:

> Does training-only session-resolved supervision improve the station-level forecaster on total-load prediction without requiring session data at inference?

A negative result closes this route. It must not trigger feature engineering or a new backbone rescue inside the same protocol.

## 8. Portability test required later

If R11-M1 passes on JPL development data, the next evidence must use at least one station-level deployment setting where session information is hidden or unavailable to the deployed model.

Required comparison:

```text
station-only model trained normally
vs
same station-only model initialized/pretrained with privileged source supervision
```

The method is only genuinely portable if its inference contract remains aggregate-only and its advantage is not confined to the ACN session-rich source.

## 9. Frozen boundaries

The new direction does not reopen old result-driven rescue routes.

Still prohibited:

- opening the JPL final holdout;
- retuning R7 to pass R10;
- new requested-departure bins/ratios/weights as prediction features;
- claiming generic multi-scale, Transformer, knowledge distillation or multi-horizon forecasting as novel by themselves;
- selecting a target dataset after seeing favorable prediction results;
- using session-resolved future information as inference input.

## 10. Current decision

```text
portable algorithm objective                         ACCEPTED
session-level features required at inference         NO
generic multi-scale model as novelty                 REJECTED
generic knowledge distillation as novelty            REJECTED
training-only session-resolved auxiliary supervision SELECTED FOR PROTOCOL DESIGN
next stage                                            R11-S0 protocol design
model run                                             NOT YET AUTHORIZED
final JPL holdout                                     SEALED
```
