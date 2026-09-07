# EV-Charging-Forecasting-Research

充电站功率/负荷预测独立研究库。先验证具体预测问题，再确定算法；不以分布外泛化、未见城市或未见站点作为论文核心，不沿用其他充电站联邦预测项目的方法或结果。

## 当前进度

更新：2026-09-07。**已经完成数据准备、基础模型、季节复核、会话分组消融和预测组合探索，现处于模型方案收敛与独立验证准备阶段。**不是仍在修复旧数据，也不是最终论文方法已经完成。

当前状态只在 [CURRENT_STATUS.md](CURRENT_STATUS.md) 维护。已完成任务不因Issue仍开放、PR尚未合并或旧文档存在而自动重跑。

| 入口 | 用途 |
| --- | --- |
| [CURRENT_STATUS.md](CURRENT_STATUS.md) | 当前阶段、版本状态、待解决事项及授权边界 |
| [HANDOFF.md](HANDOFF.md) | 接管所需研究口径、数据快照、执行方式与下一步 |
| [docs/EXPERIMENT_LEDGER.md](docs/EXPERIMENT_LEDGER.md) | 已执行实验、结论、局限、包/协议/结果SHA及审查来源 |
| [docs/DATA_USAGE_LEDGER.md](docs/DATA_USAGE_LEDGER.md) | 已用数据与独立验证候选；本地月份盘点及其范围限制 |
| [AGENTS.md](AGENTS.md) | 执行代理和本地资产保护规则 |
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | 主控—用户本地Python—GitHub协作及文档更新规则 |
| [ROADMAP.md](ROADMAP.md) | 阶段依赖，不作为自动运行授权 |
| [docs/REPOSITORY_INDEX.md](docs/REPOSITORY_INDEX.md) | 当前材料、冻结证据与历史设计的分层索引 |

## 结论边界

5月pilot为 `PASS_ACTIVE_SESSION_DROP_M4`；新增月份主实验为 `MIXED_SEASONAL_EVIDENCE`。分组消融未支持统一删除一整组会话信息；预测组合中，简单平均优先保留为低复杂度独立验证候选，校准加权未稳定胜过简单平均。完整M3和M2都保留作参照。数据、实验与结论依据统一见实验台账，不把常规组合本身写成论文创新。

主建模目标是 `station_current_mean_a`，单位A，不是直接实测净有功功率。季节数据准备条件通过，11月保持电流代理限制；kW列未授权。模型预测为负不构成真实V2G证据。双源分解、概率预测和调度收益仍未验证。

## 代码、计算与证据

最后已合并预测实验基线为PR #21。季节数据代码固定读取已审PR #23 HEAD；PR #23尚未合并。Issue #25—#27使用外置本地运行包，GitHub当前记录协议、证据身份与主控评论，不声称这些包的源码和完整结果载荷已经进入main。详见 [代码入口说明](code/README.md)。

主控负责研究协议、代码开发/审查、结果审查和仓库维护；用户在现有本地Python环境执行明确命令。Codex暂停承担新任务；Actions只做轻量CI。命令执行前以对应协议和精确版本为准，不因脚本存在而运行旧任务。

raw/interim/processed、完整预测、模型、私有索引、凭据和本机绝对路径不得提交Git。运行后的各个外置包目录及 `local_runs/private` 必须保留；原main工作区未提交修改和数据任务worktree不动。禁止为清理旧文档而删除实验资产。

## 历史材料

[literature/](literature/)、[datasets/](datasets/)、[related_code/](related_code/) 保留文献、数据审计及外部代码来源。历史设计按仓库索引原位归档，不再充当当前指令。失效状态文字从当前入口删除并通过Git历史追溯；原结果、失败记录、M4负结果和SHA继续保留。

## 校验

既有校验由获授权的本地环境或CI执行；不要在运行环境盲目升级依赖。本次导航不启动任何下载、训练或环境变更。

```bash
python scripts/validate_library.py
python -m pytest code/tests
python -m compileall -q code/src scripts
python -m ruff check code/src scripts code/tests
git diff --check
```
