# 当前状态｜充电站功率/负荷预测独立研究

更新日期：2026-09-07。本文件是当前状态的唯一入口；历史执行记录见 [实验台账](docs/EXPERIMENT_LEDGER.md)，完整接管规则见 [HANDOFF](HANDOFF.md)。

**通俗说明：数据已经用于多轮模型训练和比较。现在处于模型方案收敛与独立验证准备阶段，不是在重做旧数据清洗，也还没有确定最终论文方法。**

## 1. 当前工作与待解决事项

| 项目 | 当前状态 |
| --- | --- |
| 当前任务 | 固定下一轮比较对象，制定未参与方案选择数据的独立验证协议 |
| 保留候选 | M2、完整M3、两者各占50%的简单平均；尚未确定最终方法 |
| 旧数据修复 | 已完成，PR #23的缺测记账技术阻断已解除；数据准备为 `CONDITIONAL_PASS` |
| 季节主实验 | 已完成并接受执行/汇总交付；研究结论为 `MIXED_SEASONAL_EVIDENCE` |
| 分组消融及预测组合 | 已完成并接受探索性交付；不构成新的独立验证 |
| 月份目录盘点 | 2026-09-07收到结果；扫描范围内只发现已用的2019-02/05/08/11，无额外月份目录 |
| 当前未满足条件 | 尚未落实未参与方案选择的验证数据；具体验证月份和完整协议未冻结 |
| 本地执行 | 此轮盘点已完成；没有待用户执行的新训练、下载或重复诊断命令 |
| Codex | 暂停承担新任务；由主控开发/审查，用户在普通本地Python环境执行明确授权的任务 |

目录盘点仅覆盖3个已登记worktree的 `data/{raw,interim,processed}/acn/jpl`，未读数据内容或压缩包。未发现额外目录不证明电脑其他位置没有数据，也不等于已完成完整性/独立性审计。原1个有未提交修改的worktree状态保持不变。见 [数据用途与盘点台账](docs/DATA_USAGE_LEDGER.md)。

## 2. 版本、验收与合并分别记录

- 最后已合并的预测实验基线：PR #21，`c2af2cdf4ecf5dad059d2ac92e929df8df35d42b`；5月结论 `PASS_ACTIVE_SESSION_DROP_M4`。
- 已审数据/代码工作基线：PR #23 HEAD `4c2b1988ea9927b27287d6935bd22d01bd9df875`，修复实现 `6ded3bdd810a8115ea5b8a51091de71fab894a03`；[主控条件验收](https://github.com/Kato814/EV-Charging-Forecasting-Research/pull/23#pullrequestreview-5125619014)。**PR #23仍未合并，不因本文更新而变为已合并。**
- Issue #25—#27的新实验由外置运行包执行，主控已审查回传汇总；对应包/协议/结果SHA见实验台账。外置源码和完整回传载荷尚未作为仓库代码/结果提交，本仓库登记审查及证据身份，不冒称全部复现材料已进入main。
- main文档提交不是实验执行提交。旧 `8c0eeea` 只用于修正前对账，不能作为新版输入要求。

## 3. 已有结果及可支持的结论

| 工作 | 已审结论 | 证据 |
| --- | --- | --- |
| 5月pilot | 会话状态具有增量价值，M4-lite不保留进入后续主实验 | [PR #21](https://github.com/Kato814/EV-Charging-Forecasting-Research/pull/21) |
| 季节复核 | 8月通过原月度筛选；2月和11月未满足全部条件，不能宣称跨月稳定有效 | [Issue #25复核](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/25#issuecomment-5566541374) |
| 分组消融 | 没有得到统一删除某一整组信息的稳定依据 | [Issue #26复核](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/26#issuecomment-5568854896) |
| 预测组合 | 简单平均相对M2的15个“月份×时距”组合MAE均降低；相对M3并非全面占优；校准加权未稳定优于简单平均 | [Issue #27复核](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/27#issuecomment-5570724142) |

2/8/11月已经用于方案探索；后续同数据变体不得包装为新的独立验证。预测组合是常规方法，不将其本身宣称为论文创新。双源分解、概率预测、调度收益和最终论文创新均未验证。

## 4. 继续保持的边界

目标仍为 `station_current_mean_a`，单位A。数据准备 `CONDITIONAL_PASS`、11月 `CURRENT_PROXY_ONLY`、季节kW列未授权；11月2884个连续UTC物理时间格及唯一异常轨迹隔离规则不变。缺测不能当作零，已知整段current缺测不能被高coverage掩盖。

不重下既有raw，不重做已完成修复，不恢复M4，不启动Gate 2/概率/联邦/调度，不按已经查看的测试结果改门槛或挑选最好变体。新数据获取或实验须另行明确授权。

原main未提交修改、数据任务worktree、raw/interim/processed，以及运行后的 `evcf_seasonal_runner_v1_1`、`evcf_session_ablation_v1`、`evcf_forecast_combination_v1` 和各自 `local_runs/private` 均保留。消融导出恢复ZIP及错误记录保留，不为补写 `completed.json` 重训。

## 5. 状态维护规则

每轮验收、失败恢复、授权变化或数据范围变化，主控必须同步更新本页、HANDOFF及相关台账，再汇报完成。失效的当前指令直接替换或删除，不保留为并行入口；旧措辞通过Git历史追溯。冻结协议、原始结果、负结果、SHA和审查记录不是过时垃圾，不能因日期较旧而删除。详见 [工作流](docs/WORKFLOW.md)。
