# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-13。当前入口为本文件与 [HANDOFF](HANDOFF.md)。正式 R4-I0 结果见 [R4-I0 outcome](docs/JPL_R4_I0_INFORMATION_SUFFICIENCY_OUTCOME_20260913.md)；R4-D1、R4-D2 已完成并归档；R5 方法协议见 [R5 FTAR protocol](docs/JPL_R5_FUTURE_TRANSITION_ALIGNED_REPRESENTATION_PROTOCOL_20260913.md)，held-out geometry audit 的训练前尺度修补见 [R5 geometry audit repair](docs/JPL_R5_GEOMETRY_AUDIT_SCALE_REPAIR_20260913.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 均已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`。R4-D1、R4-D2 均已 COMPLETE，Level/M3 gate 路线不推进。R5-FTAR 协议、实现和 pinned launcher 均已就绪，但正式 R5 本地 development run 尚未执行。final holdout 2019-03/06/09/12 继续封存。**

## 1. R4-D2 accepted result

```text
status                         COMPLETE
source status SHA256           d04a5f185b193e7b2dd3bafbafe3e095a054de3c71e9a69143f7a8d58f84bdfa
reviewed executable            599982eadbf1c1ea9868ea20ad5ed0a87d19b74d
runtime                        70.5320704 s
records                        23876
fit_count                      0
holdout accessed               false
```

D2 只支持一个项目层面的结论：手工 issue-time geometry balance 不足以成为稳定 Level/M3 gate/router，因此不开发 hard gate、learned gate、MoE router 或 month gate。R4-I0 的 `MIXED_STATE_ALIASING_SIGNAL` 不变。

## 2. R5-FTAR frozen question

R5 = **Future-Transition-Aligned Representation**。冻结问题为：在完全相同的 canonical M3 issue-time 输入和完全相同的单一 MLP 下，让 latent pairwise geometry 显式对齐未来五时距负荷转移轨迹 geometry，是否能稳定改善多时距预测？

```text
R5-Direct : identical MLP, prediction loss only
R5-FTAR   : identical MLP + 0.25 * future-transition geometry loss
```

没有 gate、专家、attention、Transformer、Set Transformer、Mamba、Neural ODE 或个体 session-set encoder。未来标签只允许进入历史训练折中的监督损失；推理时只读取 issue-time M3。

## 3. Frozen model/training contract

```text
input                          canonical M3: 311 raw -> 391 encoded
encoder                        391 -> 128 -> 32, GELU
head                           32 -> 64 -> 5, GELU
optimizer                      AdamW, lr=1e-3, wd=1e-4
epochs                         80
batch                          256
seed                           20260913
FTAR geometry weight           0.25
formal Python                  3.11.16
formal PyTorch                 2.14.0+cu132
formal CUDA/device             13.2 / RTX 5080 / cuda:0
formal fits                    110
```

Strong frozen references: M3、Equal=`0.5*(M2+M3)`、S1。Primary mechanism comparison: FTAR vs Direct。

Held-out geometry audit 只允许同一 daily refit 内配对，并在每个 refit 内分别标准化 latent/future distance 后再跨日聚合；该 repair 在任何 R5 real-data fit 前冻结。

## 4. R5 implementation identity

```text
protocol merge                  3f964696606f05bdc01b6f0b217e821d0f1933bf
geometry-audit repair merge     431e1fe2fede50216d36ab89a5e61a835a29e737
reviewed CI-passed head          4f2925cba92d606b929a25dc84468fcc16f1afc4
implementation merge             efec1cce23daf64da20afd254d92d5eb79f9cf3e
PR                               #89
full CI                          PASS: 1194 passed, 2 skipped; compileall PASS; Ruff PASS
```

R5 production entry uses the reviewed head above, not a later docs-only main commit. Direct/FTAR use identical initialization, deterministic row order, mini-batch partition and architecture; the only scientific intervention is the frozen geometry loss.

## 5. Pinned launcher

External launcher:

```text
evcf_r5_ftar_launcher_v1.py
SHA256 = bde5df90397004304f3489afc633ed115492be8be3c9fb6a52f4bbe80dd2e975
```

Launcher contract:

- requires explicit `--authorize-r5`;
- binds execution to reviewed head `4f2925cb...` in a detached worktree;
- preserves existing worktrees and never reset/clean/stash/delete;
- automatically locates the accepted four-month development snapshots and frozen baseline/S1 private caches by SHA-256;
- blocks traversal into final-holdout month directories;
- checks Python/scientific packages/PyTorch/CUDA/RTX 5080 before fitting;
- prepends reviewed worktree `code/src` to `PYTHONPATH` so an existing editable install cannot redirect imports;
- verifies development data integrity before and after the run;
- runs exactly one R5 development experiment and writes `evcf_r5_ftar_status_*.json` next to the launcher.

## 6. Current execution state

| 项目 | 状态 |
| --- | --- |
| R4-I0 decision | **MIXED_STATE_ALIASING_SIGNAL** |
| R4-D1 / R4-D2 | **COMPLETE / ARCHIVED** |
| Level/M3 gate route | **NOT ADVANCING** |
| R5 protocol | **FROZEN / MERGED** |
| R5 geometry-audit repair | **FROZEN PRE-FIT / MERGED** |
| R5 implementation | **CI PASS / MERGED** |
| R5 pinned launcher | **READY / STATICALLY AUDITED** |
| R5 formal local run | **NOT RUN YET** |
| Final holdout | **SEALED** |

下一步只允许：使用 pinned launcher 做 **exactly one development-only R5 run**，随后上传最新 `evcf_r5_ftar_status_*.json`。在该结果解释和归档前，不访问 final holdout，不修改 R5 架构、loss weight 或判定阈值。