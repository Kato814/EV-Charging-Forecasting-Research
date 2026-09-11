# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-11。先读 [CURRENT_STATUS](CURRENT_STATUS.md)，再读本文、[实验台账](docs/EXPERIMENT_LEDGER.md) 和 [数据用途台账](docs/DATA_USAGE_LEDGER.md)。

## 1. 接管结论

**当前处于 S1 开发集 Go/No-Go 完成后的 MIXED 失败分解阶段。S1 launcher v1.3 已完整运行，`status=COMPLETE`，正式冻结判定为 `MIXED_STRUCTURED_SIGNAL`。整体 pooled MAE 同时优于 M3 与 Equal，5 个 horizon 中 4 个优于 Equal，但只有 2/4 个开发月优于 Equal，因此未达到 `PASS_STRUCTURED_SIGNAL`。最终 holdout 2019-03/06/09/12 继续封存。**

当前研发 Issue 为 [#29](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29)。主控负责协议、代码、审查、结果裁决和仓库维护；用户仅执行明确授权的本地单行 PowerShell/Python 命令。

## 2. 当前科学问题

候选主问题：

> 充电站负荷是否存在可复现的、随预测时距变化的“当前会话连续性 → 会话周转 / 未来到达主导”的机制转变；显式利用这一时距依赖结构，能否稳定优于强 M2/M3/0.5 基线。

边界：
- reliability gate 已降级/终止，不再作为核心方法；
- existing + arrival 双源分解本身不作为 novelty claim；
- current/pilot stage 识别不作为 novelty claim；
- 普通 Transformer/Mamba/diffusion/state-space 换骨干不作为当前主线；
- 真正后续创新只有在开发证据支持后，才能围绕 horizon-dependent transition / session turnover mechanism 展开。

## 3. 数据与目标边界

目标固定为 `station_current_mean_a`，单位 A。未经授权不得改为 kW。

数据分区：
- 已使用/探索：2019-02/05/08/11；
- 方法开发集：2019-01/04/07/10；
- 最终独立 holdout：2019-03/06/09/12；继续禁止访问。

冻结开发 snapshot：

```text
2019-01 e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12
2019-04 f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299
2019-07 9eea83e13ea6fbe5fef694c5de93b5bc4c4a82f7efe00e90e4fadd6d0b9e9ff2
2019-10 e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296
```

source expert protocol SHA256：

```text
02c7809f1113aeaf20723030c96006ee0831b20ff219106da7d6968df535d71a
```

baseline private manifest SHA256：

```text
2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd
```

## 4. 冻结强基线

- M2：24 h history/calendar + 当前站级 aggregate state。
- M3：M2 + 当前连接 session 的 legal fine-grained state pools。
- Equal：`0.5*M2 + 0.5*M3`。

正式开发集 pooled weighted MAE：

```text
M2    30.164406 A
M3    29.190188 A
Equal 28.917286 A
```

按 horizon：

```text
15:  M2 9.321587 / M3 8.540405 / Equal 8.703288
30:  16.999966 / 15.916203 / 15.974630
60:  27.534578 / 26.552741 / 26.141292
120: 42.351233 / 40.920106 / 40.249069
240: 54.614668 / 54.021484 / 53.518152
```

## 5. G0 结构发现

existing-session 对总负荷 pooled 贡献：

```text
15 min  97.38%
30 min  90.61%
60 min  78.10%
120 min 56.52%
240 min 26.21%
```

future-arrival 补集分别为 2.62%、9.39%、21.90%、43.48%、73.79%。

这说明负荷组成随 horizon 出现明显结构转移，但该发现本身不等于最终预测方法通过。

## 6. S1 冻结定义

`yhat_S1 = yhat_existing + yhat_arrival`

Existing branch：
- M3 legal features；
- M3 已冻结 HGB 参数；
- 目标为 issue time 已连接 sessions 的未来贡献。

Arrival branch：
- M2 legal features；
- M2 已冻结 HGB 参数；
- 目标为 future-arrival sessions 的未来贡献。

禁止 branch-specific tuning、calibration、clipping、gate、HSMM/state-space、M2/M3 重调以及 holdout 访问。

## 7. S1 运行链

- PR #47：S1 structured baseline；merge `7e914c1fe73376c720c376f0c12fa226a1082314`。
- launcher v1：`MERGE_COMMIT_NOT_FOUND`，未训练。
- launcher v1.1：`MERGE_COMMIT_NOT_FOUND_AFTER_EXPLICIT_FETCH`，未训练。
- launcher v1.2：首次真实进入 S1，`COMMON_ROW_IDENTITY_INVALID`。
- 根因之一：baseline cache truth 使用 exact equality，与 G0 数值重构约 4e-9 A roundoff 不一致。
- PR #48：改为 `np.allclose(..., rtol=0, atol=1e-6 A)`；reviewed head `8853d17c5a567a8458e0f638eec90cd31b0dab82`；merge `0f85508f04e8192ec8c7949a512c488255fa58ef`。
- launcher v1.3 SHA256：`dc43e61f3dbb55c93c8bf070a0fd61170555f309c7c15fe8ee889773979fa9b8`。
- v1.3：**COMPLETE / MIXED_STRUCTURED_SIGNAL**。

## 8. S1 v1.3 结果

Overall pooled MAE：

```text
M2    30.1644064624 A
M3    29.1901878199 A
Equal 28.9172859886 A
S1    28.5948815297 A
```

S1 相对 M3 改善 2.0394%，相对 Equal 改善 1.1149%。

By horizon：

```text
15  S1 8.317093  vs Equal +4.44%
30  S1 15.894373 vs Equal +0.50%
60  S1 27.181805 vs Equal -3.98%
120 S1 39.991241 vs Equal +0.64%
240 S1 51.589895 vs Equal +3.60%
```

By month：

```text
2019-01 S1 26.127334 vs Equal -0.65%
2019-04 S1 29.505123 vs Equal -2.72%
2019-07 S1 28.901955 vs Equal +3.56%
2019-10 S1 29.944196 vs Equal +3.48%
```

## 9. 冻结判定

PASS 条件逐项：

```text
1 pooled S1 < M3                  PASS
2 pooled S1 < Equal               PASS
3 >=3/5 horizons < Equal          PASS (4/5)
4 >=3/4 months < Equal            FAIL (2/4)
5 max horizon degradation <=5%    PASS (3.98%)
```

因此只能判定：

```text
MIXED_STRUCTURED_SIGNAL
```

不得事后改阈值。

## 10. 当前允许的失败分解

只允许：
- month × horizon；
- existing branch 误差；
- arrival branch 误差；
- 判断 long horizon 是否由 arrival branch 主导；
- 判断短/中时距结构化分解是否破坏 M3/Equal 优势。

初步定位：
- 2019-04 最弱，只有 15 min 优于 Equal；
- 60 min 是跨月最持续的弱点；
- 2019-07/10 在 120/240 或 240 min 有明显收益；
- 30–120 min turnover transition 区域表现最不稳定。

不要立即启动深度模型或复杂机制。

## 11. 协议安全状态

v1.3：

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

private structured output 继续仓库外本地保存；不提交逐点预测或 private cache。

## 12. 当前禁止事项

- 不访问 2019-03/06/09/12；
- 不恢复 reliability gate；
- 不开发 HSMM / neural state-space；
- 不做 branch-specific tuning；
- 不做 calibration/clipping；
- 不重调 M2/M3；
- 不根据结果换开发月；
- 不清理历史 worktree、失败 status、private cache；
- 不使用 `reset --hard`、`clean`、盲目 stash 或 force push。

## 13. 当前下一步

当前不需要重新运行 S1。先完成 MIXED 的只读失败分解并把结论记录到 Issue #29 / 实验台账。只有该分解完成后，才讨论是否还值得保留 structured session route；在此之前不设计下一代复杂模型，也不访问 final holdout。
