# 仓库分层索引

更新：2026-09-08。当前入口只使用 [CURRENT_STATUS](../CURRENT_STATUS.md) 和 [HANDOFF](../HANDOFF.md)。本索引区分当前任务、已审证据及历史设计，不自动授权本地操作。

## 当前入口与台账

| 文件 | 用途 |
| --- | --- |
| CURRENT_STATUS.md | 当前模型开发阶段、processed重试与holdout边界 |
| HANDOFF.md | 接管口径、版本、故障根因和当前授权 |
| [EXPERIMENT_LEDGER.md](EXPERIMENT_LEDGER.md) | 已执行实验、processed失败/诊断/PR #37修复 |
| [DATA_USAGE_LEDGER.md](DATA_USAGE_LEDGER.md) | 已用月份、开发集/最终holdout分区 |
| [WORKFLOW.md](WORKFLOW.md) | 主控/用户Python分工及维护规则 |
| [ROADMAP.md](../ROADMAP.md) | 阶段依赖，不是自动运行指令 |

## 当前证据与代码位置

| 层级 | 位置 | 状态 |
| --- | --- | --- |
| 5月pilot | PR #21 | 已合并；M4负结果保留 |
| 季节数据准备 | PR #23 | 已合并；`CONDITIONAL_PASS`，11月 `CURRENT_PROXY_ONLY` |
| 开发集raw获取 | PR #30 / Issue #29 | 01/04/07/10本地获取与QA已完成 |
| 开发集processed协议/入口 | PR #34 | 独立开发YAML与固定四月准备入口 |
| **processed兼容性修复** | **PR #37** | **已合并；修复`acn_jpl_gate1_prep`旧月份白名单遗漏** |
| processed首次失败与只读诊断 | Issue #29 / 用户回传JSON | 已定位；四月无partial输出；holdout未访问 |
| 当前方法开发 | Issue #29 | 当前先重试processed，验收后再训练可靠性门控 |

PR #37固定身份：

```text
final HEAD e47f05cb7a663df9c599270ac939c9301d26840b
main merge c1ff4e675ae14e7667e0c6b7f887fb15319aff38
```

CI：1058 passed、2 skipped，compileall/Ruff PASS。

## 数据用途索引

- 已使用/探索：2019-02、05、08、11；
- 方法开发集：2019-01、04、07、10；raw已获取，当前允许processed重试；
- 最终独立保留集：2019-03、06、09、12；继续封存。

详细规则见 [DATA_USAGE_LEDGER](DATA_USAGE_LEDGER.md)。

## 本地资产

外置季节复核、消融、组合运行包及其 `local_runs/private` 继续保留。开发raw worktree、首次PR #34 preparation code worktree、只读诊断证据和新PR #37 v2 code worktree均不得因远端更新自动删除。

raw/interim/processed、完整预测、模型、私有索引和本地路径不提交Git。

## 历史材料

`literature/`、`datasets/`、`related_code/`、`research/`及旧计划继续用于追溯，不等于当前执行授权。冻结结果、失败记录、SHA和M4负结果保留；失效当前指令从入口替换，由Git历史追溯。

Gate2、概率、调度、联邦和GPU扩展仍需单独授权。
