# JPL/ACN R11-S0 launcher recovery and execution-control refreeze

Date: 2026-09-15  
Status: **execution-control correction only; scientific protocol unchanged; formal R11-S0 run still NOT RUN**.

## 1. Why this correction was required

The previously documented external launcher `evcf_r11_s0_launcher_v1.py` with SHA-256 `c732aac69e8dee1ca6c7d6e76138a78821f7f491c59bf7ee627fcf8cf534e2f4` could not be found on the user machine, in the current project files, or in the persistent launcher artifacts available to the project. No evidence was available that the exact file had actually been delivered before its identity was written into the handoff documents.

Because the formal R11-S0 experiment had not started (`fit_count=0`), the missing artifact can be corrected without observing any R11-S0 model result and without changing any scientific choice.

The unavailable v1 launcher identity is therefore **retired and not authorized for execution**. It must not be recreated under the old filename/hash.

## 2. Scientific protocol remains unchanged

No change was made to:

```text
R11-S0 protocol freeze commit  9dfeb7b1b99d7e99de1b653473742b6c5148be04
reviewed executable            04b4d0ad5d7c09e84841f438725abb4b25b6f91c
implementation merge           726ffe8f8c7239152e09f056d0c256e0d1f46cf5
PR                             #103
formal model families          GRU / TCN / N-HiTS / PatchTST
same-information anchor        Station-HGB
formal fit ceiling             68
seeds                          2026091401 / 2026091402 / 2026091403
horizons                       15 / 30 / 60 / 120 / 240 min
final holdout                  2019-03 / 06 / 09 / 12 (sealed)
```

PR #104 remains a parallel non-authoritative implementation and is not used by the formal run.

## 3. New authoritative launcher identity

The recovered execution-control launcher is newly versioned rather than pretending to be the missing v1 artifact:

```text
filename  evcf_r11_s0_launcher_v1_1.py
SHA256    fce2ac327ca13af530faf0d2a70a1443b010218b1b3a0abb8826f5f640d6cc00
schema    evcf-r11-s0-launcher/v1.1
```

Static Python syntax compilation: `PASS`.

Frozen Git blob identities checked by the launcher:

```text
R11-S0 protocol blob           6a317c025997bf6ac86538883da25e89b2882f35
source expert protocol blob    159961572f1fa9a73c31ce44661a2b467f419181
```

Frozen development processed-manifest SHA-256 values checked by the launcher:

```text
2019-01  e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12
2019-04  f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299
2019-07  9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2
2019-10  e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296
```

## 4. Launcher guards

Before any fit, v1.1:

1. verifies Python 3.11;
2. fetches/checks the frozen reviewed commit and implementation merge;
3. checks reviewed-executable ancestry;
4. checks the two frozen Git blob identities above;
5. creates/reuses a clean detached worktree at the reviewed executable;
6. locates exactly one development-data worktree whose four processed manifests match the frozen hashes;
7. rejects any candidate containing final-holdout month paths;
8. sets `CUBLAS_WORKSPACE_CONFIG=:4096:8` and `PYTHONHASHSEED=0`;
9. invokes the authoritative PR #103 environment preflight;
10. starts the authoritative PR #103 runner only after preflight PASS.

After execution it verifies the development manifests and all pre-existing worktree states are unchanged. It performs no automatic cleanup.

Formal environment remains:

```text
Python 3.11.x
PyTorch 2.14.0
CUDA 13.2
NVIDIA GeForce RTX 5080 / cuda:0
float32 only
no CPU fallback
```

## 5. Public status contract

The launcher writes exactly one aggregate-only file beside itself:

```text
evcf_r11_s0_status_YYYYMMDDTHHMMSSZ.json
```

A COMPLETE result must report:

```text
fit_count                 68
holdout_accessed          false
session_predictors_used   false
hyperparameter_search     false
prediction_clipping       false
prediction_calibration    false
model_ensemble            false
```

Allowed decisions remain exactly:

```text
SELECT_STATION_BACKBONE
MIXED_STATION_BACKBONE
STOP_DEEP_CORE_ROUTE
```

## 6. Current execution state

```text
formal R11-S0 run        NOT RUN
formal fit_count         0
final holdout accessed   false
session predictors used  false
```

## 7. Next action

Only the exact v1.1 file above is authorized. Verify its SHA-256 before the single formal local run. After the process exits, upload only the newest `evcf_r11_s0_status_*.json`, whether COMPLETE or INCOMPLETE.

If INCOMPLETE, do not edit code, alter the environment, or rerun before the status is inspected. The final JPL holdout remains sealed under every R11-S0 outcome.