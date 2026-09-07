# 主控交付说明｜充电站功率/负荷预测独立研究

更新：2026-09-07。仓库 `Kato814/EV-Charging-Forecasting-Research`。先读 [CURRENT_STATUS](CURRENT_STATUS.md)，再读本文、[实验台账](docs/EXPERIMENT_LEDGER.md)和[数据用途台账](docs/DATA_USAGE_LEDGER.md)。

## 1. 接管结论

**当前处于模型开发阶段。旧数据准备、基础模型、季节复核、负值诊断、分组消融和预测组合均已完成；当前要开发“基于信息可靠性门控的M2/M3双专家预测”。开发集获取代码已经合并，下一步是用户本地只获取/QA 2019-01/04/07/10。**

PR #23和PR #30均已合并；Issue #22、#25、#26、#27均已完成关闭。当前唯一研发Issue为 [#29](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29)。Codex暂停新任务，主控负责方案/代码/审查，用户在普通本地Python环境执行明确授权的任务。

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
| 缺测修复实现 | `6ded3bdd810a8115ea5b8a51091de71fab894a03` |
| 开发集获取代码 | PR #30 已合并；最终HEAD `e8370693c31f540d90c9a17e47534fbb0034e777`；main合并 `1d4c5f377f757aaea80b23987047f97899e958a4` |
| PR #30 CI | 1048 passed、2 skipped；compileall PASS；Ruff PASS |
| 数据准备状态 | `CONDITIONAL_PASS`；11月 `CURRENT_PROXY_ONLY`；季节kW未授权 |
| 外置实验 | Issue #25—#27，已执行并完成主控汇总复核；完整逐点结果仍留本地 |
| 当前研发Issue | #29，信息可靠性门控双专家预测 |

代码合并不代表新数据已经下载。PR #30只把安全获取入口放入main；当前开发集本地获取尚未执行。

## 4. 已用数据与新分区

已使用或探索：2019-02/05/08/11；均不能再声明为未使用holdout。

在任何新下载前已固定：

- **方法开发集：2019-01、04、07、10**；
- **最终独立保留集：2019-03、06、09、12**。

当前只允许开发集获取和后续方法开发。最终保留集在门控变量、公式/模型、超参数、阈值、评价和停止条件冻结前不得获取时序或运行模型；不能根据后续结果换月。

2026-09-07的本地目录盘点只在3个登记worktree的指定JPL目录发现02/05/08/11；未发现额外月份目录不证明电脑其他位置或未打开压缩包不存在数据。

## 5. 已审实验结论

| 工作 | 可支持结论 |
| --- | --- |
| 5月pilot | `PASS_ACTIVE_SESSION_DROP_M4`；M3近端有增量价值 |
| 2/8/11月季节复核 | 8月通过原月度规则，2月/11月未满足全部条件；总体 `MIXED_SEASONAL_EVIDENCE` |
| 负值诊断 | 部分负预测非微小，但仅置零不足以消除主要M3相对退化；不是V2G测量证据 |
| 分组消融 | 没有稳定依据统一删除实时状态、进度或用户申报中的任一整组 |
| 预测组合 | 简单平均相对M2的15个“月份×时距”MAE均下降，但相对M3非全面占优；校准权重未稳定胜过简单平均 |

解释：**站级状态与会话级状态具有互补信息，但M3的额外价值依赖时距和会话信息可观测/可靠程度。**后续不在已查看月份上继续调固定权重或删特征。

## 6. 当前方法开发方向

候选方法采用标准Mixture-of-Experts/gating范式，但普通MoE/动态加权本身不作为创新。2026年已有EV负荷的动态堆叠和station/horizon-specific gating；当前可检验的新点是**会话信息可靠性驱动的低维门控与向M2回退**。

专家：M2和完整M3。门控器只允许使用issue-time可得的低维变量，例如connected数、current/pilot observed ratio、用户申报可用比例、M3 missingness摘要、M2/M3预测差及horizon。不允许测试误差、最终kWh、最终离开时间、未来到达/轨迹、离线异常原因或测试标签作输入。

开发阶段至少比较M2、完整M3、0.5简单平均、可靠性门控。若门控不能在开发集上稳定超过简单平均，或收益依赖高复杂度不可解释调参，则停止该方向，不消耗最终holdout。

## 7. 开发集获取代码的实际保护

PR #30没有把01/04/07/10永久加入默认生产月份。专用上下文运行时才临时安装四个月配置，并临时扩展已审季节获取/QA模块原先按值导入的月份allowlist；退出时精确恢复。

最终holdout 03/06/09/12不安装，CLI没有 `--month`/`--months` 任意覆盖参数。新开发月份若出现同步时间倒退等新的轨迹异常，默认QA失败，不能自动使用11月唯一3596秒特例。

下一次用户执行采用外置安全启动器：它从当前仓库只做 `git fetch origin main`，新建/复用一个**独立detached worktree**锁定PR #30已审HEAD，不切换或清理现有工作区；凭据只读本地 `ACN_API_TOKEN`；只输出脱敏汇总JSON。

## 8. 长期冻结的数据语义

当地月用 `America/Los_Angeles` 半开区间，内部连续UTC、900 s物理网格，carry-in由完整元数据识别。11月合法DST回拨保留4个额外格；唯一3596 s倒退轨迹按已批准规则隔离。

元数据正常的无效容器会话保留结构和coverage分母；current/pilot独立缺测。整段current不可观测与15 min格有正时长相交时，该格不得作为完整总电流标签，即使coverage>=90%。pilot-only缺失不否决有效current。缺测不是零，未知active不是确定未充电。

## 9. 资产保护

保留用户原main未提交修改、所有登记worktree和raw/interim/processed。保留运行后的 `evcf_seasonal_runner_v1_1`、`evcf_session_ablation_v1`、`evcf_forecast_combination_v1` 及各自 `local_runs/private`、binding、日志、原汇总、错误和恢复包。

不执行 `reset --hard`、`clean`、盲目stash或force push。开发集获取失败/中断时保留新worktree和已下载数据，不自动清理或盲目重启。

## 10. 下一步最小动作

1. 用户使用主控交付的安全启动器获取/QA开发集01/04/07/10；
2. 回传脱敏状态JSON；若任一月失败或出现新异常，先审查，不自动修数据或换月；
3. 获取通过后更新DATA_USAGE_LEDGER，并开发开发集processed快照/门控数据入口；
4. 在开发集选择可靠性门控；
5. 方法全部冻结后才建立最终holdout Issue并允许03/06/09/12进入独立验证。

## 11. 状态维护

任何数据授权、方法冻结、运行完成或结论变化必须在同一轮更新CURRENT_STATUS、HANDOFF及台账，并校对README/ROADMAP/code/README/索引。失效当前指令直接替换；历史证据保留在Git、Issue/PR和台账中。
