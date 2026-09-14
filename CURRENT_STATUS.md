# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。当前入口为本文件与 [HANDOFF](HANDOFF.md)。正式 R4-I0 结果见 [R4-I0 outcome](docs/JPL_R4_I0_INFORMATION_SUFFICIENCY_OUTCOME_20260913.md)；R4-D1、R4-D2 已完成并归档；R5 协议见 [R5 FTAR protocol](docs/JPL_R5_FUTURE_TRANSITION_ALIGNED_REPRESENTATION_PROTOCOL_20260913.md)，训练前几何审计尺度修补见 [R5 geometry audit repair](docs/JPL_R5_GEOMETRY_AUDIT_SCALE_REPAIR_20260913.md)，正式结果见 [R5 outcome](docs/JPL_R5_FUTURE_TRANSITION_ALIGNED_REPRESENTATION_OUTCOME_20260914.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 均已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`；R4-D1、R4-D2 COMPLETE；R5=`STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`。Level/M3 gate、higher-order set rescue 和 FTAR geometry route 均不推进。final holdout 2019-03/06/09/12 继续封存。**

## 1. R5 formal result

Single authorized development-only run:

```text
status                         COMPLETE
decision                       STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE
source status SHA256           d3c820d90cb4d54a56f50bd9d1293aa1a3e53da50d3418ddb34abc6fa6a8a196
reviewed executable            4f2925cba92d606b929a25dc84468fcc16f1afc4
formal fits                    110
holdout accessed               false
development data unchanged     true
```

Frozen decision support:

```text
pooled FTAR improvement vs Direct     +0.0348677%
horizon wins vs Direct                3/5
month wins vs Direct                  1/4
max horizon degradation               1.01985%
held-out geometry Spearman gain       +0.0914087
FTAR improvement vs Equal             -21.0402%
FTAR improvement vs S1                -22.4050%
```

STOP is triggered by the frozen month-stability condition: FTAR beats Direct in only 1/4 development months.

## 2. What R5 established

Pooled MAE:

```text
Direct       35.013762 A
FTAR         35.001553 A
M3           29.190188 A
Equal        28.917286 A
S1           28.594882 A
```

FTAR therefore changes pooled MAE only marginally and remains materially worse than the frozen strong references.

However, the representation mechanism itself works in the narrow geometric sense. Held-out same-refit latent/future-transition Spearman improves from `0.378605` for Direct to `0.470014` for FTAR, and improves in all 4 development months. Thus **better future-transition-aligned latent geometry does not by itself imply better point forecasting**.

By horizon, FTAR improves Direct at 15/30/60 min by about `1.98% / 1.90% / 1.29%`, then degrades at 120/240 min by about `0.56% / 1.02%`. By month, only October improves (`+3.73%`); January/April/July worsen.

## 3. Frozen route closures

Do not return to already tested rescue paths:

- S1 target decomposition: `MIXED_STRUCTURED_SIGNAL`, closed;
- P1 continuation/count-mark: closed;
- R1 pairwise joint-state: closed;
- R2 higher-order session-set: STOP; no Deep Sets / Set Transformer / attention rescue;
- R3-C0 control endogeneity: closed;
- R4-D2 Level/M3 gate: not advancing; no hard gate, neural gate, month/horizon router or MoE;
- R5 FTAR: STOP; no larger MLP, Transformer, attention, geometry-weight tuning, clipping/calibration or post-hoc architecture rescue.

## 4. R5 identities retained for reproducibility

```text
protocol merge                  3f964696606f05bdc01b6f0b217e821d0f1933bf
geometry-audit repair merge     431e1fe2fede50216d36ab89a5e61a835a29e737
reviewed CI-passed head          4f2925cba92d606b929a25dc84468fcc16f1afc4
implementation merge             efec1cce23daf64da20afd254d92d5eb79f9cf3e
launcher SHA256                  bde5df90397004304f3489afc633ed115492be8be3c9fb6a52f4bbe80dd2e975
private result manifest          45382977a3fceecec2c88dabffeaae8a9b24bddc6dc18669ddc94e2890006eb4
formal env                       Python 3.11.16 / PyTorch 2.14.0+cu132 / CUDA 13.2 / RTX 5080
```

Preserve all worktrees, status files and private caches. Do not reset/clean/stash/delete or rerun R5.

## 5. Current execution state

| 项目 | 状态 |
| --- | --- |
| R4-I0 | **MIXED_STATE_ALIASING_SIGNAL** |
| R4-D1 / R4-D2 | **COMPLETE / ARCHIVED** |
| Level/M3 gate route | **CLOSED / NOT ADVANCING** |
| R5 protocol / implementation | **FROZEN / MERGED** |
| R5 formal run | **COMPLETE** |
| R5 decision | **STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE** |
| R5 outcome archive | **CURRENT DOCS PR** |
| Final holdout | **SEALED** |

下一步不再修改 R5。必须基于 S1–R5 的完整证据重新筛选候选方法方向；任何新模型都需先形成新的科学问题和预注册协议，再允许实现和训练。