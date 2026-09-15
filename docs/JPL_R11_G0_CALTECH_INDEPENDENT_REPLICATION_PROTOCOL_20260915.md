# R11-G0 Caltech independent-site replication protocol

Date: 2026-09-15  
Status: **PROTOCOL FROZEN / NO CALTECH FIT AUTHORIZED YET**

## 1. Trigger

R11-P1 completed the frozen JPL development experiment with:

```text
44 / 44 fits COMPLETE
decision = MIXED_PRIVILEGED_ARRIVAL_SIGNAL
```

Future-arrival training-only supervision improved the same station-only long-horizon TCN under all frozen development views:

```text
3 / 3 long horizons
4 / 4 development months
3 / 3 paired seeds
median pooled long-horizon MAE gain = 1.6437%
```

The only frozen PASS failure was seed spread:

```text
Arm B spread = 4.8547%
Arm C spread = 4.8494%
required <= 3.0%
```

Because the spread is almost identical in the control and privileged arms, R11-P1 supports a consistent privileged-supervision signal but not a fully stable carrier. The correct next step is **independent replication**, not further JPL development tuning.

JPL final holdout `2019-03/06/09/12` remains sealed.

## 2. Independent source

The independent source is the official ACN-Data **Caltech** site:

```text
site_id = caltech
source  = official ACN-Data REST API
formal endpoint family = /api/v1/sessions/caltech/ts
```

The Caltech site is independent of the JPL site used for R11 development. The official ACN-Data schema supplies session connection/disconnection metadata and charging-current time series needed to reconstruct future-arrival contribution labels offline.

No Caltech model outcome, monthly target metric, Arm B/C result, or seed result may be inspected before the data/fit contract below is frozen.

## 3. Frozen calendar months

Use exactly the complementary 2019 quarterly-offset months:

```text
2019-02
2019-05
2019-08
2019-11
```

These months are fixed before formal Caltech acquisition and fitting. They do not overlap the JPL R11 development months (`01/04/07/10`) or the sealed JPL final-holdout months (`03/06/09/12`).

No month substitution is allowed after inspecting Caltech data or model results. If a month fails the pre-fit data-integrity contract, R11-G0 stops as incomplete unless a new protocol is frozen before any replacement acquisition.

## 4. Acquisition contract

Formal acquisition must use the repository ACN-Data REST client with:

```text
site = caltech
timeseries = true
credential = local ACN_API_TOKEN environment variable only
raw payloads preserved locally
API token never written to files, logs, manifests, Git or status JSON
```

Formal data source is the official API, not a third-party mirror or repackaged static snapshot.

Acquisition must preserve source timestamps and raw session records. No timestamp shift, synthetic interpolation, or energy-based reconstruction of missing current is allowed.

## 5. Preprocessing contract

Reuse the accepted JPL physical preprocessing semantics unless this protocol explicitly says otherwise:

```text
sampling derivation      mode of positive raw timestamp differences
LOCF cap                 60 s
boundary sensitivity     60 s
aggregation              15 min
UTC grid policy          continuous physical UTC
main coverage field      valid_bin_90
minimum valid-bin rate   0.8
main active threshold    0.1 A
lookback                 1440 min
issue step               15 min
horizons                 15 / 30 / 60 / 120 / 240 min
```

The target remains exactly:

```text
station_current_mean_a
unit = A
```

The station-history representation and validity-mask semantics must match R11-S0/P1. No new weather, traffic, price, user-demographic or session-summary predictor is introduced.

### 5.1 Missing / malformed trajectory policy

Before any model fit, raw current/pilot containers are checked structurally and temporally.

For synchronized current/pilot raw-order UTC non-monotonicity that cannot be represented as a physically ordered trajectory:

```text
preserve raw              true
sort repair               false
timestamp shift           0
interpolation              false
full-session trajectory quarantine allowed only as pre-fit QA
quarantined trajectory treated as unobservable
coverage denominator includes quarantined interval
```

A month stops before fitting if full-session trajectory quarantine exceeds `0.1%` of acquired sessions.

Any target/history interval rendered unobservable by QA is handled only by the frozen observability rules. Outcome-dependent row removal is prohibited.

## 6. Formal-row freeze before fitting

After acquisition/preprocessing and **before any Arm B/C/HGB fit**, create a Caltech R11-G0 data manifest containing aggregate-only evidence:

```text
month
raw/session counts
QA/quarantine counts
processed snapshot SHA256
formal issue-time count
formal test-origin count
common-row count per horizon
```

No session IDs, user IDs, row-level targets, row-level predictions or absolute paths are published.

The manifest freezes the exact common evaluation rows. After this manifest is frozen:

```text
no test row may be removed
no test row may be reweighted
no validity threshold may change
no month may be replaced
```

## 7. Chronology

Use the exact R11-S0/P1 fold policy on the Caltech month set:

```text
for target month m:
  train       = all earlier R11-G0 Caltech months + current month days 1-14
  validation  = current month days 15-17
  test        = current month local day >= 18
```

Requirements:

```text
96-bin history must be causally available
training/validation labels must be fully realized before the next split boundary
same rows for Arm B, Arm C and Station-HGB comparison
no label from test day may enter training or validation
```

Timezone remains `America/Los_Angeles`.

## 8. Inference contract

At deployment, predictions may depend only on:

```text
96 x 15-min aggregate station-current history
96-bin validity mask
issue-time calendar context
target-time calendar / horizon context
```

Prohibited at inference:

```text
session ID
user ID
station/session identity features
requested departure
requested energy
per-session pilot/current
existing-session truth
future-arrival truth
future sessions
```

Session-resolved information is allowed only for offline training-label construction and data QA.

## 9. Future-arrival privileged label

For issue time `t` and horizon `h`:

```text
Y(t,h) = total station current target
A(t,h) = contribution at t+h from sessions with connection_time > t
E(t,h) = contribution at t+h from sessions with connection_time <= t
```

Before fitting, require on all eligible privileged-label rows:

```text
Y = E + A within 1e-6 A
A >= 0
E >= 0
finite values only
exact issue-time alignment
```

Future-arrival labels are never inference inputs.

## 10. Frozen method copied from R11-P1

No model-selection step is run on Caltech.

### Short horizons

```text
15 / 30 min -> same-information Station-HGB
```

Station-HGB uses the already frozen JPL-selected M2 HGB hyperparameters for the corresponding horizons. Caltech is not used to retune HGB hyperparameters.

### Long horizons

```text
60 / 120 / 240 min -> station-only TCN
```

Use the exact R11-P1 carrier:

```text
5 causal residual blocks
channels = 64
kernel = 3
dilations = 1,2,4,8,16
two convolutions per block
same horizon-conditioned total/arrival heads
same station-only history/calendar input
float32
```

No architecture width/depth change is allowed.

## 11. Frozen experimental arms

```text
Arm A
  Station-HGB at 15/30/60/120/240 min

Arm B
  Station-HGB at 15/30 min
  TCN total head at 60/120/240 min
  L = L_total

Arm C
  Station-HGB at 15/30 min
  same TCN total head at 60/120/240 min
  L = L_total + 0.5 * L_future_arrival
```

Arm B and C use identical architecture, rows, normalization policy, seeds, optimizer, batching, early stopping and inference contract. The arrival head is discarded at inference.

## 12. Training policy

Reuse R11-P1 exactly:

```text
optimizer        AdamW
learning rate    1e-3
weight decay     1e-4
batch size       256
max epochs       120
patience         12
min val improve  1e-4 standardized total-load MAE
grad clip        1.0
scheduler        none
AMP              off
CPU fallback     prohibited
deterministic CUDA required
```

Seeds remain exactly:

```text
2026091401
2026091402
2026091403
```

Normalization statistics are computed from training rows only. Total and future-arrival targets use separate train-only scalar mean/std values, exactly as in R11-P1.

Early stopping is based **only on total-load validation MAE**.

No extra seed, seed search or validation-ranked seed selection is allowed.

## 13. Fit ceiling

```text
Arm B   4 months x 3 seeds = 12 deep fits
Arm C   4 months x 3 seeds = 12 deep fits
Total deep fits            = 24
Station-HGB replay         = 20 deterministic fits
Total formal fits ceiling  = 44
```

No third neural arm, lambda sweep, HGB retuning, architecture search, clipping, calibration or ensemble is allowed.

## 14. Primary metrics

Primary comparison:

```text
Arm C vs Arm B
metric = pooled MAE over 60/120/240 min
```

Also report:

```text
RMSE
WAPE
by horizon
by month
paired seed pooled MAE
seed spread
local-day MAE deltas
negative prediction counts
complete five-horizon hybrid vs Station-HGB
```

JPL and Caltech results remain separately reported. Do not pool the two sites into one decision statistic.

## 15. Frozen independent-replication decision

### REPLICATE_PRIVILEGED_ARRIVAL_SIGNAL

All must hold on Caltech:

1. Arm C median pooled long-horizon MAE improvement over Arm B is `>= 1.0%`;
2. Arm C beats Arm B in at least `2/3` long horizons;
3. no long horizon degrades by more than `1.0%`;
4. Arm C beats Arm B in at least `3/4` Caltech months;
5. Arm C beats Arm B in at least `2/3` paired seeds;
6. Arm C pooled seed spread is `<= 3.0%`;
7. Arm C long-horizon pooled MAE beats frozen-parameter Station-HGB long-horizon pooled MAE;
8. complete five-horizon Arm C hybrid beats Station-HGB pooled MAE;
9. all frozen rows/folds/seeds complete.

### MIXED_INDEPENDENT_REPLICATION

Use when Arm C has a positive median pooled long-horizon gain over Arm B but one or more replication gates fail.

### FAIL_INDEPENDENT_REPLICATION

Use when Arm C does not improve Arm B in median pooled long-horizon MAE, or execution/data integrity fails after the formal row manifest is frozen.

These outcomes are exhaustive. Thresholds cannot be relaxed after result inspection.

## 16. Interpretation

If `REPLICATE_PRIVILEGED_ARRIVAL_SIGNAL`:

Allowed statement:

> The training-only future-arrival supervision effect observed on JPL development data independently replicates on the Caltech ACN site under the same aggregate-only deployment contract and frozen method definition.

This still does not authorize opening the JPL final holdout automatically.

If `MIXED_INDEPENDENT_REPLICATION`:

The mechanism has cross-site directional evidence but insufficient robustness. Do not tune on Caltech under R11-G0.

If `FAIL_INDEPENDENT_REPLICATION`:

The current privileged-arrival algorithmic claim is not independently supported. Close the route rather than rescue it with Caltech-specific tuning.

## 17. Actions-quota execution policy

GitHub Actions monthly minutes are currently exhausted. Until reset:

```text
branch + PR identity still required
local targeted/static checks required
formal acquisition/preprocessing/model runs occur locally
repository-wide Actions CI is not a blocking gate
full archival CI is deferred until quota reset
```

The quota limitation does not permit scientific-rule changes or direct untracked experimentation.

## 18. Authorization boundary

This document freezes the protocol only.

Next authorized work is **implementation and pre-fit Caltech acquisition/QA tooling**. Do not fit Arm B/C until the Caltech processed-row manifest has been generated and frozen under this protocol.
