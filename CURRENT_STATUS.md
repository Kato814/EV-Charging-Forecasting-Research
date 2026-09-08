# 当前状态｜充电站功率/负荷预测独立研究

更新日期：2026-09-08。本文件是当前状态唯一入口；历史执行记录见 [实验台账](docs/EXPERIMENT_LEDGER.md)，数据用途见 [数据台账](docs/DATA_USAGE_LEDGER.md)，接管规则见 [HANDOFF](HANDOFF.md)。

**通俗说明：当前仍处于模型开发阶段。2019-01/04/07/10 的 raw 已全部获取并通过全月QA；开发集processed准备代码已合并，但首次Windows实机准备未完成。raw预检继续通过，最终holdout未访问，当前先做只读诊断定位准备链异常，暂不重跑、不删数据、不训练模型。**

## 1. 当前唯一研发任务

| 项目 | 当前状态 |
| --- | --- |
| 当前Issue | [#29 基于信息可靠性门控的M2/M3双专家预测](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29) |
| 当前阶段 | **模型开发**；当前子步骤为开发集processed准备故障诊断 |
| 基础专家 | M2：历史/日历+当前站级聚合状态；M3：M2+当前连接会话细粒度合法状态 |
| 强基线 | M2、完整M3、0.5简单平均 |
| 开发集raw | **2019-01/04/07/10 已获取并QA PASS** |
| processed准备 | PR #34已合并；首次本地实机运行 `INCOMPLETE`，尚未验收 |
| 最终holdout | 2019-03/06/09/12；仍禁止时序获取和模型运行 |
| 模型训练 | 尚未开始新的开发集模型训练 |

## 2. 开发集raw获取已验收

冻结完整历史metadata源SHA256：

```text
bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
```

| 月份 | local | carry-in | combined | 有效日块 | QA |
| --- | ---: | ---: | ---: | ---: | --- |
| 2019-01 | 1372 | 0 | 1372 | 31/31 | PASS |
| 2019-04 | 1524 | 0 | 1524 | 30/30 | PASS |
| 2019-07 | 1489 | 0 | 1489 | 31/31 | PASS |
| 2019-10 | 1672 | 1 | 1673 | 31/31 | PASS |

四个月 trajectory/full-session quarantine 均为0，`holdout_accessed=false`。

## 3. processed准备代码与协议

PR #34最终HEAD：

```text
75590bf788712aaad3138367fe9e470b11777644
```

main合并提交：

```text
2643e15a7099b5b25ec0d4f8d22ee4195ac4b6f1
```

最终CI：`1058 passed, 2 skipped`，`compileall PASS`，`Ruff PASS`。

开发集使用独立 `code/configs/acn_jpl_development_prep_2019.yaml`，只对应01/04/07/10；旧02/08/11季节YAML与11月3596 s唯一例外保持不变。开发集任何新同步倒退均fail-closed；03/06/09/12不安装、不授权。

## 4. 2026-09-08首次实机准备未完成

用户运行 `evcf_dev_preparation_launcher_v1.py` 后返回：

```text
status=INCOMPLETE
reason_code=DEVELOPMENT_PREPARATION_INCOMPLETE
preparation_reason_code=UNEXPECTED_ERROR
```

同时确认：

- 01/04/07/10 raw预检仍全部通过，raw inventory均可验证；
- metadata冻结SHA继续匹配；
- `holdout_accessed=false`；
- `models_trained=false`；
- existing worktrees保持；
- preparation code worktree锁定PR #34合并提交；
- `months=[]` 表示没有形成任何已封闭月级准备结果，但**不能据此判断本地interim/processed是否有部分写入**；
- 当前CLI把未知异常压缩为 `UNEXPECTED_ERROR`，证据不足以判定是数据质量边界还是准备器真实数据路径缺陷。

因此当前不授权直接重跑、不删除partial输出、不修改raw。下一动作是外置只读诊断：抑制interim/processed物化写入，仅重放清洗、15 min聚合、issue snapshot、M1–M3特征和验证链，输出静态reason、异常类型及仓库模块/函数/行号。

## 5. 数据分区继续冻结

- 已使用/探索：2019-02、05、08、11；
- 方法开发集：2019-01、04、07、10；
- 最终独立保留集：2019-03、06、09、12。

不根据后续模型表现换月。最终holdout在门控变量、模型、超参数、阈值、评价与停止规则全部冻结前不得获取时序或运行模型。

## 6. 方法方向与停止规则

现有证据支持M2/M3信息互补，M3增量价值随时距和会话信息可靠性变化。当前候选贡献是**会话可观测性驱动的低维门控与向M2回退**；普通MoE/动态加权本身不作为创新。

若开发集上可靠性门控不能稳定超过0.5简单平均，或只能依赖高复杂度不可解释调参，则停止该方向，不消耗最终holdout。

## 7. 资产保护

不重下已完成raw；不切换/清理已有数据worktree；保留原main未提交修改、旧季节worktree、开发worktree和三套外置实验目录及其 `local_runs/private`。不执行 `reset --hard`、`clean`、盲目stash或force push。

当前故障诊断前不要删除任何新生成的interim/processed目录；这些目录可能用于判断失败发生在物化前还是物化后。

## 8. 状态维护规则

每次故障定位、数据准备验收、方法冻结或实验结论变化，主控必须同步更新本页、HANDOFF及相关台账，并校对README/ROADMAP/code/README/索引。失效当前指令直接替换；历史证据通过Git历史、Issue/PR和台账保留。
