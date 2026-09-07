# 仓库分层索引

更新：2026-09-07。当前入口只使用 [CURRENT_STATUS](../CURRENT_STATUS.md) 和 [HANDOFF](../HANDOFF.md)。本索引区分当前任务、已审证据及历史设计，不批量授权任何操作。

## 当前入口与台账

| 文件 | 用途 |
| --- | --- |
| CURRENT_STATUS.md | 模型方案收敛/独立验证准备、未落实事项与版本状态 |
| HANDOFF.md | 接管口径、当前数据快照、资产与执行边界 |
| [EXPERIMENT_LEDGER.md](EXPERIMENT_LEDGER.md) | PR #21/#23及Issue #25—#27的执行、审查、结果与SHA |
| [DATA_USAGE_LEDGER.md](DATA_USAGE_LEDGER.md) | 已用月份、独立性限制、本地盘点结果 |
| [WORKFLOW.md](WORKFLOW.md) | 主控/用户Python分工及同轮更新规则 |
| [AGENTS.md](../AGENTS.md) | 工作区、隐私和授权保护 |
| [ROADMAP.md](../ROADMAP.md) | 后续依赖，不是自动运行指令 |

## 已冻结证据与实际存放位置

| 层级 | 位置 | 状态 |
| --- | --- | --- |
| 5月完整获取 | PR #16，`outputs/acn_gate0/jpl_2019-05-full-ts/` | 已合并历史获取证据 |
| 5月数据准备 | PR #18，`outputs/acn_gate1_prep/jpl_2019-05/` | 已合并快照与语义证据 |
| 5月pilot | PR #21，`outputs/gate1_pilot/jpl_2019-05/` | 已合并单月筛选，原13件与M4负结果不变 |
| 季节数据准备 | PR #23已审HEAD `4c2b1988ea9927b27287d6935bd22d01bd9df875` 的 `outputs/seasonal_prep/`、`outputs/seasonal_prep_corrections/` | 条件验收，尚未合并；使用固定HEAD链接，不假定main包含 |
| 季节复核及只读诊断 | Issue #25，外置运行包与对话回传ZIP | 已审执行/汇总，跨月证据不一致 |
| 特征分组消融及导出恢复 | Issue #26，外置运行包及恢复ZIP | 已审探索交付，不重训以补标记 |
| 预测组合 | Issue #27，外置运行包与回传ZIP | 已审探索交付，简单平均保留为候选 |
| 月份盘点摘要 | [evidence/month_inventory_20260907.json](evidence/month_inventory_20260907.json) | 本轮纳入Git的脱敏摘要；不是数据内容或完整性证书 |

外置运行包与完整回传载荷并未因为登记Issue而进入Git；本次台账记录其精确身份与审查来源。后续源码/结果归档仍需单独按白名单核验，不隐瞒复现发布尚未齐备的状态。原始数据和逐点预测始终留本地。

## 历史设计：原位归档，非当前指令

`literature/`、`datasets/`、`related_code/` 是文献、数据审计和外部代码来源。`research/`中v0.4/v0.5/v0.6/v0.7设计，`experiments/gate0_gate2_protocol_v0.6.md`、`docs/ROUND2*`、`docs/ROUND3*` 和 `docs/superpowers/plans/` 是历史研究/实施材料，不等于已经执行或新授权。

它们保留原路径及日期以维持文献引用和 `scripts/validate_library.py` 的依赖；不为清理状态而移动、删掉或重新编号。历史研究结果、失败记录、原清单与SHA保留。当前入口里的失效操作文字已经替换，原文本只从Git历史查看，不再列为当前待办。

## Issue与PR的解释

#19/#21为已执行5月pilot，#20是已关闭重复方案。#22/#23的数据缺测修复已完成审查，PR #23仍未合并，不再称“修复正在运行”。#25—#27已完成其明确执行范围，开放状态保留讨论与追溯，不是重跑授权。

早期#1—#6、#10、#15等历史审计/后续方向，不因本轮文档更新而自动验收或关闭。EPFL、Gate 2、概率、调度、稳定GPU环境等另按具体授权办理。

## 远端清理与本地资产不是一回事

本轮只维护文档和脱敏台账，不删除历史分支、worktree、数据或外置运行目录。许可证、生产代码、测试、环境锁、文献计数和 `outputs/` 冻结文件不变。旧 [REPOSITORY_CLEANUP_20260905.md](REPOSITORY_CLEANUP_20260905.md) 是当日维护记录，不是当前状态入口。
