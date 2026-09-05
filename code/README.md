# Codebase

当前状态：[CURRENT_STATUS](../CURRENT_STATUS.md)。接管细节：[HANDOFF](../HANDOFF.md)。

## 已实现并验收

- `evcf.data`：ACN获取、QA、JPL 5月清洗、能量语义审计、15 min聚合与issue-time快照。
- `evcf.forecasting`：5月M1–M4固定编码、Ridge/HGB、持久性和按日滚动pilot。
- `evcf.evaluation`：该pilot的点预测、峰值/爬坡、日级配对与bootstrap。
- 脚本：`acn_jpl_full_month_ts.py`、`prepare_jpl_gate1_data.py`、`run_jpl_gate1_pilot.py`（位于仓库 `scripts/`）。只按已有任务授权运行，不因入口存在就重跑。

## 未合并工作

季节管线与当前缺测记账修复在PR #23的 `data/jpl-2019-seasonal-replication`。`scripts/acquire_jpl_seasonal.py` / `scripts/prepare_jpl_seasonal_data.py` 及对应模块需在该分支读取，不能假定已存在于main。raw已获取，不再下载。

## 未实现/未验收模块

概率场景、双源生成、flexibility、optimization和federated目录/骨架不等于已经实现。M4历史代码保留用于复现，不进入当前季节正式研发。

## 环境与校验

当前CPU环境以 `environment-gate1-pilot.yml` 与运行manifest为准。GitHub CI安装 `.[dev,gate1]` 并运行仓库校验、pytest、compileall和Ruff；本地不要在活跃环境中无条件升级。

Token从本地环境读取。raw/interim/processed/完整预测/模型均保持本地。调用任何入口前先看当前分支脚本 `--help` 与Issue，不从早期网页试下载文档复制命令。
