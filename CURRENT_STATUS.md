# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新日期：2026-09-11。本文件是当前状态唯一入口；历史执行记录见 [实验台账](docs/EXPERIMENT_LEDGER.md)，数据用途见 [数据台账](docs/DATA_USAGE_LEDGER.md)，接管规则见 [HANDOFF](HANDOFF.md)，下一阶段冻结协议见 [P1 mechanism probe protocol](docs/JPL_STRUCTURED_MECHANISM_PROBE_PROTOCOL_20260911.md)。

**通俗说明：S1 v1.3 的正式结论仍为 `MIXED_STRUCTURED_SIGNAL`，不会事后改成 PASS。两轮只读失败诊断现已完成并表明：S1 的问题不是随机月份噪声，也不是一个简单“未来有没有新到达”的 gate，而是可复现的 horizon × session-turnover × time-of-day 耦合。结构化路线因此保留，但下一步只允许低复杂度 survival/continuation + arrival count×mark 机制探针；final holdout 2019-03/06/09/12 继续封存，pycox/EasyTPP/复杂深度模型尚未授权。**

## 1. 当前研发任务

| 项目 | 当前状态 |
| --- | --- |
| 当前 Issue | [#29 多时距会话贡献分解与结构化充电站负荷预测](https://github.com/Kato814/EV-Charging-Forecasting-Research/issues/29) |
| 当前阶段 | **S1 MIXED 失败分解已完成；进入 P1 低复杂度机制探针准备** |
| 开发集 | 2019-01 / 04 / 07 / 10 |
| 最终 holdout | **2019-03 / 06 / 09 / 12，禁止访问** |
| 预测目标 | `station_current_mean_a`，单位 A；kW 未授权 |
| 强基线 | M2、M3、`0.5*M2+0.5*M3` |
| S1 冻结决策 | **`MIXED_STRUCTURED_SIGNAL`** |
| P1 主候选 | `P1-EA = continuation existing + count×mark arrival` |
| P1 协议 | `docs/JPL_STRUCTURED_MECHANISM_PROBE_PROTOCOL_20260911.md` |

## 2. 当前科学问题

候选主问题保持不变：

> 充电站负荷是否存在可复现的、随预测时距变化的“当前会话连续性 → 会话周转 → 未来到达主导”机制转变；显式利用这一时距依赖机制，能否稳定优于强 M2/M3/Equal 基线。

已知 novelty 边界：
- reliability gate 不再是主线；
- existing + arrival 两分支本身不是创新；
- current/pilot stage 识别不是创新；
- 普通 Transformer/Mamba/diffusion/state-space 换骨干不是主线；
- survival、TPP、GMM 等成熟方法本身也不能作为 novelty claim。

真正可能的贡献只允许建立在“horizon-dependent session turnover”这一可复现机制及其稳定预测收益上。

## 3. 冻结数据与身份

### Development processed snapshots

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

## 4. G0 与 S1 已冻结事实

G0 existing-session pooled contribution：

```text
15 min  97.38%
30 min  90.61%
60 min  78.10%
120 min 56.52%
240 min 26.21%
```

future-arrival complement：2.62%、9.39%、21.90%、43.48%、73.79%。

冻结开发集 pooled MAE：

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

S1 仅 2/4 开发月优于 Equal，因此正式决策保持 `MIXED_STRUCTURED_SIGNAL`；不得修改冻结阈值。

## 5. MIXED 失败分解已完成

### 第一层：branch / month / horizon

- 2019-04 是最弱月份；
- 60 min 是最持续的弱 horizon；
- future-arrival target 高度零膨胀，但 60 min 在 `arrival_truth=0` 与 `arrival_truth>0` 两侧均可退化，因此简单 binary hurdle 不能解释问题；
- existing branch 随 horizon 增长出现更高的退出/零贡献与负预测比例，支持继续检验 continuation/hazard 结构；
- branch residual 并无强同向叠加，不能把 S1 失败简单归因于两个分支误差相加。

### 第二层：transition map

realized arrival share 仅用于离线诊断，不可作为预测输入。关键跨月稳定现象：

- **30 min / arrival share 25–50%：4/4 月均劣于 Equal**；
- **60 min / arrival share 50–75%：4/4 月均劣于 Equal**，是最强的可复现 turnover 弱区；
- **60 min / arrival share 0–25%：4/4 月均优于 Equal**；
- 120 min 的 composition 方向重新变得混合；
- 240 min pooled 各 composition bin 均优于 Equal。

这说明同一个 composition share 在不同 horizon 的行为不同，不能使用单一 composition gate。

### 第三层：local-hour stability

跨四个开发月可复现的典型符号反转：

```text
30 min @07:00  4/4 worse, median S1-Equal +16.59 A
30 min @09:00  4/4 better, median S1-Equal  -2.30 A
60 min @06:00  4/4 worse, median             +17.67 A
60 min @07:00  4/4 worse, median             +24.23 A
60 min @09:00  4/4 better, median             -13.23 A
60 min @10:00  4/4 better, median             -11.69 A
120 min @07:00 4/4 worse, median             +15.15 A
120 min @09:00 4/4 better, median             -13.31 A
```

因此主要证据指向可复现的**时距相关 session-turnover regime**，而不是月份偶然性或单一 arrival-share 阈值。

## 6. 诊断代码与安全状态

- PR #52：read-only MIXED diagnostic；reviewed/CI-passed head `63ead204b99b131f2c5634f868582411aad8703b`；merge `6236d3fe451838ffb70ff0a1e3a4fcca9de60841`。
- PR #53：read-only transition-map diagnostic；reviewed/CI-passed head `cc5da1a3683452bea95ff62501dc27c9c2ab7619`；merge `6464cac561f5a1f0c4f7657a6613537c2c675f61`。

最后 transition diagnostic：

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

## 7. 当前唯一下一步：P1 mechanism probe

冻结协议：`docs/JPL_STRUCTURED_MECHANISM_PROBE_PROTOCOL_20260911.md`。

P1 分为：
- **Probe E**：当前连接 session 的低复杂度 discrete logistic hazard / continuation；
- **Probe A**：future-arrival 的 Poisson count × Gamma positive mark；
- **P1-EA**：两机制合成后的唯一主候选；Eonly/Aonly 仅做归因。

所有模型固定参数、无 hyperparameter search，并继承既有 rolling-origin / common-row / development-only 约束。

P1-EA 若要 PASS，除原稳定性要求外还必须：
- pooled MAE < Equal；
- pooled MAE < S1；
- **60-min pooled MAE < Equal**。

## 8. 当前禁止事项

- 不访问 final holdout 2019-03/06/09/12；
- 不把 realized future composition 用作预测输入；
- 不恢复 reliability/composition gate；
- 不启用 pycox / DeepSurv / EasyTPP / neural TPP；
- 不开发 HSMM / neural state-space；
- 不做 branch-specific hyperparameter search；
- 不做看到测试结果后的 clipping/calibration；
- 不重调 M2/M3 或重选开发月；
- 不清理历史 worktree、失败 status、private cache；
- 禁止 `reset --hard`、`clean`、盲目 stash、force push。

## 9. 仓库维护

重要运行、方法协议、外部开源参考和科学结论继续同步维护 CURRENT_STATUS、HANDOFF、实验台账、open-source idea ledger 与 Issue #29。private row predictions / private caches 继续仓库外保存。
