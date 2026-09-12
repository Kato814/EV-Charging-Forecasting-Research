# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新日期：2026-09-12。当前状态以本文件为入口。科学依据见 [R1 冻结协议](docs/JPL_JOINT_SESSION_STATE_PROBE_PROTOCOL_20260912.md)、[R1 outcome](docs/JPL_R1_JOINT_STATE_OUTCOME_20260912.md)、[实验台账](docs/EXPERIMENT_LEDGER.md)、[HANDOFF](HANDOFF.md)。诊断范围见 [R1 MIXED 只读诊断方案](docs/JPL_R1_MIXED_DIAGNOSTIC_PLAN_20260912.md)，本次工程失败及下一步见 [身份校验失败台账](docs/JPL_R1_DIAGNOSTIC_IDENTITY_FAILURE_20260912.md)。

**S1 保持 MIXED_STRUCTURED_SIGNAL；P1 保持 STOP_MECHANISM_ROUTE 且已关闭；R1 正式运行 COMPLETE、550 fits、MIXED_JOINT_STATE_SIGNAL。随后 R1 只读诊断 v1 在代码身份校验阶段 INCOMPLETE / IMPLEMENTATION_DRIFT，尚未产生日级/小时级结果。final holdout 2019-03/06/09/12 继续封存。**

## 1. 当前唯一下一步

不直接重跑原诊断，不修改 SHA 来放行。独立身份预检代码通过 PR/CI 并发布后，运行 `evcf_r1_identity_preflight_v1.py --authorize-r1-identity-check`，只上传 `evcf_r1_identity_preflight_status_*.json`。预检仅检查已创建的 v1 代码工作树及两个固定代码/参考文件，不打开 R1 private cache，不创建 worktree，不联网，不导入诊断/训练模块。

原失败只记录通用 IMPLEMENTATION_DRIFT。仓库原始代码和 reference 的 SHA 已与发布 pin 核对一致，但本机具体哪项不一致仍未知；不能把原因直接说成 CRLF 或缓存损坏。预检 COMPLETE 只表示身份信息采集完成，不表示原统计诊断完成。

| 项目 | 状态 |
| --- | --- |
| 当前 Issue | #29 |
| 目标 | station_current_mean_a，单位 A |
| 开发月 | 2019-01 / 04 / 07 / 10 |
| final holdout | 2019-03 / 06 / 09 / 12，禁止访问 |
| R1 原始训练 | COMPLETE，550 fits，不重复 |
| R1 科学结论 | MIXED_JOINT_STATE_SIGNAL，不改变 |
| 只读诊断 v1 | INCOMPLETE，代码身份检查未通过；耗时约 3.45 s |
| 日级/小时级诊断结果 | 尚未产生 |
| 下一步拟合/缓存访问 | 0 / 禁止；仅代码身份采集 |

## 2. 已接受 R1 结果

| 模型 | Pooled MAE (A) |
| --- | ---: |
| M2 | 30.164406 |
| M3 | 29.190188 |
| Equal | 28.917286 |
| S1 | 28.594882 |
| R1-Control | 29.192882 |
| R1-Joint | 29.039978 |

Joint 对 Control 改善 0.523773%，对 Equal 退化 0.424285%。对 Control 为 4/5 时距、3/4 月改善；对 Equal 为 3/5、2/4。60 min 优势仅 0.055223 A。八项 PASS 条件通过六项，失败的是总体优于 Equal 和至少 3/4 月优于 Equal，因此保持 MIXED。

已完成聚合分解：7 月 Joint 所有时距差于 Control；10 月虽改善 Control，仍落后 Equal；60 min 仅 1、4 月胜 Equal；120/240 min 总体落后 Equal。不支持直接升级集合网络，也不证明所有集合表示无效。

## 3. 保留的只读分析范围（身份故障关闭后）

R1 cache manifest：`56178b6eac582a7ed844d6f94324a6947580e0f9a42e95cb9307fd78adecfd0f`。

原计划完整报告四月×五时距的 Joint-Control、Joint-Equal 日级/小时级配对绝对误差；正值表示 Joint 更差。空格保留 null，按日与按小时汇总必须还原原指标。25,375 条记录包含同一 issue time 的五个时距，不视为独立样本；不计算显著性，不自动判定物理原因，不检查缺失的原特征支持度。该计划本轮没有运行。

## 4. 执行身份与历史证据

R1 protocol：PR #61，merge `5c56ac71d6e94e6c566e88a855b4f9646eb170ea`。

R1 model：PR #62，reviewed head `e01607078431141a1fccdd6a9db5f75ae561bfda`；merge `0a2f1fc29af3fc6232534c8f6073c276dbe9122f`。

R1 outcome：PR #64，merge `a1c97ce425d4d2fb84c4582fb6a0d9eb2588878b`。这是聚合 status 审计，不是本机缓存独立复放。

只读诊断：PR #65，reviewed head `dd05258bf44d0a71773b6522ef6fb039831c77f1`；merge `f8d23749ec792d8cf35199e3a32436d22c17f003`。v1 launcher SHA：`784752eb1db8bfd22c77c954224f4c489faa717e0db0c61e880028dcb60273bc`。上述源代码 pin 不改。

历史保留：[P1 outcome](docs/JPL_P1_MECHANISM_PROBE_OUTCOME_20260912.md)、[P1-A post-mortem](docs/JPL_P1_A_POSTMORTEM_OUTCOME_20260912.md)、[方法筛选](docs/JPL_POST_P1_METHOD_SCREENING_20260912.md)。旧筛选建议不授权启动新模型。

## 5. 保护与运行体验

保留失败 JSON、刚创建的代码 worktree、所有历史 worktree 及 private cache。null 完整性字段表示尚未复核，不解释为已损坏。禁止清理、reset/clean/stash/force push。禁止 R1 调参、筛 pair、更换相关估计器、clipping/calibration、事后拼接模型、P1 rescue、未经授权的 Deep Sets/Set Transformer/MoE。

PowerShell 命令单行；进度实时 flush，最终 JSON 分流，记录实际耗时。身份预检只用标准库/Git，不调用 GPU。后续只在批准模型与后端支持时使用 RTX 5080，不为使用 GPU 更换冻结模型。
