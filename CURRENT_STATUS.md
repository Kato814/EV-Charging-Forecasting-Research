# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新日期：2026-09-12。本文件是当前状态唯一入口。历史证据见 [实验台账](docs/EXPERIMENT_LEDGER.md)，[P1 outcome](docs/JPL_P1_MECHANISM_PROBE_OUTCOME_20260912.md)，[P1-A post-mortem](docs/JPL_P1_A_POSTMORTEM_OUTCOME_20260912.md)，[post-P1 方法筛选](docs/JPL_POST_P1_METHOD_SCREENING_20260912.md)，[R1 冻结协议](docs/JPL_JOINT_SESSION_STATE_PROBE_PROTOCOL_20260912.md)，[R1 outcome](docs/JPL_R1_JOINT_STATE_OUTCOME_20260912.md)，接管规则见 [HANDOFF](HANDOFF.md)。

**当前结论：S1 保持 `MIXED_STRUCTURED_SIGNAL`；P1 已 `STOP_MECHANISM_ROUTE` 且关闭；R1 正式开发集运行已 COMPLETE，550 次拟合，按冻结判据审计为 `MIXED_JOINT_STATE_SIGNAL`。当前仅进入失败来源分析，不重跑、不调参、不升级集合网络。final holdout 2019-03/06/09/12 继续封存。**

## 1. 当前阶段

| 项目 | 当前状态 |
| --- | --- |
| 当前 Issue | #29 |
| 开发集 | 2019-01 / 04 / 07 / 10 |
| final holdout | 2019-03 / 06 / 09 / 12，禁止访问 |
| 预测目标 | `station_current_mean_a`，单位 A |
| S1 | `MIXED_STRUCTURED_SIGNAL` |
| P1 | `STOP_MECHANISM_ROUTE`，post-mortem 已关闭 |
| R1 protocol | PR #61，结果前冻结 |
| R1 implementation | PR #62，CI PASS + merged |
| R1 正式运行 | COMPLETE，550 fits |
| R1 正式结论 | **`MIXED_JOINT_STATE_SIGNAL`** |
| 当前允许动作 | **失败来源分析；当前 status 的月度/时距分解已完成** |

## 2. R1 结果

| 模型 | Pooled MAE (A) |
| --- | ---: |
| M2 | 30.164406 |
| M3 | 29.190188 |
| Equal | 28.917286 |
| S1 | 28.594882 |
| R1-Control | 29.192882 |
| R1-Joint | 29.039978 |

Joint 比 Control 改善 0.523773%，但比 Equal 退化 0.424285%。对 Control 为 4/5 horizon wins、3/4 month wins；对 Equal 为 3/5、2/4。60 min：Joint 26.086069 A，Equal 26.141292 A，优势仅 0.211249%。最大 horizon 退化为 1.110700%。

八项 PASS 条件通过六项，失败的是 pooled 优于 Equal 和至少 3/4 月优于 Equal。MIXED 判据成立，STOP 判据未触发；不能改写为 PASS。

## 3. 已完成的第一层失败分析

- **7 月：**Joint 五个时距均差于 Control，表示增量本身存在不稳定性。
- **10 月：**Joint pooled 优于 Control，但仍明显差于 Equal，表示增益不足以补偿原有基线差距。
- **60 min：**仅 1、4 月优于 Equal；7、10 月仍退化。不能声称已稳定修复 turnover。
- **120/240 min：**pooled 均差于 Equal。

当前 JSON 不含日级配对损失、小时级结果、特征支持度或逐点尾部，不能据此判断显著性、具体物理原因或 07:00/09:00 弱点是否修复。25,375 条 pooled 记录是五个时距合并的预测记录，不是独立样本数。

## 4. R1 设计与执行身份保持不变

两条 arm 均采用 M3 311 维 raw 输入与相同 55 个 pair 位置，共 366 维。Control 在可定义位置填 0；Joint 填 pairwise-complete Pearson correlation；不可定义位置均为 NaN。采用相同 M3 horizon-specific HGB 参数、缺失模式、rolling-origin、OOS rows 与站级直接目标。

Protocol merge：`5c56ac71d6e94e6c566e88a855b4f9646eb170ea`。

Implementation reviewed head：`e01607078431141a1fccdd6a9db5f75ae561bfda`；merge：`0a2f1fc29af3fc6232534c8f6073c276dbe9122f`。

本次 status 报告 development data、baseline/S1 cache 未变化，既有 worktree 保留，holdout 未访问。此次远程审计复算了 status 中聚合指标与判据，未独立重放本机私有数据。

## 5. 当前下一步与限制

只允许按冻结 MIXED 规则分析失败来源。需要更细结果时，应另走只读诊断 PR/CI，仅使用已有 R1 prediction cache，不重新拟合。当前没有交付新的运行命令。

禁止 final holdout、R1 重跑调参、pair selection、相关系数类型更换、clipping/calibration、事后拼接 S1/R1、P1 rescue、Deep Sets / Set Transformer / MoE 升级。不得删除异常日期、历史 worktree、失败记录或私有缓存。

R1 的小幅 matched-control 收益不等于最终模型有效，也不能把低阶 Pearson 表示的局限泛化成所有集合表示无效。

## 6. 后续脚本运行体验要求

用户要求已纳入维护约束：PowerShell 显示粗粒度阶段与已完成/总拟合数；子进程进度实时输出并 flush，不与最终 JSON 混在一起；记录阶段起止与耗时；说明实际 CPU/GPU 设备。仅在批准的模型和后端支持时使用 RTX 5080，不为使用 GPU 而替换冻结模型。PowerShell 命令保持单行。

当前 status 没有起止/耗时字段，不能据此反推出精确运行时长。此处记录要求，不代表已完成 progress/GPU 代码改造。
