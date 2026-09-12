# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-12。当前入口为本文件与 [HANDOFF](HANDOFF.md)。最新证据与本步审计台账见 [R1 MIXED 只读诊断结果](docs/JPL_R1_MIXED_DIAGNOSTIC_OUTCOME_20260912.md)；原科学判据见 [R1 冻结协议](docs/JPL_JOINT_SESSION_STATE_PROBE_PROTOCOL_20260912.md)，原结果见 [R1 outcome](docs/JPL_R1_JOINT_STATE_OUTCOME_20260912.md)，历史见 [实验台账](docs/EXPERIMENT_LEDGER.md)。

**R1 日级/小时级只读诊断现已 COMPLETE 并经聚合算术审计。启动阻塞解除，用户无需再跑身份预检、训练或同一统计。R1 仍为 MIXED_JOINT_STATE_SIGNAL；S1 仍为 MIXED_STRUCTURED_SIGNAL；P1 仍为 STOP_MECHANISM_ROUTE 且已关闭。final holdout 2019-03/06/09/12 继续封存。**

## 1. 当前状态与下一动作

本轮既定失败分析已完成。当前没有新的本机运行命令，不重跑原 R1 的550次拟合，不自动升级集合网络。下一工作只能先依据既有证据评议候选假设；任何新的数据读取、特征诊断或训练都需另行明确范围和独立协议授权。本次没有冻结新模型。

| 项目 | 状态 |
| --- | --- |
| Issue | #29 |
| 目标 | station_current_mean_a，单位 A |
| Development | 2019-01/04/07/10 |
| Final holdout | 2019-03/06/09/12，禁止访问 |
| R1 原训练 | COMPLETE，550 fits，MIXED |
| 只读诊断 v1 | 历史启动失败，保留 |
| 身份预检 | 已完成，不重复 |
| 只读诊断 v1.1 | COMPLETE，总耗时2.494681 s，0 fits |
| 日级/小时级审计 | 20个month-horizon、275个day-horizon、480个小时格、120个跨月小时汇总全部复算通过 |
| 新模型/holdout授权 | 无 |

## 2. 本次运行身份与安全检查

Status：`evcf_r1_mixed_diagnostic_status_20260912T140907656088Z.json`。
SHA256：`84a424d8cb34cd8e7a82a87d3d8cf3c713e6d9ef5be162f8728e38669fb2cbc3`。

统计继续使用 PR #65 head `dd05258bf44d0a71773b6522ef6fb039831c77f1`。Launcher v1.1 为 PR #68 head `a6efb6477041f552fdac0448b3d3ea0d89a10cfa`，merge `518baade359cb35680b40f989d355629c1a6be7e`。Launcher SHA：`b4db218f1f8f3ae22f17a8229adae62baa6a1dc22faacb22a613f57dcac41e2b`。

代码/reference在运行前后本地与Git blob指纹均通过；R1 cache前后不变；现有工作树HEAD/受跟踪状态前后不变。无新增工作树、清理、联网、raw/interim/processed或holdout访问。设备CPU，模型拟合数0。原git show返回128的底层原因仍未知，不把成功运行写成Windows/EOL原因已经证明。

## 3. 结果与新增认识

原pooled MAE：Joint=29.039978、Control=29.192882、Equal=28.917286、S1=28.594882 A。Joint对Control改善0.523773%，对Equal退化0.424285%。原八项PASS条件仅六项满足，MIXED不改。

- 七月并非单日故障：240 min有11/14天Joint差于Control；五时距同日汇总有9/14天退化。不能删掉一个日期解释掉全部问题。
- 十月120 min有11/14天Joint胜Control，但仍有8/14天输Equal。240 min同时损伤Control和Equal。全时距日级多数天胜Equal，但少数较大损失使pooled仍退化；不能说十月每天都失败。
- 60 min总体仅比Equal好0.055223 A；07时仅2/4月胜Equal，09时3/4月退化。尚无跨月稳定修复证据。
- 240 min仅24/55天胜Control、21/55天胜Equal，小幅均值增益不代表日级稳定优势。

详表、集中度定义和全部月度/时距结果见本步outcome。日级/小时级形态不是因果证明，不能从无原特征的缓存推断具体相关字段失效。

## 4. 审计范围与后续限制

本机报告还原原指标并完成输入hash复核。主控只独立复算上传JSON的聚合算术并对照原R1 status，没有远程读取用户NPZ或重新训练。25,375条origin-horizon记录对应5,075个issue times、55天，不是25,375个独立样本。本轮不计算p值/置信区间，不修改判据。

当前Pearson增强不直接提升为最终方法，不自动升级Deep Sets/Set Transformer/MoE；也不声称所有集合表示无效。禁止P1 rescue、R1调参/筛pair/换相关估计器、clipping/calibration、删日期、事后拼接、未来真实组成输入及holdout访问。

## 5. 保留与维护

保留所有历史worktree、失败status、身份预检和private cache，不做reset/clean/stash/force push。原[启动失败记录](docs/JPL_R1_DIAGNOSTIC_IDENTITY_FAILURE_20260912.md)、[修复记录](docs/JPL_R1_DIAGNOSTIC_BINARY_IDENTITY_REPAIR_20260912.md)继续保留，仅撤去其已完成步骤的当前执行含义。

PowerShell命令单行；后续耗时脚本实时flush进度、真实完成数、阶段耗时及设备。RTX5080仅在另行批准且后端支持时调用，不为启用GPU改变冻结学习器或升级环境。
