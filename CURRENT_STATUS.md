# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新日期：2026-09-12。本文件是当前状态唯一入口。历史证据见 [实验台账](docs/EXPERIMENT_LEDGER.md)，P1 正式结果见 [P1 outcome](docs/JPL_P1_MECHANISM_PROBE_OUTCOME_20260912.md)，P1-A 最终只读审计见 [P1-A post-mortem outcome](docs/JPL_P1_A_POSTMORTEM_OUTCOME_20260912.md)，post-P1 方法筛选见 [method screening](docs/JPL_POST_P1_METHOD_SCREENING_20260912.md)，R1 冻结协议见 [R1 protocol](docs/JPL_JOINT_SESSION_STATE_PROBE_PROTOCOL_20260912.md)，接管规则见 [HANDOFF](HANDOFF.md)。

**当前结论：S1 保持 `MIXED_STRUCTURED_SIGNAL`；P1 已正式 `STOP_MECHANISM_ROUTE` 且 post-mortem 已关闭。下一阶段已冻结为 R1 joint-session-state representation probe：先用 matched `R1-Control` / `R1-Joint` 检验当前连接会话的 within-session 联合状态是否提供稳定增量信息。R1 尚未拟合，final holdout 2019-03/06/09/12 继续封存。**

## 1. 当前阶段

| 项目 | 当前状态 |
| --- | --- |
| 当前 Issue | #29 多时距会话贡献分解与结构化充电站负荷预测 |
| 开发集 | 2019-01 / 04 / 07 / 10 |
| final holdout | **2019-03 / 06 / 09 / 12，禁止访问** |
| 预测目标 | `station_current_mean_a`，单位 A |
| S1 冻结决策 | `MIXED_STRUCTURED_SIGNAL` |
| P1 冻结决策 | `STOP_MECHANISM_ROUTE` |
| P1-A post-mortem | COMPLETE，scientific decision unchanged |
| post-P1 method screening | COMPLETE |
| R1 protocol | **FROZEN BEFORE FIT** |
| R1 fit | **NOT STARTED** |
| 当前允许动作 | **实现 R1-Control / R1-Joint，先经 PR/CI；CI 通过后才能本机运行** |

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

Probe E / A 均为 `NO_COMPONENT_SIGNAL`，P1-EA 为 `STOP_MECHANISM_ROUTE`。P1-A post-mortem 进一步确认严重 extreme-tail OOS extrapolation，但 Probe E 也独立失败，因此 P1 不再 rescue。

## 4. post-P1 方法筛选结论

2025–2026 相关工作已经覆盖 generic EV multi-horizon Transformer、MoE、horizon-conditioned routing、probabilistic residual forecasting 与 session-generative forecasting。因此 generic backbone / generic MoE / existing+arrival decomposition 本身不能构成核心创新。

仓库代码核对确认 M3 对 11 个合法 session 字段分别做 10 个独立边际统计，共 110 个 session-pool 特征；这保留边际分布，却不保留哪些字段值属于同一个 session。P1-E 虽保留 session tuple，但独立预测每个 session 的未来贡献并失败。

因此当前新问题被缩窄为：

> 当前已连接 session population 的 within-session joint state 是否包含被 M3 独立边际池化丢失、且对多时距 aggregate current 预测稳定有用的信息？

## 5. R1 冻结协议

R1 不直接训练 Deep Sets / Set Transformer。两条 matched arm 都以 frozen M3 311 维 raw context 为基础，并追加相同 55 个 session-field-pair 位置：

```text
R1 raw width = 311 + C(11,2) = 366
```

- `R1-Control`：pair feature 可定义时填 0，不可定义时 NaN；
- `R1-Joint`：在完全相同 availability mask 下填 pairwise-complete Pearson correlation；
- 两者使用完全相同的 frozen M3 horizon-specific HGB 参数、preprocessing、rolling-origin 与 OOS rows。

主比较只允许：`R1-Joint vs R1-Control`。外部参照：M2 / M3 / Equal / S1。

冻结决策为：`PASS_JOINT_STATE_SIGNAL / MIXED_JOINT_STATE_SIGNAL / STOP_JOINT_STATE_ROUTE`。判据已在 protocol 中提前锁定，不得看结果后修改。

## 6. 当前禁止事项

- 不访问 final holdout；
- 不恢复 reliability/composition gate；
- 不把 realized future composition 当 predictor；
- 不继续 P1 rescue；
- R1 不做 pair selection、相关系数类型切换、clipping/calibration 或 hyperparameter search；
- R1 结果出来前不训练 Deep Sets / Set Transformer / MoE；
- 不删除极端 P1 rows、历史 worktree、failed status 或 private cache；
- 禁止 `reset --hard`、`clean`、blind stash、force push。

## 7. 仓库维护

R1 必须形成独立 protocol → implementation PR/CI → local status → outcome 链路。private row-level outputs/cache 继续仓库外保存。若 R1 PASS，也不能直接访问 final holdout；只能进入单独预注册的 learned session-set 阶段。
