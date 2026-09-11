# 实验与证据台账

更新：2026-09-11。当前任务见 [CURRENT_STATUS](../CURRENT_STATUS.md)。本台账记录已执行/已审查事实及版本身份；接受交付不等于科学假设通过。

## 1. 版本与发布状态

- 5月预测实验：PR #21 已合并，`c2af2cdf4ecf5dad059d2ac92e929df8df35d42b`。
- 季节数据/代码：PR #23 已合并；数据准备 `CONDITIONAL_PASS`，11 月 `CURRENT_PROXY_ONLY`，季节 kW 未授权。
- development raw/processed：2019-01/04/07/10 已完成并冻结。
- processed compatibility：PR #37，main `c1ff4e675ae14e7667e0c6b7f887fb15319aff38`。
- M2/M3 OOS experts：PR #41；accepted expert code 最终绑定 `e5fe6d0aee9035374b6fb3240d3c5ebe2f1b7df7`（PR #45）。
- S1 structured baseline：PR #47；merge `7e914c1fe73376c720c376f0c12fa226a1082314`。
- cache truth tolerance：PR #48；reviewed head `8853d17c5a567a8458e0f638eec90cd31b0dab82`；merge `0f85508f04e8192ec8c7949a512c488255fa58ef`。
- read-only MIXED diagnostic：PR #52；CI-passed head `63ead204b99b131f2c5634f868582411aad8703b`；merge `6236d3fe451838ffb70ff0a1e3a4fcca9de60841`。
- read-only transition-map diagnostic：PR #53；CI-passed head `cc5da1a3683452bea95ff62501dc27c9c2ab7619`；merge `6464cac561f5a1f0c4f7657a6613537c2c675f61`。
- 当前方法 Issue：[#29](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29)。
- 下一阶段冻结协议：`docs/JPL_STRUCTURED_MECHANISM_PROBE_PROTOCOL_20260911.md`。

## 2. 已审工作一览

| 工作 | 执行与技术验收 | 研究结论/限制 | 证据 |
| --- | --- | --- | --- |
| 5月 pilot | PR #21 | `PASS_ACTIVE_SESSION_DROP_M4` | PR #21 |
| 2/8/11 季节主实验 | 570 次日级拟合 | `MIXED_SEASONAL_EVIDENCE` | Issue #25 |
| 负值诊断/会话消融 | 诊断 + 570 次消融 | 单纯置零不足；不支持统一删除整组 | Issue #25/#26 |
| 预测组合 | 30 项控制 + 300 次校准拟合 | Equal 为强基线；校准加权未稳定超过 | Issue #27 |
| development data prep | 01/04/07/10 | 数据冻结；holdout 未访问 | Issue #29 |
| M2/M3 expert protocol | 固定 May HGB 参数、日级 OOS、共同测试行、私有缓存 | 强基线冻结 | PR #41/#45 |
| S1 launcher v1 | 拟合前停止 | `MERGE_COMMIT_NOT_FOUND` | local failed status |
| S1 launcher v1.1 | 拟合前停止 | `MERGE_COMMIT_NOT_FOUND_AFTER_EXPLICIT_FETCH` | local failed status |
| S1 launcher v1.2 | 首次进入真实 S1 | `COMMON_ROW_IDENTITY_INVALID` | PR #48 前置证据 |
| PR #48 | 4e-9 A roundoff PASS；2e-6 A mismatch FAIL | 只修 tolerance | PR #48 |
| S1 launcher v1.3 | COMPLETE，fit_count=550 | **`MIXED_STRUCTURED_SIGNAL`** | v1.3 status |
| MIXED diagnostic | COMPLETE；read-only | binary arrival hurdle 不足；branch 误差结构已定位 | PR #52 + status |
| transition-map diagnostic | COMPLETE；read-only | horizon-conditioned turnover + local-hour regime 可复现 | PR #53 + status |

## 3. 冻结开发数据身份

```text
2019-01 e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12
2019-04 f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299
2019-07 9eea83e13ea6fbe5fef694c5de93b5bc4a82f7efe00e90e4fadd6d0b9e9ff2
2019-10 e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296
```

```text
source expert protocol SHA256
02c7809f1113aeaf20723030c96006ee0831b20ff219106da7d6968df535d71a

baseline private manifest SHA256
2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd

S1 private manifest SHA256
562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1
```

## 4. G0 结构证据

| horizon | existing-session | future-arrival |
| ---: | ---: | ---: |
| 15 min | 97.38% | 2.62% |
| 30 min | 90.61% | 9.39% |
| 60 min | 78.10% | 21.90% |
| 120 min | 56.52% | 43.48% |
| 240 min | 26.21% | 73.79% |

G0 支持 horizon-dependent composition shift，但不支持一个统一 prefix model。

## 5. 冻结强基线与 S1

```text
M2    30.1644064624 A
M3    29.1901878199 A
Equal 28.9172859886 A
S1    28.5948815297 A
```

S1 vs Equal by horizon：

| horizon | S1 vs Equal |
| ---: | ---: |
| 15 | +4.44% |
| 30 | +0.50% |
| 60 | -3.98% |
| 120 | +0.64% |
| 240 | +3.60% |

S1 vs Equal by development month：

| month | S1 vs Equal |
| --- | ---: |
| 2019-01 | -0.65% |
| 2019-04 | -2.72% |
| 2019-07 | +3.56% |
| 2019-10 | +3.48% |

冻结 PASS 条件仅第 4 项（至少 3/4 月优于 Equal）失败，因此正式结论保持：

```text
MIXED_STRUCTURED_SIGNAL
```

## 6. MIXED diagnostic：branch-level evidence

只读 diagnostic 使用已验收 baseline/S1 private cache；不拟合模型、不访问 development raw/processed、不访问 holdout。

关键事实：
- future-arrival target 的零比例随 horizon 从约 80.4% 降到约 40.5%；
- 60 min 在 `arrival_truth=0` 与 `arrival_truth>0` 两组均可弱于 Equal，因此 binary hurdle 不能独立修复；
- existing branch 的零贡献/退出与负预测 incidence 随 horizon 增长，240 min existing branch negative prediction fraction 约 39.5%；
- branch residual cosine 多接近 0 或轻微负值，不支持“两个 branch 同向误差简单叠加”解释。

## 7. transition-map diagnostic：最终失败分解

realized arrival-share bins 仅用于离线解释，禁止成为 predictor。

### 7.1 Pooled composition behavior

关键 pooled 现象：
- 30 min / 25–50% arrival share：S1 比 Equal 差约 17.15%；
- 60 min / 50–75% arrival share：S1 比 Equal 差约 25.01%；
- 60 min / 0–25% arrival share：S1 比 Equal 好约 4.83%；
- 120 min 多数 mixed bins重新出现轻微正收益；
- 240 min pooled 所有 composition bins 都优于 Equal。

### 7.2 Cross-month composition sign stability

最重要的可复现组合：

```text
30 min / arrival share 25–50% : 0/4 months better, 4/4 worse
60 min / arrival share 0–25%  : 4/4 months better, 0/4 worse
60 min / arrival share 50–75% : 0/4 months better, 4/4 worse
240 min / arrival share 0–25% : 4/4 months better, 0/4 worse
```

所以 composition 并非单调门控变量；同一 composition state 在不同 horizon 表现不同。

### 7.3 Cross-month local-hour sign stability

代表性结果：

```text
30 @07:00 : 4/4 worse, median S1-Equal +16.59 A
30 @09:00 : 4/4 better, median               -2.30 A
60 @06:00 : 4/4 worse, median               +17.67 A
60 @07:00 : 4/4 worse, median               +24.23 A
60 @09:00 : 4/4 better, median               -13.23 A
60 @10:00 : 4/4 better, median               -11.69 A
120 @07:00: 4/4 worse, median               +15.15 A
120 @09:00: 4/4 better, median               -13.31 A
```

该跨月符号反转是当前最强的 turnover-regime 证据之一。

## 8. transition diagnostic 安全审计

```text
status = COMPLETE
reason_code = null
development_data_accessed = false
holdout_accessed = false
model_fit_attempted = false
baseline_private_cache_unchanged = true
structured_private_cache_unchanged = true
existing_worktrees_preserved = true
resolved_code_commit = cc5da1a3683452bea95ff62501dc27c9c2ab7619
reported_merge_commit = 6464cac561f5a1f0c4f7657a6613537c2c675f61
```

## 9. 阶段裁决

- S1 的正式 scientific decision **仍是 MIXED**。
- MIXED failure diagnosis **已完成**。
- structured session route **不停止**，但只授权进入预注册的低复杂度 P1 mechanism probe。
- 不允许用更大的深度模型“救”S1。

下一步协议：`docs/JPL_STRUCTURED_MECHANISM_PROBE_PROTOCOL_20260911.md`。

P1-E：horizon-specific logistic continuation probability × Gamma positive-current mark；首轮不强制 survival monotonicity。

P1-A：Poisson count × Gamma positive mark。

P1-EA：唯一主候选；Eonly/Aonly 只用于归因。

在 P1 结果产生前，final holdout、pycox/EasyTPP、HSMM/state-space、composition/reliability gate、hyperparameter search、post-hoc clipping/calibration 均禁止。
