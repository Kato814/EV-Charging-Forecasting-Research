# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-12。当前入口为本文件与 [HANDOFF](HANDOFF.md)。R1 最终诊断见 [R1 MIXED 诊断结果](docs/JPL_R1_MIXED_DIAGNOSTIC_OUTCOME_20260912.md)；R2 选择依据见 [post-R1 screening](docs/JPL_POST_R1_METHOD_SCREENING_20260912.md)，新协议见 [R2 higher-order session-set protocol](docs/JPL_R2_HIGHER_ORDER_SESSION_SET_PROTOCOL_20260912.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1=`STOP_MECHANISM_ROUTE` 且已关闭；R1=`MIXED_JOINT_STATE_SIGNAL` 且日级/小时级诊断已关闭。下一研究阶段冻结为 R2：真实 origin-active session joint set 对 marginal-preserving permuted control。R2 尚未实现、尚未训练；final holdout 2019-03/06/09/12 继续封存。**

## 1. 已关闭的 R1 阶段

R1 正式训练 COMPLETE，550 fits。其只读日级/小时级诊断也已 COMPLETE，0 fits；20 个 month-horizon、275 个 day-horizon、480 个小时格和 120 个跨月小时比较已复算一致。

R1 主要结论保持：

```text
R1-Control pooled MAE 29.1928819023 A
R1-Joint   pooled MAE 29.0399775992 A
Equal      pooled MAE 28.9172859886 A
S1         pooled MAE 28.5948815297 A
```

Joint 对 Control 改善 0.523773%，但对 Equal 退化 0.424285%；八项 PASS 条件仅六项满足。七月退化分布在多个日期，十月既有 Joint-vs-Control 收益又有对 Equal 的残余差距；60 min 对 Equal 仅改善 0.055223 A，07:00/09:00 方向不稳定。因此 R1 不升级为 PASS，也不通过删日期、筛 pair、换相关系数或小时门控 rescue。

R1 诊断 outcome：PR #69，merge `7c8c07fcce1409283b9764616d9f7811056f6d99`。

## 2. 当前唯一科学问题：R2

R1 只测试低阶 Pearson joint summaries。当前冻结的新问题是：

> 当前已连接充电会话群体的**高阶非线性同会话联合状态**，在所有字段边际分布保持完全相同的条件下，是否仍提供稳定的 issue-time 多时距预测增量？

R2 主比较不是“Deep Sets vs HGB”，而是同一小网络下的：

```text
R2-Joint     = 真实同会话 11 字段 tuple set
R2-Permuted  = 每个字段在同一 issue 内独立确定性置乱；字段值/缺失边际、会话数、M2 context 全部保持
```

两 arm 的架构、参数量、fold preprocessing、初始化、batch 顺序、优化器、epochs、rolling-origin 行完全相同。唯一科学差异是是否保留真实 cross-field same-session alignment。

R2 使用 M2 的 201 维 raw issue-time context，加 variable-length origin-active session set；直接预测 `station_current_mean_a`。不做 existing/arrival target 分解，不生成未来 session，不用未来组成。

## 3. Novelty boundary

不得把以下内容写成创新：

- Deep Sets / Set Transformer 架构；
- 处理可变数量 EV；
- 使用 active-session 信息；
- session-aware station forecasting；
- existing/future-session decomposition 或 session generation；
- generic Transformer/MoE/horizon routing。

已核对的直接邻近工作包括 Deep Sets、Set Transformer、Kwon & Zhu 的 EVCS variable-population representation、Berkeley `StationLevelPowerForecasting` 的 active-session forecasting features，以及 2026 SessionFlow 的 origin-active continuation + future-session generation。

R2 当前可检验的贡献边界是：**marginal-preserving counterfactual 下，高阶 origin-active joint session state 对 aggregate multi-horizon forecast 的增量价值。**

## 4. R2 冻结模型与训练边界

第一轮只使用小型 Deep-Sets-style sum encoder，不用 attention：

```text
session phi:    22 -> 32 -> 32, ReLU
sum pooling:    32
M2 context:    204 -> 64 -> 32, ReLU
forecast head:  64 -> 32 -> 1, ReLU only on hidden layer
```

固定训练：L1Loss、AdamW、lr=1e-3、weight_decay=1e-4、batch=256、30 epochs、无 early stopping / scheduler / dropout / AMP / torch.compile / clipping / calibration。

五个 horizon 分别训练。Joint 和 Permuted 每个 fold 使用相同初始化与 batch order。

完整 PASS/MIXED/STOP 规则已经在 R2 protocol 预注册。PASS 不自动开放 final holdout；只允许另行冻结 seed-robustness / method-freeze 阶段。MIXED 只做失败分析；STOP 关闭当前 higher-order set 路线，不事后跳 Set Transformer rescue。

## 5. GPU / 环境要求

R2 不修改历史 `evcf-gate1-pilot` 环境。实现阶段另建：

```text
environment = evcf-r2-set
Python      = 3.11.16
PyTorch     = 2.14.0
CUDA wheel  = cu132
formal GPU  = NVIDIA GeForce RTX 5080 / cuda:0
```

正式 R2 launcher 在任何 fit 前必须验证 CUDA 可用、实际设备为 RTX 5080，并做 float32 forward/backward smoke test；失败就 fail-closed，不能静默回 CPU。CI 可使用 CPU 做单元测试，但不代表正式实验运行。

耗时脚本继续实时显示 device、month、horizon、arm、fit/day、粗粒度 epoch（至少每 5 epochs）和实际耗时。PowerShell 命令保持单行。

## 6. 当前执行状态

| 项目 | 状态 |
| --- | --- |
| Issue | #29 |
| 目标 | `station_current_mean_a`，A |
| Development | 2019-01 / 04 / 07 / 10 |
| Final holdout | 2019-03 / 06 / 09 / 12，封存 |
| S1 | MIXED，历史保留 |
| P1 | STOP，关闭 |
| R1 | MIXED，诊断关闭 |
| R2 screening | COMPLETE |
| R2 protocol | **frozen in current protocol PR; no fit yet** |
| R2 implementation | NOT STARTED |
| R2 GPU env/preflight | NOT STARTED |
| 当前本机命令 | **无** |

当前下一动作只在 GitHub：完成 R2 protocol PR 的全量 CI/审查/合并。之后才能新建独立 implementation PR；实现、环境预检、CI 全部通过后，才发布一次 development-only launcher。

## 7. 长期保护

保留所有历史 worktree、失败/成功 status 和 private cache；不 reset/clean/stash/force push。禁止 P1/R1 rescue、删日期、筛 pair、未来真实组成输入、final holdout 访问、未经协议授权的 Set Transformer/MoE/TPP/新数据训练。

代码通过、PR 合并、本机 fit 完成、科学假设通过必须分别报告。任何 R2 结果都不得事后修改上述判据。
