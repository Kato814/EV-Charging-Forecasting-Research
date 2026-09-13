# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-13。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R3-C0 outcome](docs/JPL_R3_C0_CONTROL_ENDOGENEITY_OUTCOME_20260913.md) 和 [post-R3 screening](docs/JPL_POST_R3_METHOD_SCREENING_20260913.md)。历史链再读 R2/R1/P1 outcomes 与 [EXPERIMENT_LEDGER](docs/EXPERIMENT_LEDGER.md)。

## 1. 当前科学状态

```text
S1 = MIXED_STRUCTURED_SIGNAL
P1 = STOP_MECHANISM_ROUTE, CLOSED
R1 = MIXED_JOINT_STATE_SIGNAL, diagnostic CLOSED
R2 = STOP_HIGHER_ORDER_SET_ROUTE, CLOSED
R3-C0 = STOP_CONTROL_ENDOGENEITY_ROUTE, CLOSED
R4-I0 = information-sufficiency / state-aliasing protocol design only
```

Final holdout `2019-03/06/09/12` 继续封存。当前**没有用户本机命令**。

## 2. R3-C0 正式结果

Protocol merge：`a1b6fb1773860448cedd0335841b3e9c4f9a69fe`。

Implementation PR #76 reviewed head：`3ab1692536c7713ac780288b49607fdc09bf4e2c`；merge：`587200ed0b3ad81c494d24231255ad40fcd0aa94`。

Formal launcher SHA256：`962dc62f28744ae765ae60efc30c2b67c9a6ce4ff6b0a208998fe55ba4b10521`。

正式运行：

```text
status                       COMPLETE
runtime                      10.9733355 s
fit_count                    0
model_fit_attempted          false
reference_models_retrained   false
holdout_accessed             false
overall_valid_issue_fraction 0.3625615764
decision                     STOP_CONTROL_ENDOGENEITY_ROUTE
stop_reason                  INSUFFICIENT_CONTROL_STATE_SUPPORT
```

月度 support：

```text
2019-01 valid=0.530268 pairs=345
2019-04 valid=0.248305 pairs=145
2019-07 valid=0.277434 pairs=179
2019-10 valid=0.382716 pairs=246
```

冻结 support 要求 overall>=0.70 且每月 valid>=0.50、pairs>=100。仅 January 达到月度 valid floor，因此 route 必须 STOP；不要降低 coverage/pilot floor，不要改5 bins，不要重做 matching，不要 future-control predictor rescue。

有效子集描述性 pooled contrast：

```text
Equal      delta_fraction -0.071229
S1         delta_fraction -0.073845
R1-Joint   delta_fraction -0.086692
```

定义为 low-U error minus high-U error。负值说明有效子集中 lower-U matched error 较低，但这不是可推广机制证据：support 稀疏，Equal horizon sign 仅3/5与 pooled 一致，60-min 两 primary refs 仅2/4月份同时保持 pooled 方向。R3-C0 不允许因这些描述性结果被重新打开。

Development 数据和 R2 private cache 运行后均保持不变，历史 worktree 保留，final holdout 未访问。

## 3. 为什么不继续 session/control representation

S1/P1/R1/R2/R3 已依次检验 future composition、explicit session mechanism、pairwise joint state、higher-order nonlinear session set、pilot-vs-actual control state。继续增加 session/control representation 已缺乏科学依据。

Post-R3 screening 同时排除以下即时核心方向：

- larger Deep Sets / Set Transformer / attention / trajectory encoder；
- generic residual/ramp correction；
- peak profile / peak magnitude forecasting；
- latent/censored demand；
- generic probabilistic multi-horizon model；
- generic horizon routing/MoE/similar-day selection。

这些方向已有直接或邻近 EV prior art，或已被当前 development evidence 关闭。

## 4. 当前下一问题：R4-I0 information sufficiency / state aliasing

下一问题不是“再换一个模型”，而是：

> 在冻结的合法 issue-time 信息下，是否存在状态非常相似、但未来 `station_current_mean_a` 显著分叉的经验 state aliasing；该分叉是否随 horizon 稳定增大？

目的：判断当前 deterministic point-forecast search 是否还有信息论上的空间，还是现有 issue-time boundary 已存在明显 partial observability，需要另行转向 uncertainty / external-information route。

这不是“first predictability analysis”。已有用户级 EV predictability、site/horizon predictability、probabilistic EV load forecasting、similar-day selection等 prior art。窄问题只能是**当前冻结 JPL issue-time state 的 empirical aliasing / information sufficiency**。

## 5. R4-I0 尚未冻结的关键设计

当前只允许 protocol design，不允许本机 run。Protocol 必须结果前写死：

1. exact legal state vector；
2. historical-only feature scaling；
3. historical-neighbor / matched-control rule；
4. support floor；
5. target-dispersion metric；
6. horizon-specific aggregation；
7. PASS/MIXED/STOP thresholds；
8. target/error 不得进入 state matching；
9. positive gate 只授权下一 uncertainty/target-design stage；
10. final holdout 继续封存。

## 6. 资产和执行保护

保留全部历史 worktree、failed/complete status、private caches、R2/R3 outputs 和 `evcf-r2-set`；不 reset/clean/stash/force push。

禁止 P1/R1/R2/R3 rescue、删日期/小时/时距、未来真实组成输入、未授权的新模型训练和 final holdout 访问。

后续耗时脚本只输出 **stage / month / horizon / coarse completed count / completion**，不输出高频 epoch 日志；PowerShell 命令必须单行。

代码通过、PR 合并、本机运行完成、科学假设通过必须分别报告。