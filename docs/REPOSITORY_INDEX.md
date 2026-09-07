# 仓库分层索引

更新：2026-09-07。当前入口只使用 [CURRENT_STATUS](../CURRENT_STATUS.md) 和 [HANDOFF](../HANDOFF.md)。本索引区分当前任务、已审证据及历史设计，不自动授权本地操作。

## 当前入口与台账

| 文件 | 用途 |
| --- | --- |
| CURRENT_STATUS.md | 当前模型开发阶段、Issue #29、数据分区及授权边界 |
| HANDOFF.md | 接管口径、方法方向、数据分区、版本和资产保护 |
| [EXPERIMENT_LEDGER.md](EXPERIMENT_LEDGER.md) | PR #21/#23及Issue #25—#29的执行、审查、结果与SHA |
| [DATA_USAGE_LEDGER.md](DATA_USAGE_LEDGER.md) | 已用月份、开发集/最终holdout分区、本地盘点结果 |
| [WORKFLOW.md](WORKFLOW.md) | 主控/用户Python分工及同轮更新规则 |
| [AGENTS.md](../AGENTS.md) | 工作区、隐私和授权保护 |
| [ROADMAP.md](../ROADMAP.md) | 后续依赖，不是自动运行指令 |

## 已冻结证据与实际存放位置

| 层级 | 位置 | 状态 |
| --- | --- | --- |
| 5月完整获取 | PR #16，`outputs/acn_gate0/jpl_2019-05-full-ts/` | 已合并历史获取证据 |
| 5月数据准备 | PR #18，`outputs/acn_gate1_prep/jpl_2019-05/` | 已合并快照与语义证据 |
| 5月pilot | PR #21，`outputs/gate1_pilot/jpl_2019-05/` | 已合并单月筛选，原13件与M4负结果不变 |
| 季节数据准备 | PR #23，`outputs/seasonal_prep/`、`outputs/seasonal_prep_corrections/` | 已合并；数据准备 `CONDITIONAL_PASS`，11月 `CURRENT_PROXY_ONLY` |
| 季节复核及诊断 | Issue #25，外置运行包与回传ZIP | 已审执行/汇总，Issue已完成关闭；`MIXED_SEASONAL_EVIDENCE` |
| 特征分组消融及导出恢复 | Issue #26，外置运行包及恢复ZIP | 已审探索交付，Issue已完成关闭 |
| 预测组合 | Issue #27，外置运行包与回传ZIP | 已审探索交付，Issue已完成关闭 |
| 当前方法开发 | Issue #29 | 信息可靠性门控的M2/M3双专家预测；尚未运行新数据/模型 |
| 月份盘点摘要 | [evidence/month_inventory_20260907.json](evidence/month_inventory_20260907.json) | 脱敏目录摘要；不是数据完整性证书 |

外置运行包、完整预测检查点和私有数组仍留本地。仓库保存其SHA、协议和审查来源，不冒称所有复现材料已入Git。

## 数据用途索引

- 已使用/探索：2019-02、05、08、11；
- 方法开发集：2019-01、04、07、10；
- 最终独立保留集：2019-03、06、09、12。

这一分区在新下载前冻结。当前下一阶段只允许开发集获取/QA，最终保留集不得提前获取或用于模型选择。详细规则见 [DATA_USAGE_LEDGER](DATA_USAGE_LEDGER.md)。

## 历史设计：原位归档，非当前指令

`literature/`、`datasets/`、`related_code/` 是文献、数据审计和外部代码来源。`research/`中v0.4/v0.5/v0.6/v0.7设计，`experiments/gate0_gate2_protocol_v0.6.md`、`docs/ROUND2*`、`docs/ROUND3*` 和 `docs/superpowers/plans/` 是历史研究/实施材料，不等于已经执行或新授权。

它们保留原路径及日期以维持引用和 `scripts/validate_library.py` 依赖；不为“仓库整洁”删除冻结结果、失败记录、原清单或SHA。失效当前操作文字从入口移除，历史内容通过Git追溯。

## Issue与PR的解释

#19/#21为5月pilot；#20为已关闭重复方案。#22/#23季节获取和缺测修复均已完成，PR #23已合并。#25—#27已完成并关闭，保留其探索/诊断证据但不再作为当前执行入口。当前唯一研发Issue为#29。

早期#1—#6、#10、#15等历史审计/后续方向，不因当前方法开发自动验收或关闭。Gate 2、概率、调度、联邦和GPU扩展仍需单独授权。

## 远端维护与本地资产不是一回事

远端文档、代码和Issue状态可以更新；用户本地worktree、未提交修改、raw/interim/processed及外置运行目录不得因此自动删除或重置。旧 [REPOSITORY_CLEANUP_20260905.md](REPOSITORY_CLEANUP_20260905.md) 是历史维护记录，不是当前状态入口。
