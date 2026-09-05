# 仓库分层索引与历史材料状态

更新：2026-09-05。入口以 [CURRENT_STATUS](../CURRENT_STATUS.md) 和 [HANDOFF](../HANDOFF.md) 为准；旧版本文件不自动授权执行。

## 当前执行与已验收证据

| 层级 | 位置 | 使用方式 |
| --- | --- | --- |
| 当前修复 | Issue #22 / PR #23，`data/jpl-2019-seasonal-replication` | 读取最新审查；修正前季节SHA不作最终输入 |
| 5月完整获取 | PR #16，`outputs/acn_gate0/jpl_2019-05-full-ts/` | 历史获取与QA证据 |
| 5月数据准备 | PR #18，`outputs/acn_gate1_prep/jpl_2019-05/` | 已验收快照与语义证据 |
| 5月pilot | PR #21，`outputs/gate1_pilot/jpl_2019-05/` | 已验收的单月信息价值实验 |
| 季节准备 | PR #23，`outputs/seasonal_prep/jpl_2019/` | 尚在PR，不假定main可读取；旧版37件待修订 |

`outputs/`内已冻结文件和SHA清单不作人工清理、重新编号或换单位。M4负结果保留，不能为“删除M4分支”而删除历史实验。

## 文献与候选设计：原位历史归档

`literature/`、`datasets/`、`related_code/`保留论文元信息、搜索记录、数据审计、代码来源和阅读笔记。此轮不重新审读全部文献，不改变文献计数及其证据等级。

`research/`内v0.4/v0.5问题缺口材料、v0.6决策/接口/路线及v0.7分阶段获取文件是历史设计。`experiments/gate0_gate2_protocol_v0.6.md` 和 `docs/ROUND2*`、`docs/ROUND3*`也是历史协议。它们保留原路径，因为交叉引用和 `scripts/validate_library.py` 依赖其中多项，不能为整理而直接移动/删除。

`docs/superpowers/plans/`保留实施计划，不按文件名日期替代运行commit和结果清单。`research/forecast_dispatch_interface_v0.6.md`可参考未来接口，但不表示调度已运行。

## Issue治理

- #19/#21：实际执行并验收的5月pilot。
- #20：已关闭的重复/未执行方案，不与#19混用。
- #22/#23：唯一在执行的数据修复与待审查PR。
- #10：5月窗口的旧总任务，可由#16/#18/#21证据收口。
- #3/#4：早期样本/信息价值设计已被更具体任务替代；其中泛化能力、概率指标或“同一会话不得跨集合”等早期设想不自动并入已执行pilot。
- #1：保留未完成的许可/控制影响核验范围，不把5月完成等同于全部候选数据审计完成。
- #2（EPFL）、#5（Gate 2）、#6（调度）、#15（稳定GPU环境）：待办/未授权，不与当前修复并行启动。

## 安全保留

保留生产代码、测试、环境锁、许可证、引用文件、历史commits/tags和所有原始证据路径。本地data.zip、被忽略数据和worktree不在远端整理范围。远端历史分支不自动删除；其与本地资产的关系未核验。

整理记录见 [REPOSITORY_CLEANUP_20260905.md](REPOSITORY_CLEANUP_20260905.md)。
