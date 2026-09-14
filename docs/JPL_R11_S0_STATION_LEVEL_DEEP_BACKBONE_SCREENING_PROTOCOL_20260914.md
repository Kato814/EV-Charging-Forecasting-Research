# JPL/ACN R11-S0 station-level deep-backbone screening protocol

Date: 2026-09-14  
Status: **frozen before any R11-S0 real-data fit**.  
Purpose: select a stable station-level deep backbone for the later privileged-supervision experiment. This protocol does **not** claim that the selected backbone is novel.

## 1. Scientific purpose

R11-S0 is an engineering-controlled architecture screen under a stricter portability contract than the earlier ACN/JPL structured line.

The deployed core must work when a future dataset contains only aggregate station load/current and timestamps. Therefore R11-S0 forbids session-resolved predictors and asks only:

> Which compact deep architecture provides the most stable carrier for a station-level multi-horizon forecaster under matched aggregate-only information and matched development chronology?

The result of R11-S0 is a backbone-selection decision, not a publication contribution. The planned scientific experiment remains R11-M1, which will hold the selected backbone and station-level inputs fixed and vary only whether training receives session-resolved existing/arrival auxiliary labels.

Final JPL holdout `2019-03/06/09/12` remains sealed.

## 2. Frozen data boundary

Development months only:

```text
2019-01
2019-04
2019-07
2019-10
```

Target:

```text
station_current_mean_a
unit = A
```

Grid and forecast horizons:

```text
15-min aggregation
15 / 30 / 60 / 120 / 240 min horizons
```

The test origins must be the exact common formal OOS issue times already used by the frozen JPL development line. The implementation must verify the intersection across all five horizons before any deep fit.

Expected test identity:

```text
2019-01   1305 origins
2019-04   1180 origins
2019-07   1294 origins
2019-10   1296 origins
------------------------
pooled     5075 origins
pooled    25375 origin-horizon records
```

Any mismatch in the frozen test-origin identity is a pre-fit failure. No favorable row deletion is permitted.

## 3. Station-level-only input contract

### 3.1 Historical sequence

Each issue origin uses exactly the previous 24 h of aggregate station current:

```text
context_length = 96 bins
bin_width      = 15 min
```

The sequence contains two channels only:

```text
1. standardized station_current_mean_a
2. history-validity mask (1 valid, 0 unavailable)
```

Normalization statistics are computed from the training partition of the current chronological fold only. An unavailable historical load value is set to zero **after standardization** and identified by the mask. No test/validation value contributes to normalization.

History must not cross a month boundary when the underlying monthly artifact has no physically verified carry-in. Origins lacking 96 historical positions are excluded from training/validation construction, but the frozen formal test-origin set itself may not be altered; if a formal test origin cannot be represented under this contract, the run fails before fitting.

### 3.2 Known calendar context

Generic timestamp-derived information is allowed because it exists in any timestamped station-level dataset.

Issue-time context:

```text
sin/cos(time of day)
sin/cos(day of week)
weekend flag
```

For each target horizon, the decoder also receives target-time context:

```text
sin/cos(target time of day)
sin/cos(target day of week)
target weekend flag
horizon_minutes / 240
```

No weather, tariff, traffic, occupancy, connected-session count, pilot, requested-departure or per-session quantity is used in R11-S0. Optional exogenous variables are deferred so the screening tests the minimum portable core.

### 3.3 Explicitly prohibited predictors

R11-S0 must not use:

- session IDs or individual session tuples;
- requested departure or requested energy;
- connected/active-session counts if they are derived from session records;
- per-session or aggregate pilot/current state derived from ACN session telemetry beyond the aggregate target history itself;
- existing/arrival component truths;
- realized future sessions;
- any final-holdout artifact.

The existing/arrival component truths are reserved for the later R11-M1 **training-only supervision** experiment.

## 4. Frozen chronological screening folds

R11-S0 uses four chronological development folds, one for each development month. There is no random train/test split.

For target month `m`:

### Training partition

Use:

1. all eligible issue rows from earlier development months in chronological order; and
2. eligible issue rows from local days 1–14 of month `m`.

Examples:

```text
January fold: training = Jan days 1-14 only
April fold:   training = all Jan + Apr days 1-14
July fold:    training = all Jan + all Apr + Jul days 1-14
October fold: training = all Jan + all Apr + all Jul + Oct days 1-14
```

Only rows whose complete five-horizon labels are causally known inside the training partition are permitted.

### Validation partition

Current target month local days 15–17 only.

Validation is used only for early stopping/checkpoint selection. It is never merged into training after model selection.

### Test partition

Current target month local day >=18, restricted to the exact frozen common formal OOS origins.

Thus every reported test prediction is chronologically after the current-month training/validation window. Earlier development months may become historical training information for later folds because their outcomes would be known by then.

## 5. Candidate deep backbones

All candidates receive the same station-level information contract and predict all five horizons jointly.

A shared horizon-conditioned decoder is used where the architecture naturally produces one latent state. Architecture-specific native forecasting heads are allowed only when needed to preserve the defining structure of that family; they must receive the same raw information.

### 5.1 GRU reference

Frozen configuration:

```text
layers       = 2
hidden_size  = 96
dropout      = 0.10
input        = 96 x 2 sequence
```

The final recurrent state is concatenated with issue/target calendar context and passed through a shared two-layer horizon decoder.

### 5.2 TCN reference

Frozen configuration:

```text
residual blocks = 5
channels        = 64
kernel size     = 3
dilations       = [1, 2, 4, 8, 16]
convs/block     = 2
dropout         = 0.10
causal padding  = true
```

The receptive field must cover the 96-bin input. The final causal representation is passed to the same horizon-conditioned decoder concept used by the GRU arm.

### 5.3 N-HiTS reference

Use a compact in-repository N-HiTS implementation with no external architecture search:

```text
stacks                 = 3
pool/downsample factors= [1, 4, 16]
blocks per stack       = 1
MLP hidden width       = 128
MLP hidden layers      = 2
activation              = ReLU
forecast length         = 5
```

The implementation must preserve the defining hierarchical pooling/residual interpolation logic. Calendar context may enter as known exogenous decoder context, but the model may not receive any additional information unavailable to the other candidates.

### 5.4 PatchTST control

Frozen compact configuration:

```text
context length = 96
patch length   = 16
stride         = 8
d_model        = 64
heads          = 4
encoder layers = 2
FFN width      = 128
dropout        = 0.10
RevIN          = disabled
```

The two station-history channels are patched without adding session information. A shared target-time/horizon context is supplied to the forecast head.

PatchTST is a strong modern control, not a presumed final backbone and not a novelty claim.

## 6. Capacity control before real-data fitting

Target trainable-parameter band for every deep candidate:

```text
50,000 <= trainable parameters <= 250,000
```

Before any real-data fit, the implementation must report exact parameter counts using shape-only/unit-test inputs.

If a frozen configuration falls outside this band, only a deterministic width reduction/increase is allowed **before real labels are seen**. The adjustment may change hidden/channel width only; it may not change depth, receptive-field logic, patching logic or architecture family. The final adjusted widths and parameter counts must be committed before formal R11-S0 execution.

No performance-driven capacity tuning is allowed.

## 7. Non-deep station-level reference

R11-S0 includes `Station-HGB` as a same-information anchor.

For each month fold and horizon, use:

- the same 96-bin station-load history and masks;
- the same issue/target calendar context;
- the exact frozen M2 HistGradientBoostingRegressor hyperparameter set for that horizon;
- no session-derived M2 fields;
- no new hyperparameter search.

`Station-HGB` is trained separately per horizon because sklearn HGB is not the joint deep model under test.

Frozen S1, Equal and R7 totals may be reported on the same test origins as **context only**. They use richer information/training constructs and are not the R11-S0 eligibility threshold.

## 8. Common training policy for deep candidates

Formal environment target:

```text
Python 3.11.x
PyTorch 2.14.0 + CUDA 13.2
GPU = NVIDIA GeForce RTX 5080 / cuda:0
float32 only
no mixed precision
no CPU fallback for formal run
```

Use a separate R11 environment; do not mutate preserved historical environments/caches.

Common optimizer/training settings:

```text
optimizer        = AdamW
learning rate    = 1e-3
weight decay     = 1e-4
batch size       = 256
max epochs       = 120
early-stop patience = 12 epochs
minimum validation improvement = 1e-4 standardized-MAE units
gradient norm clip = 1.0
learning-rate scheduler = none
```

Training loss:

```text
mean SmoothL1 loss across the five standardized total-load targets
beta = 1.0
```

Target standardization uses the fold-training aggregate-current mean and standard deviation only. The same scalar train statistics are used for all five horizons because the physical target is the same station-current variable.

Validation checkpoint selection uses mean standardized MAE across all five horizons.

No ensemble prediction is allowed in R11-S0.

## 9. Random seeds and fit-count ceiling

Frozen deep seeds:

```text
2026091401
2026091402
2026091403
```

Every deep family runs all three seeds in all four month folds:

```text
4 architectures x 3 seeds x 4 month folds = 48 deep fits
```

`Station-HGB`:

```text
4 month folds x 5 horizons = 20 deterministic fits
```

Formal R11-S0 fit-count ceiling:

```text
68 fits total
```

Any additional real-data fit requires a separately frozen repair protocol. Failed preflight/configuration attempts before optimizer/model fitting do not count as fits but must be recorded.

Determinism settings must be enabled where supported. The implementation must record torch/CUDA versions and device identity. A deterministic-algorithm incompatibility must fail before silently substituting a different backend.

## 10. Required outputs

For each deep architecture and seed, report on the exact common test rows:

- pooled MAE, RMSE, WAPE;
- MAE/RMSE/WAPE by five horizons;
- MAE/RMSE/WAPE by four months;
- month x horizon MAE table;
- local-day pooled-over-horizon MAE;
- negative-prediction count/fraction;
- best epoch for each month fold;
- trainable parameter count;
- wall-clock training time per fold (descriptive only).

For model-level screening, aggregate deep results by the **median of the three seed-level metrics**. Do not ensemble the seed predictions.

Also report seed spread for pooled MAE:

```text
(max seed pooled MAE - min seed pooled MAE) / median seed pooled MAE
```

## 11. Frozen backbone eligibility and selection rule

`Station-HGB` is the station-only engineering anchor.

A deep candidate is **eligible for R11-M1 carrier selection** only if all of the following hold using median-of-seed metrics:

1. pooled MAE <= `1.02 * Station-HGB pooled MAE`;
2. worst horizon relative MAE degradation vs Station-HGB <= 10%;
3. worst month relative MAE degradation vs Station-HGB <= 10%;
4. pooled seed-spread <= 3%;
5. no test month/horizon is removed or reweighted;
6. all four chronological folds completed under the frozen input contract.

This screen intentionally allows a deep core to be within 2% of the strong same-information HGB reference because R11-S0 is selecting a carrier for the later privileged-supervision hypothesis, not claiming that deep learning alone is already superior.

### `SELECT_STATION_BACKBONE`

If one or more deep candidates are eligible:

1. choose the eligible candidate with the lowest median pooled MAE;
2. if the top two differ by <0.25% relative pooled MAE, choose the one with fewer trainable parameters;
3. freeze that architecture and its R11-S0 configuration before R11-M1 protocol design.

### `MIXED_STATION_BACKBONE`

If no candidate satisfies all eligibility conditions, but at least one candidate has pooled MAE within 2% of Station-HGB and pooled seed-spread <=3%, return `MIXED_STATION_BACKBONE`.

Consequence: do not start R11-M1 automatically. Review which stability condition failed without retuning models or adding a fifth architecture.

### `STOP_DEEP_CORE_ROUTE`

If every deep candidate is >2% worse than Station-HGB in pooled MAE, or every candidate exceeds the 3% pooled seed-spread ceiling, return `STOP_DEEP_CORE_ROUTE`.

Consequence: do not proceed to privileged-supervision R11-M1 with these backbones. Do not rescue the result with Mamba, a larger Transformer, extra station/session features or performance-driven architecture search inside this stage.

## 12. Relationship to R11-M1

R11-S0 never uses `E(t,h)` or `A(t,h)` as labels or inputs.

Only after `SELECT_STATION_BACKBONE` may a separate R11-M1 protocol compare:

```text
Arm 1: station-level inputs + total-load supervision
Arm 2: identical station-level inputs/backbone + training-only E/A auxiliary supervision
```

R11-M1 must keep inference station-only. The R11-S0 result does not authorize session inputs at deployment.

## 13. Prohibited actions

R11-S0 forbids:

- access to final JPL holdout `2019-03/06/09/12`;
- changing the five horizons after seeing results;
- changing the 96-bin context after seeing results;
- using session-derived predictors;
- using R7 requested-departure features;
- hyperparameter search over learning rate, depth, patch length, dilation pattern or dropout;
- seed selection;
- model ensembling;
- post-hoc clipping/calibration;
- adding Mamba/SSM/another backbone after observing R11-S0;
- selecting favorable months, days or horizons;
- changing the selection thresholds after execution.

## 14. Implementation gate before formal run

This protocol freezes the scientific screen but does not yet authorize a local formal fit.

Before R11-S0 execution:

1. implement data construction and the four candidates on an isolated code branch;
2. add unit tests for chronology, no-session feature contract, target-row identity and model output shapes;
3. run CPU shape/smoke tests and CUDA-environment preflight;
4. confirm parameter-count band without real-label training;
5. review code and freeze the executable commit;
6. run full GitHub CI once for the final code candidate where practical;
7. issue one pinned local launcher;
8. only then run the formal 68-fit R11-S0 screen once.

Pure protocol/documentation updates remain CI-free under the current GitHub Actions conservation policy.
