# 主控交付说明｜充电站功率/负荷预测独立研究

更新：2026-09-09。先读 [CURRENT_STATUS](CURRENT_STATUS.md)，再读本文、[实验台账](docs/EXPERIMENT_LEDGER.md)和[数据用途台账](docs/DATA_USAGE_LEDGER.md)。

## 1. 接管结论

**当前处于模型开发阶段。开发集2019-01/04/07/10的raw与processed均已完成并PASS；M2/M3固定OOS专家协议保持不变。v1与v1.1两次本地启动均在形成有效专家结果前安全停止：v1为JSON标签键顺序读取bug，v1.1为Windows CRLF导致的实现身份误判。PR #43和PR #45已分别修复。当前唯一授权动作是使用v1.2启动器重新执行开发集专家预测；可靠性门控尚未训练，最终holdout 2019-03/06/09/12继续封存。**

当前唯一研发Issue为 [#29](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29)。主控负责协议、代码、审查和仓库维护；用户仅执行明确授权的本地Python命令。

## 2. 数据与目标边界

目标固定为 `station_current_mean_a`，单位A。M2=24 h历史/日历+当前站级聚合状态；M3=M2+当前连接会话细粒度合法状态。

数据分区：
- 已使用/探索：2019-02/05/08/11；
- 方法开发集：2019-01/04/07/10；raw与processed均完成；
- 最终独立保留集：2019-03/06/09/12；方法冻结前不得访问。

开发月snapshot SHA保持：

```text
2019-01 e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12
2019-04 f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299
2019-07 9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2
2019-10 e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296
```

## 3. 专家预测科学协议

协议 `JPL_DEVELOPMENT_HGB_EXPERT_OOS_20260909_V1` 不变：M2/M3沿用5月已选tier×horizon HGB参数；15/30/60/120/240 min；每月当地18日起OOS、当地午夜日级重训；fit仅使用同月 `issue < cutoff` 且 `issue+h <= cutoff` 的formal行；无imputation/scaling/clipping/calibration；M2/M3共享测试行和truth；0.5平均同步计算；逐点预测仅外置本地缓存；本轮不训练gate。

May参数源manifest SHA：

```text
a43ac609629d0dfa1568ce19d8e51666cbeb8392d96cbe976927f9397f19cb0d
```

## 4. 专家本地启动故障链

### v1
`STOPPED / DEVELOPMENT_PROCESSED_NOT_VERIFIED`。根因是读取器错误依赖JSON对象键顺序。PR #43改为验证精确horizon键集合并按固定horizon顺序读取。main `7dda9d38a091f731c6f5c4ea74e293936996884c`；CI 1068 passed、2 skipped。

### v1.1
四个月processed与环境预检均PASS，随后在实现身份校验处以 `IMPLEMENTATION_DRIFT` 停止。没有持久化专家模型、没有训练gate、没有holdout访问，processed保持不变。

根因是Windows Git可把LF仓库文本合法检出为CRLF，而旧校验用 `git show` blob原始字节与working-tree原始字节直接比较。PR #45改为精确HEAD + tracked regular-file存在 + Git规范化 `git diff --quiet`。CRLF-only通过，真实内容修改与错误HEAD继续fail closed。

PR #45 main：

```text
e5fe6d0aee9035374b6fb3240d3c5ebe2f1b7df7
```

最终CI：1071 passed、2 skipped，compileall/Ruff PASS。

v1与v1.1均退役，不得重跑。

## 5. 当前方法假设

候选贡献仅定位为**会话可观测性/可靠性驱动的低维门控与信息不足时向M2回退**，普通MoE、动态权重或简单平均本身不作为创新。若可靠性门控不能稳定超过0.5简单平均，或收益依赖复杂不可解释调参，则停止该方向，不消耗最终holdout。

## 6. 当前唯一本地执行

只允许：

```text
evcf_dev_expert_launcher_v1_2.py
SHA256 42f4bee442b1586330344b15073079dab70fa093ee070c9131fcf5444e0d7abf
code commit e5fe6d0aee9035374b6fb3240d3c5ebe2f1b7df7
```

v1.2创建新的 `code-v3` detached worktree，并将私有预测写入仓库外新的 `...jpl-development-expert-runs-v2` 目录。成功后只回传脱敏状态JSON；20个`.npz`和`private_manifest.json`必须原地保留，后续门控开发复用。

保留所有既有worktree、raw/interim/processed、v1/v1.1失败状态JSON和外置目录。禁止 `reset --hard`、`clean`、盲目stash和force push。当前不恢复M4，不启动Gate2、概率、联邦或调度。
