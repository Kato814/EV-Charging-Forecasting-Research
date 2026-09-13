# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-13。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、R4-I0/R4-D1/R4-D2 outcome、[R5 FTAR protocol](docs/JPL_R5_FUTURE_TRANSITION_ALIGNED_REPRESENTATION_PROTOCOL_20260913.md) 和 [R5 geometry audit repair](docs/JPL_R5_GEOMETRY_AUDIT_SCALE_REPAIR_20260913.md)。

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

Final holdout `2019-03/06/09/12` remains sealed. Do not rerun S1/P1/R1/R2/R3/R4 diagnostics unless a separate frozen repair protocol explicitly requires replay.

## 2. Accepted D2 consequence

D2 source status SHA256:

```text
d04a5f185b193e7b2dd3bafbafe3e095a054de3c71e9a69143f7a8d58f84bdfa
```

D2 does not support a stable Level/M3 gate/router. Do not advance hard gate, learned gate, horizon/month gate or MoE from this evidence. This does not modify R4-I0 MIXED or deny M3 incremental information vs M2.

## 3. Frozen R5 mechanism

R5-FTAR tests whether supervised alignment of issue-time latent geometry with five-horizon future-transition geometry improves prediction.

Both arms use identical canonical M3 input and identical single MLP:

```text
Direct: L = L_pred
FTAR:   L = L_pred + 0.25 * L_geo
```

No attention, Transformer, Set Transformer, Mamba, Neural ODE, gate, router, MoE, individual-session set encoder, target-aware test-time retrieval or architecture rescue.

Formal contract:

```text
M3 encoded width       391
latent width           32
output horizons        5: 15/30/60/120/240 min
optimizer              AdamW(lr=1e-3, weight_decay=1e-4)
epochs                 80
batch size             256
seed                   20260913
formal fits            110
formal env             Python 3.11.16 / PyTorch 2.14.0+cu132 / CUDA 13.2
formal GPU             NVIDIA GeForce RTX 5080 / cuda:0
```

Strong references are read-only M3, Equal 0.5 and S1.

Held-out geometry audit is same-refit only. Distances are standardized inside each daily refit before any cross-day/month aggregation. That repair was frozen before the first R5 real-data fit.

## 4. R5 reviewed identities

```text
protocol merge                  3f964696606f05bdc01b6f0b217e821d0f1933bf
geometry-audit repair merge     431e1fe2fede50216d36ab89a5e61a835a29e737
reviewed CI-passed executable    4f2925cba92d606b929a25dc84468fcc16f1afc4
implementation merge             efec1cce23daf64da20afd254d92d5eb79f9cf3e
PR #89 CI                        1194 passed, 2 skipped; compileall/Ruff PASS
```

The formal local run must execute the reviewed head `4f2925cb...`, not a later docs-only main commit.

## 5. Pinned launcher

```text
name     evcf_r5_ftar_launcher_v1.py
SHA256   bde5df90397004304f3489afc633ed115492be8be3c9fb6a52f4bbe80dd2e975
```

Launcher behavior:

- explicit `--authorize-r5` required;
- create/reuse detached worktree at reviewed head without reset/clean/stash/delete;
- if reviewed commit is absent locally, only fetch PR #89 head;
- auto-locate four accepted development snapshots by exact snapshot-manifest SHA;
- auto-locate accepted M2/M3 baseline and S1 private caches by exact private-manifest SHA;
- skip final-holdout month directories during discovery;
- verify reviewed `code/src` takes precedence over any editable install via `PYTHONPATH`;
- preflight exact formal Python/scientific-package/PyTorch/CUDA/GPU contract;
- verify development artifact hashes before and after execution;
- preserve all worktrees, private caches, status files and R5 private output;
- emit only aggregate `evcf_r5_ftar_status_*.json` for upload.

## 6. Current execution order

```text
R5 protocol                     FROZEN / MERGED
R5 audit repair                 FROZEN PRE-FIT / MERGED
R5 implementation               CI PASS / MERGED
R5 pinned launcher              READY
R5 formal development run       NOT RUN YET
Final holdout                   SEALED
```

Next and only user-side action: run the pinned R5 launcher once and upload only the newest `evcf_r5_ftar_status_*.json`.

After the status file is returned: verify code/data/environment identity, then interpret the frozen `PASS_FUTURE_TRANSITION_GEOMETRY` / `MIXED_FUTURE_TRANSITION_GEOMETRY` / `STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE` result. Do not alter thresholds or architecture after seeing the result, and do not access final holdout before outcome archival.

## 7. Asset protection

Preserve all worktrees, status files, private caches and historical outputs. Do not reset/clean/stash/force-push or automatically delete detached worktrees. Any PowerShell instruction to the user must be one line.