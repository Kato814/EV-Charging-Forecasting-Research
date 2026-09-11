# 实验与证据台账

更新：2026-09-11。当前任务见 [CURRENT_STATUS](../CURRENT_STATUS.md)。本台账记录已执行/已审查事实及版本身份；“接受交付”不等于科学假设通过。

## 1. 版本与发布状态

- 5月预测实验：PR #21 已合并，`c2af2cdf4ecf5dad059d2ac92e929df8df35d42b`。
- 季节数据/代码：PR #23 已合并；数据准备 `CONDITIONAL_PASS`，11 月 `CURRENT_PROXY_ONLY`，季节 kW 未授权。
- 开发集 raw/processed：2019-01/04/07/10 均已完成。
- processed 兼容性修复：PR #37，main `c1ff4e675ae14e7667e0c6b7f887fb15319aff38`。
- M2/M3 OOS expert 基础入口：PR #41，main `653cb447...`。
- JSON 标签键顺序修复：PR #43，main `7dda9d38...`。
- Windows EOL 实现身份校验修复：PR #45，accepted expert code `e5fe6d0aee9035374b6fb3240d3c5ebe2f1b7df7`。
- S1 structured baseline：PR #47，reviewed head `182100bf128493bdcb722ed2ac90eb3bf982d2b1`，merge `7e914c1fe73376c720c376f0c12fa226a1082314`。
- structured baseline cache truth tolerance 修复：PR #48，reviewed head `8853d17c5a567a8458e0f638eec90cd31b0dab82`，merge `0f85508f04e8192ec8c7949a512c488255fa58ef`。
- 当前方法开发 Issue：[ #29 多时距会话贡献分解与结构化充电站负荷预测](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29)。

## 2. 已审工作一览

| 工作 | 执行与技术验收 | 研究结论/限制 | 证据 |
| --- | --- | --- | --- |
| 5月 pilot | PR #21 | `PASS_ACTIVE_SESSION_DROP_M4` | PR #21 |
| 2/8/11 季节主实验 | 570 次日级拟合 | `MIXED_SEASONAL_EVIDENCE` | Issue #25 |
| 负值诊断/会话消融 | 诊断 + 570 次消融 | 单纯置零不足；不支持统一删除整组 | Issue #25/#26 |
| 预测组合 | 30 项控制 + 300 次校准拟合 | 0.5 简单平均为强基线；校准加权未稳定超过 | Issue #27 |
| 开发集 raw/processed | 01/04/07/10 | 开发数据冻结；holdout 未访问 | Issue #29 |
| M2/M3 expert 协议 | 固定 May HGB 参数、日级 OOS、共同测试行、私有缓存 | 强基线冻结 | PR #41/#45 |
| S1 launcher v1 | 模型拟合前停止 | `MERGE_COMMIT_NOT_FOUND`；未训练 | 本地失败 status |
| S1 launcher v1.1 | 模型拟合前停止 | `MERGE_COMMIT_NOT_FOUND_AFTER_EXPLICIT_FETCH`；未训练 | 本地失败 status |
| S1 launcher v1.2 | 首次真实进入 S1 | `COMMON_ROW_IDENTITY_INVALID`；定位 cache truth exact-equality 不一致 | PR #48 前置证据 |
| PR #48 | 4e-9 A roundoff PASS、2e-6 A mismatch FAIL；CI 通过 | 只修 tolerance，一切科学协议不变 | PR #48 |
| **S1 launcher v1.3** | **COMPLETE，fit_count=550** | **`MIXED_STRUCTURED_SIGNAL`** | **2026-09-11 v1.3 status** |

## 3. 冻结开发数据身份

```text
2019-01 e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12
2019-04 f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299
2019-07 9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2
2019-10 e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296
```

S1 v1.3 status 确认 `development_data_unchanged=true`，四个月 snapshot 均与冻结值一致。

source expert protocol SHA256：

```text
02c7809f1113aeaf20723030c96006ee0831b20ff219106da7d6968df535d71a
```

source baseline private manifest SHA256：

```text
2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd
```

## 4. G0 结构证据

未来站级电流中 existing-session pooled 贡献：

| horizon | existing | future arrivals |
| ---: | ---: | ---: |
| 15 min | 97.38% | 2.62% |
| 30 min | 90.61% | 9.39% |
| 60 min | 78.10% | 21.90% |
| 120 min | 56.52% | 43.48% |
| 240 min | 26.21% | 73.79% |

current-prefix Ridge 相对 persistence 仅 120/240 min 明显改善，因此 G0 原判定为 `STOP_OR_REVISE`。该结果支持 horizon-dependent composition shift 的机理分析，但不支持统一 prefix 模型。

## 5. 冻结 M2/M3/Equal 开发基线

Overall pooled weighted MAE：

```text
M2    30.1644064624 A
M3    29.1901878199 A
Equal 28.9172859886 A
```

By horizon：

```text
15:  M2 9.321587 / M3 8.540405 / Equal 8.703288
30:  16.999966 / 15.916203 / 15.974630
60:  27.534578 / 26.552741 / 26.141292
120: 42.351233 / 40.920106 / 40.249069
240: 54.614668 / 54.021484 / 53.518152
```

## 6. S1 冻结协议

`yhat_S1 = yhat_existing + yhat_arrival`

- existing branch：M3 legal features + M3 frozen HGB parameters；目标为 issue time 已连接 sessions 的未来贡献。
- arrival branch：M2 legal features + M2 frozen HGB parameters；目标为 future-arrival sessions 的贡献。
- 与 M2/M3/Equal 共用 test rows 和 total truth。
- 禁止 branch-specific tuning、calibration、clipping、gate、HSMM/state-space、M2/M3 重调和 final holdout。

冻结裁决：

### PASS_STRUCTURED_SIGNAL
必须同时满足：
1. S1 pooled MAE < M3；
2. S1 pooled MAE < Equal；
3. 至少 3/5 horizons < Equal；
4. 至少 3/4 months < Equal；
5. 任一 horizon 相对 Equal 退化 <= 5%。

### MIXED_STRUCTURED_SIGNAL
整体优于 M3 或 Equal，但稳定性条件未全部满足；只允许做失败分解。

### STOP_STRUCTURED_ROUTE
整体不优于 M3/Equal，或收益主要由单一 month/horizon 驱动；停止结构化路线。

## 7. S1 v1.3 正式结果

launcher：`evcf_structured_s1_launcher_v1_3.py`

SHA256：

```text
dc43e61f3dbb55c93c8bf070a0fd61170555f309c7c15fe8ee889773979fa9b8
```

代码身份：PR #48 reviewed head `8853d17c5a567a8458e0f638eec90cd31b0dab82`。

运行安全状态：

```text
status = COMPLETE
reason_code = null
holdout_accessed = false
m2_m3_retrained = false
gate_trained = false
hsmm_trained = false
state_space_model_trained = false
baseline_private_cache_unchanged = true
development_data_unchanged = true
fit_count = 550
```

### Overall pooled MAE

| 模型 | MAE (A) |
| --- | ---: |
| M2 | 30.164406 |
| M3 | 29.190188 |
| Equal | 28.917286 |
| **S1** | **28.594882** |

S1 vs M3：+2.0394%；S1 vs Equal：+1.1149%。

### By horizon

| horizon | M3 | Equal | S1 | S1 vs Equal |
| ---: | ---: | ---: | ---: | ---: |
| 15 | 8.540405 | 8.703288 | **8.317093** | +4.44% |
| 30 | 15.916203 | 15.974630 | **15.894373** | +0.50% |
| 60 | 26.552741 | **26.141292** | 27.181805 | -3.98% |
| 120 | 40.920106 | 40.249069 | **39.991241** | +0.64% |
| 240 | 54.021484 | 53.518152 | **51.589895** | +3.60% |

### By month

| month | M3 | Equal | S1 | S1 vs Equal |
| --- | ---: | ---: | ---: | ---: |
| 2019-01 | 26.334178 | **25.957616** | 26.127334 | -0.65% |
| 2019-04 | 28.839079 | **28.725210** | 29.505123 | -2.72% |
| 2019-07 | 29.574292 | 29.968817 | **28.901955** | +3.56% |
| 2019-10 | 32.002202 | 31.022485 | **29.944196** | +3.48% |

### 冻结判定复核

```text
pooled S1 < M3                PASS
pooled S1 < Equal             PASS
>=3/5 horizons < Equal        PASS (4/5)
>=3/4 months < Equal          FAIL (2/4)
max horizon degradation <=5%  PASS (3.98%)
```

正式决策：

```text
MIXED_STRUCTURED_SIGNAL
```

## 8. MIXED 失败分解：第一层只读结论

S1 vs Equal 的 month × horizon 改善率：

| month | 15 | 30 | 60 | 120 | 240 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2019-01 | +0.06% | -2.97% | -3.75% | +0.37% | +0.48% |
| 2019-04 | +7.56% | -1.37% | -10.69% | -3.99% | -0.60% |
| 2019-07 | +2.28% | -3.25% | -3.90% | +8.35% | +5.37% |
| 2019-10 | +6.29% | +7.34% | +0.74% | -3.55% | +8.16% |

第一层定位：
- 2019-04 是主要失败月；
- 60 min 是最持续的弱点；
- 30–120 min turnover transition 区域跨月不稳定；
- 240 min 在 01/07/10 为正、04 仅小幅负，长期 arrival-dominant 方向相对更稳定；
- 当前证据足以保留“horizon-dependent structure 值得解释”的研究价值，但不足以通过 `PASS_STRUCTURED_SIGNAL`。

## 9. 当前下一步

只继续 MIXED 允许的失败分解：existing branch、arrival branch、长时距误差主导来源、短/中时距对 M3/Equal 优势的破坏来源。

在失败分解完成前，不启动复杂模型，不访问 final holdout，不改冻结判据，不做 branch-specific tuning/calibration/clipping，也不清理任何历史 worktree、失败 status 或 private cache。
