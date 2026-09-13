# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-13。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R3-C0 正式结果见 [R3-C0 outcome](docs/JPL_R3_C0_CONTROL_ENDOGENEITY_OUTCOME_20260913.md)；post-R3 方向筛选见 [post-R3 screening](docs/JPL_POST_R3_METHOD_SCREENING_20260913.md)；R4-I0 冻结协议见 [R4-I0 protocol](docs/JPL_R4_I0_INFORMATION_SUFFICIENCY_PROTOCOL_20260913.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1=`STOP_MECHANISM_ROUTE` 且关闭；R1=`MIXED_JOINT_STATE_SIGNAL` 且关闭；R2=`STOP_HIGHER_ORDER_SET_ROUTE` 且关闭；R3-C0=`STOP_CONTROL_ENDOGENEITY_ROUTE` 且关闭。R4-I0 协议与实现已冻结并通过 CI，结果前 reporting contract 修复已合并，当前唯一授权动作是 development-only R4-I0 zero-fit 首次运行。final holdout 2019-03/06/09/12 继续封存。**

## 1. R3-C0 已关闭

R3-C0 development-only 0-fit gate 已 COMPLETE：

```text
runtime                        10.9733355 s
fit_count                      0
overall_valid_issue_fraction   0.3625615764
decision                       STOP_CONTROL_ENDOGENEITY_ROUTE
stop_reason                    INSUFFICIENT_CONTROL_STATE_SUPPORT
```

冻结 support 要求 overall>=0.70、每月 valid>=0.50、pairs>=100；实际仅 January 达到月度 valid floor。Equal/S1 在有效子集上的 pooled delta_fraction 约 -7%，但描述性差异不能覆盖 support failure。另一个重要边界是：60-min 下 Equal 与 S1 同时保持各自 pooled 方向的月份只有 2/4；因此即使只作反事实描述、忽略 support failure，也不能把该结果提升为稳定 PASS 机制证据。development 数据与 R2 private cache 保持不变，holdout 未访问。

## 2. R4-I0 科学问题

R4-I0 不训练新的 forecasting model。它检验：

> 在冻结合法 issue-time 状态下，历史中“非常相似”的状态是否仍对应 materially different future `station_current_mean_a`；完整 M2 或 M3 state 是否能比仅当前负荷水平稳定选出 future outcome 更接近的历史 analog？

这是 empirical state-aliasing / information-sufficiency gate，不是严格的信息论不可预测证明，也不是 nearest-neighbor forecasting 方法创新。

## 3. 冻结 analog 设计

Development：2019-01/04/07/10；horizons：15/30/60/120/240 min。

```text
Level-Control = M2 Ridge 标准化后的 station_current_a 单坐标
M2-State      = 完整 canonical M2，201 raw -> 204 encoded
M3-State      = 完整 canonical M3，311 raw -> 391 encoded
```

每个 month × local test day × horizon：

1. 历史候选必须 issue time 早于 test-day midnight，且该 horizon 标签在 midnight 前已可用；
2. `RidgePreprocessor` 仅在 eligible historical rows 上做 historical-only median imputation / nullable indicators / mean-std standardization；
3. 候选只取同一 month、exact same `America/Los_Angeles` 15-min clock slot；
4. `MIN_CANDIDATES=10`；`K=3`；
5. Level 距离为标准化 `station_current_a` 绝对差；M2/M3 为 encoded vector RMS Euclidean distance；
6. ties 由更早 issue time 决定；future target/error 禁止参与 matching。

## 4. “相似状态”支持规则

Support 只由 M3 历史 feature geometry 定义：同一 candidate pool 内历史 third-NN M3 distance 的 empirical q95（`higher`）作为 threshold；test third-NN M3 distance <= q95 才 in-support。同一 supported test-row set 用于 Level/M2/M3。

整体 support gate：

```text
pooled supported origin-horizon fraction >= 0.70
每个 month-horizon supported fraction >= 0.50
每个 month-horizon supported records >= 250
```

Support fail 直接 `STOP_STATE_ALIASING_ROUTE / INSUFFICIENT_ANALOG_SUPPORT`，禁止结果后改 K、clock window、candidate floor 或 q95。

## 5. Future-outcome divergence 与冻结判据

Analog identity 固定后才读取标签：

```text
D_a(i,h) = mean_j |y(i,h)-y(j,h)|
G_level = mean(D_level)
G_M2    = mean(D_M2)
G_M3    = mean(D_M3)
Y_scale = mean(abs(y))

skill_M2_vs_Level = 1 - G_M2/G_level
skill_M3_vs_Level = 1 - G_M3/G_level
skill_M3_vs_M2    = 1 - G_M3/G_M2
normalized_M3_divergence = G_M3/Y_scale
```

`PASS_STATE_ALIASING_SIGNAL`、`STOP_STATE_ALIASING_ROUTE`、`MIXED_STATE_ALIASING_SIGNAL` 的全部数值阈值以冻结 R4-I0 protocol 为准，不在结果产生后重写。PASS 只说明 frozen metric 下存在 material empirical aliasing，只授权另行 uncertainty/external-information/target-design protocol，不自动开 holdout。

## 6. 实现与审计状态

```text
R4-I0 protocol PR             #78
protocol merge                fec13c28cb5d4b2490256f8a26d82f45d8af6051
R4-I0 implementation PR       #79
implementation merge          58ebcb97869dc48ea0dfa5a7615134a5e822ac3b
pre-result reporting repair   #80
reviewed executable head      d3f00320e90aeb213d97d63d3460f58d495dd34a
reporting repair merge        1590b980b50e6ac1cb2db955b102431aa0c1ad25
```

PR #80 仅补齐冻结协议要求的 public distance-support summaries（candidate count、test third-neighbor M3 distance、historical q95 threshold 等）；不改变 causal eligibility、Ridge preprocessing、same-clock rule、K、support、target divergence 或 PASS/MIXED/STOP。完整 pytest / compileall / Ruff 已通过后合并。R4-I0 仍未运行，因此修复发生在任何 R4 outcome 产生之前。

## 7. Pinned launcher

当前唯一授权 launcher：

```text
evcf_r4_i0_launcher_v1.py
SHA256 = 880a5221594b5434386d62ec1b242c915cf229802ddc5644f09b52f9ea82345e
expected reviewed head = d3f00320e90aeb213d97d63d3460f58d495dd34a
```

Launcher 保护：development-only；final holdout path blocked；Python/package 环境固定；必要时只通过 PR #80 head ref fetch reviewed commit；detached code worktree；运行前后校验 development snapshots 与已有 worktree tracked state；移除 `ACN_API_TOKEN`；不自动清理；public output 必须报告 `fit_count=0` 且所有禁止动作 flag 为 false。

运行结束后只审计 `evcf_r4_i0_status_*.json`，严格按冻结规则裁决，不因结果修改阈值。

## 8. Novelty boundary

不得宣称 first EV predictability、first kNN/similar-day、first probabilistic EV forecast。R4-I0 的窄贡献边界仅是：**在本项目连续 richer deterministic representations 失败之后，对冻结 causal JPL issue-time state 做结果前注册的 empirical information-sufficiency / state-aliasing test。**

## 9. 当前执行状态

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
| R4-I0 protocol | FROZEN / MERGED |
| R4-I0 implementation | FROZEN / MERGED |
| R4-I0 pre-result reporting repair | MERGED |
| R4-I0 model fit | 必须为0 |
| R4-I0 run | **NOT RUN** |
| 当前用户本机动作 | **运行 pinned R4-I0 launcher exactly once** |

## 10. 资产与执行保护

保留全部历史 worktree、failed/complete status、private caches、R2/R3 outputs 和 `evcf-r2-set`；不 reset/clean/stash/force push。首次 R4-I0 运行前不再修改科学阈值。后续长任务 PowerShell 仅输出 stage/month/horizon/coarse progress/completion。