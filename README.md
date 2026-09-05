# EV-Charging-Forecasting-Research

充电站功率/负荷预测研究库。先验证具体预测问题，再确定算法；不以分布外泛化、未见城市或未见站点作为论文核心。此仓库不沿用其他充电站联邦预测项目的模型或结果。

## 从这里接管

| 入口 | 用途 |
| --- | --- |
| [CURRENT_STATUS.md](CURRENT_STATUS.md) | 当前状态、唯一在执行任务与禁止提前开展的工作 |
| [HANDOFF.md](HANDOFF.md) | 新主控窗口交付说明：证据、版本、修复验收与后续顺序 |
| [AGENTS.md](AGENTS.md) | 本地执行代理的工作边界 |
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | 主控—本地 Codex—GitHub 的交接流程 |
| [docs/REPOSITORY_INDEX.md](docs/REPOSITORY_INDEX.md) | 当前证据、历史材料、未启动模块的分层索引 |
| [ROADMAP.md](ROADMAP.md) | 已完成、进行中、待授权阶段 |

**2026-09-05 交接状态：5月 Gate 1 pilot 已完成；季节准备 PR #23 正在修复缺测会话记账问题，尚未验收，禁止启动季节模型。** 最新远端提交、Issue 评论和主控审查可能晚于本文，接管时必须重新读取。

## 已有结论与边界

[PR #21](https://github.com/Kato814/EV-Charging-Forecasting-Research/pull/21) 已合并，实验基线提交为 `c2af2cdf4ecf5dad059d2ac92e929df8df35d42b`。JPL 2019-05 pilot 分类为 `PASS_ACTIVE_SESSION_DROP_M4`：HGB-M3 相对 M2 的 15/30/60 min MAE 改善为 11.226% / 14.503% / 18.939%；当前 M4-lite 不进入后续主实验。该结论仅适用于此次单月筛选，并未证明双源分解、概率预测、跨季节效果或调度收益。

正式历史证据位于 [outputs/gate1_pilot/jpl_2019-05/](outputs/gate1_pilot/jpl_2019-05/)，保留原文件与 SHA256SUMS。

## 当前唯一执行任务

- Issue：[#22](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/22)
- PR：[#23](https://github.com/Kato814/EV-Charging-Forecasting-Research/pull/23)
- 分支：`data/jpl-2019-seasonal-replication`
- 工作：保留无效 current/pilot 容器会话的合法结构状态、分支缺测和 coverage 分母，重算受影响季节快照。
- 审查：[CHANGES_REQUIRED_INVALID_CONTAINER_ACCOUNTING](https://github.com/Kato814/EV-Charging-Forecasting-Research/pull/23#pullrequestreview-5120653692)

Codex 已在本地执行该修订。不要另派重复任务、向其分支并行写代码，或因旧 CI 成功而合并旧结果。`8c0eeeaff8367dba3c4790de79ba97a018022e0a` 的季节报告为**修正前证据**。

## 预测对象与研究候选

当前使用实测电流构造的 `station_current_mean_a`。5月名义208 V换算只作 `A × 0.208` 的重构量/等价误差，不能称为直接实测有功功率；季节数据未统一授权重构 kW。

候选后续问题为“发布时间已连接会话与未来到达会话的双源不确定性”。先复核 M3 会话状态价值，再判断分开建模是否优于强直接预测模型。未来调度须区分外生执行负荷与可优化的充电需求，不能把同一 EV 功率同时固定为预测输入又自由作为调度变量。

## 计算与数据边界

GitHub 管代码、配置、审查、轻量 CI 和去标识化汇总；正式数据处理、训练及后续优化在本地执行。CPU pilot 环境由 [environment-gate1-pilot.yml](environment-gate1-pilot.yml) 与运行清单记录。RTX 5080 留给经授权的 GPU 任务；不为当前 CPU 修复修改驱动、系统 CUDA 或 PyTorch。

raw、interim、processed、完整预测、模型、私有索引、Token、本机绝对路径不提交 Git。被忽略的数据当前可能仍在任务 worktree 内：未经本地确认和备份，禁止删除 worktree。

## 文献与历史材料

[literature/](literature/) 是文献及证据库，[datasets/](datasets/) 是数据目录及审计，[related_code/](related_code/) 是外部代码索引。保留历史 v0.4–v0.7 决策、实验协议和阅读笔记以供追溯；它们不再充当当前任务入口。完整分层见 [仓库索引](docs/REPOSITORY_INDEX.md)。不因文档日期较新就把其中的候选方案当作已实现结论。

## 校验入口

在已批准的本地环境或现有 CI 中运行，不要在正在工作的环境中盲目升级依赖：

```bash
python scripts/validate_library.py
python -m pytest code/tests
python -m compileall -q code/src scripts
python -m ruff check code/src scripts code/tests
git diff --check
```

新的运行命令以任务分支脚本 `--help` 和相应 Issue 为准；本文不触发下载或训练。
