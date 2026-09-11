# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-11。先读 [CURRENT_STATUS](CURRENT_STATUS.md)，再读本文、[实验台账](docs/EXPERIMENT_LEDGER.md)、[数据用途台账](docs/DATA_USAGE_LEDGER.md)、[open-source idea ledger](docs/OPEN_SOURCE_IDEA_LEDGER.md) 和 [P1 mechanism probe protocol](docs/JPL_STRUCTURED_MECHANISM_PROBE_PROTOCOL_20260911.md)。

## 1. 接管结论

S1 launcher v1.3 已完整运行，正式冻结判定保持 `MIXED_STRUCTURED_SIGNAL`：pooled MAE 同时优于 M3 与 Equal，5 个 horizon 中 4 个优于 Equal，但只有 2/4 个开发月优于 Equal，因此不得改判为 PASS。

两轮只读 MIXED 失败诊断已经完成。当前不再处于“继续找失败原因”的开放状态，而是进入**P1 低复杂度 mechanism probe 准备阶段**。结构化路线被保留的依据是可复现的 horizon × turnover × local-hour 结构，而不是 S1 本身通过。

最终 holdout 2019-03/06/09/12 继续封存。

## 2. 当前科学问题

> 充电站负荷是否存在可复现的、随预测时距变化的“当前会话连续性 → 会话周转 → 未来到达主导”机制转变；显式利用这一时距依赖机制，能否稳定优于 M2/M3/Equal/S1。

边界：
- reliability gate 不是主线；
- existing + arrival 双分支本身不是 novelty；
- current/pilot stage identification 不是 novelty；
- generic Transformer/Mamba/diffusion/state-space replacement 不是主线；
- survival/TPP/GMM 等成熟方法本身也不是 novelty。

真正候选贡献只允许围绕经开发集证据支持的 horizon-dependent session-turnover mechanism 展开。

## 3. 冻结数据与目标

目标：`station_current_mean_a`，单位 A。

开发集：2019-01 / 2019-04 / 2019-07 / 2019-10。

final holdout：2019-03 / 2019-06 / 2019-09 / 2019-12，禁止访问。

冻结 development snapshots：

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

## 4. 冻结强基线与 S1

```text
M2    30.164406 A
M3    29.190188 A
Equal 28.917286 A
S1    28.594882 A
```

S1 vs Equal by horizon：

```text
15  +4.44%
30  +0.50%
60  -3.98%
120 +0.64%
240 +3.60%
```

S1 vs Equal by month：

```text
2019-01 -0.65%
2019-04 -2.72%
2019-07 +3.56%
2019-10 +3.48%
```

冻结判定：`MIXED_STRUCTURED_SIGNAL`。

## 5. 失败分解的最终证据

### 5.1 binary arrival hurdle 不足

60 min 的 S1 弱势同时存在于 `arrival_truth=0` 和 `arrival_truth>0` 子集，因此不能用“未来有没有新到达”一个二分类 gate 解释或修复。

### 5.2 composition 不是单调 gate

realized future arrival share 只作为离线诊断标签，不可作为预测输入。

跨四开发月：
- 30 min / arrival share 25–50%：4/4 月 S1 劣于 Equal；
- 60 min / arrival share 50–75%：4/4 月 S1 劣于 Equal；
- 60 min / arrival share 0–25%：4/4 月 S1 优于 Equal；
- 120 min composition 方向重新混合；
- 240 min pooled 各 composition bin 均优于 Equal。

所以真正现象是 horizon-conditioned turnover instability，而不是单一 composition threshold。

### 5.3 local-hour regime 可复现

典型跨月符号稳定：

```text
30 min @07:00 4/4 worse, median +16.59 A
30 min @09:00 4/4 better, median  -2.30 A
60 min @06:00 4/4 worse, median +17.67 A
60 min @07:00 4/4 worse, median +24.23 A
60 min @09:00 4/4 better, median -13.23 A
60 min @10:00 4/4 better, median -11.69 A
120 min @07:00 4/4 worse, median +15.15 A
120 min @09:00 4/4 better, median -13.31 A
```

这足以排除“单一月份偶然噪声”作为主要解释。

## 6. 诊断版本链

- PR #52：read-only MIXED diagnostic；CI-passed head `63ead204b99b131f2c5634f868582411aad8703b`；merge `6236d3fe451838ffb70ff0a1e3a4fcca9de60841`。
- PR #53：read-only transition-map diagnostic；CI-passed head `cc5da1a3683452bea95ff62501dc27c9c2ab7619`；merge `6464cac561f5a1f0c4f7657a6613537c2c675f61`。

最后一次 diagnostic：

```text
status = COMPLETE
reason_code = null
development_data_accessed = false
holdout_accessed = false
model_fit_attempted = false
baseline_private_cache_unchanged = true
structured_private_cache_unchanged = true
existing_worktrees_preserved = true
```

## 7. 当前唯一下一步：P1 low-complexity mechanism probe

协议文件：`docs/JPL_STRUCTURED_MECHANISM_PROBE_PROTOCOL_20260911.md`。

### Probe E — existing-session continuation × mark

只使用 issue-time legal M3 session fields + calendar。对每个 horizon，固定 logistic model 预测该当前连接 session 在目标窗口仍有正电流贡献的概率，并用固定 GammaRegressor 预测正电流 mark；两者乘积后对当前连接 sessions 求和得到 existing contribution。

首轮故意不强制 formal survival/hazard monotonicity，因为同一 EV session 可能临时停充后恢复。只有 continuation×mark 显示稳定开发信号后，才允许评估真正的 hazard/survival 模型。

### Probe A — future-arrival count × mark

只使用 M2 legal features：
- PoissonRegressor 预测 future-arrival contributing session count；
- GammaRegressor 预测 positive mark；
- 两者相乘得到 arrival contribution。

不启用 neural TPP。

### Primary candidate

`P1-EA = Probe-E existing + Probe-A arrival` 是唯一主候选。

`P1-Eonly` / `P1-Aonly` 仅用于归因，禁止事后挑最好结果作为 headline。

PASS 除稳定性要求外必须同时满足：
- pooled total MAE < Equal；
- pooled total MAE < S1；
- 60-min pooled MAE < Equal。

## 8. 当前禁止事项

- 不访问 final holdout；
- 不把 realized future composition 当 predictor/gate；
- 不使用 pycox/DeepSurv；
- 不使用 EasyTPP/RMTPP/NHP/THP；
- 不恢复 reliability/composition gate；
- 不使用 HSMM/neural state-space；
- 不做 branch-specific hyperparameter search；
- 不根据测试结果 clipping/calibration；
- 不重调 M2/M3，不更换开发月；
- 不清理历史 worktree、失败 status、private cache；
- 不使用 `reset --hard`、`clean`、盲目 stash、force push。

## 9. 执行与仓库管理

主控负责：协议、代码实现、测试、PR/CI、结果裁决、GitHub 维护和外部开源检索。用户只执行明确授权的本地单行 PowerShell/Python 命令。

所有重要 method/protocol/status/scientific conclusion 都要保持 commit/PR/Issue 可追溯；private row-level outputs 继续仓库外保存。
