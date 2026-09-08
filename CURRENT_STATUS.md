# 当前状态｜充电站功率/负荷预测独立研究

更新日期：2026-09-08。本文件是当前状态的唯一入口；历史执行记录见 [实验台账](docs/EXPERIMENT_LEDGER.md)，数据用途见 [数据台账](docs/DATA_USAGE_LEDGER.md)，接管规则见 [HANDOFF](HANDOFF.md)。

**通俗说明：当前仍处于模型开发阶段。方法开发月份2019-01/04/07/10的raw已经全部获取并通过全月QA；开发集专用的数据准备代码和协议也已经完成审查并合入main。下一步是用户本地生成四个月的interim/processed、15 min聚合和M1–M3快照，完成后才开始可靠性门控模型开发。最终验证月份2019-03/06/09/12继续封存。**

## 1. 当前唯一研发任务

| 项目 | 当前状态 |
| --- | --- |
| 当前Issue | [#29 基于信息可靠性门控的M2/M3双专家预测](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29) |
| 当前阶段 | **模型开发**；当前子步骤为开发集本地数据准备 |
| 基础专家 | M2：历史/日历+当前站级聚合状态；M3：M2+当前连接会话细粒度合法状态 |
| 门控方向 | issue-time可得的会话观测完整度、连接规模、预测时距、M2/M3预测差等低维变量决定M3权重；信息不足时向M2回退 |
| 强基线 | M2、完整M3、0.5简单平均 |
| 开发集raw | **2019-01/04/07/10 已获取并QA PASS** |
| 开发集准备代码 | **PR #34已合并，等待本地执行** |
| 最终holdout | 2019-03/06/09/12；仍禁止时序获取和模型运行 |
| 模型训练 | 当前尚未开始新开发集模型训练 |

## 2. 开发集raw获取已验收

回传文件 `evcf_development_acquisition_status_20260907T182836Z.json` 状态为 `COMPLETE`。冻结完整历史metadata源SHA256继续匹配：

```text
bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
```

| 月份 | local | carry-in | combined | 有效日块 | QA |
| --- | ---: | ---: | ---: | ---: | --- |
| 2019-01 | 1372 | 0 | 1372 | 31/31 | PASS |
| 2019-04 | 1524 | 0 | 1524 | 30/30 | PASS |
| 2019-07 | 1489 | 0 | 1489 | 31/31 | PASS |
| 2019-10 | 1672 | 1 | 1673 | 31/31 | PASS |

四个月 `trajectory_quarantine_count=0`、`full_session_quarantine_count=0`，没有模型训练或processed输出，`holdout_accessed=false`。`SOURCE_LAYOUT=3`/`SOURCE_MANIFEST=3`仅是其他metadata候选被拒绝的筛选诊断，不是月份运行失败。

## 3. PR #34：开发集专用数据准备协议与入口

PR #34最终HEAD：

```text
75590bf788712aaad3138367fe9e470b11777644
```

main合并提交：

```text
2643e15a7099b5b25ec0d4f8d22ee4195ac4b6f1
```

最终CI：`1058 passed, 2 skipped`，`compileall PASS`，`Ruff PASS`。

关键设计：

1. 新增 `code/configs/acn_jpl_development_prep_2019.yaml`，协议身份只对应01/04/07/10；
2. 清洗、15 min聚合、snapshot和M1–M3特征数值规则与已审季节单月路径一致；
3. 四个开发月trajectory/full-session quarantine期望均为0；发现新同步时间倒退即fail-closed；
4. 只生成本地ignored的interim/processed和脱敏汇总，不创建旧02/08/11的37件季节发布包；
5. 旧 `acn_jpl_seasonal_prep_2019.yaml` 保持其02/08/11、11月唯一3596 s例外和历史发布身份，不被改写；
6. 最终holdout 03/06/09/12仍不安装、不授权；
7. 不训练模型、不重新下载raw。

第一版代码曾准备直接复用旧季节YAML。主控在任何本地processed结果产生之前否决了这一协议身份，并改为独立开发集YAML；这是预运行协议修正，不是依据模型结果调整。

## 4. 数据分区继续冻结

- 已使用/探索：2019-02、05、08、11；
- **方法开发集：2019-01、04、07、10**，raw已获取，允许数据准备和门控开发；
- **最终独立保留集：2019-03、06、09、12**，在门控变量、模型、超参数、阈值、非负处理、评价、统计和停止规则全部冻结前不得获取时序或运行模型。

不根据后续预测表现换月。

## 5. 已有研究结论

- 5月pilot：`PASS_ACTIVE_SESSION_DROP_M4`；M3近端有增量价值，M4-lite退出主线。
- 2/8/11季节复核：总体 `MIXED_SEASONAL_EVIDENCE`。
- 负值诊断：存在非微小负预测，但仅置零不能解释主要M3退化；负预测不是V2G测量证据。
- 会话分组消融：不支持统一删除实时状态、进度或用户申报任一整组。
- 预测组合：0.5简单平均相对M2的15个“月份×时距”MAE均下降，但相对M3非全面占优；校准权重未稳定胜过简单平均。

因此当前假设是：M2/M3信息互补，而M3增量价值随时距和会话信息可靠性变化。普通MoE/动态加权本身不是创新；当前可检验贡献是**会话可观测性驱动的低维门控与向M2回退**。

若开发集上可靠性门控不能稳定超过简单平均，或只能靠高复杂度不可解释调参取得收益，则停止该方向，不消耗最终holdout。

## 6. 下一步与资产保护

下一步只运行PR #34合并后的开发集准备入口：复用已有raw worktree，生成01/04/07/10的interim/processed、15 min聚合、M1–M3快照与processed SHA。完成并审查后再进入模型训练。

不重下任何已完成raw；不切换/清理已有数据worktree；保留原main未提交修改、旧季节worktree和三套外置实验目录及其 `local_runs/private`。不执行 `reset --hard`、`clean`、盲目stash或force push。

不恢复M4，不启动Gate2、概率预测、联邦学习或调度。

## 7. 状态维护规则

每次新增数据授权、数据准备完成、方法冻结、实验完成、故障恢复或结论变化，主控必须在同轮更新本页、HANDOFF及相关台账，并校对README/ROADMAP/code/README/索引。失效当前指令直接替换；历史证据通过Git历史、Issue/PR和台账保留。
