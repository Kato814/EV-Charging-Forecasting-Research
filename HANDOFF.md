# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-12。先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[本次代码身份故障台账](docs/JPL_R1_DIAGNOSTIC_IDENTITY_FAILURE_20260912.md)，再读 [R1 outcome](docs/JPL_R1_JOINT_STATE_OUTCOME_20260912.md)、[R1 protocol](docs/JPL_JOINT_SESSION_STATE_PROBE_PROTOCOL_20260912.md)、[只读诊断方案](docs/JPL_R1_MIXED_DIAGNOSTIC_PLAN_20260912.md)、[实验台账](docs/EXPERIMENT_LEDGER.md)。历史方法筛选、开源台账和旧入口不是新训练授权。

## 1. 当前结论与故障

S1=MIXED_STRUCTURED_SIGNAL；P1=STOP_MECHANISM_ROUTE 且 post-mortem 关闭；R1 正式训练 COMPLETE、550 fits、MIXED_JOINT_STATE_SIGNAL。

后续只读诊断 v1 的用户回传 status 为 INCOMPLETE / IMPLEMENTATION_DRIFT，耗时 3.452330800006166 秒，在 RESOLVE_REVIEWED_CODE 阶段停止。诊断代码 worktree 已创建，应保留。model_fit_attempted=false、fit_count=0；raw/interim/processed 和 holdout 未访问。没有缓存定位、READ_VERIFY 或 ANALYZE 阶段，也没有日级/小时级结果。

完整性字段 null 表示后检查未执行，不是缓存或 worktree 损坏的证据。不得把本次启动故障当成 R1 科学失败，不修改已有 MIXED。

## 2. 下一步（替代原直接运行诊断指令）

只运行经过独立 PR/CI 后发布的 `evcf_r1_identity_preflight_v1.py`，参数 `--authorize-r1-identity-check`。只上传 `evcf_r1_identity_preflight_status_*.json`。

它检查现存 `-jpl-r1-mixed-diagnostic-code-v1` 代码 worktree 的 HEAD、两个固定文件的本地字节与 SHA、换行/BOM计数、原始 Git blob、二进制和原版文本模式 git show 输出指纹。公共输出无绝对路径、文件内容或私有预测。

预检不创建或修改 worktree、不联网、不打开 R1/baseline/S1/P1 缓存、不导入诊断/模型、不执行训练或日级/小时级分析。COMPLETE 只表示采集完成；即便身份不匹配，也仅报告差异，不跳过检查继续执行。

审计预检结果前不重跑原诊断，也不发布猜测性修复。若当前身份全部一致，应明确此前原因尚未复现，而不是臆断问题已修好。

## 3. 已核实的发布身份

原诊断 PR #65 reviewed head：`dd05258bf44d0a71773b6522ef6fb039831c77f1`；merge：`f8d23749ec792d8cf35199e3a32436d22c17f003`。

原诊断 launcher SHA：`784752eb1db8bfd22c77c954224f4c489faa717e0db0c61e880028dcb60273bc`，与失败 status 一致。

诊断模块 SHA256：`f552ce48f5a831064cff77e88ddccc26f76466697a0697860d5692bc1a1bbfc9`；Git blob：`ce4030e37cc1fb261847e0e18636ce7582c9129c`。

Aggregate reference SHA256：`0c8075eb05c2405769862db72012076fc2f5a019c85a260d5b0315809520c703`；Git blob：`34bea59010a808719e84d72dc21950c51eec751d`。

主控经 GitHub 读取并核对两个文件的内容与 Git blob SHA/SHA256；两项 pin 均正确。原校验已对本地 CRLF 做 LF 规范化。仅凭通用 IMPLEMENTATION_DRIFT 不能确定哪项检查失败，不可直接归因为 CRLF、Git 输出或本地文件损坏。

## 4. 冻结数据与历史身份

目标 station_current_mean_a，单位 A。Development=2019-01/04/07/10；final holdout=2019-03/06/09/12，继续禁止访问。

R1 cache manifest：`56178b6eac582a7ed844d6f94324a6947580e0f9a42e95cb9307fd78adecfd0f`。
Baseline manifest：`2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd`。
S1 manifest：`562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1`。
P1 manifest：`df222c4731f3c3192735a6df2ccd2f692f1ea6d640a7954706e7bca17f51580f`。

本次身份预检不读取这些缓存。

R1 protocol：PR #61，merge `5c56ac71d6e94e6c566e88a855b4f9646eb170ea`。
R1 model：PR #62，head `e01607078431141a1fccdd6a9db5f75ae561bfda`，merge `0a2f1fc29af3fc6232534c8f6073c276dbe9122f`。
R1 outcome：PR #64，merge `a1c97ce425d4d2fb84c4582fb6a0d9eb2588878b`。
原训练 status SHA：`7e37ca253452ac246445aea7fcd2d30179c3648168c911c28062ac54df417ec2`。

## 5. 科学结果与解释边界

Pooled MAE：M2=30.164406、M3=29.190188、Equal=28.917286、S1=28.594882、R1-Control=29.192882、R1-Joint=29.039978 A。

Joint 对 Control 改善 0.523773%，对 Equal 退化 0.424285%；分别为 4/5、3/4 和 3/5、2/4 的时距/月胜数。60 min 只优于 Equal 0.055223 A。八项 PASS 通过六项，总体优于 Equal 与至少 3/4 月优于 Equal 两项失败。

7 月所有时距 Joint 劣于 Control；10 月改善 Control 但未追平 Equal。当前没有日级/小时级细分结果、显著性或特征归因证据。25,375 条记录重复包含 5,075 个 issue times，不视为独立样本。

原 matched design、Pearson特征、HGB参数、rolling-origin、阈值均不改。身份故障关闭后才恢复原 prediction-cache-only 诊断计划，完整报告四月×五时距的 Joint-Control / Joint-Equal 配对损失，不挑日期、不拼接模型。

## 6. 保护与交付要求

保留所有历史 worktree、失败 JSON 和 private cache；禁止 reset/clean/stash/force push、R1 调参筛 pair、更换相关估计器、clipping/calibration、P1 rescue、未来组成输入、未经授权的 Deep Sets/Set Transformer/MoE。

旧 7 月正文 SHA 的 62 位转录勘误继续保留，正确机器值为 `9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2`，不修改冻结协议或数据。

命令保持 PowerShell 单行。实时进度和实际耗时明确输出。本次标准库/Git身份检查不调用GPU；后续仅在批准模型和后端适用时使用RTX 5080。原失败及新增预检分别记录，科学结果与工程启动问题不得混同。
