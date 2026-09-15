# JPL/ACN R11-S0 authority clarification and parallel-implementation quarantine

Date: 2026-09-15  
Status: **authority clarification only; no scientific protocol or result changed**.

> Launcher identity was subsequently corrected by `docs/JPL_R11_S0_LAUNCHER_RECOVERY_20260915.md`. The unavailable v1 launcher is retired; formal execution now requires `evcf_r11_s0_launcher_v1_1.py` with SHA-256 `fce2ac327ca13af530faf0d2a70a1443b010218b1b3a0abb8826f5f640d6cc00`.

## 1. Why this note exists

R11-S0 had already completed its frozen implementation/review/CI path through PR #103 before a second, independently developed R11-S0 implementation path was merged through PR #104.

PR #104 is therefore a **parallel non-authoritative implementation**. Its existence does not supersede, amend, or reopen the already frozen R11-S0 scientific protocol or reviewed execution identity.

No R11-S0 formal real-data fit had been run when this collision was identified.

## 2. Sole authoritative R11-S0 execution identity

The only implementation authorized for the formal R11-S0 run remains:

```text
protocol freeze commit    9dfeb7b1b99d7e99de1b653473742b6c5148be04
reviewed executable       04b4d0ad5d7c09e84841f438725abb4b25b6f91c
implementation merge      726ffe8f8c7239152e09f056d0c256e0d1f46cf5
PR                        #103
final CI workflow run     34930090477
```

The current authorized launcher is:

```text
filename                  evcf_r11_s0_launcher_v1_1.py
SHA256                    fce2ac327ca13af530faf0d2a70a1443b010218b1b3a0abb8826f5f640d6cc00
```

The launcher checks out the reviewed executable itself in a detached preserved worktree. The current `main` head is **not** the formal executable identity.

## 3. Quarantined parallel path

The later parallel implementation entered through:

```text
PR                        #104
PR head                   6688f9c631b9f03a8f1a995bab913141cedf9905
merge to main             2433e76b0d1ab3f1d1bfa8feb2cae42bd782ae57
```

Its unprefixed files include:

```text
code/src/evcf/forecasting/r11_s0_contracts.py
code/src/evcf/forecasting/r11_s0_data.py
code/src/evcf/forecasting/r11_s0_models.py
code/src/evcf/forecasting/r11_s0_screen.py
code/src/evcf/forecasting/r11_s0_training.py
scripts/check_r11_s0_cuda_environment.py
scripts/check_r11_s0_model_shapes.py
code/tests/test_r11_s0_*.py
```

These files are **quarantined for scientific execution**:

- do not use them for the formal R11-S0 run;
- do not mix their code, parameter counts, model outputs, status schema or environment checks with the PR #103 line;
- do not use them to alter any frozen R11-S0 threshold, architecture, seed, chronology or feature contract;
- do not use their presence on `main` as evidence that the formal executable changed.

They remain in repository history as an implementation artifact. Do not reset, force-push, or delete historical evidence merely to hide the collision.

## 4. Scientific state is unchanged

```text
formal R11-S0 run        NOT RUN
formal fit_count         0
final holdout accessed   false
session predictors used  false
```

Final JPL holdout remains sealed:

```text
2019-03 / 2019-06 / 2019-09 / 2019-12
```

The next authorized scientific action remains one formal local R11-S0 execution using the PR #103 reviewed executable through the exact recovered v1.1 launcher only.