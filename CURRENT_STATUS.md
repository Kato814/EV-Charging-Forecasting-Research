# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-13。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R2 正式结果见 [R2 outcome](docs/JPL_R2_HIGHER_ORDER_SESSION_SET_OUTCOME_20260913.md)；post-R2 选择依据见 [screening](docs/JPL_POST_R2_METHOD_SCREENING_20260913.md)；当前新协议见 [R3-C0 protocol](docs/JPL_R3_C0_CONTROL_ENDOGENEITY_GATE_PROTOCOL_20260913.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1=`STOP_MECHANISM_ROUTE` 且关闭；R1=`MIXED_JOINT_STATE_SIGNAL` 且诊断关闭；R2=`STOP_HIGHER_ORDER_SET_ROUTE` 且关闭。当前下一阶段为 R3-C0：0-fit control-endogeneity gate。final holdout 2019-03/06/09/12 继续封存。**

## 1. 已关闭的 R2

R2 已完成唯一授权的 development-only 正式运行：

```text
fit_count        = 550
runtime          = 448.055812 s
formal device    = NVIDIA GeForce RTX 5080 / cuda:0
PyTorch          = 2.14.0+cu132
CUDA             = 13.2
R2-Joint MAE     = 33.5660251919 A
R2-Permuted MAE  = 33.3294171470 A
Equal MAE        = 28.9172859886 A
S1 MAE           = 28.5948815297 A
R1-Joint MAE     = 29.0399775992 A
```

R2-Joint 仅 2/5 horizons、1/4 development months 优于 Permuted，且 pooled Joint > Permuted，因此直接触发预注册 STOP。R2 不做 Set Transformer、attention、MoE、更大 Deep Sets、session-feature 筛选或其他 post-hoc rescue。

正式运行后 development 数据未改变，R1 private cache 未改变，历史 worktree 全部保留，final holdout 未访问。R2 outcome：PR #74，merge `154ff4c10d725f24e84955c5895ad74668029c9c`。

## 2. 当前唯一问题：R3-C0 control endogeneity

S1/P1/R1/R2 连续尝试了未来组成、显式会话机制、低阶 joint state 与高阶 nonlinear session set，但均未形成稳定优于强基线的路线。下一步不再换 backbone，而先检验被预测量本身是否混合了用户需求与充电控制作用。

ACN/JPL 同时记录 measured charging current 与 EVSE pilot/current limit。R3-C0 的问题是：

> 当未来控制路径没有作为预测时输入时，issue-time pilot-versus-actual operating state 是否能在匹配当前 station-current level 后，稳定区分未来 realized-current 的预测难度？

这是 forecastability / target-generating-process gate，不是因果证明，也不声称首次使用 pilot 信息。

## 3. R3-C0 冻结设计

R3-C0 为 **0-fit、development-only、read-only** 诊断。

合法输入：

```text
M3 current_current_a
M3 current_pilot_a
M2 station_current_a   # 仅用于当前负荷水平匹配
```

控制利用率：

```text
U = sum(current_current_a) / sum(current_pilot_a)
```

只保留 paired-valid coverage>=0.80、pilot sum>=6A、当前 station current 有效的 issue times；不 clip U。

每月先按当前 station current 分成5个等计数 bin，再在每个 bin 内按 U 分 lower/upper halves，并按 station current rank 配对。匹配完全不读取 truth/error，同一对 issue times 复用于五个 horizons 和所有 frozen references。

Primary references：Equal、S1。R1-Joint 仅 secondary。

Primary contrast：matched lower-U 与 upper-U 的 absolute-error 差，报告 `delta_fraction`。完整支持阈值及 PASS/MIXED/STOP 已在 R3-C0 protocol 结果前冻结。

## 4. 当前执行状态

| 项目 | 状态 |
| --- | --- |
| Issue | #29 |
| Target | `station_current_mean_a`，A |
| Development | 2019-01/04/07/10 |
| Final holdout | 2019-03/06/09/12，封存 |
| S1 | MIXED，历史保留 |
| P1 | STOP/CLOSED |
| R1 | MIXED，diagnostic CLOSED |
| R2 | STOP/CLOSED，550 fits complete |
| R2 GPU env | `evcf-r2-set`，RTX5080/CUDA13.2 PASS，保留 |
| post-R2 screening | COMPLETE |
| R3-C0 protocol | FROZEN in current docs PR；**尚未运行** |
| R3-C0 model fit | 禁止；必须始终为0 |
| 当前用户本机命令 | **无** |

当前下一动作仅在 GitHub：完成 R3-C0 protocol PR 的 CI/审查/合并；随后新建独立只读 implementation PR。实现与 CI 均通过前，不发布本机 launcher。

## 5. Novelty / scope boundary

当前不把以下内容作为新核心：

- 更大 Deep Sets / Set Transformer / attention；
- Transformer/LSTM 充电轨迹编码；
- horizon/time-of-day MoE/gating；
- generic residual/ramp correction；
- arrival/departure climatology或 queueing 本身；
- P1/R1/R2 rescue。

R3-C0 只检验：**future control path 缺失条件下，当前 pilot-versus-actual operating state 是否稳定关联 forecastability。** targeted search 未发现完全相同的 station-load forecasting gate；这是定向检索证据，不是“首次”证明。

## 6. 执行与资产保护

- final holdout 继续封存；
- 保留所有历史 worktree、失败/成功 status、private cache 和 R2 private output；
- 不 reset/clean/stash/force push；
- 不修改冻结 reference predictions；
- 不为 R3-C0 训练模型、调阈值、删日期、筛小时/时距或做 clipping/calibration；
- 代码/PR通过、本机运行完成、科学假设通过分别报告。

后续长任务 PowerShell 输出按用户要求仅保留**阶段 / 月份 / 时距 / 粗粒度完成数 / 完成状态**，不再输出每5个 epoch 等高频日志。