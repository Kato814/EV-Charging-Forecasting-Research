# 仓库分层索引

更新：2026-09-09。当前入口只使用 [CURRENT_STATUS](../CURRENT_STATUS.md) 和 [HANDOFF](../HANDOFF.md)。本索引区分当前任务、已审证据及历史设计，不自动授权本地操作。

## 当前入口与台账

| 文件 | 用途 |
| --- | --- |
| CURRENT_STATUS.md | 当前模型开发阶段、开发集processed结果和holdout边界 |
| HANDOFF.md | 接管口径、版本、数据分区、方法方向和下一步 |
| [EXPERIMENT_LEDGER.md](EXPERIMENT_LEDGER.md) | 已执行实验、processed完成证据及当前结论 |
| [DATA_USAGE_LEDGER.md](DATA_USAGE_LEDGER.md) | 已用月份、开发集/最终holdout分区 |
| [ROADMAP.md](../ROADMAP.md) | 阶段依赖，不是自动运行指令 |
| [code/README.md](../code/README.md) | 当前代码与运行入口状态 |

## 当前证据与代码位置

| 层级 | 位置 | 状态 |
| --- | --- | --- |
| 5月pilot | PR #21 | 已合并；M4负结果保留 |
| 季节数据准备 | PR #23 | 已合并；`CONDITIONAL_PASS`，11月 `CURRENT_PROXY_ONLY` |
| 开发集raw获取 | PR #30 / Issue #29 | 01/04/07/10获取与QA完成 |
| 开发集processed协议/入口 | PR #34 | 独立开发YAML与固定四月准备入口 |
| processed兼容性修复 | PR #37 | 已合并；旧月份白名单遗漏已关闭 |
| **开发集processed数据** | **Issue #29 / `evidence/development_preparation_20260909.json`** | **01/04/07/10全部PASS，四个snapshot SHA冻结** |
| **当前模型开发** | **Issue #29** | **下一步建立M2/M3专家预测协议与入口；门控尚未训练** |

processed完成代码绑定：

```text
c1ff4e675ae14e7667e0c6b7f887fb15319aff38
```

开发集四个snapshot：

```text
2019-01 e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12
2019-04 f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299
2019-07 9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2
2019-10 e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296
```

## 数据用途索引

- 已使用/探索：2019-02、05、08、11；
- 方法开发集：2019-01、04、07、10；raw/processed已完成；
- 最终独立保留集：2019-03、06、09、12；继续封存。

下一步只允许开发集专家模型协议/代码开发；本地专家训练需新的明确授权。详细规则见 [DATA_USAGE_LEDGER](DATA_USAGE_LEDGER.md)。

## 本地资产

外置季节复核、消融、组合运行包及其 `local_runs/private` 继续保留。开发raw worktree、processed目录、旧失败/诊断JSON及两个preparation code worktree都不得因远端更新自动删除。

raw/interim/processed、完整预测、模型、私有索引和本地路径不提交Git。

## 历史材料

`literature/`、`datasets/`、`related_code/`、`research/`及旧计划继续用于追溯，不等于当前执行授权。冻结结果、失败记录、SHA和M4负结果保留；失效当前指令从入口替换，由Git历史追溯。

Gate2、概率、调度、联邦和GPU扩展仍需单独授权。
