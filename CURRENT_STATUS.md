# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-13。当前入口为本文件与 [HANDOFF](HANDOFF.md)。正式 R4-I0 结果见 [R4-I0 outcome](docs/JPL_R4_I0_INFORMATION_SUFFICIENCY_OUTCOME_20260913.md)；R4-D1 只读诊断协议见 [R4-D1 protocol](docs/JPL_R4_D1_STATE_GEOMETRY_DIAGNOSTIC_PROTOCOL_20260913.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1=`STOP_MECHANISM_ROUTE` 且关闭；R1=`MIXED_JOINT_STATE_SIGNAL` 且关闭；R2=`STOP_HIGHER_ORDER_SET_ROUTE` 且关闭；R3-C0=`STOP_CONTROL_ENDOGENEITY_ROUTE` 且关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`。R4-D1 协议和实现均已冻结并合并，当前唯一授权动作是 development-only R4-D1 read-only 运行一次。final holdout 2019-03/06/09/12 继续封存。**

## 1. R4-I0 正式结果

首次 development-only R4-I0 已 COMPLETE：

```text
runtime                      39.9417172 s
fit_count                    0
supported fraction           0.9409261084
supported rows               23876 / 25375
decision                     MIXED_STATE_ALIASING_SIGNAL
holdout_accessed             false
```

R4-I0 的 13 个 PASS 条件中 12 个满足，唯一失败条件是 `pooled skill_M3_vs_M2 <= 0.02`，实际为 `+0.0819284863`。因此 M3 相对 M2 有稳定增量信息，但 M3 pooled 相对 Level 仍为 `-0.015761`，正式结论必须保持 MIXED。

## 2. R4-D1 做什么

R4-D1 **不是新预测模型**。它只解释：为什么 M3 相对 M2 更好，却不能稳定超过只看当前站级电流的 Level-Control。

冻结做法：exact replay 原 R4 supported rows 与 Level/M2/M3 三组 K=3 analog identities，然后在相同邻居上交叉计算：

- standardized current-level gap；
- complete M2 RMS geometry；
- M3-only session-extension RMS geometry；
- complete M3 RMS geometry；
- Level/M2/M3 neighbor overlap；
- 原始 `D_Level/D_M2/D_M3` 及 `DeltaFuture`。

禁止：改 K、改 same-clock window、改 q95/support、重选 analog、PCA、metric learning、feature selection、hybrid/two-stage matching、模型训练、target-informed matching、final holdout。

## 3. R4-D1 实现状态

```text
R4-D1 protocol PR            #82
protocol merge               e20481f304d416433ca2d30b9e3bae57a017a8f6
R4-D1 implementation PR      #83
reviewed executable head     51048259f8d9c61f324db07e05ded0a3c2f9d48e
implementation merge         1a55796aa79ce976d115ac5b508ebb250a77c6a6
```

PR #83 完整 CI 已通过：1177 tests passed、2 skipped；compileall PASS；Ruff PASS。第一次 CI 仅有两个 test-style Ruff 问题（import order 与 `range(0, 201)`），已作零逻辑修复后完整复验通过。

## 4. Pinned launcher

当前唯一授权 launcher：

```text
evcf_r4_d1_launcher_v1.py
SHA256 = e84bbe7bc165b84cbe6d6f8e9df7e07fb9730a1c956dde1174fd33c09f211dfa
expected reviewed head = 51048259f8d9c61f324db07e05ded0a3c2f9d48e
```

Launcher 保护：development-only 2019-01/04/07/10；holdout path blocked；固定 Python/packages；必要时仅 fetch PR #83 head；detached exact-code worktree；运行前后校验 development snapshots 与已有 worktree tracked state；移除 `ACN_API_TOKEN`；不自动清理；要求 `fit_count=0`、`r4_replay_verified=true`、`scientific_decision_unchanged=true`，且所有禁止动作 flag 为 false。

## 5. 当前执行状态

| 项目 | 状态 |
| --- | --- |
| R4-I0 run | COMPLETE |
| R4-I0 decision | **MIXED_STATE_ALIASING_SIGNAL** |
| R4-D1 protocol | FROZEN / MERGED |
| R4-D1 implementation | CI PASS / MERGED |
| R4-D1 model fit | 必须为 0 |
| R4-D1 local run | **NOT RUN** |
| Final holdout | SEALED |
| 当前用户本机动作 | **运行 pinned R4-D1 launcher exactly once** |

R4-D1 结果只用于解释 R4 的 MIXED 结构，不能把 R4 改写成 PASS/STOP。完成后才允许选择下一类真正的预测模型问题。
