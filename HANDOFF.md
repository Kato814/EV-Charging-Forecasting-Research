# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-12。先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R1 outcome](docs/JPL_R1_JOINT_STATE_OUTCOME_20260912.md)、[R1 protocol](docs/JPL_JOINT_SESSION_STATE_PROBE_PROTOCOL_20260912.md)、[当前只读诊断方案及本步台账](docs/JPL_R1_MIXED_DIAGNOSTIC_PLAN_20260912.md)。历史依据见 [实验台账](docs/EXPERIMENT_LEDGER.md)、[P1 outcome](docs/JPL_P1_MECHANISM_PROBE_OUTCOME_20260912.md)、[P1-A post-mortem](docs/JPL_P1_A_POSTMORTEM_OUTCOME_20260912.md)、[方法筛选](docs/JPL_POST_P1_METHOD_SCREENING_20260912.md) 与 [开源台账](docs/OPEN_SOURCE_IDEA_LEDGER.md)。旧筛选建议不是模型训练授权。

## 1. 接管结论

S1 保持 `MIXED_STRUCTURED_SIGNAL`。P1 已 `STOP_MECHANISM_ROUTE`，post-mortem 关闭，不再 rescue。R1 正式开发集运行已 COMPLETE、550 fits、`MIXED_JOINT_STATE_SIGNAL`，不能再说 NOT STARTED 或 PASS。

当前工作是用户授权推进的 R1 MIXED 失败来源分析。代码实现限定为已有 R1 prediction cache 的日级、小时级配对损失诊断。**真实诊断尚待用户本机 status；助手只用合成缓存测试代码。**实现须经过独立 PR、全量 CI、合并，再发布绑定 reviewed head 的 launcher。不得重新训练 R1，不启动 Deep Sets / Set Transformer / MoE。

## 2. 冻结数据、缓存与执行身份

目标 `station_current_mean_a`，单位 A。Development：2019-01/04/07/10。Final holdout：2019-03/06/09/12，禁止访问。

R1 只读输入的 private manifest SHA256：

`56178b6eac582a7ed844d6f94324a6947580e0f9a42e95cb9307fd78adecfd0f`

R1 缓存包含二十个 month-horizon NPZ 与 private_manifest.json。缓存中已经保存 M2/M3/Equal/S1/Control/Joint 的预测和公共时间索引；不需要打开各 baseline/S1 原缓存目录。

历史身份继续保留：
- Baseline manifest：`2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd`。
- S1 manifest：`562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1`。
- P1 manifest：`df222c4731f3c3192735a6df2ccd2f692f1ea6d640a7954706e7bca17f51580f`，不是本轮输入。
- R1 protocol：PR #61，merge `5c56ac71d6e94e6c566e88a855b4f9646eb170ea`。
- R1 implementation：PR #62，reviewed head `e01607078431141a1fccdd6a9db5f75ae561bfda`，merge `0a2f1fc29af3fc6232534c8f6073c276dbe9122f`。
- R1 launcher v1 SHA256：`4f38e5e924c58142d15ce3a0a3965c33663fa028347d30e52fdcbf02bed830b4`。保留为历史，不为增加日志而重跑。
- R1 outcome audit：PR #64 已全量 CI 通过并合并，merge `a1c97ce425d4d2fb84c4582fb6a0d9eb2588878b`。

原 status SHA256 为 `7e37ca253452ac246445aea7fcd2d30179c3648168c911c28062ac54df417ec2`。仓库新增 reference 仅提取二十个 cell 的 n/MAE 与所有总体指标，不是上传原 private status 或逐行预测。

## 3. 冻结 R1 实验没有改变

两条 arm 均用 M3 的 311 维 raw features，加 55 个 pair 位置。可定义处 Control=0、Joint=pairwise-complete Pearson correlation；不可定义处均为 NaN。定义要求至少两个共同观测会话且两字段正有限方差。两者宽度、缺失模式、冻结 HGB 参数、rolling-origin、OOS rows 与直接站级目标一致。

主比较 Joint vs Control；外部参照 M2/M3/Equal/S1。没有 existing/arrival 目标分解，没有未来真实组成输入。

## 4. 已接受 R1 结果

| 模型 | Pooled MAE (A) |
| --- | ---: |
| M2 | 30.164406 |
| M3 | 29.190188 |
| Equal | 28.917286 |
| S1 | 28.594882 |
| R1-Control | 29.192882 |
| R1-Joint | 29.039978 |

Joint 对 Control 改善 0.523773%，对 Equal 退化 0.424285%。对 Control 为 4/5 horizon wins、3/4 month wins；对 Equal 为 3/5、2/4。60 min Joint 26.086069 A 对 Equal 26.141292 A，仅改善 0.055223 A。最大时距退化 1.110700%。PASS 八项中六项通过；总体优于 Equal、至少 3/4 月优于 Equal 两项失败，正式保持 MIXED。

第一层 status 分析已完成：7 月 Joint 所有时距劣于 Control；10 月改善 Control 但仍差于 Equal；60 min 仅 1、4 月优于 Equal；120/240 min 总体差于 Equal。不要重新训练来获取这些已有表。

PR #64 是聚合 status 的数值和冻结判据审计，不是对本机私有缓存的独立复放。原 status 报告 holdout 未访问、development data 与 baseline/S1 cache 未变、worktree 保留。

## 5. 当前只读诊断回答什么

对每条已存在预测记录计算：

`delta = abs(Joint - truth) - abs(comparator - truth)`，comparator 分别为 Control、Equal。正值表示 Joint 更差。

完整保留四月×五时距，输出全部观测日、全部 24 个 local-hour 格；空格 n=0、误差 null。分别核对日级与小时级计数及损失总和还原 month-horizon 汇总。

报告日级胜/负/平、日均/中位损失差、正向净日级误差增量在最差 1/3 天的集中程度，并报告每个 horizon-hour 的跨月方向一致性。目的在于区分 7 月联合特征增量退化与 10 月强基线差距，而不是挑选有利日期或拼接预测模型。

先按精确 manifest/file hashes 校验输入，用已哈希的内存字节载入 NPZ（pickle 禁用），检查维度、有限值、时间索引、日期边界、跨时距行一致性和 Equal 重建；复算二十 cell 的 n/MAE 与六模型总体 MAE/RMSE/WAPE/负预测数；分析后重新核验全部缓存。

本轮不读取 raw/interim/processed、不读取 P1/baseline/S1 缓存目录、不访问 holdout、不拟合模型、不下载数据。仅 Git fetch 可用于获取固定 reviewed code。原 R1 private cache 只读。

## 6. 解释边界

25,375 条 origin-horizon 记录对应重复出现的 5,075 个 issue times，不视为独立样本。本轮不输出 p 值、置信区间、因果结论或新决策。07:00/09:00 仅描述完整小时表，不变成新 gate 或停止规则。

缓存没有原输入特征，无法做 feature-support 或重要特征归因。不得将其当成有特征的数据源。低阶 Pearson 表示表现不稳也不等于所有集合表示无效。诊断结果不能自动改变 MIXED 或授权更大网络。

## 7. 本机运行与交付

发布后的唯一 launcher：`evcf_r1_mixed_diagnostic_launcher_v1.py`。使用原 `evcf-gate1-pilot` 环境，显式授权参数 `--authorize-r1-diagnostic`，PowerShell 单行命令。

仓库中的 `scripts/evcf_r1_mixed_diagnostic_launcher_template.py` 不是可执行发布版。发布时只替换 reviewed-head、PR number、core SHA256 三个占位符，其余内容须与 CI 测试版本一致。正式 head/merge/launcher SHA 记在对应 PR 和 Issue #29。

launcher 创建或核验专用 detached code worktree，不切换已有 worktree；精确绑定代码内容和 aggregate reference。仅读取已有外置 R1-run 目录下单层候选 manifest，按 hash 选择唯一缓存，不能递归扫描其他数据区。

进度实时输出并 flush：环境/工作树检查、版本解析、缓存定位、校验文件数、month-horizon 分析数、末次完整性检查。最终 JSON 单独写入 launcher 所在的仓库外目录。记录 UTC 起止、阶段及总体实际耗时；30 秒心跳仅表示仍运行，不当作训练进度。

DEVICE=CPU、GPU_USED=false，原因是本轮为 NumPy 数组统计且模型拟合数为零。后续仅在批准模型/后端适用时启用 RTX 5080，不更换冻结学习器来强行用 GPU。

结束后只上传 `evcf_r1_mixed_diagnostic_status_*.json`，不上传 NPZ。INCOMPLETE 后先审计 failure code，不自动重跑；所有失败记录保留。

## 8. 文档身份勘误保留

旧 R1 protocol/台账正文的 7 月 SHA 转录为 62 位，缺少 `c4`；原机器配置、launcher 与已接受 status 一致使用完整值：

`9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2`

这是一项已记录的正文勘误，不修改冻结协议、机器配置、数据或判据。本轮 prediction-only 诊断不需要 processed snapshot。

## 9. 禁止事项与维护

不访问 final holdout；不做 P1 rescue；不重跑 R1 调参、筛 pair、更换相关估计器、clipping/calibration；不删日期；不事后拼接 S1/R1；不使用未来真实组成；不启动 Deep Sets/Set Transformer/MoE；不清理历史 worktree、失败 status 或 private cache。

CURRENT_STATUS、HANDOFF、R1 outcome、实验台账与本轮诊断方案构成审计链。新诊断只有独立 CI/代码身份，不覆盖正式 R1 结果。旧路线图、旧开源建议或开放 Issue 均不替代当前授权。
