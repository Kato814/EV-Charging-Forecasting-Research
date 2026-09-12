# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-12。先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R1 outcome](docs/JPL_R1_JOINT_STATE_OUTCOME_20260912.md) 和 [R1 protocol](docs/JPL_JOINT_SESSION_STATE_PROBE_PROTOCOL_20260912.md)。历史依据包括 [P1 outcome](docs/JPL_P1_MECHANISM_PROBE_OUTCOME_20260912.md)、[P1-A post-mortem](docs/JPL_P1_A_POSTMORTEM_OUTCOME_20260912.md)、[方法筛选](docs/JPL_POST_P1_METHOD_SCREENING_20260912.md)、[实验台账](docs/EXPERIMENT_LEDGER.md) 和 [开源台账](docs/OPEN_SOURCE_IDEA_LEDGER.md)。

## 1. 接管结论

S1 保持 `MIXED_STRUCTURED_SIGNAL`。P1 已 `STOP_MECHANISM_ROUTE`，post-mortem 关闭，不再 rescue。

**R1 已完成开发集正式运行：COMPLETE、550 fits、`MIXED_JOINT_STATE_SIGNAL`。不是 NOT STARTED，也不是 PASS。当前唯一科研动作类别是失败来源分析，不再发出 R1 训练命令，不直接启动 Deep Sets / Set Transformer / MoE。**

## 2. 冻结数据与身份

目标：`station_current_mean_a`，单位 A。Development：2019-01/04/07/10。Final holdout：2019-03/06/09/12，禁止访问。

Baseline private manifest：`2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd`。

S1 private manifest：`562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1`。

P1 private manifest：`df222c4731f3c3192735a6df2ccd2f692f1ea6d640a7954706e7bca17f51580f`，仅历史证据。

R1 status 报告的 private manifest：`56178b6eac582a7ed844d6f94324a6947580e0f9a42e95cb9307fd78adecfd0f`。私有逐行预测留在用户本机，不要求上传 NPZ。

R1 protocol：PR #61，merge `5c56ac71d6e94e6c566e88a855b4f9646eb170ea`。

R1 implementation：PR #62，reviewed head `e01607078431141a1fccdd6a9db5f75ae561bfda`，merge `0a2f1fc29af3fc6232534c8f6073c276dbe9122f`，pytest/compileall/Ruff 已通过。

Launcher v1 SHA256：`4f38e5e924c58142d15ce3a0a3965c33663fa028347d30e52fdcbf02bed830b4`，保留为历史执行版本，不因增加日志重跑 R1。

## 3. 实验设计没有改变

科学问题：同一已连接会话内部合法状态字段的联合关系，是否提供独立边际池化之外的预测信息？

两条 arm 均使用 frozen M3 311 raw features + 55 个 pair 位置。可定义位置：Control = 0、Joint = pairwise-complete Pearson correlation；不可定义位置两者均为 NaN。定义要求：至少两个共同观测会话、两字段均有正有限方差。两者宽度、缺失模式、HGB 参数、rolling-origin 和直接站级目标一致。

主比较 Joint vs Control；外部参照 M2/M3/Equal/S1。没有 existing/arrival 目标分解，没有未来组成输入。

## 4. R1 正式结果

| 模型 | Pooled MAE (A) |
| --- | ---: |
| M2 | 30.164406 |
| M3 | 29.190188 |
| Equal | 28.917286 |
| S1 | 28.594882 |
| R1-Control | 29.192882 |
| R1-Joint | 29.039978 |

Joint 对 Control 改善 0.523773%，对 Equal 退化 0.424285%。Control 比 M3 仅差 0.002694 A。

冻结判据复算：
- 对 Control：pooled 更好，4/5 horizon wins、3/4 month wins；
- 对 Equal：pooled 更差，3/5 horizon wins、2/4 month wins；
- 60 min：Joint 26.086069 A < Equal 26.141292 A；
- 最大 horizon 退化：1.110700%，未超过 5%；
- 六项 PASS 要求通过，两项失败，正式为 MIXED。

## 5. 已完成审计与失败分解

状态报告 integrity flags 均正常：开发数据及 baseline/S1 cache 未变，worktree 保留，holdout 未访问，M2/M3 未重训，无调参或预测后处理。

已从 20 个 month-horizon cell 重新汇总整体、各 horizon、各 month 的 MAE/RMSE/WAPE/负预测数，并复算所有 decision_support 项。结果数值一致。这是聚合报告审计，不是对未上传私有数据的独立重放。

7 月：Joint 五个时距均劣于 Control。10 月：Joint 改善 Control，但未追平 Equal。两类失败不可混同。

60 min 的 pooled 优势只有 0.055223 A（0.211249%），且仅 1、4 月胜 Equal，7、10 月仍退化。不能宣称已稳定修复 turnover。120/240 min pooled 均差于 Equal。

当前 status 没有日级配对损失、local-hour 分解、相关特征支持度或逐点误差。不能推出统计显著性、具体特征原因或 07:00/09:00 修复结论。每 horizon 5,075 条预测，合并为 25,375 个 origin-horizon 记录，不可视为独立样本。

## 6. 下一步

按照冻结 MIXED 规则，仅分析失败来源。第一层月度/时距分析已完成，不需要重跑获得。

若进一步实现只读诊断，应单独 PR/CI，并限制在既有 R1 prediction cache。完整报告四月×五时距，区分 Joint-Control 与 Joint-Equal 的日级、小时级误差差值；不得靠筛日期、筛时距或事后拼接 S1/R1 改写结果。当前未交付新的 launcher。

Feature-support 检查需要额外 processed 输入，不能把 prediction-only cache 当成含特征的数据源；新增访问范围应明确提出。

## 7. 文档身份勘误

R1 protocol 和旧台账正文中的 7 月 SHA 转录为 62 位，缺少 `c4`；事前机器配置 `code/configs/acn_jpl_development_experts_2019.yaml`、原 launcher 和本次 status 一致使用完整 64 位值：

`9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2`

此处明确记录正文转录错误；不修改冻结 protocol、机器配置、数据或实验判据。不能将旧正文的无效 62 位字符串重新用作运行校验值。

## 8. 后续脚本的固定运行要求

用户要求 PowerShell 可见粗粒度进度。后续耗时脚本应显示阶段、月份/时距/arm、完成数/总数，实时 flush/stream，最终 JSON 与进度分流，并记录阶段起止和实际耗时。长步骤可输出心跳，但不能把心跳冒充已完成训练。

本机 RTX 5080 应在已批准模型/后端支持 GPU 时使用；启动时明确输出实际设备与 CPU 回退原因，不为使用 GPU 而替换冻结学习器。PowerShell 命令单行。当前仅记录要求，没有改写已运行的 launcher。

## 9. 禁止事项与仓库维护

不访问 final holdout；不做 P1 rescue；不重跑 R1 调参、筛 pair、更换相关估计器、clipping/calibration；不删除日期或记录；不使用未来真实组成；MIXED 不授权 Deep Sets/Set Transformer/MoE；不清理历史 worktree、失败 status 或私有缓存。

Issue #29、CURRENT_STATUS、HANDOFF、实验台账、开源台账与 outcome 应同步。所有后续诊断或代码修改须单独记录其范围、PR、CI 和执行身份，不能覆盖正式 R1 结果。
