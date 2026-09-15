# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-15。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、`docs/JPL_R11_S0_STATION_LEVEL_DEEP_BACKBONE_SCREENING_PROTOCOL_20260914.md`、`docs/JPL_R11_S0_PREFIT_INTEGRITY_REPAIR_20260915.md`、`docs/JPL_R11_S0_LABEL_READER_REPAIR_20260915.md`。

## 1. Frozen scientific state

```text
R10-R0 = MIXED_DEVELOPMENT_ROBUSTNESS, COMPLETE
R11 direction = portable station-level deep method
R11-S0 protocol = FROZEN
R11-S0 completed formal fits = 0
R11-S0 scientific result = NONE
attempt v1.1 = INCOMPLETE / IMPLEMENTATION_DRIFT / fit_count 0
attempt v1.2 = INCOMPLETE / LABEL_INVALID / fit_count 0
repair PR #106 = MERGED / FULL CI PASS
sole authorized launcher = v1.3
v1.3 formal run = NOT RUN
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

The planned scientific hypothesis remains `station-level multi-horizon core + session-resolved training-only auxiliary supervision`. Session information is training-only privileged information, not a deployment feature.

## 3. R11-S0 frozen protocol

```text
target              station_current_mean_a (A)
development months  2019-01 / 2019-04 / 2019-07 / 2019-10
history              96 x 15-min bins
horizons             15 / 30 / 60 / 120 / 240 min
train                earlier dev months + current days 1-14
validation           current days 15-17
test                 current day >=18 on exact frozen origins
formal fit ceiling   68
```

Candidates:

```text
GRU / TCN / N-HiTS / PatchTST
Station-HGB same-information anchor
```

Frozen test identity:

```text
2019-01 1305
2019-04 1180
2019-07 1294
2019-10 1296
pooled  5075 origins = 25375 origin-horizon records
```

## 4. Confirmed local environment

```text
NVIDIA GeForce RTX 5080 / cuda:0
PyTorch 2.14.0+cu132
CUDA 13.2
float32 smoke PASS
```

Parameter counts:

```text
GRU        93,697
TCN       118,785
N-HiTS    116,133
PatchTST   76,737
```

## 5. Pre-fit failure history

### v1.1

```text
status   INCOMPLETE
reason   IMPLEMENTATION_DRIFT
fits     0
holdout  false
```

Root cause: raw-byte Git identity verification was not portable to Windows checkout normalization. Repair PR #105 replaced it with exact HEAD + Git-normalized clean diff verification.

### v1.2

```text
status file    evcf_r11_s0_status_20260915T102447Z.json
status SHA256  9b3d3570ba33c96c24cdef094b0bcdeeeefd7e29a5179958b15b85e1f9d8eb60
status         INCOMPLETE
reason         LABEL_INVALID
fits           0
holdout        false
```

Root cause: frozen label JSON was serialized with `sort_keys=True`; the historical base reader depended on object insertion order. The accepted compatibility reader already validates the exact horizon-key set and reads values in numerical frozen order. R11-S0 now installs that accepted reader process-locally. No data values or scientific settings changed.

## 6. Current authoritative execution identity

```text
protocol freeze commit       9dfeb7b1b99d7e99de1b653473742b6c5148be04
label-reader repair PR       #106
reviewed executable          6ec9d690bbeb4b5dbe078daf42b52a6549eb14c9
implementation merge         da8989d16668bcf806e0e5efce2eabe52ec7b837
final CI run                 34958616708
final CI                     PASS
```

PR #104 remains non-authoritative and must not be mixed into formal execution.

## 7. Sole authorized launcher

```text
filename  evcf_r11_s0_launcher_v1_3.py
SHA256    da9824d472f6dc3541babab8aad001837a0cc1437504f8f2e0a3610059f031c1
schema    evcf-r11-s0-launcher/v1.3
```

v1.1/v1.2 are retired from execution but preserved as evidence. v1.3 checks out the reviewed executable in a detached preserved worktree and verifies code ancestry, frozen Git blobs, development manifest identities, absence of final holdout, deterministic CUDA configuration and formal device before fitting.

## 8. Frozen R11-S0 decision

Eligibility:

```text
pooled median MAE <= 1.02 * Station-HGB
worst horizon degradation <= 10%
worst month degradation   <= 10%
pooled seed spread        <= 3%
all four folds complete
```

Possible results only:

```text
SELECT_STATION_BACKBONE
MIXED_STATION_BACKBONE
STOP_DEEP_CORE_ROUTE
```

No fifth model, extra seed, ensemble, clipping, calibration, Mamba/SSM rescue or result-driven retuning.

## 9. Next action

Run the exact v1.3 launcher once on the user machine after SHA verification. After exit, upload only the newest:

```text
evcf_r11_s0_status_YYYYMMDDTHHMMSSZ.json
```

If `INCOMPLETE`, do not edit/debug/rerun before status inspection. If `COMPLETE`, audit against the frozen SELECT/MIXED/STOP rule before any R11-M1 design.

## 10. Hygiene

Preserve all worktrees, status files and caches. No reset/clean/stash/force-push/automatic deletion. Final holdout remains sealed. Continue GitHub Actions conservation.
