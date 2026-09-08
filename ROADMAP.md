# 研究路线图｜按证据推进

更新：2026-09-08。实时阶段见 [CURRENT_STATUS](CURRENT_STATUS.md)，数据用途见 [DATA_USAGE_LEDGER](docs/DATA_USAGE_LEDGER.md)。路线图不自动授权本地计算。

| 阶段 | 状态 | 证据或下一条件 |
| --- | --- | --- |
| 5月获取/准备/pilot | 已完成 | PR #16/#18/#21；`PASS_ACTIVE_SESSION_DROP_M4` |
| 2/8/11季节数据与主实验 | 已完成 | PR #23 / Issue #25；`MIXED_SEASONAL_EVIDENCE` |
| 负值诊断、消融、组合 | 已完成探索 | Issue #25/#26/#27 |
| 信息可靠性门控方法开发 | **当前工作** | Issue #29 |
| 开发集raw获取/QA | 已完成 | 01/04/07/10均PASS；holdout未访问 |
| 开发集processed准备代码 | 已完成并合并 | PR #34；独立开发集YAML；1058 passed/2 skipped，compileall/Ruff PASS |
| 开发集processed首次实机运行 | **未完成** | raw preflight PASS；CLI返回 `UNEXPECTED_ERROR`；holdout未访问、未训练模型 |
| **processed故障只读诊断** | **当前下一步** | no-write重放清洗/15min/snapshot/feature/validation，定位静态reason/异常帧 |
| processed正式重跑 | 未授权 | 仅在诊断定位并完成必要修复/CI后重新授权 |
| 门控器开发与选择 | 未执行 | processed快照正式验收后再开始 |
| 方法冻结 | 未完成 | 门控变量、模型、超参数、阈值、评价和停止规则全部锁定 |
| 最终holdout 03/06/09/12 | **继续封存** | 方法冻结后单独授权 |

## 当前方法决策

保留M2、完整M3和0.5简单平均作为强基线。候选方法聚焦**会话可观测性/可靠性驱动的低维门控与向M2回退**；普通MoE/动态加权不作为创新。

若开发集上可靠性门控不能稳定超过简单平均，或收益依赖高复杂度、不可解释的参数搜索，则停止该方向，不消耗最终holdout。

## 当前故障边界

首次processed实机失败不能解释为raw损坏：四个月raw和metadata预检继续通过。`months=[]`仅表示没有形成已封闭月级结果，不能证明没有partial interim/processed。当前不允许直接重跑、删目录或改数据；先做只读诊断。

## 数据分区冻结

- 已使用/探索：02、05、08、11；
- 方法开发集：01、04、07、10；
- 最终独立保留集：03、06、09、12。

不按结果换月。开发集当前只允许故障诊断；最终holdout仍禁止访问。
