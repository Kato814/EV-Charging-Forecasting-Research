# 代码与运行入口

更新：2026-09-07。当前阶段见 [CURRENT_STATUS](../CURRENT_STATUS.md)，运行/证据身份见 [实验台账](../docs/EXPERIMENT_LEDGER.md)。脚本存在不等于有执行授权。

## 已合并的基础实现

`evcf.data`包含ACN获取、QA、5月清洗、语义审计、15 min及issue-time快照；`evcf.forecasting`包含5月M1—M4编码、Ridge/HGB、持久性和滚动pilot；`evcf.evaluation`包含点预测、峰值/爬坡、日级配对及bootstrap。

PR #21为5月预测实验基线；PR #23的季节获取/准备和缺测记账修复也已合并。季节数据准备仍是 `CONDITIONAL_PASS`，11月 `CURRENT_PROXY_ONLY`，这不因代码合并而改变。

`scripts/run_jpl_gate1_pilot.py`是冻结的5月入口，不是通用季节入口，不能只换月份运行。

## 当前新增：开发集获取入口

PR #30 已合并，新增：

- `evcf.data.acn_jpl_development_months`：只在显式上下文内临时批准2019-01/04/07/10；
- `scripts/acquire_jpl_development.py`：开发集专用获取/QA入口，要求 `--authorize-development`，月份固定、不可命令行改成holdout；
- 最终holdout 2019-03/06/09/12在该上下文中仍保持未批准；
- 已审季节获取/QA模块中原本按值导入的02/08/11月份限制仅在开发上下文内临时扩展，结束后精确恢复；
- 新开发月份没有预批准轨迹隔离签名，发现新的同步倒退时QA失败，不能自动套用11月3596秒特例。

PR #30最终HEAD `e8370693c31f540d90c9a17e47534fbb0034e777` 的CI通过：1048 passed、2 skipped，compileall与Ruff均PASS。合并本身没有下载数据。下一步由外置安全启动器在新独立worktree中执行开发集获取。

## 已执行的外置运行包

| 工作 | 外置目录 | 状态 |
| --- | --- | --- |
| Issue #25季节复核 | `evcf_seasonal_runner_v1_1` | 已执行并审查，原主实验 `MIXED_SEASONAL_EVIDENCE` |
| Issue #26分组消融 | `evcf_session_ablation_v1` | 已执行；导出故障由独立恢复工具收口 |
| Issue #27预测组合 | `evcf_forecast_combination_v1` | 已执行并审查；简单平均留作强基线 |

这些运行目录及 `local_runs/private`、绑定、错误/恢复ZIP必须保留；不要为仓库同步重跑旧命令。

## 当前模型开发与未授权模块

当前Issue #29开发M2/M3双专家的**会话信息可靠性门控与向M2回退**。普通MoE/动态加权不是创新点。开发阶段至少比较M2、完整M3、0.5简单平均和可靠性门控。

概率场景、双源生成、flexibility、optimization和federated目录/骨架不等于已实现；M4历史代码仅用于复现。最终holdout、Gate2、概率、调度、联邦和GPU深度扩展均未授权。

## 环境与保护

CPU环境以 `environment-gate1-pilot.yml` 和运行清单为准，当前冻结环境 `evcf-gate1-pilot` / Python3.11.16；不无条件升级。CI与私有数据实机执行分开报告。

Token只在本地环境；raw/interim/processed、完整预测、模型和私有路径不提交。用户原main未提交修改和已有worktree不清理；新开发集任务使用独立worktree，不要求当前本地工作区切分支或拉取。
