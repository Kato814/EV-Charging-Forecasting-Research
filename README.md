# EV-Charging-Forecasting-Research

充电站功率/负荷预测独立研究库。先验证具体预测问题，再确定算法；不以分布外泛化、未见城市或未见站点作为论文核心，不沿用其他充电站联邦预测项目的方法或结果。

## 当前进度

更新：2026-09-07。**数据准备、基础模型、季节复核、会话分组消融和预测组合探索均已完成。当前进入模型开发阶段，候选方向是“基于信息可靠性门控的M2/M3双专家预测”。最终论文方法尚未确定，最终独立验证也尚未开始。**

当前状态只在 [CURRENT_STATUS.md](CURRENT_STATUS.md) 维护。已完成任务不因旧Issue正文、历史分支或旧文档仍存在而自动重跑。

| 入口 | 用途 |
| --- | --- |
| [CURRENT_STATUS.md](CURRENT_STATUS.md) | 当前阶段、版本状态、唯一研发任务及授权边界 |
| [HANDOFF.md](HANDOFF.md) | 接管所需研究口径、数据分区、方法方向与下一步 |
| [docs/EXPERIMENT_LEDGER.md](docs/EXPERIMENT_LEDGER.md) | 已执行实验、结论、局限和结果SHA |
| [docs/DATA_USAGE_LEDGER.md](docs/DATA_USAGE_LEDGER.md) | 已用数据、方法开发集与最终holdout分区 |
| [AGENTS.md](AGENTS.md) | 执行代理和本地资产保护规则 |
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | 主控—用户本地Python—GitHub协作及维护规则 |
| [ROADMAP.md](ROADMAP.md) | 阶段依赖，不作为自动运行授权 |
| [docs/REPOSITORY_INDEX.md](docs/REPOSITORY_INDEX.md) | 当前材料、冻结证据与历史设计索引 |

## 当前方法与数据分区

M2使用历史/日历及当前站级聚合状态；完整M3在M2基础上增加当前连接会话的细粒度合法状态。现有结果表明二者信息互补，但M3的额外价值随时距和信息可靠程度变化。

因此当前Issue #29开发标准Mixture-of-Experts/gating框架下的**会话信息可靠性门控与向M2回退机制**。普通动态加权、简单平均或MoE本身不作为论文创新；2026年EV负荷文献已存在动态堆叠和station/horizon-specific gating。

2019年月份用途在新下载前冻结：

- 已使用/探索：02、05、08、11；
- 方法开发集：01、04、07、10；
- 最终独立保留集：03、06、09、12。

当前下一阶段只允许开发集01/04/07/10的获取/QA。最终保留集在方法、门控变量、超参数、评价和停止规则全部冻结前不得下载或运行模型。

## 已有结论边界

5月pilot为 `PASS_ACTIVE_SESSION_DROP_M4`；新增月份主实验为 `MIXED_SEASONAL_EVIDENCE`。分组消融未支持统一删除一整组会话信息；简单平均相对M2的15个“月份×时距”组合MAE均下降，但相对M3并非全面占优；校准加权未稳定胜过简单平均。

主建模目标是 `station_current_mean_a`、单位A，不是直接实测净有功功率。季节数据准备为 `CONDITIONAL_PASS`，11月保持 `CURRENT_PROXY_ONLY`，kW列未授权。模型预测为负不构成真实V2G证据。双源分解、概率预测和调度收益仍未验证。

## 代码、计算与证据

PR #21和PR #23均已合并。PR #23合并的是已审季节数据准备与缺测记账修正，不改变后续探索实验的研究结论。Issue #22、#25、#26、#27已按完成关闭；当前研发Issue为 #29。

Issue #25—#27使用外置本地运行包，GitHub记录协议、证据身份、SHA和主控复核；完整预测、模型及私有逐点检查点仍只保存在本地。主控负责研究协议、代码开发/审查、结果核验和仓库维护；用户在冻结Python环境执行明确命令。Codex暂停承担新任务。

raw/interim/processed、完整预测、模型、私有索引、凭据和本机绝对路径不得提交Git。运行后的外置包目录及 `local_runs/private` 必须保留；原main工作区未提交修改和数据worktree不得因远端更新被清理。

## 历史材料

[literature/](literature/)、[datasets/](datasets/)、[related_code/](related_code/) 保留文献、数据审计及外部代码来源。历史设计按仓库索引原位归档，不再充当当前指令。失效状态文字从当前入口删除并通过Git历史追溯；原结果、失败记录、M4负结果和SHA继续保留。

## 校验

既有校验由获授权的本地环境或CI执行；不要在运行环境盲目升级依赖。README本身不触发下载、训练或环境变更。

```bash
python scripts/validate_library.py
python -m pytest code/tests
python -m compileall -q code/src scripts
python -m ruff check code/src scripts code/tests
git diff --check
```
