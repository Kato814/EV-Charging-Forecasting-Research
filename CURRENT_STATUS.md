# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-13。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R2 正式结果见 [R2 outcome](docs/JPL_R2_HIGHER_ORDER_SESSION_SET_OUTCOME_20260913.md)；R3-C0 正式结果见 [R3-C0 outcome](docs/JPL_R3_C0_CONTROL_ENDOGENEITY_OUTCOME_20260913.md)；post-R3 方向筛选见 [post-R3 screening](docs/JPL_POST_R3_METHOD_SCREENING_20260913.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1=`STOP_MECHANISM_ROUTE` 且关闭；R1=`MIXED_JOINT_STATE_SIGNAL` 且诊断关闭；R2=`STOP_HIGHER_ORDER_SET_ROUTE` 且关闭；R3-C0=`STOP_CONTROL_ENDOGENEITY_ROUTE` 且关闭。下一阶段为 R4-I0：issue-time information-sufficiency / state-aliasing protocol design。final holdout 2019-03/06/09/12 继续封存。**

## 1. 已关闭的 R3-C0

R3-C0 已完成唯一授权的 development-only 0-fit gate：

```text
status                         = COMPLETE
runtime                        = 10.9733355 s
fit_count                      = 0
model_fit_attempted            = false
reference_models_retrained     = false
overall_valid_issue_fraction   = 0.3625615764
decision                       = STOP_CONTROL_ENDOGENEITY_ROUTE
stop_reason                    = INSUFFICIENT_CONTROL_STATE_SUPPORT
```

冻结 support 要求为 overall valid >=0.70，且每月 valid >=0.50、matched pairs >=100。实际仅 2019-01 的月度 valid fraction 超过0.50：

```text
2019-01  0.530268  pairs=345
2019-04  0.248305  pairs=145
2019-07  0.277434  pairs=179
2019-10  0.382716  pairs=246
```

因此 route 在 effect-size 解释前即触发 STOP。禁止降低 coverage/pilot floor、改5个 current-level bins、重做 matching 或训练 future-control predictor rescue。

在有效子集上存在描述性差异，但不能升级为机制证据：

```text
Equal pooled delta_fraction     -0.071229
S1 pooled delta_fraction        -0.073845
R1-Joint pooled delta_fraction  -0.086692
```

定义为 low-U error minus high-U error，因此负值表示有效子集中 lower-U issue 的 matched error 平均更低。但 support 稀疏，Equal 的 horizon sign 仅3/5与 pooled 一致，60-min 两个 primary references 仅2/4月份同时保持 pooled 方向；不能据此建立稳定 control-endogeneity route。

正式运行后 development 数据未改变，R2 private cache 未改变，历史 worktree 保留，final holdout 未访问。

## 2. 当前下一问题：R4-I0 information sufficiency / state aliasing

S1/P1/R1/R2/R3 已连续检验 future composition、显式 session mechanism、低阶 joint state、高阶 nonlinear session set、pilot-vs-actual control state。继续增加 session/control representation 的科学收益已不足。

post-R3 选择将下列路线排除为当前核心：

- larger Deep Sets / Set Transformer / attention / trajectory encoder；
- generic ramp/residual correction；
- peak-profile/peak-magnitude forecasting；
- latent/censored demand；
- generic probabilistic multi-horizon model；
- generic horizon routing/MoE/similar-day selection。

下一步先回答：

> **在冻结的合法 issue-time 信息集合下，是否存在“当前状态非常相似，但未来 station current 显著分叉”的 state aliasing；并且这种分叉是否随 horizon 稳定增大？**

这不是新预测模型，而是 information-sufficiency / identifiability gate。其作用是决定是否还有理由继续寻找 deterministic point-forecast model，还是应承认当前信息边界的预测上限并另行设计 uncertainty / external-information 路线。

## 3. R4-I0 当前边界

R4-I0 尚未冻结完整 protocol，当前**禁止本机运行**。protocol 设计必须先明确：

1. exact legal state vector；
2. causal historical-only scaling；
3. historical-neighbor / matched-control rule；
4. support floor；
5. label-dispersion metric；
6. 15/30/60/120/240 min 独立判据；
7. PASS/MIXED/STOP thresholds；
8. future label 只用于结果诊断，不能进入 state matching；
9. positive gate 不等于 probabilistic forecasting novelty；
10. PASS 也不自动开放 final holdout。

## 4. 当前执行状态

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
| R3-C0 data/cache integrity | PASS |
| post-R3 screening | COMPLETE |
| R4-I0 | protocol design only；no run |
| 当前用户本机命令 | **无** |

## 5. Novelty / scope boundary

当前不得把以下内容写成创新：generic Deep Sets/Set Transformer、active-session forecasting、variable-size EV population、generic ramp residual、peak forecasting、latent-demand censoring、probabilistic EV forecasting、similar-day selection、generic predictability analysis。

R4-I0 若继续，窄问题只能是：**冻结 JPL issue-time state 的 empirical aliasing / information sufficiency 是否足以解释 richer deterministic representation 的连续失效。** Existing user-level predictability and generic uncertainty literature构成 novelty boundary，不是本项目可重复声称的贡献。

## 6. 执行与资产保护

- final holdout继续封存；
- 保留所有历史 worktree、失败/成功 status、private cache 和 R2/R3 outputs；
- 不 reset/clean/stash/force push；
- 不修改冻结 reference predictions；
- 不降低 R3-C0 support thresholds 做 rescue；
- R4-I0 protocol 未合并前不写实现、不运行本机数据；
- 代码/PR通过、本机运行完成、科学假设通过分别报告。

后续长任务 PowerShell 输出继续按用户要求只保留**阶段 / 月份 / 时距 / 粗粒度完成数 / 完成状态**。