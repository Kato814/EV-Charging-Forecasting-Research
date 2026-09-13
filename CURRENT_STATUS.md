# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-13。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R3-C0 正式结果见 [R3-C0 outcome](docs/JPL_R3_C0_CONTROL_ENDOGENEITY_OUTCOME_20260913.md)；post-R3 方向筛选见 [post-R3 screening](docs/JPL_POST_R3_METHOD_SCREENING_20260913.md)；当前新协议见 [R4-I0 protocol](docs/JPL_R4_I0_INFORMATION_SUFFICIENCY_PROTOCOL_20260913.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1=`STOP_MECHANISM_ROUTE` 且关闭；R1=`MIXED_JOINT_STATE_SIGNAL` 且关闭；R2=`STOP_HIGHER_ORDER_SET_ROUTE` 且关闭；R3-C0=`STOP_CONTROL_ENDOGENEITY_ROUTE` 且关闭。当前阶段冻结为 R4-I0：issue-time information sufficiency / state aliasing。final holdout 2019-03/06/09/12 继续封存。**

## 1. R3-C0 已关闭

R3-C0 唯一授权的 development-only 0-fit gate 已 COMPLETE：

```text
runtime                        10.9733355 s
fit_count                      0
overall_valid_issue_fraction   0.3625615764
decision                       STOP_CONTROL_ENDOGENEITY_ROUTE
stop_reason                    INSUFFICIENT_CONTROL_STATE_SUPPORT
```

冻结 support 要求 overall>=0.70、每月 valid>=0.50、pairs>=100；实际仅 January 达到月度 valid floor。Equal/S1 在有效子集上的 pooled delta_fraction 约 -7%，但不能因描述性差异放宽支持阈值或重新打开 control route。development 数据与 R2 private cache 保持不变，holdout 未访问。

## 2. R4-I0 科学问题

R4-I0 不训练新的 forecasting model。它检验：

> 在冻结合法 issue-time 状态下，历史中“非常相似”的状态是否仍对应 materially different future `station_current_mean_a`；完整 M2 或 M3 state 是否能比仅当前负荷水平稳定选出 future outcome 更接近的历史 analog？

这是 empirical state-aliasing / information-sufficiency gate，不是严格的信息论不可预测证明，也不是 nearest-neighbor forecasting 方法创新。

## 3. 冻结 analog 设计

Development：2019-01/04/07/10；horizons：15/30/60/120/240 min。

三组 analog：

```text
Level-Control = M2 Ridge 标准化后的 station_current_a 单坐标
M2-State      = 完整 canonical M2，201 raw -> 204 encoded
M3-State      = 完整 canonical M3，311 raw -> 391 encoded
```

M2 和 M3 都是 information-sufficiency 的合法状态 arm。若 M2 已经明显优于 Level，就不能因为高维 M3 距离效果不好而误判“信息不足”。

每个 month × local test day × horizon：

1. 历史候选必须 issue time 早于 test-day midnight，且该 horizon 标签在 midnight 前已可用；
2. 使用仓库现有 `RidgePreprocessor` 在 eligible historical rows 上做 training-only median/imputation/nullable indicators/standardization；
3. 候选只取**同一 America/Los_Angeles 当地15分钟 clock slot**；
4. `MIN_CANDIDATES=10`；
5. `K=3` analogs；
6. Level 距离为标准化 station_current 绝对差；M2/M3 为 encoded vector RMS Euclidean distance；
7. ties 由更早 issue time 决定；
8. future target/error 禁止参与匹配。

## 4. “相似状态”支持规则

Support 只由 M3 历史 feature geometry 定义：

- 在 same-clock historical candidate pool 内，对每个历史 row 计算其第三近邻 M3 distance；
- 取这些 third-NN distances 的 empirical q95，quantile method=`higher`；
- test issue 的第三近邻 M3 distance <= historical q95 才算 in-support。

同一 supported test-row set 用于 Level/M2/M3 三组比较。

整体 support gate：

```text
pooled supported origin-horizon fraction >= 0.70
每个 month-horizon supported fraction >= 0.50
每个 month-horizon supported records >= 250
```

Support fail 直接 `STOP_STATE_ALIASING_ROUTE / INSUFFICIENT_ANALOG_SUPPORT`，禁止事后改 K、clock window、candidate floor 或 q95。

## 5. Future-outcome divergence

Analog identity 固定后才读取标签：

```text
D_a(i,h) = mean_j |y(i,h)-y(j,h)|, j 属于该 arm 的3个 analog
```

聚合报告：

```text
G_level
G_M2
G_M3
Y_scale = mean(abs(y))
skill_M2_vs_Level = 1 - G_M2/G_level
skill_M3_vs_Level = 1 - G_M3/G_level
skill_M3_vs_M2    = 1 - G_M3/G_M2
normalized_M3_divergence = G_M3/Y_scale
```

正 skill 表示 richer state 选出的历史状态未来更接近。

## 6. 冻结科学判据

### PASS_STATE_ALIASING_SIGNAL

全部满足：support pass；pooled normalized M3 divergence>=0.10；>=3/5 horizons normalized divergence>=0.08；pooled M2-vs-Level skill<=5%；pooled M3-vs-Level skill<=5%；pooled M3-vs-M2 skill<=2%；M2 与 M3 各自只有<=1/5 horizons、<=1/4 months 的 vs-Level skill>=10%；60-min M2-vs-Level 和 M3-vs-Level 均<=5%，且60-min normalized divergence>=0.10。

含义：在 frozen metric 下，相近 M3 state 仍有 materially divergent futures，且 M2/M3 两个合法状态 tier 都没有明显优于 simple current-level analog。只授权后续 uncertainty/external-information/target-design protocol，不开 holdout。

### STOP_STATE_ALIASING_ROUTE

Support pass 后满足任一：

A. **M2 或 M3 任一 legal state arm** materially resolves divergence：同一 arm 的 pooled vs-Level skill>=10%，>=3/5 horizons 和 >=3/4 months skill>=5%，且60-min>=5%；

或 B. M3 analog future divergence 本身很小：pooled normalized divergence<0.05，且>=4/5 horizons<0.08。

含义：不支持“当前 legal issue-time state 信息不足”解释。

其余为 `MIXED_STATE_ALIASING_SIGNAL`，只能做另行冻结的只读 failure analysis。

## 7. Novelty boundary

不得宣称 first EV predictability、first kNN/similar-day、first probabilistic EV forecast。2024 Applied Energy 已研究 EV charging predictability heterogeneity；2026 Applied Energy 已有 EV similar-day selection；DiffPLF/CUP-EV 等已覆盖概率多时距 EV load forecasting。

R4-I0 的窄贡献边界仅是：**在本项目连续 richer deterministic representations 失败之后，对冻结 causal JPL issue-time state 做结果前注册的 empirical information-sufficiency / state-aliasing test。**

## 8. 当前执行状态

| 项目 | 状态 |
| --- | --- |
| Issue | #29 |
| Target | `station_current_mean_a`，A |
| Development | 2019-01/04/07/10 |
| Final holdout | 2019-03/06/09/12，封存 |
| S1 | MIXED |
| P1 | STOP/CLOSED |
| R1 | MIXED/CLOSED |
| R2 | STOP/CLOSED |
| R3-C0 | STOP/CLOSED，0 fits |
| post-R3 screening | COMPLETE |
| R4-I0 protocol | **frozen in current protocol PR; no implementation/run yet** |
| R4-I0 model fit | 必须为0 |
| 当前用户本机命令 | **无** |

当前下一动作仅在 GitHub：protocol PR 全量 CI/审查/合并；之后才允许单独 zero-fit implementation PR。

## 9. 资产与执行保护

保留全部历史 worktree、failed/complete status、private caches、R2/R3 outputs 和 `evcf-r2-set`；不 reset/clean/stash/force push。R4-I0 protocol 未合并前不写实现、不运行本机数据。后续长任务 PowerShell 仅输出 stage/month/horizon/coarse progress/completion。