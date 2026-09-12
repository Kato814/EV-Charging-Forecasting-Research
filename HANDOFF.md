# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-12。先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[身份预检结果及 v1.1 修复](docs/JPL_R1_DIAGNOSTIC_BINARY_IDENTITY_REPAIR_20260912.md)、[原启动失败](docs/JPL_R1_DIAGNOSTIC_IDENTITY_FAILURE_20260912.md)，再读 [R1 outcome](docs/JPL_R1_JOINT_STATE_OUTCOME_20260912.md)、[R1 协议](docs/JPL_JOINT_SESSION_STATE_PROBE_PROTOCOL_20260912.md)、[只读诊断方案](docs/JPL_R1_MIXED_DIAGNOSTIC_PLAN_20260912.md) 和 [实验台账](docs/EXPERIMENT_LEDGER.md)。旧开源候选与历史入口不是新训练授权。

## 1. 当前结论

S1=MIXED_STRUCTURED_SIGNAL；P1=STOP_MECHANISM_ROUTE 且已关闭；R1 正式训练 COMPLETE、550 fits、MIXED_JOINT_STATE_SIGNAL。不要重训 R1 或将本次启动故障解释成新科学结果。

只读诊断 v1 在 RESOLVE_REVIEWED_CODE 阶段以 IMPLEMENTATION_DRIFT 停止，原失败 status 和代码 worktree 保留。其 null 后检查字段不是缓存损坏证据。

现已收到并审计身份预检 `evcf_r1_identity_preflight_status_20260912T133808491942Z.json`，SHA256=`ae2d6e5d7e5e689028f2d99177b7bdd79bc6d9f265645cdb4924c551e092c2f2`。结果 COMPLETE、约 0.411 s，无拟合、缓存/holdout访问或联网，检查的工作树状态未变。

诊断模块本地字节与固定 Git blob 都为 18029 字节且 SHA 正确；HEAD 正确、diff=0；但文本和二进制 git show 都返回 128、stdout为空。参考文件 7821 字节，全部检查通过。两个文件均无CRLF及BOM。标签 LEGACY_GIT_SHOW_TEXT_MISMATCH 太宽，不能据此声称编码出错；底层命令失败原因尚无 stderr 证据。

## 2. 当前下一步

独立修复 PR 审查、全量 CI、合并后，发布 `evcf_r1_mixed_diagnostic_launcher_v1_1.py`。发布后只执行一次原范围的 R1 prediction-cache-only 诊断，参数 `--authorize-r1-diagnostic`；只上传最新 `evcf_r1_mixed_diagnostic_status_*.json`。

v1.1 仍绑定原 PR #65 的 source HEAD、模块 SHA、reference SHA 和 cache manifest。只把 Git 对象读取替换为二进制 `git cat-file blob`；保留本地 LF 规范化 SHA 检查和精确 HEAD 检查。新增的 launcher reviewed head/PR 仅用于修复版本身份，不替代原统计代码身份。新模板只有这两个赋值占位符可在发布时替换。

仅复用已创建、已注册、HEAD 正确且 tracked-clean 的 `-jpl-r1-mixed-diagnostic-code-v1` 工作树。缺失或不一致就停止，不 fetch、不创建、切换、修复或清理工作树。无需手工 git pull 或改本机文件。

不要再重复身份预检、运行旧诊断 v1，或手改 SHA。新校验失败时报告 CORE/REFERENCE_LOCAL_SHA256_MISMATCH、BLOB_READ_FAILED、BLOB_SHA256_MISMATCH 等具体静态原因，先审计再决定。

## 3. 不变的发布与科学身份

统计源码：PR #65 head `dd05258bf44d0a71773b6522ef6fb039831c77f1`；merge `f8d23749ec792d8cf35199e3a32436d22c17f003`。

模块 SHA256：`f552ce48f5a831064cff77e88ddccc26f76466697a0697860d5692bc1a1bbfc9`；Git blob `ce4030e37cc1fb261847e0e18636ce7582c9129c`。

Reference SHA256：`0c8075eb05c2405769862db72012076fc2f5a019c85a260d5b0315809520c703`；Git blob `34bea59010a808719e84d72dc21950c51eec751d`。

R1 cache manifest：`56178b6eac582a7ed844d6f94324a6947580e0f9a42e95cb9307fd78adecfd0f`。
Baseline manifest：`2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd`。
S1 manifest：`562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1`。
P1 manifest：`df222c4731f3c3192735a6df2ccd2f692f1ea6d640a7954706e7bca17f51580f`，仅历史证据。

R1 protocol：PR #61，merge `5c56ac71d6e94e6c566e88a855b4f9646eb170ea`。
R1 model：PR #62，head `e01607078431141a1fccdd6a9db5f75ae561bfda`；merge `0a2f1fc29af3fc6232534c8f6073c276dbe9122f`。
R1 outcome：PR #64，merge `a1c97ce425d4d2fb84c4582fb6a0d9eb2588878b`。
原训练 status SHA：`7e37ca253452ac246445aea7fcd2d30179c3648168c911c28062ac54df417ec2`。
身份预检：PR #67 head `4ba2b5599e180d01bb4e537e519dbdbfbf9112d8`；merge `52130c40b26fa955de3095d1056906222255087f`。
旧诊断 launcher v1 SHA：`784752eb1db8bfd22c77c954224f4c489faa717e0db0c61e880028dcb60273bc`。
预检 launcher v1 SHA：`88070416879a751e71dfcb7be4ff4424daab7d380615e26954296649bf55d29d`。

修复 launcher 的最终 reviewed/merge 身份和 SHA 记录在修复 PR 与 Issue #29；不能把“代码提交”“CI通过”“本机故障已消失”“真实统计完成”混为一谈。

## 4. 只读统计与结论边界

目标 station_current_mean_a（A）；development=2019-01/04/07/10；final holdout=2019-03/06/09/12，始终禁止访问。

仅读取已有 R1 二十个 month-horizon NPZ 与 manifest，不读取 raw/interim/processed 或 baseline/S1/P1 缓存目录。原 PR #65 核验和统计不改：固定hash、行/日期身份、Equal重建、已接受指标还原、四月×五时距全部日级与24小时配对损失、末次完整性复核。所有输入只读，无 fit/refit。

科学结果仍是 Joint MAE 29.039978 A、Control 29.192882 A、Equal 28.917286 A、S1 28.594882 A。Joint 对 Control 改善0.523773%，对 Equal 退化0.424285%；60min优势仅0.055223 A，八项PASS通过六项，仍为MIXED。

7月全部时距Joint劣于Control，10月改善Control但未追平Equal。真实日级/小时级细分仍未产生。25,375条预测重复包含5,075个issue times，不是独立样本；本轮不计算p值、不作因果归因、不读特征、不自动授权新模型。

## 5. 长期保护与交付

保留旧launcher、失败JSON、身份预检和全部历史worktree/cache。禁止reset/clean/stash/force push、删日期、筛pair、换相关估计器、clipping/calibration、P1 rescue、未来组成输入、事后拼接或未经授权的Deep Sets/Set Transformer/MoE。

旧7月正文SHA转录勘误继续保留，正确机器值 `9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2`，不修改冻结协议或数据。

PowerShell命令单行。阶段、文件/单元完成数、心跳及实际耗时实时flush；最终JSON分流。当前CPU数组统计、GPU_USED=false、FIT_COUNT=0；后续仅在批准后端适用时使用RTX5080，不为使用显卡替换冻结模型或升级用户环境。CURRENT_STATUS、HANDOFF和本步修复台账同轮更新，原失败记录与科学台账继续保留。
