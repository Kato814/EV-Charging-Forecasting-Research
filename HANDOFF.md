# 主控交付说明｜充电站功率/负荷预测独立研究

更新：2026-09-09。先读 [CURRENT_STATUS](CURRENT_STATUS.md)，再读本文、[实验台账](docs/EXPERIMENT_LEDGER.md)和[数据用途台账](docs/DATA_USAGE_LEDGER.md)。

## 1. 接管结论

**当前处于模型开发阶段。开发集2019-01/04/07/10的raw与processed均已完成并PASS；固定M2/M3 OOS专家预测协议已由PR #41冻结。首次v1本地预检因JSON标签键顺序兼容性错误在模型训练前安全停止，PR #43已修复并合入main。当前唯一授权动作是使用v1.1启动器重新执行开发集专家预测，形成M2、M3和0.5简单平均基线及私有逐点预测缓存；可靠性门控尚未训练。最终holdout 2019-03/06/09/12继续封存。**

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

## 3. 专家预测协议与代码身份

PR #41 main合并 `653cb447382044911ce655175239f52f83dc892a`；最终CI 1066 passed、2 skipped，compileall/Ruff PASS。

协议 `JPL_DEVELOPMENT_HGB_EXPERT_OOS_20260909_V1`：
- HGB M2/M3继续使用5月已选tier×horizon参数；开发月不重新调专家超参数；
- 15/30/60/120/240 min；当地18日起OOS；每个当地午夜重训；
- fit仅允许同月formal行，且 `issue < cutoff`、`issue+h <= cutoff`；
- HGB原NaN+冻结nullable indicators，无imputation/scaling/clipping/calibration；
- M2/M3完全共享测试行和truth，0.5平均同步计算；
- 逐点预测只保留在仓库外部私有缓存；公共/回传只用聚合指标；
- gate不在本轮训练。

May参数源manifest SHA：

```text
a43ac609629d0dfa1568ce19d8e51666cbeb8392d96cbe976927f9397f19cb0d
```

## 4. v1预检失败与PR #43兼容修复

首次v1启动器状态为 `STOPPED / DEVELOPMENT_PROCESSED_NOT_VERIFIED`。它在任何HGB拟合前停止：expert/gate均未训练，holdout未访问，未下载ACN数据，既有worktree保持不变。

根因不是processed损坏，而是PR #41读取器错误依赖JSON对象键顺序。processed准备器使用 `sort_keys=True` 写 `labels.jsonl.gz`，horizon键在磁盘上按字符串排序；读取器却要求固定插入顺序。PR #43改为验证精确horizon键集合，并继续按15/30/60/120/240固定顺序读取值；新增真实sorted-key回归测试和v1.1 CLI，不修改任何科学协议参数。

PR #43 main合并：

```text
7dda9d38a091f731c6f5c4ea74e293936996884c
```

最终CI：1068 passed、2 skipped，compileall/Ruff PASS。

**旧v1启动器已停用；后续只允许v1.1。**

## 5. 当前方法假设

已有5月、季节复核、消融和组合结果表明M2/M3互补，且M3额外价值随horizon/信息可靠性变化。候选创新只能落在**会话可观测性驱动的低维门控和信息不足时向M2回退**，不能把普通MoE/动态权重本身写成创新。

开发阶段至少比较M2、M3、0.5简单平均、可靠性门控。门控若不能稳定超过简单平均，或仅依赖复杂不可解释调参，则停止该方向，不消耗最终holdout。

## 6. 当前本地执行与保全

当前只运行一次v1.1固定专家OOS预测。启动器将：
1. 锁定PR #43 main merge代码；
2. 复核四个月processed manifest/snapshot SHA；
3. 不下载ACN数据、不改processed；
4. 训练日级滚动M2/M3 HGB专家并生成20个私有预测缓存；
5. 私有缓存保存于仓库外部本地目录；
6. 只回传脱敏 `evcf_development_expert_status_*.json`。

保留首次v1失败状态JSON、旧v1 code worktree、所有既有worktree/raw/interim/processed/失败诊断资料和外置运行目录。v1.1成功后的新私有缓存也必须保留，后续门控开发会复用。禁止 `reset --hard`、`clean`、盲目stash和force push。

当前不恢复M4，不启动Gate2、概率、联邦或调度。