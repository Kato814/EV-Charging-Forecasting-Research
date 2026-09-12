# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新日期：2026-09-12。当前状态以本文件为入口。科学依据见 [R1 冻结协议](docs/JPL_JOINT_SESSION_STATE_PROBE_PROTOCOL_20260912.md)、[R1 outcome](docs/JPL_R1_JOINT_STATE_OUTCOME_20260912.md)、[实验台账](docs/EXPERIMENT_LEDGER.md)、[HANDOFF](HANDOFF.md)。当前执行细则及本步审计台账见 [R1 MIXED 只读诊断方案](docs/JPL_R1_MIXED_DIAGNOSTIC_PLAN_20260912.md)。

**S1 保持 `MIXED_STRUCTURED_SIGNAL`；P1 保持 `STOP_MECHANISM_ROUTE` 且已关闭；R1 正式运行 COMPLETE、550 fits、`MIXED_JOINT_STATE_SIGNAL`。目前推进的是只读失败分析，不是新一轮训练。final holdout 2019-03/06/09/12 继续封存。**

## 1. 当前唯一下一步

完成独立诊断代码的 PR/CI 后，运行绑定该 CI-passed reviewed head 的 `evcf_r1_mixed_diagnostic_launcher_v1.py`，只上传 `evcf_r1_mixed_diagnostic_status_*.json`。代码尚未通过 CI、尚未合并或 launcher 尚未绑定正式版本时，不运行模板。

诊断代码已实现缓存身份核验、已接受指标复算、日级/小时级配对损失、跨月小时方向一致性和末次完整性检查。真实诊断结果仍待用户本机执行；助手容器测试使用合成数据，不替代真实结果。

| 项目 | 状态 |
| --- | --- |
| 当前 Issue | #29 |
| 目标 | `station_current_mean_a`，单位 A |
| 开发月 | 2019-01 / 04 / 07 / 10 |
| final holdout | 2019-03 / 06 / 09 / 12，禁止访问 |
| R1 原始训练 | COMPLETE，550 fits，不重复 |
| R1 科学结论 | `MIXED_JOINT_STATE_SIGNAL`，不改变 |
| 日级/小时级诊断结果 | 待本机 status，当前不作结论 |
| 本轮模型拟合 | 0 |

## 2. 已接受 R1 结果

| 模型 | Pooled MAE (A) |
| --- | ---: |
| M2 | 30.164406 |
| M3 | 29.190188 |
| Equal | 28.917286 |
| S1 | 28.594882 |
| R1-Control | 29.192882 |
| R1-Joint | 29.039978 |

Joint 对 Control 改善 0.523773%，对 Equal 退化 0.424285%。对 Control 为 4/5 个时距、3/4 个月改善；对 Equal 为 3/5、2/4。60 min 的优势仅 0.055223 A。八项 PASS 条件通过六项，失败的是总体优于 Equal 和至少 3/4 月优于 Equal，因此保持 MIXED。

已完成的聚合分解：7 月 Joint 在所有时距差于 Control；10 月虽改善 Control，仍落后于 Equal；60 min 仅 1、4 月胜 Equal；120/240 min 总体落后 Equal。这些结果不支持直接升级集合网络，也不能将低阶 Pearson 表示的局限解释为所有集合表示无效。

## 3. 只读诊断的范围

仅读取已有 R1 prediction cache。manifest SHA256：

`56178b6eac582a7ed844d6f94324a6947580e0f9a42e95cb9307fd78adecfd0f`

四个月 × 五个时距全部保留，分别报告 Joint-Control、Joint-Equal 的日级/小时级绝对误差差值。正值表示 Joint 更差。完整输出 24 小时格；空格保留 null，不填成零误差。按日与按小时的汇总必须还原原指标。

不读取 raw/interim/processed、不重新拟合、不读取 P1/baseline/S1 缓存目录、不修改任何输入。仅从 R1 缓存中已有的参照预测复算指标。新代码获取只允许 Git fetch，不下载数据。

25,375 条记录包含同一 issue time 的五个时距，不视为独立样本。诊断不计算显著性检验，不自动判定物理原因，不检查未提供的特征支持度，不改写 MIXED。07:00/09:00 仅是完整小时表的描述性切片，不是新选模标准。

## 4. 执行身份与历史证据

R1 protocol：PR #61，merge `5c56ac71d6e94e6c566e88a855b4f9646eb170ea`。

R1 model：PR #62，reviewed head `e01607078431141a1fccdd6a9db5f75ae561bfda`；merge `0a2f1fc29af3fc6232534c8f6073c276dbe9122f`。

R1 outcome：PR #64 全量 CI 通过，merge `a1c97ce425d4d2fb84c4582fb6a0d9eb2588878b`。该 PR 是聚合 status 审计，不是本机缓存独立复放。后续诊断使用独立代码身份，不能覆盖原 R1 结果。

历史保留：[P1 outcome](docs/JPL_P1_MECHANISM_PROBE_OUTCOME_20260912.md)、[P1-A post-mortem](docs/JPL_P1_A_POSTMORTEM_OUTCOME_20260912.md)、[方法筛选](docs/JPL_POST_P1_METHOD_SCREENING_20260912.md)。旧开源筛选建议不是启动新模型的授权；当前 R1 MIXED 限制优先。

## 5. 运行体验与保护

新诊断 launcher 实时输出阶段、完成文件/单元数、实际耗时，并将进度与最终 JSON 分离；长步骤显示 RUNNING 心跳，不伪装成已完成进度。设备明确为 CPU 数组统计，GPU 未调用，本轮没有 GPU 模型。以后仅在批准模型和后端支持时使用 RTX 5080，不为用 GPU 而替换冻结模型。

PowerShell 命令单行。INCOMPLETE 后不自动重跑。保留历史 worktree、失败 status 与 private cache；禁止清理、reset/clean/stash/force push。禁止 R1 调参、筛 pair、更换相关估计器、clipping/calibration、事后拼接模型、P1 rescue 或未授权的 Deep Sets/Set Transformer/MoE。
