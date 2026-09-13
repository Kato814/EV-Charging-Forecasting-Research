# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-13。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R4-I0 outcome](docs/JPL_R4_I0_INFORMATION_SUFFICIENCY_OUTCOME_20260913.md)、[R4-D1 outcome](docs/JPL_R4_D1_STATE_GEOMETRY_DIAGNOSTIC_OUTCOME_20260913.md)、[R4-D2 outcome](docs/JPL_R4_D2_QUERY_GEOMETRY_REGIME_OUTCOME_20260913.md) 和 [R5 FTAR protocol](docs/JPL_R5_FUTURE_TRANSITION_ALIGNED_REPRESENTATION_PROTOCOL_20260913.md)。

## 1. Frozen scientific state

```text
S1    = MIXED_STRUCTURED_SIGNAL, CLOSED
P1    = STOP_MECHANISM_ROUTE, CLOSED
R1    = MIXED_JOINT_STATE_SIGNAL, CLOSED
R2    = STOP_HIGHER_ORDER_SET_ROUTE, CLOSED
R3-C0 = STOP_CONTROL_ENDOGENEITY_ROUTE, CLOSED
R4-I0 = MIXED_STATE_ALIASING_SIGNAL
R4-D1 = COMPLETE diagnostic
R4-D2 = COMPLETE diagnostic
```

Final holdout `2019-03/06/09/12` remains sealed. No current user-side command.

## 2. Accepted D2 evidence

```text
D2 status SHA256               d04a5f185b193e7b2dd3bafbafe3e095a054de3c71e9a69143f7a8d58f84bdfa
reviewed executable            599982eadbf1c1ea9868ea20ad5ed0a87d19b74d
records                        23876
runtime                        70.5320704 s
fit_count                      0
holdout accessed               false
pooled Spearman(B,A)           0.2324946715
Q4-Q1 mean A                  +13.428887 A
Q4-Q1 M3-win fraction          -0.087741
```

The hand-built target-free geometry score has weak and horizon/month-inconsistent association with M3-vs-Level advantage. D2 had no formal PASS/MIXED/STOP code; the accepted project decision is simply not to advance a Level/M3 gate/router from this evidence.

Do not turn this into a claim that M3 lacks information. R4-I0 remains MIXED and showed stable M3 increment over M2.

## 3. Historical no-rescue boundary

Do not go backwards:

- S1 has already run formally; do not rerun it.
- P1 survival/count-mark escalation is closed.
- R2 formally showed true higher-order same-session set alignment worse than its marginal-preserving control; do not rescue with larger Deep Sets, Set Transformer, attention or MoE.
- D2 does not authorize a better gate, learned gate, horizon router or month router.

## 4. Frozen R5 question

R5-FTAR tests a different mechanism: **learn the predictive geometry itself**.

Both arms receive the exact same canonical M3 issue-time input and use the exact same single MLP. Both predict a five-horizon future-transition vector. FTAR alone adds a training-fold-only loss that aligns pairwise latent distance with pairwise future-transition distance.

```text
Direct: L = L_pred
FTAR:   L = L_pred + 0.25 * L_geo
```

Inference uses issue-time M3 only. No target-aware retrieval or matching occurs at test time.

## 5. Frozen model/training contract

```text
M3 encoding       391 dimensions
encoder           Linear(391,128)-GELU-Linear(128,32)
head              Linear(32,64)-GELU-Linear(64,5)
optimizer         AdamW(lr=1e-3, weight_decay=1e-4)
epochs            80
batch size        256
seed              20260913
formal env        Python 3.11.16 / PyTorch 2.14.0+cu132
formal device     NVIDIA GeForce RTX 5080 / cuda:0
```

No early stopping, scheduler, hyperparameter search, mixed precision or CPU fallback in the formal run.

Strong frozen references: M3, Equal 0.5, S1. Primary mechanism comparison: FTAR vs Direct.

## 6. Frozen R5 decision

`PASS_FUTURE_TRANSITION_GEOMETRY` requires FTAR pooled MAE below Direct, Equal and S1; >=3/5 horizon wins vs Direct; >=3/4 month wins; no >5% horizon degradation vs Direct; and better held-out latent/future-transition Spearman than Direct.

`MIXED_FUTURE_TRANSITION_GEOMETRY`: pooled improvement over Direct and at least one strong baseline but stability/mechanism incomplete.

`STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`: FTAR not better than Direct pooled, or wins <=1 horizon, or wins <=1 month. No architecture rescue after STOP.

## 7. Execution order

```text
D2 outcome archive + R5 protocol   current docs PR
R5 implementation                  ONLY AFTER docs merge
R5 full CI                         required
R5 CUDA preflight                  required
R5 pinned launcher                 only after reviewed CI-passed head exists
R5 local run                       NOT AUTHORIZED
Final holdout                      SEALED
```

Preserve all worktrees, status files, private caches and historical outputs. Do not reset/clean/stash/force-push. Any future PowerShell command must be one line.