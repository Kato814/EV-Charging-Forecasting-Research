# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新日期：2026-09-12。本文件是当前状态唯一入口。历史证据见 [实验台账](docs/EXPERIMENT_LEDGER.md)，P1 正式结果见 [P1 outcome](docs/JPL_P1_MECHANISM_PROBE_OUTCOME_20260912.md)，P1-A 最终只读审计见 [P1-A post-mortem outcome](docs/JPL_P1_A_POSTMORTEM_OUTCOME_20260912.md)，post-P1 方法筛选见 [method screening](docs/JPL_POST_P1_METHOD_SCREENING_20260912.md)，R1 冻结协议见 [R1 protocol](docs/JPL_JOINT_SESSION_STATE_PROBE_PROTOCOL_20260912.md)，接管规则见 [HANDOFF](HANDOFF.md)。

**当前结论：S1 保持 `MIXED_STRUCTURED_SIGNAL`；P1 已正式 `STOP_MECHANISM_ROUTE` 且 post-mortem 已关闭。R1 joint-session-state representation probe 的协议与实现均已通过 GitHub PR/CI；R1 尚未在开发集上拟合。当前唯一授权下一步是运行一次 development-only R1 launcher 并审计 status JSON。final holdout 2019-03/06/09/12 继续封存。**

## 1. 当前阶段

| 项目 | 当前状态 |
| --- | --- |
| 当前 Issue | #29 多时距会话贡献分解与结构化充电站负荷预测 |
| 开发集 | 2019-01 / 04 / 07 / 10 |
| final holdout | **2019-03 / 06 / 09 / 12，禁止访问** |
| 预测目标 | `station_current_mean_a`，单位 A |
| S1 冻结决策 | `MIXED_STRUCTURED_SIGNAL` |
| P1 冻结决策 | `STOP_MECHANISM_ROUTE` |
| R1 protocol | **FROZEN BEFORE FIT；PR #61 merged** |
| R1 implementation | **PR #62 CI PASS + merged** |
| R1 fit | **NOT STARTED** |
| 当前允许动作 | **一次 development-only R1 launcher 运行；结束后只审计最新 status JSON** |

## 2. 已冻结机制证据

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

S1 仅 2/4 开发月优于 Equal，因此正式保持 `MIXED_STRUCTURED_SIGNAL`。只读诊断还确认：30 min / realized arrival share 25–50% 与 60 min / 50–75% 是跨月稳定弱区；30/60/120 min 在约 07:00 跨月稳定偏弱，09:00 附近可反转。

这些现象只证明存在 horizon-conditioned turnover structure，不证明 P1、survival、TPP、MoE 或 set network 有效。

## 3. P1 已关闭

```text
Equal       28.917286 A
S1          28.594882 A
P1-Eonly    30.065656 A
P1-Aonly   172.758507 A
P1-EA      172.966423 A
```

Probe E / A 均为 `NO_COMPONENT_SIGNAL`，P1-EA 为 `STOP_MECHANISM_ROUTE`。P1-A post-mortem 确认严重 extreme-tail OOS extrapolation，但 Probe E 也独立失败，因此 P1 不再 rescue。

## 4. R1 科学问题与 matched design

M3 对 11 个合法 issue-time session 字段分别做 10 个独立边际统计，共 110 个 session-pool 特征；它保留边际分布，却丢失哪些字段值属于同一个 session。R1 只检验这种 within-session joint alignment 是否有稳定增量信息。

两条 arm 都以 frozen M3 311 维 raw context 为基础，并追加相同 55 个 session-field-pair 位置：

```text
R1 raw width = 311 + C(11,2) = 366
```

- `R1-Control`：pair 可定义时填 0，不可定义时 NaN；
- `R1-Joint`：在完全相同 availability mask 下填 pairwise-complete Pearson correlation；
- 两者使用完全相同的 frozen M3 horizon-specific HGB 参数、preprocessing 语义、rolling-origin、OOS rows 和 aggregate target。

主比较只允许 `R1-Joint vs R1-Control`；外部参照 M2 / M3 / Equal / S1。

冻结决策为：

```text
PASS_JOINT_STATE_SIGNAL
MIXED_JOINT_STATE_SIGNAL
STOP_JOINT_STATE_ROUTE
```

判据已在 protocol 中锁定，结果后不得修改。

## 5. R1 实现身份

Protocol：
- PR #61
- merge `5c56ac71d6e94e6c566e88a855b4f9646eb170ea`

Implementation：
- PR #62
- CI-passed reviewed head `e01607078431141a1fccdd6a9db5f75ae561bfda`
- merge `0a2f1fc29af3fc6232534c8f6073c276dbe9122f`
- full pytest / compileall / Ruff PASS

Local launcher SHA256：

```text
4f38e5e924c58142d15ce3a0a3965c33663fa028347d30e52fdcbf02bed830b4
```

## 6. 当前禁止事项

- 不访问 final holdout；
- 不恢复 reliability/composition gate；
- 不把 realized future composition 当 predictor；
- 不继续 P1 rescue；
- R1 不做 pair selection、相关系数类型切换、clipping/calibration 或 hyperparameter search；
- R1 结果出来前不训练 Deep Sets / Set Transformer / MoE；
- 不删除极端 P1 rows、历史 worktree、failed status 或 private cache；
- 禁止 `reset --hard`、`clean`、blind stash、force push。

## 7. 当前唯一下一步

运行一次正式 R1 launcher。若 `COMPLETE`，按冻结规则直接裁决 PASS/MIXED/STOP；若 `INCOMPLETE`，不要自动重跑，只读最新 status JSON 定位 failure code。无论结果如何，final holdout 都不自动开放。
