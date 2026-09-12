# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-12。当前状态以本文件和 [HANDOFF](HANDOFF.md) 为入口。科学依据见 [R1 协议](docs/JPL_JOINT_SESSION_STATE_PROBE_PROTOCOL_20260912.md)、[R1 outcome](docs/JPL_R1_JOINT_STATE_OUTCOME_20260912.md)、[实验台账](docs/EXPERIMENT_LEDGER.md)。工程记录见 [原启动失败](docs/JPL_R1_DIAGNOSTIC_IDENTITY_FAILURE_20260912.md) 和 [身份预检结果及 v1.1 修复](docs/JPL_R1_DIAGNOSTIC_BINARY_IDENTITY_REPAIR_20260912.md)。

**S1 保持 MIXED_STRUCTURED_SIGNAL；P1 保持 STOP_MECHANISM_ROUTE 且已关闭；R1 正式训练 COMPLETE、550 fits、MIXED_JOINT_STATE_SIGNAL。身份预检现已 COMPLETE：本地文件、固定 Git 对象和 HEAD 一致；诊断模块的文本及二进制 git show 均返回 128。已定位启动失败环节，但底层 Git 命令失败原因仍未知。真实日级/小时级诊断仍未完成。**

## 1. 当前唯一下一步

完成独立 v1.1 launcher 修复的审查、全量 CI 和合并，再发布 `evcf_r1_mixed_diagnostic_launcher_v1_1.py`。发布后只运行一次原范围的 prediction-cache-only 诊断，参数 `--authorize-r1-diagnostic`；只上传最新 `evcf_r1_mixed_diagnostic_status_*.json`。

不再重复身份预检或运行旧诊断 v1。新版本不改固定 SHA 来放行：仍核验原 PR #65 HEAD、本地 LF 规范化字节与原始 Git blob SHA256，仅将对象读取改为二进制 `git cat-file blob`。修复 PR 未通过 CI/合并/发布时，不运行模板。

| 项目 | 当前状态 |
| --- | --- |
| Issue | #29 |
| 目标 | station_current_mean_a，单位 A |
| 开发集 | 2019-01 / 04 / 07 / 10 |
| final holdout | 2019-03 / 06 / 09 / 12，禁止访问 |
| R1 原训练 | COMPLETE，550 fits，不重复 |
| R1 科学结论 | MIXED_JOINT_STATE_SIGNAL，不变 |
| 诊断 v1 | INCOMPLETE / IMPLEMENTATION_DRIFT，保留 |
| 身份预检 v1 | COMPLETE，耗时约 0.411 s；未读预测缓存 |
| 日级/小时级结论 | 尚未产生，不能提前宣称完成 |
| 下一步模型拟合 | 0，仅恢复原只读统计 |

## 2. 本机身份预检的有效信息

诊断模块：本地与 Git blob 均为 18029 字节、SHA 匹配；git diff=0；git show 文本和二进制模式均返回 128、输出零字节。参考文件：本地与 Git blob 均为 7821 字节，所有指纹和 git show 检查通过。两文件均无 CRLF、无 BOM。

不能把 `LEGACY_GIT_SHOW_TEXT_MISMATCH` 标签直接解释为文本编码问题。没有 stderr，不能归因为 Windows 换行、杀毒软件、长路径或某个 Git 配置。新校验仍拒绝错误 HEAD、错误/缺失对象及本地文件改动，不降低实验身份要求。

## 3. 科学结果保持不变

| 模型 | Pooled MAE (A) |
| --- | ---: |
| M2 | 30.164406 |
| M3 | 29.190188 |
| Equal | 28.917286 |
| S1 | 28.594882 |
| R1-Control | 29.192882 |
| R1-Joint | 29.039978 |

Joint 对 Control 改善 0.523773%，对 Equal 退化 0.424285%；对 Control 为 4/5 时距、3/4 月改善，对 Equal 为 3/5、2/4。60 min 仅优于 Equal 0.055223 A。八项 PASS 要求中六项通过，因此保持 MIXED。

7 月 Joint 所有时距劣于 Control；10 月改善 Control 但未追平 Equal。日级/小时级细分、显著性及具体特征原因尚无证据；25,375 条记录重复包含 5,075 个 issue times，不视为独立样本。

## 4. 执行与输入边界

统计代码继续绑定 PR #65 reviewed head `dd05258bf44d0a71773b6522ef6fb039831c77f1`。模块、reference 和 R1 cache manifest 的固定 SHA 见修复记录，均不更改。v1.1 launcher 的 reviewed head/PR 是另一个独立身份，不替代统计代码身份。

只复用已存在的 `-jpl-r1-mixed-diagnostic-code-v1` 工作树，不联网、不创建或切换工作树、不修改既有文件。只读已有 R1 cache，完整报告四月×五时距的 Joint-Control/Joint-Equal 日级与小时级误差；不读取 raw/interim/processed、其他模型缓存或 final holdout。统计核心、样本、分组、判据及原结果均不变。

## 5. 保护、进度与交付

保留旧 launcher、失败 JSON、身份预检 JSON、所有历史工作树及私有缓存。禁止 reset/clean/stash/force push、P1 rescue、R1 重训调参、筛 pair、更换相关估计器、clipping/calibration、删日期、事后拼接或未经授权的 Deep Sets/Set Transformer/MoE。

PowerShell 命令单行；实时阶段/单元进度、心跳和实际耗时继续输出，最终 JSON 分流。本次 CPU 数组统计、GPU_USED=false、FIT_COUNT=0；以后仅在已批准后端适用时使用 RTX 5080，不为用 GPU 更换冻结模型。INCOMPLETE 后先审计具体原因，不自动重跑。
