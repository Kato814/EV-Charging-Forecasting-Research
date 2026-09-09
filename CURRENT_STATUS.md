# 当前状态｜充电站功率/负荷预测独立研究

更新日期：2026-09-09。本文件是当前状态唯一入口；历史执行记录见 [实验台账](docs/EXPERIMENT_LEDGER.md)，数据用途见 [数据台账](docs/DATA_USAGE_LEDGER.md)，接管规则见 [HANDOFF](HANDOFF.md)。

**通俗说明：方法开发集2019-01/04/07/10的raw与processed均已完成并PASS。固定M2/M3开发集OOS专家协议已冻结。v1和v1.1两次本地启动均在有效模型结果产生前安全停止：v1暴露JSON标签键顺序读取bug，v1.1进一步暴露Windows CRLF导致的实现身份误判。PR #43和PR #45已分别修复。当前唯一授权入口为v1.2启动器；可靠性门控尚未训练，最终holdout 2019-03/06/09/12继续封存。**

## 1. 当前研发任务

| 项目 | 当前状态 |
| --- | --- |
| 当前Issue | [#29 基于信息可靠性门控的M2/M3双专家预测](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29) |
| 当前阶段 | **模型开发**；当前子步骤为开发集M2/M3 OOS专家预测重试 |
| 开发集 | 2019-01/04/07/10；raw与processed均已验收 |
| 专家协议基础实现 | PR #41；main `653cb447382044911ce655175239f52f83dc892a` |
| JSON键顺序修复 | PR #43；main `7dda9d38a091f731c6f5c4ea74e293936996884c` |
| Windows EOL身份校验修复 | **PR #45；main `e5fe6d0aee9035374b6fb3240d3c5ebe2f1b7df7`** |
| 当前模型 | 固定HGB M2、固定HGB M3、0.5简单平均；门控尚未训练 |
| 当前授权入口 | **仅 `evcf_dev_expert_launcher_v1_2.py`；v1/v1.1停用** |
| 最终holdout | **2019-03/06/09/12继续禁止访问** |
| 预测口径 | `station_current_mean_a`，单位A；kW未授权 |

## 2. 开发集processed身份

```text
processed code = c1ff4e675ae14e7667e0c6b7f887fb15319aff38
processed protocol SHA256 = 4f2baf0439202bc1db9771a0db530ad9823d9d1261bbcea4c914925beeea5fe1
metadata SHA256 = bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
```

| 月份 | sessions | valid90 / bins | formal / scheduled | processed snapshot SHA256 | 状态 |
| --- | ---: | ---: | ---: | --- | --- |
| 2019-01 | 1372 | 2970 / 2976 | 2836 / 2865 | `e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12` | PASS |
| 2019-04 | 1524 | 2772 / 2880 | 2552 / 2769 | `f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299` | PASS |
| 2019-07 | 1489 | 2931 / 2976 | 2742 / 2865 | `9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2` | PASS |
| 2019-10 | 1673 | 2943 / 2976 | 2742 / 2865 | `e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296` | PASS |

总计11616/11808个15 min格达到valid90，10872/11364个scheduled issue进入formal集合。raw unchanged，trajectory/full-session quarantine均0。四个月power audit虽为 `KW_RECONSTRUCTION_CANDIDATE`，当前仍只授权A口径预测。

## 3. 固定M2/M3 OOS专家协议

协议 `JPL_DEVELOPMENT_HGB_EXPERT_OOS_20260909_V1` 保持不变：M2/M3使用5月已选tier×horizon HGB参数；horizon=15/30/60/120/240 min；每月当地18日起OOS、当地午夜日级重训；fit仅使用同月 `issue < cutoff` 且 `issue+h <= cutoff` 的formal行；raw NaN与冻结missing indicators保持；无imputation/scaling/clipping/calibration；M2/M3共享相同测试行和truth，0.5简单平均同步计算；完整逐点预测仅保存在仓库外本地私有缓存；本轮不训练可靠性门控。

May参数源manifest SHA256：

```text
a43ac609629d0dfa1568ce19d8e51666cbeb8392d96cbe976927f9397f19cb0d
```

## 4. 两次本地预检故障与修复

### v1：JSON对象键顺序
v1以 `DEVELOPMENT_PROCESSED_NOT_VERIFIED` 在模型拟合前停止。根因是processed使用 `sort_keys=True` 写 `labels.jsonl.gz`，而PR #41读取器错误依赖JSON对象键顺序。PR #43改为验证精确horizon键集合，并始终按15/30/60/120/240取值。PR #43 CI：1068 passed、2 skipped，compileall/Ruff PASS。

### v1.1：Windows EOL实现身份误判
v1.1已通过四个月processed与环境预检，但在正式专家入口的实现身份检查处以 `IMPLEMENTATION_DRIFT` 停止。该次 `expert_models_persisted=false`、`gate_trained=false`、`holdout_accessed=false`，processed unchanged。

根因是原实现用 `git show` 的LF blob字节直接比较Windows worktree文件字节；Git在Windows可合法物化CRLF，因此干净checkout会被误判为漂移。PR #45改为：精确HEAD + tracked regular-file存在 + `git diff --quiet --no-ext-diff <commit> -- <paths>` 的Git规范化语义。真实内容变化和错误HEAD仍然失败。新增回归测试覆盖CRLF-only、真实内容变化、错误HEAD三种情况。

PR #45 main：

```text
e5fe6d0aee9035374b6fb3240d3c5ebe2f1b7df7
```

最终CI：`1071 passed, 2 skipped`，compileall PASS，Ruff PASS。

两次失败均不改变processed、不访问最终holdout，也没有形成可用于研究结论的专家预测结果。

## 5. 当前方法假设与停止规则

M2使用历史/日历与当前站级聚合状态；M3在M2上增加当前连接会话合法细粒度状态。候选贡献聚焦**会话可观测性驱动的低维门控与向M2可解释回退**，普通MoE/动态加权不作为创新。

开发阶段至少比较M2、M3、0.5简单平均和可靠性门控。若门控不能稳定超过简单平均，或收益依赖高复杂度不可解释调参，则停止该方向，不消耗最终holdout。

## 6. 数据分区继续冻结

- 已使用/探索：2019-02、05、08、11；
- 方法开发集：2019-01、04、07、10；raw/processed均完成；
- 最终独立保留集：2019-03、06、09、12；继续封存。

不根据后续模型成绩换月、删月或把已看数据重新包装为独立验证。

## 7. 当前唯一本地动作

只授权 `evcf_dev_expert_launcher_v1_2.py`：

```text
launcher SHA256 = 42f4bee442b1586330344b15073079dab70fa093ee070c9131fcf5444e0d7abf
code commit = e5fe6d0aee9035374b6fb3240d3c5ebe2f1b7df7
```

v1.2使用新的 `code-v3` detached worktree，并将新私有预测缓存写入仓库外新的 `...jpl-development-expert-runs-v2` 目录。v1/v1.1启动器均停用，不得再次执行。成功后只回传 `evcf_development_expert_status_*.json`；20个私有`.npz`和`private_manifest.json`必须本地保留。

## 8. 资产保护与维护

保留原main未提交修改、所有worktree、raw/interim/processed、v1/v1.1失败状态JSON和既有外置实验目录。禁止 `reset --hard`、`clean`、盲目stash和force push。每次本地运行完成、方法协议或结论变化，主控必须同轮更新CURRENT_STATUS、HANDOFF及相关台账。
