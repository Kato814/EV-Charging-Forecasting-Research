# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-12。先读 [CURRENT_STATUS](CURRENT_STATUS.md)，再读 [P1 outcome](docs/JPL_P1_MECHANISM_PROBE_OUTCOME_20260912.md)、[实验台账](docs/EXPERIMENT_LEDGER.md)、[open-source idea ledger](docs/OPEN_SOURCE_IDEA_LEDGER.md) 与 [P1 protocol](docs/JPL_STRUCTURED_MECHANISM_PROBE_PROTOCOL_20260911.md)。

## 1. 接管结论

S1 的正式科学结论仍为 `MIXED_STRUCTURED_SIGNAL`。随后完成的低复杂度 P1 mechanism probe 已按预注册协议正式判为 **`STOP_MECHANISM_ROUTE`**：Probe E 与 Probe A 均为 `NO_COMPONENT_SIGNAL`，P1-EA 不得继续作为核心预测路线。

这不否定 G0/S1 已确认的 horizon-dependent composition shift 与 turnover/local-hour 结构；这些结果保留为机制分析与后续方法筛选依据。

final holdout 2019-03/06/09/12 继续封存。

## 2. 冻结数据与身份

目标：`station_current_mean_a`，单位 A。

Development：2019-01 / 04 / 07 / 10。

Final holdout：2019-03 / 06 / 09 / 12，禁止访问。

```text
2019-01 e4f49d92c7c95e8b4bf8069f14729f5262ac58761bccff5fd2fabef8acabda12
2019-04 f05e4892f4583c24ffe7d7da54c4cf929bd31714343c906c703b505043ccb299
2019-07 9eea83e13ea6fbe5fef694c5de93b5bc4a82f7efe00e90e4fadd6d0b9e9ff2
2019-10 e9d321a47a05baee829d2692f9ca491fd9e20563d477e6385fb2296834825296
```

Baseline private manifest：`2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd`。

S1 private manifest：`562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1`。

P1 private manifest：`df222c4731f3c3192735a6df2ccd2f692f1ea6d640a7954706e7bca17f51580f`。

P1 implementation：PR #56，CI-passed head `dac9d18596d8e3ba766e02f83b21d60e650e5957`，merge `33f391c5186650846826fdcb802e4f3e5c329d9d`。

## 3. 冻结基线 / S1

```text
M2    30.164406 A
M3    29.190188 A
Equal 28.917286 A
S1    28.594882 A
```

S1 在 5 个 horizons 中 4 个优于 Equal，但仅 2/4 开发月优于 Equal，因此正式保持 `MIXED_STRUCTURED_SIGNAL`。

最重要的 descriptive evidence：
- existing share 由 15 min 的 97.38% 降至 240 min 的 26.21%；
- future-arrival share 相反升至 73.79%；
- 30/60 min 的特定 mixed turnover bins 跨月稳定偏弱；
- 30/60/120 min 在 07:00 附近跨月稳定偏弱，09:00 附近可反转。

## 4. P1 正式结果

P1 按冻结协议测试：
- E：existing-session continuation probability × positive mark；
- A：future-arrival Poisson count × positive mark；
- EA：唯一主候选。

Pooled MAE：

```text
Equal      28.917286 A
S1         28.594882 A
P1-Eonly   30.065656 A
P1-Aonly  172.758507 A
P1-EA     172.966423 A
```

Component MAE：

```text
S1 existing 12.791178 A
P1-E       14.495331 A
S1 arrival 23.105152 A
P1-A      167.857291 A
```

Frozen branch decisions：

```text
E = NO_COMPONENT_SIGNAL
A = NO_COMPONENT_SIGNAL
```

P1-EA decision support：
- 0/5 horizons better than Equal；
- 0/4 months better than Equal；
- 60-min MAE 109.278945 A vs Equal 26.141292 A；
- maximum horizon degradation far exceeds 5%。

Therefore：**`STOP_MECHANISM_ROUTE`**。不得事后改阈值、挑 Eonly/Aonly 当 headline，或对 P1 做 rescue tuning。

## 5. P1 失败结构

主要灾难来自 Probe A。2019-10 的 fixed Poisson count model 在短/中 horizon 出现严重外推失稳，局部 hour 产生极端 predicted count / arrival contribution。该现象需要一次只读 post-mortem 以确认是 model-form/numerical extrapolation 还是 implementation/target-identity 问题，但该审计不能改变 STOP。

Probe E 本身也未显示稳定 component improvement；只有 1/5 horizon component win，0/4 month wins，因此没有依据直接升级到 formal survival/pycox。

P1 同时未修复 morning turnover：30/60/120 min @07:00 仍 4/4 月更差；60/120 min @09:00 仍可改善。说明 turnover phenomenon 存在，但 P1 参数化路线不适合充当核心预测器。

## 6. 当前唯一下一步

### Step A — read-only P1-A post-mortem
仅审计：
- 极端预测所在 rolling fold / local hour；
- Poisson predicted count 与线性预测量的分布；
- target identity 与 private-cache row identity；
- 是否为实现错误、数值失稳或模型形式不适配。

严格禁止：
- 重跑 P1 调参；
- 改 Poisson alpha / feature set；
- clipping/calibration；
- 用 holdout；
- 因 post-mortem 结果把 STOP 改成 MIXED/PASS。

### Step B — new-method selection
post-mortem 关闭后重新进入方法创新筛选。继续系统检索 GitHub/论文，重点利用已验证的 horizon-conditioned turnover phenomenon 找成熟表示、可复用工程组件和真正缺口；不得因为已有 pycox/EasyTPP 就直接套用。

## 7. 当前禁止事项

- final holdout 继续封存；
- reliability/composition gate 不回归；
- realized future composition 不做 predictor；
- P1 不做 post-hoc retuning/clipping/calibration；
- 不用大型 neural survival/TPP 来“救”失败 branch；
- 不重调 M2/M3，不重选开发月；
- 不删除历史 worktree、失败 status、private cache；
- 禁止 `reset --hard`、`clean`、盲目 stash、force push。

## 8. GitHub 维护

所有关键科学裁决需同步 Issue #29、CURRENT_STATUS、HANDOFF 与 durable outcome 文档。private row-level outputs/cache 继续仓库外保存。新方法在本机执行前必须先冻结问题、协议、代码身份并通过 PR/CI。
