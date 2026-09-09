# 仓库分层索引

更新：2026-09-09。当前入口只使用 [CURRENT_STATUS](../CURRENT_STATUS.md) 和 [HANDOFF](../HANDOFF.md)。本索引区分当前任务、已审证据及历史设计，不自动授权本地操作。

## 当前入口与台账

| 文件 | 用途 |
| --- | --- |
| CURRENT_STATUS.md | 当前模型开发阶段、专家本地运行与holdout边界 |
| HANDOFF.md | 接管口径、版本、数据分区、方法方向和下一步 |
| [EXPERIMENT_LEDGER.md](EXPERIMENT_LEDGER.md) | 已执行实验、专家协议/代码与证据身份 |
| [DATA_USAGE_LEDGER.md](DATA_USAGE_LEDGER.md) | 已用月份、开发集/最终holdout分区 |
| [ROADMAP.md](../ROADMAP.md) | 阶段依赖，不是自动运行指令 |
| [code/README.md](../code/README.md) | 当前代码与运行入口状态 |

## 当前证据与代码位置

| 层级 | 位置 | 状态 |
| --- | --- | --- |
| 5月pilot | PR #21 | 已合并；M4负结果保留 |
| 季节数据准备 | PR #23 | 已合并；`CONDITIONAL_PASS`，11月 `CURRENT_PROXY_ONLY` |
| 开发集raw/processed | PR #30/#34/#37 / Issue #29 | 01/04/07/10全部PASS，四个snapshot SHA冻结 |
| **固定M2/M3开发集OOS专家入口** | **PR #41** | **已合并；当前授权本地运行；gate尚未训练** |
| 当前方法开发 | Issue #29 | 先审M2/M3/0.5基线，再开发可靠性门控 |

专家代码main绑定：

```text
653cb447382044911ce655175239f52f83dc892a
```

专家协议：`JPL_DEVELOPMENT_HGB_EXPERT_OOS_20260909_V1`。完整逐点预测不进Git，只保留在仓库外部本地目录；公共记录只保存协议、SHA和脱敏聚合结果。

## 数据用途索引

- 已使用/探索：2019-02、05、08、11；
- 方法开发集：2019-01、04、07、10；raw/processed已完成；
- 最终独立保留集：2019-03、06、09、12；继续封存。

当前只允许开发集固定专家OOS运行；最终holdout继续禁止访问。详细规则见 [DATA_USAGE_LEDGER](DATA_USAGE_LEDGER.md)。

## 本地资产

外置季节复核、消融、组合运行包及其 `local_runs/private` 继续保留。开发raw/processed worktree、失败/诊断JSON及preparation code worktree均不得因远端更新自动删除。新专家预测将另建detached code worktree，并把20个逐点缓存写到仓库外部本地目录；这些缓存后续门控开发要复用，也必须保留。

raw/interim/processed、完整预测、模型、私有索引和本地路径不提交Git。

## 历史材料

`literature/`、`datasets/`、`related_code/`、`research/`及旧计划继续用于追溯，不等于当前执行授权。冻结结果、失败记录、SHA和M4负结果保留；失效当前指令从入口替换，由Git历史追溯。

Gate2、概率、调度、联邦和GPU扩展仍需单独授权。
