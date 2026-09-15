# JPL/ACN R11-S0 implementation handoff

Date: 2026-09-15  
Status: **implementation reviewed / CI passed / pinned external launcher frozen / formal R11-S0 run NOT RUN**.

## 1. Frozen scientific protocol

R11-S0 remains the station-level-only deep-backbone screen defined by:

`docs/JPL_R11_S0_STATION_LEVEL_DEEP_BACKBONE_SCREENING_PROTOCOL_20260914.md`

No scientific threshold, model family, seed, horizon, chronology or input contract was changed during implementation.

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

The reviewed executable is the PR head that passed full CI. The merge commit only integrates that reviewed head into `main`; the formal launcher checks out the reviewed executable itself in a detached preserved worktree.

## 3. Final CI result

Final CI on reviewed head `04b4d0ad5d7c09e84841f438725abb4b25b6f91c` passed:

```text
pytest       PASS
compileall   PASS
Ruff         PASS
```

The final CI runner does not provide the formal RTX 5080 environment and therefore does not execute the 68-fit experiment. GPU identity and CUDA/PyTorch compatibility are checked locally by the formal preflight.

An earlier CI attempt passed tests and compileall but failed on Ruff-only import/style findings. Those findings were repaired before the reviewed head above; no scientific logic or result-dependent parameter was changed in response.

## 4. Implemented input boundary

All R11-S0 forecasting arms use only:

```text
96-bin station_current_mean_a history
96-bin history-validity mask
issue-time calendar context
target-time calendar context
normalized forecast horizon
```

The implementation verifies the first 192 canonical M2 fields are exactly the frozen station-history and history-mask fields before extracting them. Later M2/M3/session-derived fields are not supplied to the models.

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

All are inside the frozen `50,000–250,000` band, so **no width correction was required**.

`Station-HGB` uses the same station-only input information and the already frozen M2 HGB hyperparameter set for each horizon.

## 6. Implemented execution guards

The implementation is fail-closed on:

- development-month identity;
- exact frozen formal test-origin counts;
- 96-history / 96-mask station-input schema;
- causal training/validation cutoffs;
- missing-history mask semantics;
- finite labels and predictions;
- parameter-count band;
- frozen three seeds;
- 68-fit ceiling;
- reviewed Git content identity;
- formal PyTorch/CUDA/GPU identity.

The formal local process requires:

```text
PyTorch 2.14.0
CUDA wheel/runtime 13.2
NVIDIA GeForce RTX 5080 / cuda:0
float32
CUBLAS_WORKSPACE_CONFIG=:4096:8
```

There is no CPU fallback for the formal run.

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

The executable applies only the preregistered decisions:

```text
SELECT_STATION_BACKBONE
MIXED_STATION_BACKBONE
STOP_DEEP_CORE_ROUTE
```

No fifth architecture, extra seed, ensemble, clipping, calibration or post-result hyperparameter search is permitted.

## 8. Pinned external launcher

External launcher filename:

```text
evcf_r11_s0_launcher_v1.py
```

Frozen launcher SHA-256:

```text
c732aac69e8dee1ca6c7d6e76138a78821f7f491c59bf7ee627fcf8cf534e2f4
```

The launcher is intentionally kept outside the repository. It:

1. verifies/fetches the reviewed executable;
2. verifies frozen protocol/config Git blob identities;
3. verifies reviewed executable ancestry in the implementation merge;
4. creates or reuses a preserved detached reviewed worktree;
5. sets `CUBLAS_WORKSPACE_CONFIG=:4096:8` before importing PyTorch;
6. runs the formal environment preflight;
7. only after preflight PASS invokes the reviewed R11-S0 runner;
8. writes one aggregate-only `evcf_r11_s0_status_*.json` outside the repository worktree;
9. performs no automatic cleanup.

## 9. Current execution state

```text
formal R11-S0 run       NOT RUN
formal fit_count        0
final holdout accessed  false
session predictors used false
```

No JPL real-label R11-S0 fit was performed during implementation, code review, shape preflight or CI.

## 10. Next action

The implementation gate is now satisfied. The next authorized action is the **single formal local R11-S0 run** using the pinned launcher above.

After the launcher exits, upload only the newest:

```text
evcf_r11_s0_status_YYYYMMDDTHHMMSSZ.json
```

whether it reports `COMPLETE` or `INCOMPLETE`.

If `INCOMPLETE`, do not edit code, rerun, change the environment or create extra fits before the status is inspected. If `COMPLETE`, the result is audited against the frozen SELECT/MIXED/STOP logic before any R11-M1 protocol is designed.

No JPL final-holdout access is authorized by R11-S0 regardless of its result.
