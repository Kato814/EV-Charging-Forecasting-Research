# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新日期：2026-09-12。本文件是当前状态唯一入口。历史证据见 [实验台账](docs/EXPERIMENT_LEDGER.md)，P1 正式结果见 [P1 outcome](docs/JPL_P1_MECHANISM_PROBE_OUTCOME_20260912.md)，P1-A 最终只读审计见 [P1-A post-mortem outcome](docs/JPL_P1_A_POSTMORTEM_OUTCOME_20260912.md)，接管规则见 [HANDOFF](HANDOFF.md)。

**当前结论：S1 保持 `MIXED_STRUCTURED_SIGNAL`；P1 已正式 `STOP_MECHANISM_ROUTE`；P1-A 唯一授权的只读 post-mortem 已 COMPLETE。结构化 `continuation×mark + Poisson count×mark` 路线至此关闭，不再 rescue。G0/S1 已验证的 horizon-dependent composition shift 与 turnover/local-hour 结构保留为机制证据。final holdout 2019-03/06/09/12 继续封存。**

## 1. 当前阶段

| 项目 | 当前状态 |
| --- | --- |
| 当前 Issue | #29 多时距会话贡献分解与结构化充电站负荷预测 |
| 开发集 | 2019-01 / 04 / 07 / 10 |
| final holdout | **2019-03 / 06 / 09 / 12，禁止访问** |
| 预测目标 | `station_current_mean_a`，单位 A |
| S1 冻结决策 | `MIXED_STRUCTURED_SIGNAL` |
| P1 冻结决策 | **`STOP_MECHANISM_ROUTE`** |
| Probe E | `NO_COMPONENT_SIGNAL` |
| Probe A | `NO_COMPONENT_SIGNAL` |
| P1-A post-mortem | **COMPLETE，scientific decision unchanged** |
| 当前允许动作 | **重新进入新方法创新筛选；不得继续修补 P1** |

## 2. 已冻结的机制证据

G0 pooled 真实负荷组成：

```text
horizon   existing   future-arrival
15 min     97.38%       2.62%
30 min     90.61%       9.39%
60 min     78.10%      21.90%
120 min    56.52%      43.48%
240 min    26.21%      73.79%
```

强基线与 S1 pooled MAE：

```text
M2    30.164406 A
M3    29.190188 A
Equal 28.917286 A
S1    28.594882 A
```

S1 仅 2/4 开发月优于 Equal，因此正式保持 `MIXED_STRUCTURED_SIGNAL`。只读诊断还确认：
- 30 min / realized arrival share 25–50% 为稳定弱区；
- 60 min / 50–75% 为稳定弱区，而 0–25% 为稳定强区；
- 30/60/120 min 在约 07:00 跨月稳定偏弱，09:00 附近可反转。

这说明 horizon-conditioned turnover phenomenon 可复现，但不等于已有 P1 参数化有效。

## 3. P1 冻结结果

Pooled MAE：

| model | MAE (A) |
| --- | ---: |
| Equal | 28.917286 |
| S1 | 28.594882 |
| P1-Eonly | 30.065656 |
| P1-Aonly | 172.758507 |
| P1-EA | 172.966423 |

Component MAE：

| component | MAE (A) |
| --- | ---: |
| S1 existing | 12.791178 |
| P1-E | 14.495331 |
| S1 arrival | 23.105152 |
| P1-A | 167.857291 |

P1-EA 对 Equal 为 0/5 horizon wins、0/4 month wins；60-min P1-EA MAE = 109.278945 A vs Equal = 26.141292 A。正式决策只能是 `STOP_MECHANISM_ROUTE`。

## 4. P1-A 最终 post-mortem

执行身份：
- PR #58 CI-passed head `9bc752f1b416e0dce4cb59942d3ecb07315b9273`；
- merge `6df5cc836635fedb2034f27cdb34e7dda6e8a885`；
- P1 private manifest `df222c4731f3c3192735a6df2ccd2f692f1ea6d640a7954706e7bca17f51580f`；
- `status = COMPLETE`；
- no model fit / no raw or processed access / no holdout access / private cache unchanged。

P1-A 25,375 个 OOS rows 的 pooled 结果：

```text
MAE            167.857291 A
prediction q50  10.396828 A
prediction q99 518.312153 A
prediction max 2,526,912.316702 A
truth max      742.980111 A
```

误差高度集中：
- worst 1 row = 59.33% total absolute error；
- worst 5 rows = 81.99%；
- worst 10 rows = 82.09%；
- worst 1% rows = 84.67%。

最强病理点集中在 **2019-10-29 12:00 local**：

```text
15 min    1,379.274 A
30 min  2,526,912.317 A
60 min    390,526.985 A
120 min   572,604.896 A
```

其中 30/60/120 min 的极端输出均出现在同一 issue state。结合 P1 代码已通过 target identity、row identity、rolling-origin 约束，最稳妥解释是：固定 standardized-feature + log-link Poisson count 路线在少量 development OOS state 上发生严重外推失稳。private cache 未保存 predicted count / linear predictor，因此不做系数级因果断言。

该结果**不能用来 rescue P1**。即使忽略 Probe A，P1-Eonly = 30.065656 A，仍差于 S1 与 Equal；Probe E 本身也只有 1/5 horizon win、0/4 month win。

## 5. 当前下一步：新方法创新筛选

P1 已关闭。新候选必须重新定义，不允许从“修 Poisson / 换 survival / 上 TPP”直接延伸。

优先筛选能显式表达以下已验证难点的方法：
1. horizon-dependent regime specialization；
2. time-of-day-dependent state transition / local-hour reversal；
3. 在相同 causal feature boundary 下对不同预测时距采用不同专家或机制；
4. 不使用 realized future composition oracle；
5. 必须与 M2/M3/Equal/S1 在统一 OOS 协议下比较。

当前开放方向包括但不限于 mixture-of-experts / regime-specialized forecasting / horizon-conditioned routing，但 generic Transformer/Mamba backbone replacement 不自动构成创新。

## 6. 当前禁止事项

- 不访问 final holdout；
- 不恢复 reliability/composition gate；
- 不把 realized future composition 当 predictor；
- 不对 P1 做 post-hoc retuning / clipping / calibration；
- 不删除 2019-10 或极端 timestamp 后重新报结果；
- 不直接把 P1-E 升级为 neural survival、P1-A 升级为 neural TPP 来 rescue；
- 不清理历史 worktree、failed status、private cache；
- 禁止 `reset --hard`、`clean`、盲目 stash、force push。

## 7. 仓库维护

P1 正式 outcome、P1-A post-mortem、Issue #29、CURRENT_STATUS、HANDOFF 与实验台账保持一致。private row-level predictions/cache 继续仓库外保存。后续新方法必须先冻结科学问题、开发判据和代码身份，再实现/CI/本机运行。
