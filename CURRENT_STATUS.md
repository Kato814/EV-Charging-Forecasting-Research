# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新日期：2026-09-12。本文件是当前状态唯一入口。历史证据见 [实验台账](docs/EXPERIMENT_LEDGER.md)，P1 冻结协议见 [P1 protocol](docs/JPL_STRUCTURED_MECHANISM_PROBE_PROTOCOL_20260911.md)，P1 正式结果见 [P1 outcome](docs/JPL_P1_MECHANISM_PROBE_OUTCOME_20260912.md)，接管规则见 [HANDOFF](HANDOFF.md)。

**当前结论：S1 仍为 `MIXED_STRUCTURED_SIGNAL`；P1 低复杂度 mechanism probe 已 COMPLETE，并按预注册规则正式判为 `STOP_MECHANISM_ROUTE`。结构化 session 分解不再作为当前核心预测路线，但 G0/S1 已验证的 horizon-dependent composition shift 与 turnover/local-hour 结构保留为机制证据。final holdout 2019-03/06/09/12 继续封存。**

## 1. 当前阶段

| 项目 | 当前状态 |
| --- | --- |
| 当前 Issue | #29 多时距会话贡献分解与结构化充电站负荷预测 |
| 开发集 | 2019-01 / 04 / 07 / 10 |
| final holdout | **2019-03 / 06 / 09 / 12，禁止访问** |
| 预测目标 | `station_current_mean_a`，单位 A |
| S1 冻结决策 | `MIXED_STRUCTURED_SIGNAL` |
| P1 冻结决策 | **`STOP_MECHANISM_ROUTE`** |
| Probe E | `NO_COMPONENT_SIGNAL` |
| Probe A | `NO_COMPONENT_SIGNAL` |
| 当前允许动作 | **一次只读 P1-A post-mortem；随后重新选择方法创新路线** |

## 2. 已冻结的科学事实

G0 的 pooled 真实负荷组成随 horizon 明显变化：

```text
horizon   existing   future-arrival
15 min     97.38%       2.62%
30 min     90.61%       9.39%
60 min     78.10%      21.90%
120 min    56.52%      43.48%
240 min    26.21%      73.79%
```

强基线与 S1 pooled MAE：

```text
M2    30.164406 A
M3    29.190188 A
Equal 28.917286 A
S1    28.594882 A
```

S1 只在 2/4 开发月优于 Equal，因此正式保持 `MIXED_STRUCTURED_SIGNAL`。只读诊断进一步确认：
- 30 min / realized arrival share 25–50% 为稳定弱区；
- 60 min / 50–75% 为稳定弱区，而 0–25% 为稳定强区；
- 30/60/120 min 在约 07:00 跨月稳定偏弱，09:00 附近可反转为强。

这些结果支持存在 horizon-conditioned session-turnover phenomenon，但不自动证明任何具体预测架构有效。

## 3. P1 正式结果

P1 按 PR #54 冻结协议执行：
- Probe E = horizon-specific continuation probability × positive-current mark；
- Probe A = future-arrival Poisson count × positive mark；
- P1-EA 为唯一主候选；Eonly/Aonly 仅归因。

执行身份：
- PR #56 CI-passed head `dac9d18596d8e3ba766e02f83b21d60e650e5957`；
- merge `33f391c5186650846826fdcb802e4f3e5c329d9d`；
- P1 private manifest `df222c4731f3c3192735a6df2ccd2f692f1ea6d640a7954706e7bca17f51580f`；
- fit_count = 1090；
- holdout 未访问，M2/M3 未重训，无 tuning/clipping/calibration/gate/neural survival/TPP。

Pooled MAE：

| model | MAE (A) |
| --- | ---: |
| Equal | 28.917286 |
| S1 | 28.594882 |
| P1-Eonly | 30.065656 |
| P1-Aonly | 172.758507 |
| P1-EA | 172.966423 |

Component MAE：

| component | MAE (A) |
| --- | ---: |
| S1 existing | 12.791178 |
| P1-E | 14.495331 |
| S1 arrival | 23.105152 |
| P1-A | 167.857291 |

因此：
- E/A 两 branch pooled component 均未改善；
- P1-EA 对 Equal 为 0/5 horizon wins、0/4 month wins；
- 60-min P1-EA MAE 109.278945 A，远高于 Equal 26.141292 A；
- 正式决策只能是 **`STOP_MECHANISM_ROUTE`**，不得事后改阈值。

## 4. P1 的主要失败结构

总模型崩坏主要由 Probe A 驱动。2019-10 的固定 Poisson count 模型发生严重外推失稳，短/中 horizon 尤其明显；局部 hour 可产生极端预测。该现象只允许做只读审计，不允许根据测试结果进行 clipping、调 alpha、重选模型或改写 STOP。

Probe E 也没有稳定 component signal：只有 1/5 horizon component MAE 优于 S1 existing，0/4 pooled month wins。

P1 同时未修复已知 morning turnover 弱点：30/60/120 min @07:00 均 4/4 月劣于 Equal；60/120 min @09:00 仍可较好。这说明 descriptive turnover phenomenon 仍存在，但 P1 的参数化实现不是解决方案。

## 5. 当前唯一允许的下一步

### A. 一次 read-only P1-A post-mortem
仅核对：
- 极端预测来自哪些 rolling folds / local hours；
- Poisson linear predictor / predicted count 的外推分布；
- count/mark target identity 是否保持；
- 是否存在实现错误、数值问题或单纯模型形式不适配。

该审计**不能**：
- 改 P1 决策；
- 重跑调参；
- clipping/calibration；
- 用 holdout；
- 直接把 A branch 升级为 EasyTPP。

### B. post-mortem 后重新进入方法创新筛选
围绕已验证的 horizon-conditioned turnover phenomenon 重新搜索 GitHub/文献中的成熟实现与缺口。P1-E 不自动升级为 pycox，P1-A 不自动升级为 TPP，因为两 branch 都没有稳定 component signal。

## 6. 当前禁止事项

- 不访问 final holdout；
- 不恢复 reliability/composition gate；
- 不把 realized future composition 当 predictor；
- 不对 P1 做 post-hoc retuning / clipping / calibration；
- 不用更大 neural backbone 强行“救”P1；
- 不删除历史 worktree、failed status 或 private cache；
- 不使用 `reset --hard`、`clean`、盲目 stash、force push。

## 7. 仓库维护

P1 的正式 outcome、Issue #29、CURRENT_STATUS 和 HANDOFF 必须保持一致。private row-level predictions/cache 继续仓库外保存。后续新方法必须先形成可审计问题定义与开发判据，再实现/CI/本机运行。
