# 仓库分层索引

更新：2026-09-08。当前入口只使用 [CURRENT_STATUS](../CURRENT_STATUS.md) 和 [HANDOFF](../HANDOFF.md)。本索引区分当前任务、已审证据及历史设计，不自动授权本地操作。

## 当前入口与台账

| 文件 | 用途 |
| --- | --- |
| CURRENT_STATUS.md | 当前模型开发阶段、Issue #29、开发集processed准备与授权边界 |
| HANDOFF.md | 接管口径、方法方向、数据分区、版本和资产保护 |
| [EXPERIMENT_LEDGER.md](EXPERIMENT_LEDGER.md) | 已执行实验、PR #34协议/代码及当前证据身份 |
| [DATA_USAGE_LEDGER.md](DATA_USAGE_LEDGER.md) | 已用月份、开发集/最终holdout分区及当前数据用途 |
| [WORKFLOW.md](WORKFLOW.md) | 主控/用户Python分工及同轮更新规则 |
| [AGENTS.md](../AGENTS.md) | 工作区、隐私和授权保护 |
| [ROADMAP.md](../ROADMAP.md) | 阶段依赖，不是自动运行指令 |

## 已冻结证据与实际存放位置

| 层级 | 位置 | 状态 |
| --- | --- | --- |
| 5月完整获取 | PR #16，`outputs/acn_gate0/jpl_2019-05-full-ts/` | 已合并历史获取证据 |
| 5月数据准备 | PR #18，`outputs/acn_gate1_prep/jpl_2019-05/` | 已合并快照与语义证据 |
| 5月pilot | PR #21，`outputs/gate1_pilot/jpl_2019-05/` | 已合并，M4负结果保留 |
| 季节数据准备 | PR #23 | 已合并；`CONDITIONAL_PASS`，11月 `CURRENT_PROXY_ONLY` |
| 开发集获取入口 | PR #30 | 已合并；01/04/07/10 raw本地获取已完成并QA PASS |
| **开发集数据准备入口** | **PR #34，`acn_jpl_development_prep_2019.yaml`、`acn_jpl_development_prep.py`、`scripts/prepare_jpl_development.py`** | **已合并；当前等待用户本地processed准备** |
| 季节复核及诊断 | Issue #25，外置运行包与回传ZIP | 已审，`MIXED_SEASONAL_EVIDENCE` |
| 特征分组消融 | Issue #26 | 已审探索交付 |
| 预测组合 | Issue #27 | 已审探索交付；简单平均为强基线 |
| 当前方法开发 | Issue #29 | 先完成开发集processed审查，再进入可靠性门控训练 |
| 月份盘点摘要 | [evidence/month_inventory_20260907.json](evidence/month_inventory_20260907.json) | 历史脱敏目录摘要 |
| 开发集raw摘要 | [evidence/development_acquisition_20260908.json](evidence/development_acquisition_20260908.json) | 四个开发月获取/QA脱敏摘要 |

外置运行包、raw/interim/processed、完整预测检查点和私有数组仍留本地。仓库保存协议、SHA及去标识化证据，不冒称私有复现材料已全部入Git。

## 数据用途索引

- 已使用/探索：2019-02、05、08、11；
- 方法开发集：2019-01、04、07、10；raw已获取，当前只允许processed准备/后续方法开发；
- 最终独立保留集：2019-03、06、09、12；继续封存。

PR #34采用独立开发集协议；旧02/08/11季节YAML不扩展到开发集。详细规则见 [DATA_USAGE_LEDGER](DATA_USAGE_LEDGER.md)。

## 历史设计：原位归档，非当前指令

`literature/`、`datasets/`、`related_code/` 以及 `research/` 中早期设计继续用于追溯，不等于当前执行授权。旧计划不因文件存在而自动运行。

冻结结果、失败记录、SHA和M4负结果保留。失效当前操作文字从入口移除，历史内容通过Git追溯。

## Issue与PR的解释

#22/#23季节数据修复已完成；#25—#27已完成并关闭。PR #30完成开发集raw获取入口，PR #34完成开发集processed准备入口。当前唯一研发Issue为#29。

Gate2、概率、调度、联邦和GPU扩展仍需单独授权。

## 远端维护与本地资产不是一回事

远端文档、代码和Issue状态可以更新；用户本地worktree、未提交修改、raw/interim/processed及外置运行目录不得因此自动删除或重置。旧 [REPOSITORY_CLEANUP_20260905.md](REPOSITORY_CLEANUP_20260905.md) 是历史维护记录，不是当前状态入口。
