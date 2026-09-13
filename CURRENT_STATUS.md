# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-13。当前入口为本文件与 [HANDOFF](HANDOFF.md)。正式 R4-I0 结果见 [R4-I0 outcome](docs/JPL_R4_I0_INFORMATION_SUFFICIENCY_OUTCOME_20260913.md)；当前只读诊断协议见 [R4-D1 protocol](docs/JPL_R4_D1_STATE_GEOMETRY_DIAGNOSTIC_PROTOCOL_20260913.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1=`STOP_MECHANISM_ROUTE` 且关闭；R1=`MIXED_JOINT_STATE_SIGNAL` 且关闭；R2=`STOP_HIGHER_ORDER_SET_ROUTE` 且关闭；R3-C0=`STOP_CONTROL_ENDOGENEITY_ROUTE` 且关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`。final holdout 2019-03/06/09/12 继续封存。**

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

Source status SHA256：

`a8b7142e0361b5cd56e53c7de99d8e699a27e1aee78728810773c127f385823f`

运行后 development data 和 existing worktrees 均保持不变。

## 2. 为什么是 MIXED

R4-I0 PASS 的 13 个冻结条件中有 12 个满足。唯一失败条件：

```text
required pooled skill_M3_vs_M2 <= 0.02
actual   pooled skill_M3_vs_M2  = 0.0819284863
```

因此不能宣称 richer legal issue-time state 完全没有增量信息。M3 相对 M2 的 pooled future-divergence skill 为 **+8.19%**。

同时，两个 STOP 路线都不成立：

```text
pooled M2 vs Level skill      = -0.106407
pooled M3 vs Level skill      = -0.015761
pooled normalized M3 divergence = 0.297930
```

M2/M3 都没有满足跨 horizon/month 的稳定 vs-Level 解析条件；M3 future divergence 也远非“很小”。因此正式结果必须保持 MIXED。

## 3. Horizon 结构

| horizon | M2 vs Level | M3 vs Level | M3 vs M2 | normalized M3 divergence |
| ---: | ---: | ---: | ---: | ---: |
| 15 min | -42.34% | -29.61% | +8.94% | 0.2411 |
| 30 min | -27.70% | -16.23% | +8.99% | 0.2542 |
| 60 min | -17.61% | -6.04% | +9.83% | 0.2778 |
| 120 min | -7.65% | +3.15% | +10.03% | 0.3156 |
| 240 min | +11.51% | +15.43% | +4.44% | 0.4013 |

短时距 Level-Control 最强；随 horizon 增大，rich state 的相对价值上升，240 min 时 M2/M3 均明显优于 Level。该趋势只作 development-data 描述，不能直接变成新的 horizon gate。

## 4. Month 结构

| month | M2 vs Level | M3 vs Level | M3 vs M2 | normalized M3 divergence |
| --- | ---: | ---: | ---: | ---: |
| 2019-01 | -6.73% | -0.83% | +5.53% | 0.2938 |
| 2019-04 | -1.24% | +20.06% | +21.04% | 0.2974 |
| 2019-07 | +2.23% | +4.90% | +2.72% | 0.3104 |
| 2019-10 | -45.35% | -40.43% | +3.39% | 0.2898 |

M3 在四个月都优于 M2，但相对 Level 高度异质：April 全时距有利，October 全时距不利。

20 个 month×horizon cells 中：

```text
M3 vs M2 > 0       19 / 20
M3 vs M2 >= 5%     12 / 20
M3 vs Level > 0     9 / 20
M3 vs Level >= 5%   8 / 20
```

## 5. 当前科学解释边界

当前最稳妥的结论是：

> legal issue-time state 中确实存在超出 M2 的 session-state 增量信息，但 richer state 相对 instantaneous station-current continuity 的预测价值具有明显 horizon/month dependence。

不得把 R4-I0 改写为 information-theoretic irreducibility，也不得因为 240 min 或 April 有利而事后改 PASS/STOP 规则。

## 6. 当前唯一后续：R4-D1

冻结的下一问题：

> M3 analog 是否通过获得更近的 session-state geometry，同时牺牲了 instantaneous current-level similarity，从而形成 R4 中观察到的 horizon/month trade-off？

R4-D1 只允许：

- exact replay 原 R4 supported rows 与 analog identities；
- cross-arm current-level / M2 / M3-extension / full-M3 geometry evaluation；
- Level/M2/M3 neighbor overlap；
- 原始 future-divergence difference 的完整 pooled/horizon/month/20-cell 汇总。

禁止：alternate K、alternate clock window、metric learning、PCA、feature selection、hybrid/two-stage analog、模型训练、holdout。

## 7. 当前执行状态

| 项目 | 状态 |
| --- | --- |
| R4-I0 run | COMPLETE |
| R4-I0 decision | **MIXED_STATE_ALIASING_SIGNAL** |
| R4-I0 fit count | 0 |
| R4-D1 protocol | frozen in current docs PR |
| R4-D1 implementation | NOT STARTED |
| Final holdout | SEALED |
| 当前用户本机动作 | **无** |

下一动作仅在 GitHub：R4 outcome + R4-D1 protocol 文档 PR 审查/CI/合并；之后再单独实现 zero-fit R4-D1。
