# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-13。当前入口为本文件与 [HANDOFF](HANDOFF.md)。正式 R4-I0 结果见 [R4-I0 outcome](docs/JPL_R4_I0_INFORMATION_SUFFICIENCY_OUTCOME_20260913.md)；R4-D1 结果见 [R4-D1 outcome](docs/JPL_R4_D1_STATE_GEOMETRY_DIAGNOSTIC_OUTCOME_20260913.md)；R4-D2 结果见 [R4-D2 outcome](docs/JPL_R4_D2_QUERY_GEOMETRY_REGIME_OUTCOME_20260913.md)；下一模型协议见 [R5 FTAR protocol](docs/JPL_R5_FUTURE_TRANSITION_ALIGNED_REPRESENTATION_PROTOCOL_20260913.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 均已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`。R4-D1、R4-D2 均已 COMPLETE，formal R4 decision 不变。Level/M3 gate 路线不推进。final holdout 2019-03/06/09/12 继续封存。**

## 1. R4-D2 accepted result

```text
status                         COMPLETE
source status SHA256           d04a5f185b193e7b2dd3bafbafe3e095a054de3c71e9a69143f7a8d58f84bdfa
reviewed executable            599982eadbf1c1ea9868ea20ad5ed0a87d19b74d
runtime                        70.5320704 s
records                        23876
D1 replay verified             true
fit_count                      0
holdout accessed               false
```

Pooled D2：

```text
Spearman(B,A)                  0.232495
Q4-Q1 mean M3 advantage       +13.4289 A
Q4-Q1 M3-win fraction          -8.774 percentage points
```

Horizon Spearman 从 15 min 的 `0.4857` 降到 120/240 min 的约 `0.1075/0.1099`；April 的 Q4-Q1 mean A 为 `-20.9472 A`，October 为 `+40.2125 A`。因此手工 issue-time geometry balance 虽有描述性信号，但不足以成为稳定 gate/router。

D2 无 PASS/MIXED/STOP code；项目层面的后果仅是：**不开发 Level/M3 hard gate、neural gate、MoE router 或 month gate。** 这不否定 M3 本身的信息价值，也不修改 R4-I0 MIXED。

## 2. 历史路线边界再确认

不得退回已关闭路线：

- S1 已正式运行并判 `MIXED_STRUCTURED_SIGNAL`；
- P1 continuation/count-mark 已 STOP；
- R1 pairwise joint-state 已 MIXED/CLOSED；
- R2 true higher-order session-set vs marginal-preserving permutation 已 STOP；
- 因 R2 STOP，不允许用更大的 Deep Sets、Set Transformer、attention 或 MoE 作 rescue；
- R3-C0 control-endogeneity 已 STOP；
- D2 后不恢复 gate 路线。

因此当前问题不是“再换一个更复杂 backbone”，而是 raw M3 issue-time geometry 与 future-transition geometry 对齐不足。

## 3. 下一阶段：R5-FTAR

R5 = **Future-Transition-Aligned Representation**。

冻结问题：

> 在完全相同的 M3 issue-time 输入和完全相同的单一预测网络下，让 latent pairwise geometry 显式对齐未来五时距负荷**转移轨迹**的 geometry，是否能稳定改善多时距预测？

两组 matched arms：

```text
R5-Direct : identical MLP, prediction loss only
R5-FTAR   : identical MLP + frozen future-transition geometry loss
```

没有 gate、专家、attention、Transformer、Set Transformer、Mamba、Neural ODE 或个体 session-set encoder。未来标签只允许进入历史训练折中的监督损失，推理时只读取 issue-time M3。

正式强基线：冻结 M3、Equal=`0.5*(M2+M3)`、S1。R5 primary mechanism comparison 为 FTAR vs Direct。

## 4. R5 frozen engineering identity

```text
input                          canonical M3: 311 raw -> 391 encoded
encoder                        391 -> 128 -> 32, GELU
head                           32 -> 64 -> 5, GELU
prediction target              normalized future transition from issue current
optimizer                      AdamW, lr=1e-3, wd=1e-4
epochs                         80
batch                          256
seed                           20260913
FTAR geometry weight           0.25
formal device                  RTX 5080 / cuda:0
formal PyTorch                 2.14.0+cu132
```

完整 loss、causal rows、held-out geometry audit 和判定见 R5 protocol。所有参数均须在 real-data R5 fit 前冻结，不做超参数搜索。

## 5. 当前执行状态

| 项目 | 状态 |
| --- | --- |
| R4-I0 decision | **MIXED_STATE_ALIASING_SIGNAL** |
| R4-D1 | **COMPLETE / ARCHIVED** |
| R4-D2 | **COMPLETE / outcome in current docs PR** |
| Level/M3 gate route | **NOT ADVANCING** |
| R5-FTAR protocol | **FROZEN in current docs PR; no real-data fit yet** |
| R5 implementation | NOT STARTED |
| Final holdout | **SEALED** |
| 当前用户本机动作 | **无** |

下一动作仅在 GitHub：先让 D2 outcome + R5 protocol 文档 PR 完整 CI/merge；之后单独实现 R5-Direct/R5-FTAR、测试、GPU preflight 和 pinned launcher。