# 主控交付说明｜充电站功率/负荷预测独立研究

更新：2026-09-09。先读 [CURRENT_STATUS](CURRENT_STATUS.md)，再读本文、[实验台账](docs/EXPERIMENT_LEDGER.md)和[数据用途台账](docs/DATA_USAGE_LEDGER.md)。

## 1. 接管结论

**当前处于模型开发阶段。开发集2019-01/04/07/10的raw与processed均已完成并PASS；固定M2/M3 OOS专家预测协议与入口已由PR #41合并。当前授权用户本地运行一次开发集专家预测，形成M2、M3和0.5简单平均基线及私有逐点预测缓存；可靠性门控尚未训练。最终holdout 2019-03/06/09/12继续封存。**

当前唯一研发Issue为 [#29](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29)。主控负责协议、代码、审查和仓库维护；用户仅执行明确授权的本地Python命令。

## 2. 数据与目标边界

目标固定为 `station_current_mean_a`，单位A。M2=24 h历史/日历+当前站级聚合状态；M3=M2+当前连接会话细粒度合法状态。

数据分区：
- 已使用/探索：2019-02/05/08/11；
- 方法开发集：2019-01/04/07/10；raw与processed均完成；
- 最终独立保留集：2019-03/06/09/12；方法冻结前不得访问。

四个开发月processed snapshot SHA：

```text
2019-01 e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12
2019-04 f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299
2019-07 9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2
2019-10 e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296
```

## 3. PR #41专家预测协议

PR #41最终HEAD `ac4e4b2b75aa46429256b6a535e1e88a8a7a61f8`，main合并 `653cb447382044911ce655175239f52f83dc892a`。最终CI：1066 passed、2 skipped，compileall和Ruff均PASS。

协议 `JPL_DEVELOPMENT_HGB_EXPERT_OOS_20260909_V1`：
- HGB M2/M3继续使用5月已选的tier×horizon参数；开发月不重新调专家超参数；
- 15/30/60/120/240 min；当地18日起OOS；每个当地午夜重训；
- fit仅允许同月formal行，且 `issue < cutoff`、`issue+h <= cutoff`；
- HGB原NaN+冻结nullable indicators，无imputation/scaling/clipping/calibration；
- M2/M3完全共享测试行和truth，0.5平均同步计算；
- 逐点预测只保留在仓库外部私有缓存；公共/回传只用聚合指标；
- gate不在本轮训练。

冻结May参数源manifest SHA继续为：

```text
a43ac609629d0dfa1568ce19d8e51666cbeb8392d96cbe976927f9397f19cb0d
```

## 4. 当前方法假设

已有5月、季节复核、消融和组合结果表明M2/M3互补，且M3额外价值随horizon/信息可靠性变化。候选创新只能落在**会话可观测性驱动的低维门控和信息不足时向M2回退**，不能把普通MoE/动态权重本身写成创新。

开发阶段至少比较M2、M3、0.5简单平均、可靠性门控。门控若不能稳定超过简单平均，或仅依赖复杂不可解释调参，则停止该方向，不消耗最终holdout。

## 5. 当前本地执行与保全

当前只运行一次固定专家OOS预测。启动器将：
1. 锁定PR #41 main merge代码；
2. 复核四个月processed manifest/snapshot SHA；
3. 不下载ACN数据、不改processed；
4. 训练日级滚动M2/M3 HGB专家并生成20个私有预测缓存；
5. 私有缓存保存于仓库外部本地目录；
6. 只回传脱敏 `evcf_development_expert_status_*.json`。

新私有缓存必须保留，后续门控开发会复用。不要删除任何既有worktree/raw/interim/processed/失败诊断JSON或外置运行目录。禁止 `reset --hard`、`clean`、盲目stash和force push。

当前不恢复M4，不启动Gate2、概率、联邦或调度。