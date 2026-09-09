# EV-Charging-Forecasting-Research

充电站功率/负荷预测独立研究库。先验证具体预测问题，再确定算法；不以分布外泛化、未见城市或未见站点作为论文核心，不沿用其他充电站联邦预测项目的方法或结果。

## 当前进度

更新：2026-09-09。**方法开发集2019-01/04/07/10的raw与processed均已完成；固定M2/M3开发集OOS专家预测协议和代码也已合并。当前授权本地生成M2、M3和0.5简单平均开发基线及私有逐点预测缓存；可靠性门控尚未训练。最终独立holdout 2019-03/06/09/12继续封存。**

当前状态只在 [CURRENT_STATUS.md](CURRENT_STATUS.md) 维护。已完成任务不因旧Issue正文、历史分支或旧文档仍存在而自动重跑。

| 入口 | 用途 |
| --- | --- |
| [CURRENT_STATUS.md](CURRENT_STATUS.md) | 当前阶段、版本状态、唯一研发任务及授权边界 |
| [HANDOFF.md](HANDOFF.md) | 接管所需研究口径、数据分区、方法方向与下一步 |
| [docs/EXPERIMENT_LEDGER.md](docs/EXPERIMENT_LEDGER.md) | 已执行实验、协议/代码版本与结果边界 |
| [docs/DATA_USAGE_LEDGER.md](docs/DATA_USAGE_LEDGER.md) | 已用数据、方法开发集与最终holdout分区 |
| [ROADMAP.md](ROADMAP.md) | 阶段依赖，不作为自动运行授权 |

## 当前方法与数据分区

M2使用历史/日历及当前站级聚合状态；完整M3在M2基础上增加当前连接会话的细粒度合法状态。现有结果表明二者信息互补，但M3额外价值随时距和信息可靠程度变化。

当前Issue #29开发标准MoE/gating框架下的**会话信息可靠性门控与向M2回退机制**。普通动态加权、简单平均或MoE本身不作为论文创新。

数据用途：
- 已使用/探索：2019-02、05、08、11；
- 方法开发集：2019-01、04、07、10；raw/processed已完成；
- 最终独立保留集：2019-03、06、09、12；继续封存。

## 当前专家预测协议

PR #41已合并，main `653cb447382044911ce655175239f52f83dc892a`，CI 1066 passed、2 skipped。

M2/M3均沿用5月已选HGB参数，不在开发月重新调专家超参数；horizon为15/30/60/120/240 min；每月当地18日起OOS，每个当地午夜重训；训练仅用 `issue < cutoff` 且 `issue+h <= cutoff` 的同月formal行。M2/M3共享相同测试行和truth，0.5简单平均为强基线。无imputation/scaling/clipping/calibration。

完整逐点预测只写入仓库外部本地保留目录，不进Git。当前本地运行只训练专家，不训练可靠性门控。

## 方法停止规则

专家基线完成后再开发低维可靠性门控。门控只允许issue-time可得可靠性变量和horizon，不允许测试标签/误差、最终kWh、未来离开/轨迹、未来到达结果或离线异常原因。若门控不能稳定超过0.5简单平均，或需要复杂不可解释调参，则停止该方向，不消耗最终holdout。

## 已有结论边界

5月pilot为 `PASS_ACTIVE_SESSION_DROP_M4`；2/8/11季节主实验为 `MIXED_SEASONAL_EVIDENCE`。分组消融未支持统一删除整组会话信息；0.5简单平均是当前强基线；校准加权未稳定胜过简单平均。预测负号不构成真实V2G证据。目标仍为 `station_current_mean_a`（A），kW未授权。

## 资产与校验

raw/interim/processed、完整预测、模型、私有索引和本机路径不提交Git。原main未提交修改、所有worktree、失败/诊断JSON及运行后的外置目录均保留。

```bash
python scripts/validate_library.py
python -m pytest code/tests
python -m compileall -q code/src scripts
python -m ruff check code/src scripts code/tests
git diff --check
```
