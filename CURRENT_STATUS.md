# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-13。当前入口为本文件与 [HANDOFF](HANDOFF.md)。正式 R4-I0 结果见 [R4-I0 outcome](docs/JPL_R4_I0_INFORMATION_SUFFICIENCY_OUTCOME_20260913.md)；R4-D1 结果见 [R4-D1 outcome](docs/JPL_R4_D1_STATE_GEOMETRY_DIAGNOSTIC_OUTCOME_20260913.md)；下一只读诊断协议见 [R4-D2 protocol](docs/JPL_R4_D2_QUERY_GEOMETRY_REGIME_PROTOCOL_20260913.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1=`STOP_MECHANISM_ROUTE` 且关闭；R1=`MIXED_JOINT_STATE_SIGNAL` 且关闭；R2=`STOP_HIGHER_ORDER_SET_ROUTE` 且关闭；R3-C0=`STOP_CONTROL_ENDOGENEITY_ROUTE` 且关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`。R4-D1 已 COMPLETE；formal R4 decision 不变。final holdout 2019-03/06/09/12 继续封存。**

## 1. R4-D1 run validity

```text
status                        COMPLETE
source status SHA256          522af0c71236ad3da7d8de006875394420f702aa650613660e619d8dd0048c94
runtime                       75.3963333 s
supported records             23876
fit_count                     0
R4 replay verified            true
scientific decision unchanged true
holdout accessed              false
development data unchanged    true
```

## 2. D1 的核心结果

Pooled geometry：

```text
                         Level       M2         M3
current-level gap        0.05693    0.20448    0.19514
M2 RMS geometry          0.74920    0.35782    0.42044
M3 extension RMS         0.63620    0.65480    0.39369
full M3 RMS              0.78589    0.58670    0.46207
future divergence (A)   43.17263   47.76651   43.85308
```

相对 Level，M3 的 current-level gap 约为 **3.43×**，但 M3-extension geometry 近 **38.12%**，full-M3 geometry 近 **41.20%**。因此，M3 确实用 instantaneous current continuity 换取 richer session-state similarity。

相对 M2，M3 的 session-extension geometry 近 **39.88%**、full-M3 geometry 近 **21.24%**；同时 shared-M2 geometry 远约 **17.50%**。M3 相对 M2 的增量主要来自 session extension，而不是单纯当前电流。

## 3. D1 为什么不足以直接做模型

Horizon 上，issue-time geometry 基本不随 15/30/60/120/240 min 改变，但 `D_M3-D_Level` 从 `+8.1171 A` 逐步变为 `-10.7252 A`。因此 horizon reversal 不是由不同 horizon 选择了不同几何类型的邻居造成，而是同一种 state similarity 对不同未来时间尺度的价值不同。

Month 上：

```text
2019-01  D_M3-D_Level   +0.3039 A
2019-04                  -10.4143 A
2019-07                   -2.4247 A
2019-10                  +14.1236 A
```

四个月都存在几何冲突，但 aggregate geometry 不能解释 April/October 的巨大反转。因此 D1 结论是：**geometry conflict mechanistically present, but insufficient as a complete regime explanation**。

## 4. 下一科学问题：R4-D2

R4-D2 仍是 zero-fit/read-only diagnostic，不是新预测模型。

冻结问题：

> 对每个 supported query，仅用 issue-time geometry 构造 current-continuity loss 与 session-state gain 的 target-free balance score，能否稳定区分什么时候 M3 比 Level 的未来更接近？

主分数：

```text
S_current = (C_M3-C_Level)/(C_M3+C_Level+1e-12)
S_session = (QE_Level-QE_M3)/(QE_Level+QE_M3+1e-12)
B         = S_session-S_current
```

未来只作为诊断 outcome：`A=D_Level-D_M3`，正值表示 M3 更好。B 的 pooled quartile cutpoints 只根据 issue-time geometry 确定，不能用 target 调参；同一 cutpoints 用于全部 horizon/month/cell。

R4-D2 禁止训练 gate、分类器、回归器或预测模型，禁止改变 analog/K/support，禁止 month 作为 gating input，禁止访问 final holdout。

## 5. 当前执行状态

| 项目 | 状态 |
| --- | --- |
| R4-I0 decision | **MIXED_STATE_ALIASING_SIGNAL** |
| R4-D1 run | **COMPLETE** |
| R4-D1 outcome archive | 当前 docs PR |
| R4-D2 protocol | 当前 docs PR，待 CI/merge |
| R4-D2 implementation | NOT STARTED |
| R4-D2 local run | NOT AUTHORIZED |
| Final holdout | **SEALED** |
| 当前用户本机动作 | **无** |

只有 R4-D2 protocol 合并并完成独立实现/CI/pinned launcher 后，才允许一次 development-only D2 run。D2 完成后，才决定是否进入真正的 adaptive Level/M3 two-branch forecasting model。
