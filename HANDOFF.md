# 主控交付说明｜充电站功率/负荷预测独立研究

更新：2026-09-08。仓库 `Kato814/EV-Charging-Forecasting-Research`。先读 [CURRENT_STATUS](CURRENT_STATUS.md)，再读本文、[实验台账](docs/EXPERIMENT_LEDGER.md)和[数据用途台账](docs/DATA_USAGE_LEDGER.md)。

## 1. 接管结论

**当前处于模型开发阶段。旧数据准备、基础模型、季节复核、负值诊断、分组消融和预测组合均已完成；开发集2019-01/04/07/10的raw获取与全月QA已完成，开发集专用processed准备代码/协议也已合并。当前下一步是用户本地生成这四个月的interim/processed、15 min聚合和M1–M3快照，随后才开发“基于信息可靠性门控的M2/M3双专家预测”。**

PR #23、#30、#34均已合并；Issue #22、#25、#26、#27均已完成关闭。当前唯一研发Issue为 [#29](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29)。Codex暂停新任务，主控负责方案/代码/审查，用户在普通本地Python环境执行明确授权任务。

## 2. 研究边界

这是独立研究，不继承其他三类型充电站/联邦岭回归论文的方法、指标、空间特征或结果。分布外泛化、未见城市/站点不作为论文核心。

主目标为 `station_current_mean_a`，单位A。季节数据没有统一授权重构kW。预测负号不等于实测V2G；当前清洗的非负充电电流目标也不能反向证明原始数据或设备绝无V2G。

M2与M3：
- M2：24 h历史/日历 + 当前站级connected/active、聚合current、观测率、pilot摘要；
- M3：M2 + 当前连接会话的合法细粒度状态池化；
- M4-lite：历史负结果保留，不恢复进入主线。

## 3. 版本与发布状态

| 类型 | 固定身份与状态 |
| --- | --- |
| 5月预测实验 | PR #21 已合并，`c2af2cdf4ecf5dad059d2ac92e929df8df35d42b` |
| 季节数据/代码 | PR #23 已合并；已审HEAD `4c2b1988ea9927b27287d6935bd22d01bd9df875`；main合并 `faa4cc8ad9051bd2f17f695e7c7741d769aee263` |
| 开发集获取代码 | PR #30 已合并；最终HEAD `e8370693c31f540d90c9a17e47534fbb0034e777`；main合并 `1d4c5f377f757aaea80b23987047f97899e958a4` |
| 开发集准备代码 | **PR #34 已合并；最终HEAD `75590bf788712aaad3138367fe9e470b11777644`；main合并 `2643e15a7099b5b25ec0d4f8d22ee4195ac4b6f1`** |
| PR #34 CI | **1058 passed、2 skipped；compileall PASS；Ruff PASS** |
| 当前研发Issue | #29，信息可靠性门控双专家预测 |

## 4. 数据用途与开发集raw结果

已使用或探索：2019-02/05/08/11；不能重新声明为未使用holdout。

在任何新下载前固定：
- **方法开发集：2019-01、04、07、10**；
- **最终独立保留集：2019-03、06、09、12**。

开发集raw获取已完成：

| 月份 | local | carry-in | combined | 有效日块 | QA |
| --- | ---: | ---: | ---: | ---: | --- |
| 2019-01 | 1372 | 0 | 1372 | 31/31 | PASS |
| 2019-04 | 1524 | 0 | 1524 | 30/30 | PASS |
| 2019-07 | 1489 | 0 | 1489 | 31/31 | PASS |
| 2019-10 | 1672 | 1 | 1673 | 31/31 | PASS |

四个月trajectory quarantine=0、full-session quarantine=0；月级reason_codes均为空。冻结metadata源SHA继续为 `bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a`。raw获取没有训练模型，也没有创建processed数据；`holdout_accessed=false`。

## 5. PR #34数据准备协议

不能直接把旧 `acn_jpl_seasonal_prep_2019.yaml` 当成开发集协议：旧文件明确绑定02/08/11、11月唯一3596 s轨迹隔离以及37件季节发布。主控在任何01/04/07/10 processed结果产生之前否决了该协议复用。

最终PR #34新增 `code/configs/acn_jpl_development_prep_2019.yaml`：

1. 只对应01/04/07/10；
2. 清洗、15 min聚合、coverage、lookback、horizon和M1–M3特征数值规则与已审单月链一致；
3. 四个月trajectory/full-session quarantine期望均为0，新异常直接fail-closed；
4. 只写本地ignored interim/processed，不创建旧37件季节发布；
5. 最终holdout 03/06/09/12 `access_allowed=false`；
6. 旧02/08/11协议保持原样；
7. 复用已审 `prepare_jpl_seasonal_month` 单月链，避免重写科学处理逻辑。

本地准备只做数据处理与快照封存，不联网下载、不训练M2/M3或门控模型。

## 6. 已审实验结论

| 工作 | 可支持结论 |
| --- | --- |
| 5月pilot | `PASS_ACTIVE_SESSION_DROP_M4`；M3近端有增量价值 |
| 2/8/11月季节复核 | 8月通过原月度规则，2月/11月未满足全部条件；总体 `MIXED_SEASONAL_EVIDENCE` |
| 负值诊断 | 部分负预测非微小，但仅置零不足以消除主要M3相对退化；不是V2G测量证据 |
| 分组消融 | 没有稳定依据统一删除实时状态、进度或用户申报中的任一整组 |
| 预测组合 | 简单平均相对M2的15个“月份×时距”MAE均下降，但相对M3非全面占优；校准权重未稳定胜过简单平均 |

解释：**站级状态与会话级状态具有互补信息，但M3的额外价值依赖时距和会话信息可观测/可靠程度。**

## 7. 当前方法开发方向

候选方法采用标准Mixture-of-Experts/gating范式，但普通MoE/动态加权本身不作为创新。当前可检验的新点是**会话信息可靠性驱动的低维门控与向M2回退**。

门控器只允许使用issue-time可得的低维变量，例如connected数、current/pilot observed ratio、用户申报可用比例、M3 missingness摘要、M2/M3预测差及horizon。不允许测试误差、最终kWh、最终离开时间、未来到达/轨迹、离线异常原因或测试标签作输入。

开发阶段至少比较M2、完整M3、0.5简单平均、可靠性门控。若门控不能在开发集上稳定超过简单平均，或收益依赖高复杂度不可解释调参，则停止该方向，不消耗最终holdout。

## 8. 长期冻结的数据语义

当地月用 `America/Los_Angeles` 半开区间，内部连续UTC、900 s物理网格，carry-in由完整元数据识别。11月合法DST回拨保留4个额外格；旧11月唯一3596 s倒退轨迹继续按其历史批准规则隔离，但**该特例不扩展到开发月**。

元数据正常的无效容器会话保留结构和coverage分母；current/pilot独立缺测。整段current不可观测与15 min格有正时长相交时，该格不得作为完整总电流标签，即使coverage>=90%。pilot-only缺失不否决有效current。缺测不是零，未知active不是确定未充电。

## 9. 资产保护

保留用户原main未提交修改、所有登记worktree和raw/interim/processed。保留运行后的 `evcf_seasonal_runner_v1_1`、`evcf_session_ablation_v1`、`evcf_forecast_combination_v1` 及各自 `local_runs/private`、binding、日志、原汇总、错误和恢复包。开发raw worktree同样保留。

本轮本地准备将使用一个新的代码专用detached worktree锁定PR #34合并提交，并把interim/processed写在已有开发raw worktree的ignored目录；不切换或清理既有worktree。不执行 `reset --hard`、`clean`、盲目stash或force push。

## 10. 下一步最小动作

1. 用户运行主控提供的开发集安全准备启动器；
2. 启动器只处理01/04/07/10，生成interim/processed、15 min聚合、M1–M3快照和processed SHA；
3. 用户只回传脱敏状态JSON；失败时保留现场，不自动清理或重复运行；
4. 主控审查processed快照与泄漏/coverage QA；
5. 通过后才设计和运行可靠性门控模型开发；
6. 方法全部冻结后才允许03/06/09/12进入最终独立验证。

## 11. 状态维护

任何数据授权、方法冻结、运行完成或结论变化必须在同一轮更新CURRENT_STATUS、HANDOFF及台账，并校对README/ROADMAP/code/README/索引。失效当前指令直接替换；历史证据保留在Git、Issue/PR和台账中。
