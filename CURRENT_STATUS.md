# 当前状态｜充电站功率/负荷预测独立研究

更新日期：2026-09-08。本文件是当前状态唯一入口；历史执行记录见 [实验台账](docs/EXPERIMENT_LEDGER.md)，数据用途见 [数据台账](docs/DATA_USAGE_LEDGER.md)，接管规则见 [HANDOFF](HANDOFF.md)。

**通俗说明：当前仍处于模型开发阶段。2019-01/04/07/10 raw 已获取并通过全月QA。首次processed准备失败已通过只读诊断定位为代码兼容性遗漏，不是1月raw数据质量失败；PR #37已修复并合并。现在允许用新v1.1启动器重新执行四个月processed准备。最终holdout 2019-03/06/09/12继续封存。**

## 1. 当前研发任务

| 项目 | 当前状态 |
| --- | --- |
| 当前Issue | [#29 基于信息可靠性门控的M2/M3双专家预测](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29) |
| 当前阶段 | **模型开发**；当前子步骤为开发集processed准备重试 |
| 开发集raw | **2019-01/04/07/10 已获取并QA PASS** |
| processed准备代码 | PR #34建立开发集专用协议；PR #37修复清洗校验模块旧月份白名单遗漏 |
| 模型训练 | 尚未开始开发集模型训练 |
| 最终holdout | **2019-03/06/09/12继续禁止访问** |
| 基础比较 | M2、完整M3、0.5简单平均；后续再开发可靠性门控 |

## 2. 开发集raw已验收

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

四个月trajectory/full-session quarantine均为0；`holdout_accessed=false`。

## 3. processed准备协议与代码

PR #34：

```text
final HEAD 75590bf788712aaad3138367fe9e470b11777644
main merge 2643e15a7099b5b25ec0d4f8d22ee4195ac4b6f1
```

建立独立 `code/configs/acn_jpl_development_prep_2019.yaml`，只对应01/04/07/10；清洗、15 min、coverage、issue-time快照和M1–M3数值语义复用已审单月链。旧02/08/11协议、11月3596 s唯一轨迹例外和历史37件发布身份不改。开发集任何新同步倒退均fail-closed。

## 4. 首次实机失败、只读诊断与根因

首次 `evcf_dev_preparation_launcher_v1.py` 返回 `INCOMPLETE/UNEXPECTED_ERROR`。随后只读诊断 `evcf_development_preparation_diagnostic_20260908T141021Z.json` 明确定位：

- 2019-01失败于 `evcf.data.acn_jpl_gate1_prep.validate_seasonal_cleaning_documents()`；
- 异常类型为 `ValueError`；
- 对应代码行为是 `config.month not in SEASONAL_MONTHS` 的历史季节月份守卫；
- 原因是开发上下文已临时扩展多个按值导入的 `SEASONAL_MONTHS`，但漏掉 `acn_jpl_gate1_prep`；
- 因此这是**兼容性遗漏，不是raw数据质量结论**。

诊断同时确认：四个月在首次失败后均无interim/processed月份目录或manifest残留，`writes_suppressed=true`，holdout未访问，模型未训练。

## 5. PR #37修复状态

PR #37 `fix: extend development month compatibility to cleaning validator`：

```text
final HEAD e47f05cb7a663df9c599270ac939c9301d26840b
main merge c1ff4e675ae14e7667e0c6b7f887fb15319aff38
```

修复仅把 `evcf.data.acn_jpl_gate1_prep` 加入 `installed_development_month_contracts()` 的临时月份兼容列表，并在上下文退出时精确恢复；增加相应回归断言。没有修改数据合同、清洗参数、特征、trajectory规则、模型或holdout权限。

最终CI：

```text
1058 passed, 2 skipped
compileall PASS
Ruff PASS
```

## 6. 当前授权动作

下一步允许重新执行**开发集processed准备**，仅01/04/07/10：

- 不重新下载raw；
- 不训练模型；
- 不访问03/06/09/12；
- 使用绑定PR #37合并提交的新v1.1外置启动器；
- 新启动器使用新的detached code worktree名称，旧PR #34代码worktree原样保留；
- 重试前再次确认没有开发月interim/processed残留，否则停止；
- 成功后只回传脱敏status JSON。

processed审查通过后，才进入M2/M3开发集预测与可靠性门控训练。

## 7. 方法方向

当前假设：M2与M3信息互补，M3增量价值受预测时距和会话信息可靠性影响。候选贡献是**会话可观测性驱动的低维门控与向M2回退**，普通MoE/动态加权本身不作为创新。

开发阶段至少比较M2、完整M3、0.5简单平均、可靠性门控。若门控不能稳定超过简单平均，或收益依赖高复杂度不可解释调参，则停止该方向，不消耗最终holdout。

## 8. 数据分区与资产保护

- 已使用/探索：2019-02、05、08、11；
- 方法开发集：2019-01、04、07、10；
- 最终独立保留集：2019-03、06、09、12。

不根据模型表现换月。保留用户原main未提交修改、所有登记worktree、raw/interim/processed、旧季节worktree、开发raw worktree及三套外置实验目录的 `local_runs/private`。不执行 `reset --hard`、`clean`、盲目stash或force push。

## 9. 状态维护规则

每次故障定位、修复合并、数据准备验收、方法冻结或实验结论变化，主控必须同步更新本页、HANDOFF及相关台账，并校对README/ROADMAP/code/README/索引。失效当前指令直接替换；历史证据通过Git历史、Issue/PR和台账保留。
