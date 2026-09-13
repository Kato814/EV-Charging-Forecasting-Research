# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-13。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R4-I0 outcome](docs/JPL_R4_I0_INFORMATION_SUFFICIENCY_OUTCOME_20260913.md) 和 [R4-D1 protocol](docs/JPL_R4_D1_STATE_GEOMETRY_DIAGNOSTIC_PROTOCOL_20260913.md)。历史协议/结果再按 R4-I0 → R3-C0 → R2 → R1 → P1 顺序回读。

## 1. 当前科学状态

```text
S1    = MIXED_STRUCTURED_SIGNAL
P1    = STOP_MECHANISM_ROUTE, CLOSED
R1    = MIXED_JOINT_STATE_SIGNAL, CLOSED
R2    = STOP_HIGHER_ORDER_SET_ROUTE, CLOSED
R3-C0 = STOP_CONTROL_ENDOGENEITY_ROUTE, CLOSED
R4-I0 = MIXED_STATE_ALIASING_SIGNAL
```

Final holdout `2019-03/06/09/12` 继续封存。当前**没有用户本机命令**。

## 2. R4-I0 正式结果

首次 R4-I0 development-only zero-fit run 已 COMPLETE：

```text
source status SHA256          a8b7142e0361b5cd56e53c7de99d8e699a27e1aee78728810773c127f385823f
reviewed executable head      d3f00320e90aeb213d97d63d3460f58d495dd34a
runtime                       39.9417172 s
fit_count                     0
pooled supported fraction     0.9409261084
supported rows                23876 / 25375
decision                      MIXED_STATE_ALIASING_SIGNAL
holdout_accessed              false
```

Support 不是问题：所有 20 个 month×horizon cells 均超过 `0.50` supported fraction 与 `250` supported-record floor。

## 3. 为什么不是 PASS

13 个冻结 PASS 条件中只有一个失败：

```text
required pooled skill_M3_vs_M2 <= 0.02
actual   pooled skill_M3_vs_M2  = 0.0819284863
```

其余 12 个 PASS 条件全部满足。因此不能把 R4 写成“rich issue-time state 完全没有增量信息”。

M3 相对 M2：

- pooled +8.19%；
- 5/5 pooled horizons 为正；
- 4/4 pooled months 为正；
- 19/20 month×horizon cells 为正。

## 4. 为什么也不是 STOP

Pooled：

```text
M2 vs Level skill             -0.106407
M3 vs Level skill             -0.015761
normalized M3 divergence       0.297930
```

M2/M3 都没有达到 STOP 所需的跨 horizon/month 稳定 vs-Level improvement；close-M3 future divergence 也并不小。

所以正式结果必须保持 MIXED，不能事后修改阈值。

## 5. R4 的关键结构

Horizon：

```text
15m   M3 vs Level -29.61%   M3 vs M2 +8.94%
30m   M3 vs Level -16.23%   M3 vs M2 +8.99%
60m   M3 vs Level  -6.04%   M3 vs M2 +9.83%
120m  M3 vs Level  +3.15%   M3 vs M2 +10.03%
240m  M3 vs Level +15.43%   M3 vs M2 +4.44%
```

Month：

```text
2019-01  M3 vs Level  -0.83%   M3 vs M2  +5.53%
2019-04  M3 vs Level +20.06%   M3 vs M2 +21.04%
2019-07  M3 vs Level  +4.90%   M3 vs M2  +2.72%
2019-10  M3 vs Level -40.43%   M3 vs M2  +3.39%
```

当前最稳妥的描述：**M3 session-state information 对 M2 有稳定增量价值，但 richer state 相对 instantaneous current-level continuity 的价值具有明显 horizon/month dependence。**

## 6. 当前下一步：R4-D1

R4-D1 是 zero-fit/read-only state-geometry failure analysis，不是新预测模型。

问题：

> M3 analog 是否通过获得更近的 session-state geometry，同时牺牲了 current-level similarity，从而造成短时距/October 相对 Level 较差，而长时距/April 相对更好？

冻结诊断：

- exact replay 原 R4 causal eligibility、same-clock candidates、K=3、q95 support、supported rows 与三组 analog identities；
- 对 Level/M2/M3 三组 frozen analog identities 交叉计算：
  - standardized current-level gap；
  - complete M2 RMS geometry；
  - M3-only session-extension RMS geometry；
  - complete M3 RMS geometry；
- 报告三组 neighbor overlap；
- 复用原始 `D_Level/D_M2/D_M3`，仅作 future-divergence difference；
- 只汇总 pooled、5 horizons、4 months、完整20 cells。

R4-D1 **不得**改变 analog、K、support、metric weights，不得 PCA/feature selection，不得训练模型，不得访问 holdout。

## 7. 当前执行顺序

```text
R4-I0 formal run                  DONE
R4-I0 frozen decision             MIXED
R4 outcome archive                current docs PR
R4-D1 protocol freeze             current docs PR
R4-D1 implementation              AFTER docs merge
R4-D1 local run                   NOT AUTHORIZED YET
Final holdout                     SEALED
```

## 8. 资产与表达保护

保留全部 worktree、status、private caches、R2/R3/R4 outputs 与 `evcf-r2-set`；不 reset/clean/stash/force push。PowerShell 必须单行。任何 D1 结果都不能回写成 R4 PASS，也不能把 state-aliasing 解释成 information-theoretic irreducibility。
