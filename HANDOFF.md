# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-15。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、`docs/JPL_R11_S0_BACKBONE_SCREEN_OUTCOME_20260915.md` 与 `docs/JPL_R11_P1_HORIZON_TARGETED_PRIVILEGED_ARRIVAL_PROTOCOL_20260915.md`。

## 1. Frozen scientific state

```text
R10-R0 = MIXED_DEVELOPMENT_ROBUSTNESS, COMPLETE
R11-S0 = COMPLETE / STOP_DEEP_CORE_ROUTE
R11-S0 fits = 68 / 68
selected_backbone = null
original R11-M1 = CANCELLED
R11-P1 protocol = FROZEN
R11-P1 implementation = NOT YET DONE
R11-P1 run = NOT RUN
final holdout = SEALED
```

Final JPL holdout remains `2019-03/06/09/12` and has not been accessed.

## 2. Accepted S0 result

Station-HGB pooled anchor:

```text
MAE   25.8731522189 A
RMSE  53.1466051439 A
WAPE  0.1737126243
```

Deep candidates:

```text
GRU      27.2072425618 A  (+5.16%)  ineligible
TCN      26.9086600381 A  (+4.00%)  ineligible
N-HiTS   34.8304657865 A (+34.62%)  ineligible
PatchTST 32.3044344149 A (+24.86%)  ineligible
```

Do not reopen S0, add a fifth architecture, relax thresholds or rerun it.

## 3. Why R11-P1 exists

Earlier R6 mechanism evidence and the S0 horizon diagnostic point to the same regime boundary:

```text
15–30 min   existing-session evolution dominates removable error
60–240 min  future-arrival uncertainty dominates removable error

TCN vs HGB:
15 min   +49.36%
30 min   +11.87%
60 min    -2.22%
120 min   -1.01%
240 min   -3.35%
```

This does not rescue S0. It motivates a separately frozen method experiment.

## 4. Methodological choice

Do not implement direct HGB residual targets as the primary carrier. A leakage-free residual learner would require nested chronological HGB cross-fitting for training rows and would confound the privileged-supervision question.

R11-P1 instead freezes a deterministic horizon-gated hybrid:

```text
15/30 min       Station-HGB
60/120/240 min  station-only TCN
```

The scientific object is not the hybrid itself. The object is whether a **future-arrival contribution label available only during training** improves the long-horizon station-only TCN representation.

## 5. Arms

```text
Arm A  Station-HGB all five horizons

Arm B  HGB short + TCN long
       L = L_total

Arm C  HGB short + identical TCN long
       L = L_total + 0.5 * L_arrival
```

`L_arrival` uses offline session-resolved future-arrival contribution `A(t,h)` only as a label during training. The deployed model never receives session fields.

The arrival head is discarded at inference.

## 6. Data/training contract

Reuse exact S0:

```text
development months  2019-01 / 2019-04 / 2019-07 / 2019-10
train               earlier dev months + current days 1-14
validation          current days 15-17
test                day >=18 exact frozen origins
history             96 x 15-min bins, aggregate current + validity mask
seeds               2026091401 / 02 / 03
optimizer           AdamW 1e-3, wd 1e-4
batch               256
max epochs          120
patience            12
AMP                 off
deterministic CUDA  required
CPU fallback        prohibited
```

Long-horizon task set is exactly `{60,120,240}`.

Auxiliary weight is frozen at `0.5`; no search.

Early stopping uses **total-load validation MAE only**.

## 7. Decision rule

PASS requires all:

```text
C vs B long-horizon pooled MAE gain >= 1.0%
C wins >= 2/3 long horizons
no horizon degradation > 1.0%
C wins >= 3/4 months
C wins >= 2/3 paired seeds
C seed spread <= 3.0%
C long pooled beats HGB long pooled
full five-horizon C hybrid beats HGB pooled
all folds complete / no test-row removal
```

Exhaustive decisions:

```text
PASS_PRIVILEGED_ARRIVAL_SUPERVISION
MIXED_PRIVILEGED_ARRIVAL_SIGNAL
STOP_PRIVILEGED_SUPERVISION_ROUTE
```

If MIXED or STOP, do not tune lambda, add an existing-session auxiliary head, add another backbone or move the 30/60 boundary inside the same protocol.

## 8. Fit ceiling

```text
Arm B  12 deep fits
Arm C  12 deep fits
total  24 deep fits
```

Station-HGB deterministic replay is allowed only for the frozen anchor when row-level local predictions are needed.

## 9. Novelty boundary

Do not claim novelty for:

```text
LUPI generally
multi-task learning generally
TCN
hybrid boosting + DL
decomposition
residual correction
existing/future-session split
```

Candidate contribution, subject to evidence:

> cross-granularity future-arrival supervision: session-resolved future-arrival contribution labels are used only during training to improve a station-level aggregate-only forecaster, with no session information needed at inference.

Targeted literature search has not located an exact match; this is negative search evidence, not proof of priority.

## 10. Execution policy

Next step is implementation of R11-P1. Favor fast local preflight and user-machine execution because the frozen experiment is small and the RTX 5080 run is fast. Do not make every small implementation repair wait for full GitHub CI. Preserve branch/PR/code identity and run a full CI pass when the local candidate is stable enough for archival.

Preserve worktrees/status files; no reset/clean/stash/force-push/automatic deletion. Final holdout remains sealed.