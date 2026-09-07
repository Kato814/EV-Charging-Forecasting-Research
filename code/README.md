# 代码与运行入口

更新：2026-09-07。当前阶段见 [CURRENT_STATUS](../CURRENT_STATUS.md)，运行/证据身份见 [实验台账](../docs/EXPERIMENT_LEDGER.md)。脚本存在不等于有新执行授权。

## 已合并的实现

`evcf.data`包含ACN获取、QA、5月清洗、语义审计、15 min及issue-time快照；`evcf.forecasting`包含5月M1—M4编码、Ridge/HGB、持久性和滚动pilot；`evcf.evaluation`包含点预测、峰值/爬坡、日级配对及bootstrap。

`scripts/run_jpl_gate1_pilot.py`是冻结的5月入口，不是通用季节入口，不能只换月份运行。PR #21仍是最后已合并的预测实验基线。

## 已审但未合并的数据分支

PR #23的缺测记账修复已经完成并条件验收。固定HEAD为 `4c2b1988ea9927b27287d6935bd22d01bd9df875`，分支 `data/jpl-2019-seasonal-replication`，PR仍未合并。季节获取/准备模块以该HEAD为准，不假定main包含。已获取raw和已生成快照不重下、不重做。

## 已执行的外置运行包

| 工作 | 外置目录 | 状态 |
| --- | --- | --- |
| Issue #25季节复核 | evcf_seasonal_runner_v1_1 | 已执行并审查，原主实验结论不变 |
| Issue #26分组消融 | evcf_session_ablation_v1 | 已执行；导出故障通过独立恢复工具收口 |
| Issue #27预测组合 | evcf_forecast_combination_v1 | 已执行并审查，仍为探索性证据 |

这些包通过对话交付，源码与完整结果载荷尚未作为仓库commit发布。其冻结包/协议/结果SHA和审查链接在台账中，不与main源码混淆。原运行目录及 `local_runs/private`、绑定、错误/恢复ZIP必须保留；不要重跑旧命令来完成文档更新。

## 未实现或未授权

概率场景、双源生成、flexibility、optimization和federated目录/骨架不等于已实现。M4历史代码保留供复现，不进入当前研发。当前独立验证的具体验证月份和新运行入口未冻结，不自动启动下载或训练。

## 环境与保护

CPU环境以 `environment-gate1-pilot.yml` 和运行清单为准，现有环境名 `evcf-gate1-pilot`、Python3.11.16；不无条件升级。CI与私有数据实机测试分开报告。

Token只在本地环境，raw/interim/processed、完整预测、模型和私有路径不提交。用户原main未提交修改、数据任务worktree和外置目录不清理；远端文档提交不要求本地切分支或拉取。
