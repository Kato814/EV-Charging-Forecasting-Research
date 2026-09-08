# 主控交付说明｜充电站功率/负荷预测独立研究

更新：2026-09-08。先读 [CURRENT_STATUS](CURRENT_STATUS.md)，再读本文、[实验台账](docs/EXPERIMENT_LEDGER.md)和[数据用途台账](docs/DATA_USAGE_LEDGER.md)。

## 1. 接管结论

**当前仍处于模型开发阶段。01/04/07/10 raw获取与全月QA已完成。首次processed准备失败已通过只读诊断定位为代码兼容性遗漏：`acn_jpl_gate1_prep`仍持有旧02/08/11 `SEASONAL_MONTHS`绑定。PR #37已修复、全量CI通过并合并。当前重新授权四个月processed准备；最终holdout仍封存，尚未训练开发集模型。**

当前唯一研发Issue为 [#29](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29)。主控负责协议、代码、审查和仓库维护；用户仅执行明确授权的本地Python命令。

## 2. 研究与数据边界

主目标保持 `station_current_mean_a`，单位A。M2=历史/日历+当前站级聚合状态；M3=M2+当前连接会话细粒度合法状态。M4历史负结果保留，不恢复主线。

数据分区固定：
- 已使用/探索：2019-02/05/08/11；
- 方法开发集：2019-01/04/07/10；
- 最终独立保留集：2019-03/06/09/12。

03/06/09/12在门控变量、模型、超参数、阈值、评价和停止规则全部冻结前不得获取时序或运行模型。

## 3. 版本状态

- PR #21已合并：5月pilot；
- PR #23已合并：季节数据/缺测记账；
- PR #30已合并：开发集raw获取入口；
- PR #34已合并：开发集processed准备入口与独立开发协议；
- PR #37已合并：开发月清洗校验兼容性修复。

PR #37固定身份：

```text
final HEAD e47f05cb7a663df9c599270ac939c9301d26840b
main merge c1ff4e675ae14e7667e0c6b7f887fb15319aff38
```

PR #37最终CI：

```text
1058 passed, 2 skipped
compileall PASS
Ruff PASS
```

开发集协议仍为 `code/configs/acn_jpl_development_prep_2019.yaml`，只绑定01/04/07/10。旧02/08/11季节YAML及11月唯一3596 s例外保持原身份，不扩展到开发月。

## 4. raw开发集已验收

冻结metadata源SHA256：

```text
bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
```

| 月份 | local | carry-in | combined | 有效日块 | QA |
| --- | ---: | ---: | ---: | ---: | --- |
| 2019-01 | 1372 | 0 | 1372 | 31/31 | PASS |
| 2019-04 | 1524 | 0 | 1524 | 30/30 | PASS |
| 2019-07 | 1489 | 0 | 1489 | 31/31 | PASS |
| 2019-10 | 1672 | 1 | 1673 | 31/31 | PASS |

四个月trajectory/full-session quarantine均为0。

## 5. 首次processed失败与只读诊断

首次 `evcf_dev_preparation_launcher_v1.py` 返回：

```text
status=INCOMPLETE
reason_code=DEVELOPMENT_PREPARATION_INCOMPLETE
preparation_reason_code=UNEXPECTED_ERROR
```

只读诊断文件 `evcf_development_preparation_diagnostic_20260908T141021Z.json`：

- `status=COMPLETED`；
- `diagnostic.status=DIAGNOSED`；
- `writes_suppressed=true`；
- 2019-01异常类型 `ValueError`；
- 调用栈落到 `evcf.data.acn_jpl_gate1_prep.validate_seasonal_cleaning_documents()`；
- 失败行对应 `config.month not in SEASONAL_MONTHS`；
- 四个月在首次失败后都没有interim/processed月份目录或processed manifest；
- `holdout_accessed=false`、`models_trained=false`。

因此根因被判定为PR #34开发上下文兼容列表遗漏，不是1月raw数据质量结论。

## 6. PR #37修复内容

`installed_development_month_contracts()` 现在把 `evcf.data.acn_jpl_gate1_prep` 与其他按值导入 `SEASONAL_MONTHS` 的已审模块一并临时扩展到01/04/07/10，并在上下文退出时恢复原02/08/11绑定。新增回归断言覆盖扩展和恢复。

未修改：
- 清洗/15 min/coverage/issue-time数值规则；
- 开发集YAML；
- trajectory quarantine策略；
- M1/M2/M3特征；
- holdout权限；
- 任何模型或既有结果。

## 7. 当前授权：processed重试

使用新的外置 `evcf_dev_preparation_launcher_v1_1.py`：

- 精确绑定PR #37 main合并提交；
- 使用新的 `-jpl-development-prep-code-v2` detached code worktree，旧PR #34代码worktree保留；
- 重试前再次验证metadata和四个月raw；
- 若任何开发月interim/processed目录已经出现则停止，不覆盖；
- 仅生成01/04/07/10的interim/processed、15 min、M1–M3和snapshot SHA；
- 不联网、不训练模型、不访问03/06/09/12；
- 只回传脱敏status JSON。

processed审查通过后，才进入M2/M3开发集预测和可靠性门控训练。

## 8. 方法方向与停止规则

现有证据支持M2/M3信息互补，M3增量价值随时距和会话信息可靠性变化。候选方法仍是**会话可观测性驱动的低维门控与向M2回退**；普通MoE/动态加权不作为创新。

若开发集上可靠性门控不能稳定超过0.5简单平均，或只能靠高复杂度不可解释调参取得收益，则停止该方向，不消耗最终holdout。

## 9. 资产保护

保留原main未提交修改、所有worktree、raw/interim/processed、旧失败/诊断JSON、三套外置实验目录及 `local_runs/private`。旧PR #34 preparation code worktree和新的v2 code worktree都不自动删除。

禁止 `reset --hard`、`clean`、盲目stash、force push和未经审查的重复运行。

## 10. 下一步

1. 用户执行v1.1 processed准备启动器；
2. 仅回传脱敏status JSON；
3. 主控审查四个月cleaning/coverage/leakage/snapshot SHA；
4. 通过后进入开发集M2/M3与可靠性门控训练；
5. 方法冻结后才允许最终holdout。
