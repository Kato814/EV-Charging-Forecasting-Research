# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-15。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、`docs/JPL_R11_S0_BACKBONE_SCREEN_OUTCOME_20260915.md`、`docs/JPL_R11_P1_HORIZON_TARGETED_PRIVILEGED_ARRIVAL_PROTOCOL_20260915.md` 与 `docs/JPL_R11_P1_PRIVILEGED_ARRIVAL_OUTCOME_20260915.md`。

## 1. Frozen scientific state

```text
R10-R0 = COMPLETE / MIXED_DEVELOPMENT_ROBUSTNESS
R11-S0 = COMPLETE / STOP_DEEP_CORE_ROUTE / 68 fits
original R11-M1 = CANCELLED
R11-P1 = COMPLETE / MIXED_PRIVILEGED_ARRIVAL_SIGNAL / 44 fits
final holdout = SEALED
```

Final JPL holdout remains `2019-03/06/09/12` and has not been accessed.

## 2. R11-P1 execution identity

```text
PR                     #110
candidate code commit  187c047596dffb74cef8a79fcc479edd55139d5f
launcher SHA256         a9655dba0de6a54ea52c39171e392533d8b5c5e2c6ce52e9e1c5656435c33c31
deep fits               24 / 24
HGB replay              20 / 20
total fits              44 / 44
holdout accessed        false
session predictors      false
```

Environment:

```text
RTX 5080
PyTorch 2.14.0+cu132
CUDA 13.2
deterministic CUDA backward smoke PASS
```

GitHub Actions monthly quota is exhausted. Repository-wide CI is unavailable until reset; do not interpret immediate no-run workflow failures as code failures. Use local targeted validation for active work and run archival full CI only after quota reset.

## 3. Frozen R11-P1 method

```text
15/30 min       Station-HGB
60/120/240 min  station-only TCN

Arm B  L = L_total
Arm C  L = L_total + 0.5 * L_future_arrival
```

The future-arrival label is session-resolved but training-only. At inference, no session identifiers, requested departure/energy, per-session current/pilot or future-session fields are allowed.

## 4. R11-P1 result

```text
Arm B long pooled MAE  33.2304292334 A
Arm C long pooled MAE  32.6842326626 A
C-B gain                1.6437%

horizon wins            3/3
month wins              4/4
paired seed wins        3/3

Station-HGB long        33.5592843062 A
Arm C long               32.6842326626 A

Station-HGB all-5        25.8731522189 A
Arm C hybrid all-5       25.3481212328 A
```

Frozen PASS conditions all hold except seed spread:

```text
Arm B seed spread  4.8547%
Arm C seed spread  4.8494%
required           <= 3.0%
```

Therefore the decision remains `MIXED_PRIVILEGED_ARRIVAL_SIGNAL`.

Important interpretation: the instability is carrier-level rather than obviously caused by privileged supervision, because Arm B and C have nearly identical spread while C improves B under every frozen seed, long horizon and development month.

## 5. What must not be done

Do not:

```text
relax the 3% seed-spread gate
relabel MIXED as PASS
add more seeds inside R11-P1
tune lambda=0.5 after seeing this result
add an existing-session auxiliary head inside R11-P1
change the 30/60 min split inside R11-P1
add another backbone to rescue R11-P1
open JPL final holdout now
```

No reset/clean/stash/force-push/automatic deletion of evidence or worktrees.

## 6. Next scientific direction

Preferred next stage is **independent generalization**, not another JPL development rescue.

Question:

> Does the exact frozen R11-P1 privileged-arrival training signal transfer to an independent session-rich site/source while deployment remains aggregate-only?

Before any new fit:

```text
1. identify the independent source/site;
2. freeze source identity and chronology;
3. freeze the exact Arm B/C carrier and lambda=0.5;
4. freeze seeds and decision rule;
5. prohibit architecture/lambda/horizon-boundary search;
6. keep JPL final holdout sealed.
```

If no suitable independent session-rich source exists, freeze the current result as development-stage mechanism evidence and do not tune further.
