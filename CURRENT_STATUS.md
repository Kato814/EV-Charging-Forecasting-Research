# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。当前入口为本文件与 [HANDOFF](HANDOFF.md)。正式 R5 结果见 [R5 outcome](docs/JPL_R5_FUTURE_TRANSITION_ALIGNED_REPRESENTATION_OUTCOME_20260914.md)，正式 R6-O0 结果见 [R6 outcome](docs/JPL_R6_O0_COMPONENT_ORACLE_OUTCOME_20260914.md)，Post-R6 方法筛选见 [Post-R6 screening](docs/JPL_POST_R6_METHOD_SCREENING_20260914.md)，下一正式机制协议见 [R7-C0 protocol](docs/JPL_R7_C0_DEPARTURE_STATE_ARRIVAL_PROTOCOL_20260914.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`；R5=`STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`；R6-O0=`MIXED_COMPONENT_ORACLE_SIGNAL`。R7-C0 协议与实现已冻结/合并，正式 development run 尚未执行。final holdout 2019-03/06/09/12 继续封存。**

## 1. R6-O0 accepted finding

R6-O0 source status SHA256：

```text
52bf3d7753b095a0faf39bc9aaefbd07b2c11f406ab05abd4bd1534e921dacce
```

Pooled：

```text
S1 MAE                         28.5948815297 A
G_existing                      5.4897298390 A   (19.20%)
G_arrival                      15.8037036627 A   (55.27%)
arrival > existing horizons    3/5
arrival > existing months      4/4
```

Horizon structure：

```text
15 min    existing > arrival   4/4 months
30 min    existing > arrival   3/4 months
60 min    arrival > existing   4/4 months
120 min   arrival > existing   4/4 months
240 min   arrival > existing   4/4 months
```

因此可移除误差的主导来源在 30–60 min 之间发生转换：短时距更受已连接会话后续演化影响，中长时距更受预测时尚未到达会话影响。该结论不是信息论不可约性声明。

## 2. Post-R6 selected question

R7-C0 不换大模型，只检验一个此前未被 S1/P1 单独检验的信息通道：

> 当前已连接会话的 issue-time `requested_departure_minutes_from_issue` 状态，是否能在冻结 M2 之外稳定改善 future-arrival current component，并且这种分量增益是否能在与冻结 S1 existing branch 重组后改善总负荷预测？

注意 canonical departure pool 的 `count` 是非缺失 departure 声明数，`missing_count` 是未声明数量。因此如 R7 有信号，只能表述为 **requested-departure state（声明可用性 + 时间分布）** 有增量预测信息，不得直接声称实际离站时间或端口释放具有因果作用。

## 3. R7-C0 frozen arms

```text
Base-M2        frozen S1 arrival prediction, read-only
Departure-Aug  canonical M2 + 10 requested-departure pooled statistics
               + 7 fixed nullable indicators
               211 raw / 221 encoded
Full-M3        canonical full M3, 311 raw / 391 encoded, secondary only
```

两个新拟合臂全部使用：

- `HistGradientBoostingRegressor`；
- 同一 horizon 的冻结 **M2** selected parameters；
- 同月 daily rolling-origin；
- exact S1 future-arrival target；
- 无重调、无 clipping/calibration、无非负投影、无 feature selection。

候选总预测：

```text
Total_Departure = frozen S1 existing + Departure-Aug arrival
Total_FullM3    = frozen S1 existing + Full-M3 arrival
```

正式强参考：冻结 S1 与 Equal。

## 4. R7-C0 frozen decision

Primary decision 只由 Departure-Aug 决定。

`PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL` 要求同时满足：pooled arrival 优于 Base-M2；>=3/5 horizon wins；>=3/4 month wins；在 {60,120,240} 中 >=2/3 wins；arrival horizon 最大退化 <=5%；Total_Departure pooled 同时优于 S1 和 Equal；总预测 >=3/5 horizon wins、>=3/4 month wins；总预测任一 horizon 最大退化 <=5%。

未 PASS 但 pooled arrival 或 pooled total 任一改善 -> `MIXED_DEPARTURE_STATE_ARRIVAL_SIGNAL`；两者均不改善 -> `STOP_DEPARTURE_STATE_ARRIVAL_ROUTE`。

Full-M3 仅产生次级标签 `FULL_M3_INCREMENTAL_SIGNAL` / `NO_STABLE_FULL_M3_INCREMENT`，不能改变 primary R7 code。

## 5. R7 implementation identity

```text
protocol commit                  ed427067015e60b417cd5da3838b4e0a5701b01e
reviewed CI-passed head          24e9e69413cb4b224bd1c59cdd3725b352bd27ed
implementation merge             78e51d98d476e30098a19b67121c0658a4c848b4
PR                               #94
final CI                         PASS: 1211 passed, 2 skipped; compileall PASS; Ruff PASS
expected formal fits             550 = 275 Departure-Aug + 275 Full-M3
```

External pinned launcher：

```text
evcf_r7_c0_launcher_v1.py
SHA256 = f1dbaf035055038f337f0207baba8ae0ef884ca0118c16a87ef75d7178f822e9
```

Launcher binds execution to the reviewed head, preserves existing worktrees/caches, auto-locates exact development snapshots and accepted baseline/S1 private caches, skips final-holdout directories, verifies development artifacts before and after the run, and emits only aggregate `evcf_r7_c0_status_*.json` for upload.

## 6. Current execution state

| 项目 | 状态 |
| --- | --- |
| R6-O0 | **COMPLETE / MIXED_COMPONENT_ORACLE_SIGNAL** |
| Post-R6 screening | **R7-C0 SELECTED** |
| R7 protocol | **FROZEN / COMMITTED** |
| R7 implementation | **CI PASS / MERGED** |
| R7 pinned launcher | **READY / STATICALLY AUDITED** |
| R7 formal local run | **NOT RUN YET** |
| Final holdout | **SEALED** |

下一步只允许 exactly one R7-C0 development run。COMPLETE 后先归档/解释结果，再决定是否进入任何后续方法设计；不得为结果救火式重调。

## 7. GitHub Actions conservation

完整 CI 只在 PR 修改 `code/**`、`scripts/**`、`pyproject.toml`、`MANIFEST.json` 或 workflow 时触发；纯文档和结果归档不触发全量 CI；duplicate `push` trigger 已移除；`cancel-in-progress` 保留。开发阶段优先本地/静态检查，代码最终候选才开 PR。
