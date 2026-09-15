# JPL/ACN R11-S0 implementation handoff

Date: 2026-09-15  
Status: **implementation reviewed / CI passed / launcher v1.1 recovered and frozen / formal R11-S0 run NOT RUN**.

Latest execution-control correction: see `docs/JPL_R11_S0_LAUNCHER_RECOVERY_20260915.md`. The previously documented `evcf_r11_s0_launcher_v1.py` was not recoverable and is retired; it is not authorized for execution.

## 1. Frozen scientific protocol

R11-S0 remains the station-level-only deep-backbone screen defined by:

`docs/JPL_R11_S0_STATION_LEVEL_DEEP_BACKBONE_SCREENING_PROTOCOL_20260914.md`

No scientific threshold, model family, seed, horizon, chronology or input contract changed during implementation or launcher recovery.

Final JPL holdout remains sealed:

```text
2019-03 / 2019-06 / 2019-09 / 2019-12
```

## 2. Reviewed implementation identity

```text
protocol freeze commit    9dfeb7b1b99d7e99de1b653473742b6c5148be04
reviewed executable       04b4d0ad5d7c09e84841f438725abb4b25b6f91c
implementation merge      726ffe8f8c7239152e09f056d0c256e0d1f46cf5
PR                        #103
final CI workflow run     34930090477
```

The reviewed executable is the PR head that passed full CI. Formal execution checks out this reviewed executable itself in a detached preserved worktree.

## 3. Final CI result

Final CI on reviewed head `04b4d0ad5d7c09e84841f438725abb4b25b6f91c` passed:

```text
pytest       PASS
compileall   PASS
Ruff         PASS
```

No JPL real-label R11-S0 fit was performed in CI.

## 4. Implemented input boundary

All R11-S0 forecasting arms use only:

```text
96-bin station_current_mean_a history
96-bin history-validity mask
issue-time calendar context
target-time calendar context
normalized forecast horizon
```

Explicitly not used as R11-S0 predictors:

```text
session ID / session tuples
requested departure / requested energy
connected- or active-session count
pilot information
per-session current
existing/arrival component truths
future-session information
```

## 5. Implemented model identities

Shape-only parameter-count preflight produced:

```text
GRU        93,697 trainable parameters
TCN       118,785 trainable parameters
N-HiTS    116,133 trainable parameters
PatchTST   76,737 trainable parameters
```

All are inside the frozen `50,000–250,000` band, so no width correction was required. `Station-HGB` uses the same station-only input information and the already frozen M2 HGB hyperparameter set for each horizon.

## 6. Implemented execution guards

The implementation is fail-closed on development-month identity, exact frozen formal test-origin counts, station-input schema, causal training/validation cutoffs, missing-history mask semantics, finite labels/predictions, parameter-count band, frozen seeds, 68-fit ceiling, reviewed Git content identity, and formal PyTorch/CUDA/GPU identity.

Formal environment:

```text
Python 3.11.x
PyTorch 2.14.0
CUDA 13.2
NVIDIA GeForce RTX 5080 / cuda:0
float32
CUBLAS_WORKSPACE_CONFIG=:4096:8
```

There is no CPU fallback.

## 7. Formal fit budget and decisions

```text
Station-HGB   20 fits
GRU           12 fits
TCN           12 fits
N-HiTS        12 fits
PatchTST      12 fits
--------------------
formal total  68 fits
```

Allowed decisions are exactly:

```text
SELECT_STATION_BACKBONE
MIXED_STATION_BACKBONE
STOP_DEEP_CORE_ROUTE
```

No fifth architecture, extra seed, ensemble, clipping, calibration or post-result hyperparameter search is permitted.

## 8. Current authoritative launcher

The only authorized launcher is:

```text
filename  evcf_r11_s0_launcher_v1_1.py
SHA256    fce2ac327ca13af530faf0d2a70a1443b010218b1b3a0abb8826f5f640d6cc00
schema    evcf-r11-s0-launcher/v1.1
```

The launcher verifies/fetches the reviewed executable, verifies frozen protocol/config Git blob identities and reviewed-executable ancestry in the implementation merge, creates/reuses a preserved detached reviewed worktree, verifies the four development processed-manifest identities and absence of final-holdout paths, sets deterministic CUDA configuration before PyTorch starts, runs formal environment preflight, and only then invokes the reviewed PR #103 runner. It writes one aggregate-only `evcf_r11_s0_status_*.json` beside itself and performs no automatic cleanup.

## 9. Current execution state

```text
formal R11-S0 run       NOT RUN
formal fit_count        0
final holdout accessed  false
session predictors used false
```

## 10. Next action

The implementation gate is satisfied. The next authorized action is one formal local R11-S0 run using the exact v1.1 launcher above.

After the launcher exits, upload only the newest:

```text
evcf_r11_s0_status_YYYYMMDDTHHMMSSZ.json
```

whether COMPLETE or INCOMPLETE. If INCOMPLETE, do not edit code, rerun, change the environment or create extra fits before the status is inspected. If COMPLETE, audit the result against the frozen SELECT/MIXED/STOP logic before any R11-M1 protocol is designed.

No JPL final-holdout access is authorized by R11-S0 regardless of its result.