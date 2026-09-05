# 主控交付说明｜充电站负荷预测独立研究

交接日期：2026-09-05。仓库：`Kato814/EV-Charging-Forecasting-Research`（私有）。

本说明供新的 ChatGPT 主控窗口接替当前进度。它记录已核验事实、当前阻断与已下达任务，不授权重复执行。接管时重新读取远端，不把本文中的 HEAD 当作永远最新。

## 1. 接管结论

**当前不是“季节复核可以训练”，而是“季节数据准备 PR #23 正在修复缺测会话记账，等待新结果”。**

用户已把修订指令交给本地 Codex，Codex 正在处理。新主控不要重启研究讨论、重新下载数据、重新发出相同修复任务或提前合并。

- 当前 Issue：[#22](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/22)
- 当前 PR：[#23](https://github.com/Kato814/EV-Charging-Forecasting-Research/pull/23)
- 当前任务分支：`data/jpl-2019-seasonal-replication`
- 最近已审查 HEAD：`8c0eeeaff8367dba3c4790de79ba97a018022e0a`
- 该版执行提交：`7b5b6e60177c328666896e3f26fe9e037d34e8b7`
- 主控结论：`CHANGES_REQUIRED_INVALID_CONTAINER_ACCOUNTING`
- 审查原文：[review-5120653692](https://github.com/Kato814/EV-Charging-Forecasting-Research/pull/23#pullrequestreview-5120653692)
- Issue同步：[comment-5550826691](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/22#issuecomment-5550826691)

仓库整理与交接文档在独立 `docs/handoff-20260905` 分支完成，不向 Codex 数据分支写代码。文档合并不会改变实验基线；新主控应区分 main 最新文档提交和最后已验收实验提交。

## 2. 研究目标与不能继承的背景

本研究从零探索充电站功率/负荷预测的小而真实的问题，不参考其他既有充电站联邦预测论文的方法、代码或结果。不要引入三类型站点、联邦岭回归、旧论文指标、空间特征版本等无关项目内容。

用户不接受以“未见城市/未见站点/分布外泛化”作为论文核心创新。后续可连接优化调度，但现阶段优先验证预测问题和方法增量，不急于添加复杂深度骨干或联邦学习。

候选主线：发布时间已连接会话的剩余过程与未来到达会话具有不同可观测信息，是否适合双源建模。**已验证的仅是5月实时会话状态信息价值；双源分解优越性、概率场景质量、调度收益均未验证。**

## 3. 已验收里程碑

| 里程碑 | PR与合并提交 | 状态 |
| --- | --- | --- |
| JPL 5月完整时间序列获取 | #16 / `c7300c3d80727e5e34d4c913dc4e107c6af456fb` | 已合并 |
| 5月清洗、语义、15 min和M1–M4准备 | #18 / `4e3b189f92f056b547167e8e54351f8cd09ff3cc` | 已合并 |
| 5月确定性 Gate 1 pilot | #21 / `c2af2cdf4ecf5dad059d2ac92e929df8df35d42b` | 已合并、筛选通过 |
| 2/8/11月数据准备 | #23 / 上次审查HEAD `8c0eeea` | 未合并、修复中 |

PR #21 是最后已验收的实验基线。Issue #19是实际执行的pilot协议；Issue #20是重复/未执行的另一版设计，已关闭，不得要求Codex补跑其概率指标或不同切分来验收 #21。

## 4. 数据对象、时间与单位

主开发站点 JPL；Caltech、Office001仅保留已有审计/候选复核地位，不追加下载。ACN `chargingCurrent`是电流，`pilotSignal`是导引/控制量，不是直接实测kW。

全部月份按 `America/Los_Angeles` 当地月半开区间取会话，内部UTC、900 s物理网格。UTC月计数与当地月计数不得混用。carry-in由完整历史元数据识别，不靠任意7天缓冲估计。

| 月份 | 当地月会话 | carry-in | 获取对象 | 物理15 min格 |
| --- | ---: | ---: | ---: | ---: |
| 2019-05 | 1644 | 1 | 1645 | 2976 |
| 2019-02 | 1288 | 1 | 1289 | 2688 |
| 2019-08 | 1509 | 0 | 1509 | 2976 |
| 2019-11 | 1353 | 1 | 1354 | 2884 |

11月边界为 `[2019-11-01T00:00:00-07:00, 2019-12-01T00:00:00-08:00)`，合法DST回拨产生4个额外网格，不能压成2880格。确认见 [DST评论](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/22#issuecomment-5509026023)。

主建模目标：`station_current_mean_a`。5月仅允许 `A × 0.208` 的名义208 V重构量/等价误差，不能称为直接实测功率。2/8月在修正前报告为 `KW_RECONSTRUCTION_CANDIDATE`；11月为 `CURRENT_PROXY_ONLY`。所有季节月份尚未统一授权重构kW列。

固定网络证据：`zach401/acnportal` 的 `14e723b11339e56ca3afd2bf4969f9e4bc8c2623`，JPL默认208 V。最终 `kWhDelivered` 只能用于离线语义核验，不能成为在线输入或逐测试会话校准器。不要把能量审计误差小直接等同于全部标签已获准。

## 5. 已验收的5月实验

数据snapshot：`7066ffc8ba42a98f73246acfbc62352fe55a1433a43cba80957c6034e3aeaa5d`。

2853个五时域公共样本；分组计数为训练1248、验证276、测试1329。实际各时域拟合样本还按标签可用时间筛选，不能只看分组计数。训练5月2–14日，验证15–17日，滚动测试18–31日共14个当地日。

- M1：24 h站级历史与日历、mask。
- M2：M1 + 当前connected/active、聚合电流、观测率、pilot摘要。
- M3：M2 + 当前连接会话合法状态的固定池化。
- M4-lite：M3 + 短窗轨迹派生统计；本轮不保留，不代表所有轨迹模型永远无价值。

模型为Ridge和HGB，各时域独立建模。超参数仅由验证段选择；每天午夜重拟合使用已可得标签；当前日或未来标签不得进入训练。目标为 `[issue+h-15min, issue+h)` 的均值，标签可用时刻为 `issue+h`。实际 #21 代码按单时域可用性筛选，不能误写成统一排除所有4 h标签的另一套旧协议。

| HGB M3相对M2的MAE改善 | 15 min | 30 min | 60 min | 120 min | 240 min |
| --- | ---: | ---: | ---: | ---: | ---: |
| 改善率 | 11.226% | 14.503% | 18.939% | 14.624% | 5.571% |

12/14测试日M3优于M2；HGB-M4-lite近端分别退化5.055%/2.586%/5.581%。最终 `PASS_ACTIVE_SESSION_DROP_M4`。日块bootstrap中的正差定义为父层误差减子层误差，不要反转CI符号。

证据：[PR #21](https://github.com/Kato814/EV-Charging-Forecasting-Research/pull/21)、[固定版本结果目录](https://github.com/Kato814/EV-Charging-Forecasting-Research/tree/c2af2cdf4ecf5dad059d2ac92e929df8df35d42b/outputs/gate1_pilot/jpl_2019-05)。原13件发布文件不覆盖、不删掉M4负结果。两遍重复运行和531项测试是历史报告/CI证据，不是新窗口重跑声明。

## 6. 季节准备：修正前参考，不能当最终验收值

以下来自 #23 的 `8c0eeea`，用于前后对账，不用于锁死新样本数。

| 月份 | valid90 | scheduled/formal | 原功率状态 |
| --- | ---: | --- | --- |
| 02 | 2640/2688 | 2577/2439 | 候选重构 |
| 08 | 2954/2976 | 2865/2784 | 候选重构 |
| 11 | 2769/2884 | 2773/2524 | 电流代理 |

修正前snapshot：

```text
02 436db41adca64af2b0758916a83480035638d1912e8ce90c8239186988b6711b
08 50dd7ce3f6f21fa66bc0b520201f88e6ddf061185f040424a87e8b327770cc11
11 0fcec7d93da69ddbb9674e432db88c4a82801370577a1e2a5e020b9b5d6d9dda
```

旧报告37件、82,495 bytes、本地897 tests、CI 895+2 skipped，均只描述旧版本。raw下载完整性与已获取文件可保留，但新processed快照及其验收要重做。不要以这些旧测试、文件数量、formal数或SHA阻止必要修正。

## 7. 正在修的具体问题与授权范围

问题位置：`code/src/evcf/data/acn_jpl_seasonal_prep.py::_prepare_verified_month`。旧版把 `current_invalid_ordinals | pilot_invalid_ordinals` 从 `valid_raw_records` 整体过滤，后续 `cleaned`、aggregate和snapshots缺少2月2个、11月6个会话的结构状态及coverage分母。

**A. 普通无效容器（2+6个）**

先核验connection/disconnect及官方元数据一致性。元数据正常则保留结构占位对象、connected/arrival/disconnect/carry-in与连接时间覆盖分母；current和pilot独立判断，一条无效不能删除另一条有效分支。无效分支为缺失，不造零。元数据也不可靠则诊断并停止相关月份，不猜时窗。

**B. 11月同步UTC倒退3596 s（另1个）**

保持此前 [trajectory quarantine授权](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/22#issuecomment-5519192500)：raw、manifest、时间戳不动，不排序/平移/插值。元数据正常则保留结构，current/pilot整段不可观测，继续计入coverage分母。不要混淆合法DST与该异常。

**C. 完整目标门禁**

已知某会话整段current不可观测且与15 min格相交，就标记 `known_incomplete_current`，该格不能作为完整站级总电流正式标签，即使session-seconds coverage≥90%。观测部分之和只能另名作为诊断；仅pilot缺失不自动否决current标签。不得按coverage放大电流或用最终电量补轨迹。未知active不能作确定不在充。

该规则是已下达的前瞻质量修订，不是新窗口额外加码。离线QA原因与事后信息不能作为预测特征；快照仍需严格issue-time截断。

**D. 修订交付与复核**

1. raw/manifest/时间戳前后哈希不变，获取分母仍为1289/1509/1354。
2. 分别对账获取、结构保留、current可用、pilot可用、无效容器占位、倒退隔离、元数据异常。
3. 重算受影响2/11月：15 min、coverage、history mask、M2/M3、五时域公共样本、功率审计分母、snapshot与发布清单。
4. 报告受影响bin、正式目标排除、formal数变化、connected变化、前后SHA映射。8月做数值回归，May原证据不覆盖。溯源元数据变更可导致新清单SHA变化。
5. 合成测试须包含：两会话一条缺测时coverage分母为两辆；只有pilot坏时保留current；仅未知current不能输出有效零标签；高并发下仍触发完整目标门禁；合法实测零不同于缺测；无未来信息；raw不变。
6. 同一分支/PR修订，不重下、不训练、不恢复M4。37件旧数量不是必须维持的上限；新增必要对账时同步白名单与SHA。

新主控须读实际代码和新汇总，而不只接受 `PASS` 字样。修订完成但仍有数据异常时，允许诚实保留条件通过；不因门控名称要求强行放宽阈值。

## 8. 工作流与本地资产

主控负责研究口径、远端代码/Issue/PR审查与合并；本地Codex处理私有raw、CPU/GPU任务并提交去标识化证据；GitHub Actions仅轻量CI。主控无法从GitHub独立读取未上传的raw，报告中须区分“审查提交证据”和“本地复跑”。

本地Windows工作站有RTX 5080（历史报告15.92 GiB）。已冻结CPU pilot为Python 3.11.16、scikit-learn 1.9.0，以锁文件和运行manifest为准，不因接管自动升级。旧Python 3.13/PyTorch nightly只曾用于环境识别/处理，不是已冻结正式GPU训练环境；Issue #15仍属后续工作。

用户原main工作区存在未提交修改，必须原样保留。当前任务worktree目录名为 `EV-Charging-Forecasting-Research-jpl-2019-05-full-ts`，虽名字含5月，已被继续用于后续分支。**raw/interim/processed可能仍在这个worktree里，绝不可因旧PR已合并而删除它。** 不执行 `git clean`、`reset --hard`、批量stash、force push，不动用户已有 `data.zip`。

相对目录：5月raw `data/raw/acn/jpl/gate0/2019-05-full-ts/`；季节raw优先定位 `data/raw/acn/jpl/seasonal/`；实际interim/processed、检查点和日志位置由本地运行参数/manifest核验，不猜绝对路径。Token只在本地环境，不发对话、不写Git。所有大表、模型、完整预测、私有索引保持本地。

主控文档分支合并后，Codex不要在运行中切分支或拉取。待任务结束、工作区干净，再核对远端，非破坏性合入文档main；分叉不保证能fast-forward，禁止为同步强制重置。只变文档时不需要重复下载或训练。

## 9. 后续顺序与尚未冻结的决定

先验收 #23 修正后的当前数据管线，再新建/冻结 M2–M3 季节复核任务。已有倾向是固定5月选定的HGB超参数、以各月自身可用历史滚动拟合，而不是5月已训练模型直接预测2月。该倾向不等于完整协议已授权。

新协议仍须明确：每月训练/验证/测试边界、标签可用时刻、共同样本、日块统计、节假日/缺测覆盖披露、11月电流代理限制与成功/停止判据。2月早于5月，用5月开发出的算法配置做2月复现实验应说明是回溯方法复核，不能包装成真实部署时序或分布外泛化成果。

季节复核完成后才决定是否继续双源分解（Gate 2）、概率预测和调度接口。增加会话状态有效不等于双源拆分一定有效。调度/联邦均未实现；不要引用其他项目结果填补。

## 10. 新窗口最小接管动作

先读 CURRENT_STATUS.md、本文、PR #23最新HEAD/审查与Issue #22最新评论。然后回复四项：当前任务、最后已验收基线、阻断与未授权事项、下一复核所需证据。若Codex尚未反馈新结果，保持当前任务不变；若已有修订，比较最新HEAD与8c0eeea，复核本说明第7节，再决定合并或继续修订。

权限或工具读取失败时如实说明，不能声称已合并、已重跑或已看到本地文件。历史文献/旧任务定位见 [仓库索引](docs/REPOSITORY_INDEX.md)。
