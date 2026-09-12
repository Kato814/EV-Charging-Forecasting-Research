# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-12。先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[本次R1诊断结果与审计台账](docs/JPL_R1_MIXED_DIAGNOSTIC_OUTCOME_20260912.md)，再读 [R1原结果](docs/JPL_R1_JOINT_STATE_OUTCOME_20260912.md)、[冻结协议](docs/JPL_JOINT_SESSION_STATE_PROBE_PROTOCOL_20260912.md)、[诊断方案](docs/JPL_R1_MIXED_DIAGNOSTIC_PLAN_20260912.md)、[历史实验台账](docs/EXPERIMENT_LEDGER.md)。旧开源候选、旧launcher与历史入口不是新训练授权。

## 1. 接管后的当前任务边界

S1=MIXED_STRUCTURED_SIGNAL；P1=STOP_MECHANISM_ROUTE且post-mortem已关闭；R1原训练COMPLETE、550fits、MIXED_JOINT_STATE_SIGNAL。

**R1既定日级/小时级只读诊断现已COMPLETE并完成聚合算术审计。不要再次要求用户跑身份预检、550次训练或同一统计。当前没有新的本机命令；没有新模型或holdout访问授权。**

下一步只能先依据现有证据综合评议候选假设。任何新增输入读取、特征支持度诊断、建模或训练，均须另行明确范围并取得独立协议授权。不能把“诊断完成”解释为R1 PASS或自动进入Deep Sets/Set Transformer/MoE。本轮也不将R1改成STOP。

## 2. 最新实际运行及审计

输入status：`evcf_r1_mixed_diagnostic_status_20260912T140907656088Z.json`。
SHA256：`84a424d8cb34cd8e7a82a87d3d8cf3c713e6d9ef5be162f8728e38669fb2cbc3`。

Wrapper/core均COMPLETE、reason_code=null；耗时2.494680600007996s。0fits；CPU数组统计、GPU未调用。无联网、raw/interim/processed、其他模型缓存或final-holdout访问，无clipping/calibration/删行/清理。R1 cache前后hash不变，现存工作树HEAD和受跟踪状态前后不变；没有创建新worktree。代码/reference前后本地与原始Git blob指纹均通过。

主控完整解析上传聚合JSON，核对20个month-horizon、275个day-horizon、480个month-horizon-hour、120个跨月小时汇总；重算配对损失、各分区计数/MAE/损失和/胜负数、日级中位数分位数及集中度、全部跨月小时一致性，核对原R1 status和冻结判据，全部通过。这不是主控独立读取本机NPZ或重新拟合。

原始25,375条预测记录重复包含5,075个issue times、55个当地日期，不能作为独立样本。没有计算显著性，没有原特征/模型系数或physical cause证据。

## 3. 主要科学认识

原pooled MAE保持：M2=30.164406、M3=29.190188、Equal=28.917286、S1=28.594882、Control=29.192882、Joint=29.039978 A。

Joint对Control改善0.523773%，对Equal退化0.424285%；八项PASS要求六项满足，正式MIXED不变。

- 七月Joint对Control五时距pooled均退化；15/30/60/120/240min分别9/7/8/7/11天退化。五时距同日合计9/14天退化，日级中位差+0.480704A。不是一个灾难日期可以解释掉的现象。
- 十月120min对Control改善1.676075A、11/14天胜，但对Equal退化1.557724A、8/14天负；240min对Control/Equal分别10/14、9/14天负。全时距同日汇总8/14天胜Equal却pooled退化0.697471A，较大损失日期权重不能忽略。
- 60min对Equal仅改善0.055223A；07时2/4月胜，09时3/4月负，不能宣布稳定修复turnover。
- 240min只有24/55天胜Control、21/55天胜Equal，微小均值优势不等于广泛稳定获益。

集中度分母为所有退化日的正向净日级损失增量之和，不是总误差或整体净差。十月22/21/28日占该分母81.3239%，只是描述性证据，不能删日期或改预测。完整20格与07/09表见本步outcome；不得只挑有利小时形成新门控。

当前低阶Pearson增强不直接提升为最终方法，但也不证明所有联合状态/集合表示无效。冻结MIXED规则和后续明确授权优先。

## 4. 执行与输入身份

统计源码：PR #65 head `dd05258bf44d0a71773b6522ef6fb039831c77f1`；merge `f8d23749ec792d8cf35199e3a32436d22c17f003`。
核心SHA256：`f552ce48f5a831064cff77e88ddccc26f76466697a0697860d5692bc1a1bbfc9`；Git blob `ce4030e37cc1fb261847e0e18636ce7582c9129c`。
Reference SHA256：`0c8075eb05c2405769862db72012076fc2f5a019c85a260d5b0315809520c703`；Git blob `34bea59010a808719e84d72dc21950c51eec751d`。

Launcher v1.1：PR #68 head `a6efb6477041f552fdac0448b3d3ea0d89a10cfa`，merge `518baade359cb35680b40f989d355629c1a6be7e`。
发布SHA256：`b4db218f1f8f3ae22f17a8229adae62baa6a1dc22faacb22a613f57dcac41e2b`。修复launcher身份与原统计源码身份分别记录，不能互换。

R1 manifest：`56178b6eac582a7ed844d6f94324a6947580e0f9a42e95cb9307fd78adecfd0f`。
Baseline manifest：`2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd`。
S1 manifest：`562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1`。
P1 manifest：`df222c4731f3c3192735a6df2ccd2f692f1ea6d640a7954706e7bca17f51580f`，仅历史证据。

R1 protocol：PR #61 merge `5c56ac71d6e94e6c566e88a855b4f9646eb170ea`。
R1 model：PR #62 head `e01607078431141a1fccdd6a9db5f75ae561bfda`；merge `0a2f1fc29af3fc6232534c8f6073c276dbe9122f`。
R1 outcome：PR #64 merge `a1c97ce425d4d2fb84c4582fb6a0d9eb2588878b`。
原训练status SHA：`7e37ca253452ac246445aea7fcd2d30179c3648168c911c28062ac54df417ec2`。

## 5. 历史工程故障继续保留

[原失败](docs/JPL_R1_DIAGNOSTIC_IDENTITY_FAILURE_20260912.md)：v1在RESOLVE_REVIEWED_CODE报IMPLEMENTATION_DRIFT，无统计结果；null后检查值不是损坏证据。

[身份预检与修复](docs/JPL_R1_DIAGNOSTIC_BINARY_IDENTITY_REPAIR_20260912.md)：HEAD/本地/Gitblob正确，诊断模块的binary/text git show都返回128。原原因不等同文本编码错误。PR #68改用cat-file二进制对象并保留原pin后，本次确已成功。底层git-show失败原因仍未知；无需为完成本次科学分析再追查OS原因。

身份预检PR #67 head `4ba2b5599e180d01bb4e537e519dbdbfbf9112d8`，merge `52130c40b26fa955de3095d1056906222255087f`。预检status SHA `ae2d6e5d7e5e689028f2d99177b7bdd79bc6d9f265645cdb4924c551e092c2f2`。
旧诊断v1 SHA `784752eb1db8bfd22c77c954224f4c489faa717e0db0c61e880028dcb60273bc`；预检launcher SHA `88070416879a751e71dfcb7be4ff4424daab7d380615e26954296649bf55d29d`。旧文件都保留，不重跑。

## 6. 长期保护与交付

目标station_current_mean_a（A）；development=2019-01/04/07/10；final holdout=2019-03/06/09/12封存。原311+55维matched设计、Pearson定义、HGB参数、rolling-origin、OOS行与判据不变。

禁止reset/clean/stash/force push、删日期/筛pair、换相关估计器、clipping/calibration、P1 rescue、未来真实组成输入、事后拼接或未经授权的新模型训练。保留全部历史worktree、失败JSON、成功status及private cache；不提交原NPZ、private status、会话标识/凭据/绝对本地路径。

旧7月正文SHA转录勘误保留，正确机器值 `9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2`，不修改原冻结协议或数据。

PowerShell命令保持单行。耗时脚本实时flush阶段/真实完成数/耗时/设备，最终JSON分流。RTX5080仅在批准的模型后端支持时调用，不为用显卡更换冻结模型或升级环境。状态变化同轮维护CURRENT_STATUS、HANDOFF与相关结果台账；GitHub代码测试、PR合并、本机执行与科学裁决分开报告。
