# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-12。先读 [CURRENT_STATUS](CURRENT_STATUS.md)，再读 [P1 outcome](docs/JPL_P1_MECHANISM_PROBE_OUTCOME_20260912.md)、[P1-A post-mortem outcome](docs/JPL_P1_A_POSTMORTEM_OUTCOME_20260912.md)、[post-P1 method screening](docs/JPL_POST_P1_METHOD_SCREENING_20260912.md)、[R1 protocol](docs/JPL_JOINT_SESSION_STATE_PROBE_PROTOCOL_20260912.md)、[实验台账](docs/EXPERIMENT_LEDGER.md) 与 [open-source idea ledger](docs/OPEN_SOURCE_IDEA_LEDGER.md)。

## 1. 接管结论

S1 正式结论保持 `MIXED_STRUCTURED_SIGNAL`。P1 已 `STOP_MECHANISM_ROUTE`，唯一授权的 P1-A read-only post-mortem 已 COMPLETE；P1 不再 rescue。

post-P1 method screening 将当前问题缩窄为一个表示问题：M3 的独立边际池化是否丢失当前连接 session population 的 within-session joint state，以及这些 joint state 是否对多时距 aggregate current 有稳定增量信息。

R1 protocol 与 implementation 均已在结果产生前冻结并通过 PR/CI。R1 尚未在真实开发集上运行。**当前唯一授权动作是一次 development-only R1 launcher run；final holdout 2019-03/06/09/12 继续封存。**

## 2. 冻结数据与基线

目标：`station_current_mean_a`，单位 A。

Development：2019-01 / 04 / 07 / 10。

Final holdout：2019-03 / 06 / 09 / 12，禁止访问。

```text
M2    30.164406 A
M3    29.190188 A
Equal 28.917286 A
S1    28.594882 A
```

Baseline private manifest：`2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd`。

S1 private manifest：`562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1`。

P1 private manifest：`df222c4731f3c3192735a6df2ccd2f692f1ea6d640a7954706e7bca17f51580f`，仅历史证据，不是 R1 输入。

## 3. R1 科学问题

> Does within-session joint alignment among the legal issue-time connected-session states provide stable predictive information for direct aggregate current forecasting beyond the same M3 marginal pools and the same joint-feature availability pattern?

R1 不预测 existing/arrival 分量，不预测 future-session identity，也不训练 Deep Sets / Set Transformer / MoE。

## 4. R1 matched design

两条 arm 都使用 frozen M3 311 raw features，并追加 55 个同位置 pair features：

```text
R1-Control:
  defined pair -> 0.0
  undefined pair -> NaN

R1-Joint:
  defined pair -> pairwise-complete Pearson correlation
  undefined pair -> NaN
```

Pair 定义条件相同：至少 2 个 pairwise-complete current sessions，且两个字段都有正有限方差。

因此 Control / Joint 具有：
- identical raw width = 366；
- identical nullable mask；
- identical missingness/availability pattern；
- identical frozen M3 horizon-specific HGB parameters；
- identical rolling-origin / OOS rows / direct aggregate target。

唯一主比较是 `R1-Joint vs R1-Control`。外部参照 M2 / M3 / Equal / S1。

## 5. 冻结 R1 决策

```text
PASS_JOINT_STATE_SIGNAL
MIXED_JOINT_STATE_SIGNAL
STOP_JOINT_STATE_ROUTE
```

PASS 需要同时满足 pooled Joint < Control / Equal、跨 horizon 和跨 month 稳定、60-min 优于 Equal、且任何 horizon 对 Equal 退化不超过 5%。

MIXED 仅在 pooled Joint < Control 且至少 2/5 horizon + 2/4 month 胜 Control，但一个或多个 PASS 条件失败时使用。

STOP 在 pooled Joint >= Control，或最多仅 1 个 horizon / 1 个月胜 Control 时触发。

不得结果后改阈值。

## 6. 正式代码身份

R1 protocol：
- PR #61
- merge `5c56ac71d6e94e6c566e88a855b4f9646eb170ea`

R1 implementation：
- PR #62
- CI-passed reviewed head `e01607078431141a1fccdd6a9db5f75ae561bfda`
- merge `0a2f1fc29af3fc6232534c8f6073c276dbe9122f`
- full pytest / compileall / Ruff PASS

Launcher SHA256：
`4f38e5e924c58142d15ce3a0a3965c33663fa028347d30e52fdcbf02bed830b4`。

## 7. 当前唯一下一步

Run the single authorized development-only R1 launcher.

- If COMPLETE: upload only the newest `evcf_r1_joint_state_status_*.json`; apply frozen PASS/MIXED/STOP exactly.
- If INCOMPLETE: do not rerun automatically; upload only the newest status JSON for failure audit.
- Do not upload private NPZ cache by default.

## 8. 当前禁止事项

- no final holdout access;
- no P1 rescue;
- no R1 pair selection / correlation-estimator switching / retuning;
- no clipping/calibration or row deletion;
- no realized future composition predictor/gate;
- no Deep Sets / Set Transformer / MoE before R1 outcome;
- no M2/M3 retuning or development-month reselection;
- no deletion of historical worktrees, failed statuses or private caches;
- no `reset --hard`, `clean`, blind stash or force push。

## 9. GitHub maintenance

R1 follows protocol → implementation PR/CI → local status → outcome. Issue #29, CURRENT_STATUS, HANDOFF, experiment ledger and open-source idea ledger remain the traceability chain. Private row-level outputs stay outside the repository.
