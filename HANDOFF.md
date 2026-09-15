# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-15。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R10-R0 outcome](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_OUTCOME_20260914.md)、[Post-R10 paper-viability synthesis](docs/JPL_POST_R10_PAPER_VIABILITY_NOVELTY_SYNTHESIS_20260914.md)、[R11 direction screening](docs/JPL_R11_STATION_LEVEL_DEEP_METHOD_SCREENING_20260914.md)、[R11-S0 protocol](docs/JPL_R11_S0_STATION_LEVEL_DEEP_BACKBONE_SCREENING_PROTOCOL_20260914.md)、[authority/quarantine note](docs/JPL_R11_S0_AUTHORITY_QUARANTINE_NOTE_20260915.md) 与 [pre-fit integrity repair](docs/JPL_R11_S0_PREFIT_INTEGRITY_REPAIR_20260915.md)。

## 1. Frozen scientific state

```text
S1    = MIXED_STRUCTURED_SIGNAL, CLOSED
P1    = STOP_MECHANISM_ROUTE, CLOSED
R1    = MIXED_JOINT_STATE_SIGNAL, CLOSED
R2    = STOP_HIGHER_ORDER_SET_ROUTE, CLOSED
R3-C0 = STOP_CONTROL_ENDOGENEITY_ROUTE, CLOSED
R4-I0 = MIXED_STATE_ALIASING_SIGNAL
R4-D1/R4-D2 = COMPLETE diagnostics
R5    = STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE, CLOSED
R6-O0 = MIXED_COMPONENT_ORACLE_SIGNAL, COMPLETE
R7-C0 = PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL, COMPLETE
R7-D1 = TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL, COMPLETE
R8-C0 = NO_STABLE_HORIZON_ALIGNED_ADVANTAGE, COMPLETE
R9-C0 = STOP_DEPARTURE_REPRESENTATION_REFINEMENT, COMPLETE
R10-R0 = MIXED_DEVELOPMENT_ROBUSTNESS, COMPLETE
Post-R10 paper viability = CONDITIONAL_MECHANISM_PAPER_VIABILITY
R11 direction = portable station-level deep method
R11-S0 protocol = FROZEN
R11-S0 first formal attempt = INCOMPLETE_PRE_FIT / fit_count 0
R11-S0 integrity repair = REVIEWED / MERGED / FULL CI PASS
R11-S0 replacement launcher v1.2 = FROZEN
R11-S0 replacement formal run = NOT RUN
```

Final JPL holdout `2019-03/06/09/12` remains sealed.

## 2. R11 deployment contract

Required inference inputs:

```text
aggregate station-load/current history
timestamp/calendar context
```

Not required at inference:

```text
session IDs
requested departure / requested energy
per-session current/pilot
existing/arrival component truths
future sessions
```

The planned scientific hypothesis remains `station-level multi-horizon core + session-resolved training-only auxiliary supervision`. Session information is privileged source-side supervision, not a deployment feature.

## 3. R11-S0 frozen protocol

Target and data boundary:

```text
target              station_current_mean_a (A)
development months  2019-01 / 2019-04 / 2019-07 / 2019-10
history              96 x 15-min bins = 24 h
channels             standardized aggregate current + validity mask
horizons             15 / 30 / 60 / 120 / 240 min
```

Candidates:

```text
GRU      2 layers / hidden 96
TCN      5 causal residual blocks / dilations 1,2,4,8,16
N-HiTS   3 stacks / pooling 1,4,16
PatchTST patch16 / stride8 / d_model64 / 2 layers
Station-HGB same-information anchor
```

Chronology:

```text
train      all earlier dev months + current days 1-14
validation current days 15-17
test       current day >=18, exact frozen origins only
```

Frozen formal test origins:

```text
2019-01 1305
2019-04 1180
2019-07 1294
2019-10 1296
pooled  5075 origins = 25375 origin-horizon records
```

Training is frozen to AdamW `1e-3`, weight decay `1e-4`, batch `256`, max `120` epochs, patience `12`, SmoothL1, three frozen seeds, float32, no AMP.

Formal ceiling:

```text
48 deep + 20 Station-HGB = 68 fits
```

## 4. Original implementation and first attempt

Original implementation line:

```text
protocol freeze commit    9dfeb7b1b99d7e99de1b653473742b6c5148be04
reviewed executable       04b4d0ad5d7c09e84841f438725abb4b25b6f91c
implementation merge      726ffe8f8c7239152e09f056d0c256e0d1f46cf5
PR                        #103
```

Shape-only parameter counts:

```text
GRU        93,697
TCN       118,785
N-HiTS    116,133
PatchTST   76,737
```

First formal attempt with launcher v1.1:

```text
status file       evcf_r11_s0_status_20260915T061213Z.json
status SHA256     f29049799cf1536b514d0b20464b30d057224204a6151428fbed437ddd40cd1e
status            INCOMPLETE
reason            IMPLEMENTATION_DRIFT
fit_count         0
holdout accessed  false
GPU preflight     PASS
```

Environment confirmed on the user machine:

```text
NVIDIA GeForce RTX 5080 / cuda:0
PyTorch 2.14.0+cu132
CUDA 13.2
float32 smoke PASS
```

No completed R11-S0 fit and no performance result were observed.

## 5. Root cause and repaired execution identity

The failure came from raw-byte comparison between Git blob bytes and Windows checkout bytes. It was an execution-integrity portability defect, not a model/data/result defect.

The narrow repair keeps exact fail-closed identity but uses:

```text
exact HEAD == reviewed repaired commit
all authoritative runtime paths present/non-symlink
all paths exist in reviewed commit
git diff --quiet --no-ext-diff <commit> -- <path> == clean
```

Regression tests accept CRLF/LF normalization while rejecting semantic content drift.

Frozen repair identity:

```text
repair PR                    #105
reviewed repaired executable 2107795e817bb8f2b490b98ed78f663f685306c8
repair implementation merge  384ff65f36c78bcc3cb89aed9e08ade1b5f12260
final repair CI run           34940555171
final repair CI               1264 passed, 4 skipped; compileall PASS; Ruff PASS
```

No scientific setting changed.

## 6. Parallel implementation quarantine

PR #104 remains a parallel **non-authoritative** implementation artifact:

```text
PR #104 head    6688f9c631b9f03a8f1a995bab913141cedf9905
merge to main   2433e76b0d1ab3f1d1bfa8feb2cae42bd782ae57
```

Do not use or mix its unprefixed `r11_s0_*` modules/scripts with the PR #105 repaired execution line. Preserve historical evidence; no reset/force-push/delete.

## 7. Sole authorized replacement launcher

```text
filename  evcf_r11_s0_launcher_v1_2.py
SHA256    c990a5dced70a75ac5c5b48615363fdb0e694fc19902d8c58ef13a573f2e7724
schema    evcf-r11-s0-launcher/v1.2
```

The launcher checks out reviewed repaired executable `2107795e817bb8f2b490b98ed78f663f685306c8` in a detached preserved worktree, verifies repair-merge ancestry, frozen protocol/config Git blobs, four development manifest identities, holdout absence, preserved existing worktrees, deterministic CUDA configuration and formal RTX 5080 environment before any fit. No CPU fallback or automatic cleanup.

## 8. Frozen R11-S0 decisions

Eligibility for R11-M1 carrier selection:

```text
pooled median MAE <= 1.02 * Station-HGB
worst horizon degradation <= 10%
worst month degradation   <= 10%
pooled seed spread        <= 3%
all four folds complete
```

Exhaustive outcomes:

```text
SELECT_STATION_BACKBONE
MIXED_STATION_BACKBONE
STOP_DEEP_CORE_ROUTE
```

If multiple candidates are eligible, choose lowest pooled median MAE; if top two differ by `<0.25%`, choose fewer parameters. No fifth model, extra seed, ensemble, clipping, calibration, Mamba/SSM rescue, or result-driven architecture search.

## 9. Current execution state

```text
first formal attempt          INCOMPLETE pre-fit
completed R11-S0 fits         0
scientific R11-S0 result      NONE
replacement formal run        NOT RUN
final holdout accessed        false
session predictors used       false
```

## 10. Next action

Run the exact v1.2 launcher **once** on the user machine after SHA verification:

```text
c990a5dced70a75ac5c5b48615363fdb0e694fc19902d8c58ef13a573f2e7724
```

After it exits, upload only the newest:

```text
evcf_r11_s0_status_YYYYMMDDTHHMMSSZ.json
```

whether `COMPLETE` or `INCOMPLETE`.

If `INCOMPLETE`, do not debug/edit/rerun before status inspection. If `COMPLETE`, audit the frozen SELECT/MIXED/STOP result before designing R11-M1.

R11-S0 never authorizes final JPL holdout access.

## 11. Hygiene

Preserve all worktrees, status files and private caches. No reset/clean/stash/force-push/automatic deletion. Do not reopen R7/R9/R10 routes. Continue GitHub Actions conservation; pure documentation/status archival remains CI-free where applicable.
