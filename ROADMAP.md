# 研究路线图｜按证据推进

更新：2026-09-08。实时阶段见 [CURRENT_STATUS](CURRENT_STATUS.md)，数据用途见 [DATA_USAGE_LEDGER](docs/DATA_USAGE_LEDGER.md)。路线图不自动授权本地计算。

| 阶段 | 状态 | 证据或下一条件 |
| --- | --- | --- |
| 5月获取/准备/pilot | 已完成 | PR #16/#18/#21；`PASS_ACTIVE_SESSION_DROP_M4` |
| 2/8/11季节数据与主实验 | 已完成 | PR #23 / Issue #25；`MIXED_SEASONAL_EVIDENCE` |
| 负值诊断、消融、组合 | 已完成探索 | Issue #25/#26/#27 |
| 信息可靠性门控方法开发 | **当前工作** | Issue #29 |
| 开发集raw获取/QA | 已完成 | 01/04/07/10均PASS；holdout未访问 |
| 开发集processed准备协议/入口 | 已完成并合并 | PR #34；独立开发集YAML |
| processed首次Windows实机运行 | 已完成失败记录 | `INCOMPLETE/UNEXPECTED_ERROR`；无模型训练、holdout未访问 |
| processed只读诊断 | **已完成** | 2019-01定位到 `acn_jpl_gate1_prep` 旧 `SEASONAL_MONTHS` 守卫；四月均无partial输出 |
| 兼容性修复 | **已完成并合并** | PR #37；1058 passed/2 skipped，compileall/Ruff PASS |
| **开发集processed正式重试** | **当前下一步** | v1.1启动器；仅01/04/07/10；不联网、不训练模型 |
| processed快照主控审查 | 未完成 | 核对cleaning/coverage/leakage/snapshot SHA/raw unchanged |
| 门控器开发与选择 | 未执行 | processed快照正式验收后再开始 |
| 方法冻结 | 未完成 | 门控变量、模型、超参数、阈值、评价和停止规则全部锁定 |
| 最终holdout 03/06/09/12 | **继续封存** | 方法冻结后单独授权 |

## 当前方法决策

保留M2、完整M3和0.5简单平均作为强基线。候选方法聚焦**会话可观测性/可靠性驱动的低维门控与向M2回退**；普通MoE/动态加权不作为创新。

若开发集上可靠性门控不能稳定超过简单平均，或收益依赖高复杂度、不可解释的参数搜索，则停止该方向，不消耗最终holdout。

## processed故障结论

首次prepared运行不能解释为raw损坏。只读诊断已定位为开发上下文漏扩展 `evcf.data.acn_jpl_gate1_prep.SEASONAL_MONTHS`。PR #37只修兼容绑定和回归测试，不修改科学参数或数据规则。诊断确认四个月没有interim/processed月份残留，因此可以在修复合并后从干净状态重试。

## 数据分区冻结

- 已使用/探索：02、05、08、11；
- 方法开发集：01、04、07、10；
- 最终独立保留集：03、06、09、12。

不按结果换月。开发集当前只允许processed准备重试；最终holdout仍禁止访问。
