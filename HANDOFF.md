# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-15。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R10-R0 outcome](docs/JPL_R10_R0_R7_ROBUSTNESS_HOLDOUT_READINESS_OUTCOME_20260914.md)、[Post-R10 paper-viability synthesis](docs/JPL_POST_R10_PAPER_VIABILITY_NOVELTY_SYNTHESIS_20260914.md)、[R11 direction screening](docs/JPL_R11_STATION_LEVEL_DEEP_METHOD_SCREENING_20260914.md)、[R11-S0 protocol](docs/JPL_R11_S0_STATION_LEVEL_DEEP_BACKBONE_SCREENING_PROTOCOL_20260914.md)、[R11-S0 implementation handoff](docs/JPL_R11_S0_IMPLEMENTATION_HANDOFF_20260915.md)、[R11-S0 authority/quarantine note](docs/JPL_R11_S0_AUTHORITY_QUARANTINE_NOTE_20260915.md) 和最新 [R11-S0 launcher recovery/refreeze](docs/JPL_R11_S0_LAUNCHER_RECOVERY_20260915.md)。

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
R11-S0 authoritative implementation = REVIEWED / MERGED / CI PASS
R11-S0 launcher v1 = RETIRED_MISSING_ARTIFACT
R11-S0 launcher v1.1 = FROZEN / RECOVERABLE
R11-S0 formal run = NOT RUN
```

Final JPL holdout `2019-03/06/09/12` remains sealed.

## 2. Closed R7 line remains unchanged

R7 `Departure-Aug / TotalDeparture` remains the accepted development-stage candidate of the old structured line:

```text
Arrival MAE        22.7486906628 A
Total MAE          28.4354542901 A
S1 total           28.5948815297 A
Equal total        28.9172859886 A
vs S1              +0.5576% improvement
vs Equal           +1.6662% improvement
```

R9 permanently closed further departure-representation refinement. R10 does not reverse that closure and does not authorize final holdout access.

## 3. R10 frozen result

```text
status                         COMPLETE
decision                       MIXED_DEVELOPMENT_ROBUSTNESS
status SHA256                  058ec6b1196c76e884973e36f851e5c05831bb16fc6533b240d445c4dd82dda8
local-day win rate vs S1      26/55 = 47.27%
leave-one-month-out wins      4/4 vs S1; 4/4 vs Equal
leave-one-horizon-out wins    5/5 vs S1; 5/5 vs Equal
```

The only frozen READY failure was the `<50%` local-day win rate against S1. Do not retune that result away.

## 4. R11 deployment contract

The project now continues toward a portable station-level deep forecasting method.

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

The later scientific hypothesis is `station-level multi-horizon core + session-resolved training-only auxiliary supervision`. Session information is privileged source-side supervision, not a deployment feature.

## 5. R11-S0 frozen data/input contract

Target:

```text
station_current_mean_a (A)
```

Development months:

```text
2019-01 / 2019-04 / 2019-07 / 2019-10
```

History/horizons:

```text
history  = 96 x 15-min bins = 24 h
channels = standardized aggregate current + validity mask
horizons = 15 / 30 / 60 / 120 / 240 min
```

Calendar context is issue-/target-time derived only. No session-derived predictor is allowed.

Frozen formal test origins:

```text
2019-01 1305
2019-04 1180
2019-07 1294
2019-10 1296
pooled  5075 origins = 25375 origin-horizon records
```

A mismatch fails before fitting.

## 6. R11-S0 frozen candidates and chronology

Candidates:

```text
GRU      2 layers / hidden 96
TCN      5 causal residual blocks / dilations 1,2,4,8,16
N-HiTS   3 stacks / pooling 1,4,16
PatchTST patch16 / stride8 / d_model64 / 2 layers
Station-HGB same-information anchor
```

Chronology for each target month:

```text
train      all earlier dev months + current days 1-14
validation current days 15-17
test       current day >=18, exact frozen origins only
```

Deep training is frozen to AdamW `1e-3`, weight decay `1e-4`, batch `256`, max `120` epochs, patience `12`, SmoothL1, three frozen seeds, float32, no AMP.

Fit ceiling:

```text
48 deep + 20 Station-HGB = 68 fits
```

## 7. Sole authoritative R11-S0 implementation identity

```text
protocol freeze commit    9dfeb7b1b99d7e99de1b653473742b6c5148be04
reviewed executable       04b4d0ad5d7c09e84841f438725abb4b25b6f91c
implementation merge      726ffe8f8c7239152e09f056d0c256e0d1f46cf5
PR                        #103
final CI run              34930090477
CI                        pytest PASS / compileall PASS / Ruff PASS
```

Shape-only parameter counts:

```text
GRU        93,697
TCN       118,785
N-HiTS    116,133
PatchTST   76,737
```

No width correction was required.

## 8. Parallel implementation quarantine

PR #104 was merged after the authoritative PR #103 line had already been frozen:

```text
PR #104 head    6688f9c631b9f03a8f1a995bab913141cedf9905
merge to main   2433e76b0d1ab3f1d1bfa8feb2cae42bd782ae57
```

Treat PR #104 as a **parallel non-authoritative implementation artifact**. Its unprefixed `r11_s0_*` modules, tests and scripts must not be used for the formal run, mixed with PR #103, or used to revise any frozen scientific choice. Keep the historical code/evidence; do not reset, force-push or delete it merely to erase the collision.

The current `main` head is not the formal executable identity. The only formal code identity remains reviewed executable `04b4d0ad5d7c09e84841f438725abb4b25b6f91c`.

## 9. Formal environment and recovered launcher

Formal environment:

```text
Python 3.11.x
PyTorch 2.14.0
CUDA 13.2
NVIDIA GeForce RTX 5080 / cuda:0
float32 only
no CPU fallback
CUBLAS_WORKSPACE_CONFIG=:4096:8
```

The old documented `evcf_r11_s0_launcher_v1.py` was found to be unavailable and not verifiably delivered. Since no R11-S0 fit had started, it was retired before any result was observed. This does not change the scientific protocol.

Only this recovered launcher is authorized:

```text
filename  evcf_r11_s0_launcher_v1_1.py
SHA256    fce2ac327ca13af530faf0d2a70a1443b010218b1b3a0abb8826f5f640d6cc00
schema    evcf-r11-s0-launcher/v1.1
```

v1.1 verifies/fetches the PR #103 reviewed executable, checks frozen protocol/config Git blobs and implementation-merge ancestry, creates/reuses a preserved detached reviewed worktree, verifies the exact four development processed-manifest identities and absence of final-holdout paths, sets deterministic CUDA configuration, runs the formal PR #103 environment preflight, and only then invokes the formal PR #103 runner. It performs no automatic cleanup.

## 10. Frozen R11-S0 decisions

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

If multiple candidates are eligible, select the lowest pooled median MAE; if top two differ by `<0.25%`, select the lower parameter count. No fifth model, additional seed, ensemble, clipping, calibration or result-driven architecture search is allowed.

## 11. Current execution state

```text
formal R11-S0 run       NOT RUN
formal fit_count        0
final holdout accessed  false
session predictors used false
```

No R11-S0 JPL real-label fit was performed during implementation, review, CI, launcher recovery, or documentation updates.

## 12. Next action

Run the exact v1.1 R11-S0 launcher **once** on the user machine, but only after its SHA-256 is verified as:

```text
fce2ac327ca13af530faf0d2a70a1443b010218b1b3a0abb8826f5f640d6cc00
```

After it exits, upload only the newest:

```text
evcf_r11_s0_status_YYYYMMDDTHHMMSSZ.json
```

whether `COMPLETE` or `INCOMPLETE`.

If `INCOMPLETE`, do not debug, edit code, alter environment or rerun before inspecting the status. If `COMPLETE`, audit the result against the frozen SELECT/MIXED/STOP rule before designing R11-M1.

The R11-S0 result never authorizes JPL final-holdout access.

## 13. Hygiene

Preserve all worktrees, status files and private caches. No reset/clean/stash/force-push/automatic deletion. Do not reopen R7/R9/R10 routes. Continue GitHub Actions conservation; pure documentation/status archival remains CI-free where applicable.