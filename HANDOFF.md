# 主控交付说明｜充电站功率/负荷预测独立研究

更新：2026-09-09。先读 [CURRENT_STATUS](CURRENT_STATUS.md)，再读本文、[实验台账](docs/EXPERIMENT_LEDGER.md)和[数据用途台账](docs/DATA_USAGE_LEDGER.md)。

## 1. 接管结论

**当前处于模型开发阶段。开发集2019-01/04/07/10的raw获取与processed准备均已完成并通过；首次processed兼容性故障已由PR #37修复并在v1.1实机重试中关闭。下一步是建立开发集M2/M3专家预测、0.5简单平均强基线，并开发会话信息可靠性门控。最终holdout 2019-03/06/09/12继续封存。**

当前唯一研发Issue为 [#29](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29)。主控负责协议、代码、审查和仓库维护；用户仅执行明确授权的本地Python命令。

## 2. 研究与数据边界

主目标固定为 `station_current_mean_a`，单位A。M2=24 h历史/日历+当前站级聚合状态；M3=M2+当前连接会话细粒度合法状态。M4历史负结果保留，不恢复主线。

数据分区：
- 已使用/探索：2019-02/05/08/11；
- 方法开发集：2019-01/04/07/10；raw和processed均完成；
- 最终独立保留集：2019-03/06/09/12；方法冻结前不得获取时序或运行模型。

## 3. 开发集processed完成身份

用户回传 `evcf_development_preparation_status_20260909T044544Z.json`：

```text
source status SHA256 4573b5e43094ebb8a3c85c71358aac8d93dd3e3926fe9b04366e9fe2a42dd153
code commit c1ff4e675ae14e7667e0c6b7f887fb15319aff38
protocol SHA256 4f2baf0439202bc1db9771a0db530ad9823d9d1261bbcea4c914925beeea5fe1
metadata SHA256 bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
```

| 月份 | sessions | valid90 / bins | formal / scheduled | snapshot SHA256 | 状态 |
| --- | ---: | ---: | ---: | --- | --- |
| 2019-01 | 1372 | 2970 / 2976 | 2836 / 2865 | `e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12` | PASS |
| 2019-04 | 1524 | 2772 / 2880 | 2552 / 2769 | `f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299` | PASS |
| 2019-07 | 1489 | 2931 / 2976 | 2742 / 2865 | `9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2` | PASS |
| 2019-10 | 1673 | 2943 / 2976 | 2742 / 2865 | `e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296` | PASS |

总formal 10872 / scheduled 11364；valid90 11616 / 11808。四个月raw unchanged、trajectory/full-session quarantine均0、holdout未访问、模型未训练。

四个月power audit均为 `KW_RECONSTRUCTION_CANDIDATE`，但这不等于授权kW建模；当前预测仍仅使用A口径。

## 4. processed故障历史

v1首次准备失败并未生成四个月interim/processed残留。只读诊断定位为 `acn_jpl_gate1_prep` 旧02/08/11 `SEASONAL_MONTHS`按值绑定遗漏。PR #37只扩展并恢复这一临时开发月兼容绑定，未改变清洗、coverage、特征、quarantine或holdout规则；最终CI 1058 passed、2 skipped，compileall/Ruff PASS。v1.1随后完整PASS。

## 5. 已审实验结论

- 5月pilot：`PASS_ACTIVE_SESSION_DROP_M4`；
- 2/8/11季节复核：总体 `MIXED_SEASONAL_EVIDENCE`；
- 负值诊断：单纯置零不足以解释主要退化，负预测不是V2G测量证据；
- 会话分组消融：不支持统一删除整组；
- 预测组合：0.5简单平均是强基线，校准加权未稳定超过它。

因此当前方法假设是：**M2/M3信息互补，M3增量价值受horizon和会话可观测/可靠程度影响。**

## 6. 当前模型开发方向

候选方法采用标准MoE/gating结构，但普通动态加权不是创新点。门控只允许使用issue-time可得低维变量：connected数、current/pilot observed ratio、用户申报可用比例、M3 missingness摘要、M2/M3预测差及horizon等；不得使用测试误差、测试标签、最终kWh、未来离开/轨迹、未来到达结果或离线异常原因。

开发阶段至少比较：M2、完整M3、0.5简单平均、可靠性门控。若门控不能稳定超过简单平均，或必须靠高复杂度不可解释调参取得收益，则停止该方向，不消耗最终holdout。

## 7. 下一步最小动作

1. 主控冻结开发集M2/M3专家预测协议与内部开发切分；
2. 开发本地预测/缓存入口，固定HGB专家配置和共同有效样本；
3. 用户仅在明确授权后运行开发集专家预测；
4. 主控先审M2/M3/简单平均基线，再实现可靠性门控；
5. 门控方案冻结后才允许最终holdout。

当前不恢复M4，不启动Gate2、概率、联邦或调度。

## 8. 资产保护

保留原main未提交修改、所有worktree、raw/interim/processed、失败/诊断JSON、运行后的外置目录及 `local_runs/private`。禁止 `reset --hard`、`clean`、盲目stash和force push。