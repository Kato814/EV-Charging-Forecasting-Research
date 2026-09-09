# 当前状态｜充电站功率/负荷预测独立研究

更新日期：2026-09-09。本文件是当前状态唯一入口；历史执行记录见 [实验台账](docs/EXPERIMENT_LEDGER.md)，数据用途见 [数据台账](docs/DATA_USAGE_LEDGER.md)，接管规则见 [HANDOFF](HANDOFF.md)。

**通俗说明：方法开发集2019-01/04/07/10的raw与processed均已完成并PASS；固定M2/M3开发集OOS专家预测协议和代码也已完成审查并合入main。当前下一步是用户本地运行固定专家预测，得到M2、M3和0.5简单平均开发基线及私有预测缓存；可靠性门控尚未训练。最终holdout 2019-03/06/09/12继续封存。**

## 1. 当前研发任务

| 项目 | 当前状态 |
| --- | --- |
| 当前Issue | [#29 基于信息可靠性门控的M2/M3双专家预测](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29) |
| 当前阶段 | **模型开发**；当前子步骤为开发集M2/M3 OOS专家预测 |
| 开发集 | 2019-01/04/07/10；raw与processed均已验收 |
| 专家预测代码 | **PR #41已合并；允许本地执行** |
| 当前模型 | 固定HGB M2、固定HGB M3、0.5简单平均；门控尚未训练 |
| 最终holdout | **2019-03/06/09/12继续禁止访问** |
| 预测口径 | `station_current_mean_a`，单位A；kW未授权 |

## 2. 开发集processed已验收

用户回传 `evcf_development_preparation_status_20260909T044544Z.json`：

```text
status = COMPLETE
source status SHA256 = 4573b5e43094ebb8a3c85c71358aac8d93dd3e3926fe9b04366e9fe2a42dd153
processed code = c1ff4e675ae14e7667e0c6b7f887fb15319aff38
protocol SHA256 = 4f2baf0439202bc1db9771a0db530ad9823d9d1261bbcea4c914925beeea5fe1
metadata SHA256 = bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
```

| 月份 | sessions | valid90 / bins | formal / scheduled | processed snapshot SHA256 | 状态 |
| --- | ---: | ---: | ---: | --- | --- |
| 2019-01 | 1372 | 2970 / 2976 | 2836 / 2865 | `e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12` | PASS |
| 2019-04 | 1524 | 2772 / 2880 | 2552 / 2769 | `f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299` | PASS |
| 2019-07 | 1489 | 2931 / 2976 | 2742 / 2865 | `9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2` | PASS |
| 2019-10 | 1673 | 2943 / 2976 | 2742 / 2865 | `e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296` | PASS |

总计11616/11808个15 min格达到valid90，10872/11364个scheduled issue进入formal集合。四个月raw unchanged、trajectory/full-session quarantine均0、holdout未访问。四月power audit虽为 `KW_RECONSTRUCTION_CANDIDATE`，但本研究当前仍只授权A口径预测。

## 3. PR #41：固定开发集M2/M3 OOS专家预测

PR #41最终HEAD：

```text
ac4e4b2b75aa46429256b6a535e1e88a8a7a61f8
```

main合并提交：

```text
653cb447382044911ce655175239f52f83dc892a
```

最终CI：`1066 passed, 2 skipped`，compileall PASS，Ruff PASS。

冻结协议 `JPL_DEVELOPMENT_HGB_EXPERT_OOS_20260909_V1`：

1. 只读取01/04/07/10已验收processed snapshot；03/06/09/12不可访问；
2. M2/M3均使用5月已经选定的分tier×horizon HGB参数，开发月不重新搜索专家超参数；
3. horizon固定15/30/60/120/240 min；
4. 当地每月18日起进入OOS测试，每个当地午夜重训一次；
5. 每次训练仅使用同月 `issue < cutoff` 且 `issue+h <= cutoff` 的formal行，未来标签不得进入训练；
6. HGB保留raw NaN并追加冻结nullable missing indicators；无imputation、scaling、clipping或calibration；
7. M2/M3共享完全相同的测试行和truth，并同步计算0.5简单平均；
8. 完整逐点预测只保存在仓库外的本地私有缓存；GitHub/回传只允许脱敏聚合指标；
9. 本轮只训练专家模型，不训练可靠性门控，`gate_trained=false`。

CI历史中第二轮曾尝试将scikit-learn已有传递依赖 `threadpoolctl`直接加入冻结Gate1依赖清单；原仓库测试明确锁定该依赖合同，因此该改动已撤回。最终全绿版本没有改变既有Gate1依赖合同。

## 4. 当前方法假设

M2使用历史/日历与当前站级聚合状态；M3在M2上增加当前连接会话的合法细粒度状态。已有证据说明二者信息互补，但M3增量价值随horizon和会话信息可靠程度变化。

候选贡献聚焦**会话可观测性驱动的低维门控与向M2可解释回退**，而不是普通MoE/动态加权本身。开发阶段至少比较M2、M3、0.5简单平均和可靠性门控。若门控不能稳定超过简单平均，或收益依赖高复杂度不可解释调参，则停止该方向，不消耗最终holdout。

## 5. 数据分区继续冻结

- 已使用/探索：2019-02、05、08、11；
- 方法开发集：2019-01、04、07、10；raw/processed均完成；
- 最终独立保留集：2019-03、06、09、12；继续封存。

不根据后续模型成绩换月、删月或把已看数据重新包装为独立验证。

## 6. 当前本地动作

当前只授权一次**开发集固定专家OOS预测**：

- 新建独立detached code worktree锁定PR #41合并提交；
- 复用已有processed，不重做数据准备；
- 生成20个私有缓存（4个月×5时距，内含共同truth、M2/M3/0.5预测）；
- 私有缓存写到仓库外部本地保留目录，不进入任何worktree；
- 回传只上传 `evcf_development_expert_status_*.json`；
- 主控审查M2/M3/0.5基线后，才设计可靠性门控训练。

当前不恢复M4，不启动Gate2、概率预测、联邦学习或调度。

## 7. 资产保护与维护

保留原main未提交修改、所有worktree、raw/interim/processed、失败/诊断JSON和既有外置实验目录。新生成的开发集专家私有预测缓存同样必须完整保留，后续可靠性门控开发将复用它们。

禁止 `reset --hard`、`clean`、盲目stash和force push。每次本地运行完成、方法协议变化或结论变化，主控必须同轮更新CURRENT_STATUS、HANDOFF及相关台账。