# EV-Charging-Forecasting-Research

充电站功率/负荷预测独立研究库。先验证具体预测问题，再确定算法；不以分布外泛化、未见城市或未见站点作为论文核心，不沿用其他充电站联邦预测项目的方法或结果。

## 当前进度

更新：2026-09-09。**方法开发集2019-01/04/07/10的raw获取和processed准备均已完成，四个月全部PASS。当前正式进入模型开发：下一步先建立固定M2/M3专家预测和0.5简单平均基线，再开发“会话信息可靠性门控 + 向M2回退”机制。最终独立holdout 2019-03/06/09/12继续封存。**

当前状态只在 [CURRENT_STATUS.md](CURRENT_STATUS.md) 维护。已完成任务不因旧Issue正文、历史分支或旧文档仍存在而自动重跑。

| 入口 | 用途 |
| --- | --- |
| [CURRENT_STATUS.md](CURRENT_STATUS.md) | 当前阶段、版本状态、唯一研发任务及授权边界 |
| [HANDOFF.md](HANDOFF.md) | 接管所需研究口径、数据分区、方法方向与下一步 |
| [docs/EXPERIMENT_LEDGER.md](docs/EXPERIMENT_LEDGER.md) | 已执行实验、协议/代码版本与结果边界 |
| [docs/DATA_USAGE_LEDGER.md](docs/DATA_USAGE_LEDGER.md) | 已用数据、方法开发集与最终holdout分区 |
| [ROADMAP.md](ROADMAP.md) | 阶段依赖，不作为自动运行授权 |
| [docs/REPOSITORY_INDEX.md](docs/REPOSITORY_INDEX.md) | 当前材料、冻结证据与历史设计索引 |

## 当前方法与数据分区

M2使用历史/日历及当前站级聚合状态；完整M3在M2基础上增加当前连接会话的细粒度合法状态。现有结果表明二者信息互补，但M3的额外价值随时距和信息可靠程度变化。

当前Issue #29开发标准Mixture-of-Experts/gating框架下的**会话信息可靠性门控与向M2回退机制**。普通动态加权、简单平均或MoE本身不作为论文创新。

数据用途：
- 已使用/探索：2019-02、05、08、11；
- 方法开发集：2019-01、04、07、10；**raw与processed均已完成**；
- 最终独立保留集：2019-03、06、09、12；继续封存。

开发集processed结果四月均PASS，总计10872个formal issue。当前预测目标仍为 `station_current_mean_a`（A）；即使四个月power audit为 `KW_RECONSTRUCTION_CANDIDATE`，也不自动授权kW预测。

## 当前模型开发原则

下一阶段先冻结开发集M2/M3专家预测协议：固定HGB专家配置、时间切分、共同有效样本、滚动重训和预测缓存。之后先审M2、M3和0.5简单平均基线，再开发可靠性门控。

门控仅允许使用issue-time可得的低维可靠性变量和horizon；不得使用测试误差/标签、最终kWh、未来离开/轨迹、未来到达结果或离线异常原因。若门控不能稳定超过0.5简单平均，或必须依赖高复杂度不可解释调参，则停止该方向，不消耗最终holdout。

## 已有结论边界

5月pilot为 `PASS_ACTIVE_SESSION_DROP_M4`；2/8/11季节主实验为 `MIXED_SEASONAL_EVIDENCE`。分组消融未支持统一删除整组会话信息；0.5简单平均相对M2的15个“月份×时距”MAE均下降，但相对M3并非全面占优；校准加权未稳定胜过简单平均。

旧季节数据准备仍为 `CONDITIONAL_PASS`，11月保持 `CURRENT_PROXY_ONLY`，kW列未授权。模型预测为负不构成真实V2G证据。

## 代码、计算与资产

PR #21、#23、#30、#34、#37均已合并。开发集processed v1.1结果已登记于Issue #29及 `evidence/development_preparation_20260909.json`。当前尚未授权新的专家模型本地训练，需先完成模型协议/入口审查。

raw/interim/processed、完整预测、模型、私有索引、凭据和本机绝对路径不得提交Git。原main工作区未提交修改、数据worktree、失败/诊断JSON和外置运行目录及 `local_runs/private` 必须保留。

## 校验

```bash
python scripts/validate_library.py
python -m pytest code/tests
python -m compileall -q code/src scripts
python -m ruff check code/src scripts code/tests
git diff --check
```
