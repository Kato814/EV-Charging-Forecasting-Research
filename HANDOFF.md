# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-12。先读 [CURRENT_STATUS](CURRENT_STATUS.md)，再读 [P1 outcome](docs/JPL_P1_MECHANISM_PROBE_OUTCOME_20260912.md)、[P1-A post-mortem outcome](docs/JPL_P1_A_POSTMORTEM_OUTCOME_20260912.md)、[post-P1 method screening](docs/JPL_POST_P1_METHOD_SCREENING_20260912.md)、[R1 protocol](docs/JPL_JOINT_SESSION_STATE_PROBE_PROTOCOL_20260912.md)、[实验台账](docs/EXPERIMENT_LEDGER.md) 与 [open-source idea ledger](docs/OPEN_SOURCE_IDEA_LEDGER.md)。

## 1. 接管结论

S1 正式结论保持 `MIXED_STRUCTURED_SIGNAL`。P1 已按预注册协议正式 `STOP_MECHANISM_ROUTE`，P1-A 唯一授权的 read-only post-mortem 也已 COMPLETE；P1 不再 rescue。

post-P1 method screening 已完成。当前新主线不是 generic MoE / Transformer / survival / TPP，而是一个更窄的表示问题：**M3 的独立边际池化是否丢失了当前连接 session population 的 within-session joint state，而这些 joint state 是否对不同预测时距的 aggregate current 有稳定增量信息。**

R1 joint-session-state representation probe 已在结果产生前冻结；R1 尚未拟合。final holdout 2019-03/06/09/12 继续封存。

## 2. 冻结身份

目标：`station_current_mean_a`，单位 A。

Development：2019-01 / 04 / 07 / 10。

Final holdout：2019-03 / 06 / 09 / 12，禁止访问。

Baseline private manifest：`2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd`。

S1 private manifest：`562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1`。

P1 private manifest：`df222c4731f3c3192735a6df2ccd2f692f1ea6d640a7954706e7bca17f51580f`。

P1 implementation：PR #56；CI-passed head `dac9d18596d8e3ba766e02f83b21d60e650e5957`；merge `33f391c5186650846826fdcb802e4f3e5c329d9d`。

P1-A post-mortem：PR #58；CI-passed head `9bc752f1b416e0dce4cb59942d3ecb07315b9273`；merge `6df5cc836635fedb2034f27cdb34e7dda6e8a885`。

P1 closeout docs：PR #59；merge `0dbae8be2fa71d870ff89138280e1df583ab7e60`。

Post-P1 method screening：PR #60；merge `5c964601e2374d16a341e2c55ec73ec0116731f6`。

## 3. 冻结基线 / S1 / P1

```text
M2          30.164406 A
M3          29.190188 A
Equal       28.917286 A
S1          28.594882 A
P1-Eonly    30.065656 A
P1-Aonly   172.758507 A
P1-EA      172.966423 A
```

Frozen P1 decisions：

```text
E = NO_COMPONENT_SIGNAL
A = NO_COMPONENT_SIGNAL
P1-EA = STOP_MECHANISM_ROUTE
```

P1-EA：0/5 horizons better than Equal；0/4 months better；60-min MAE 109.278945 A vs Equal 26.141292 A。

## 4. post-P1 方法筛选边界

2025–2026 adjacent work already covers generic EV multi-horizon TFT/Transformer, sparse MoE / horizon-conditioned regime routing, lightweight residual probabilistic models and session-generative forecasting. Set Transformer / Deep Sets are also mature general architectures.

Therefore none of the following is a defensible novelty claim by itself:
- generic MoE for EV load;
- horizon-specific gating;
- generic Set Transformer / Deep Sets;
- existing + future-session decomposition;
- survival / TPP usage;
- Transformer/Mamba backbone replacement.

The internal representation gap is concrete: M3 uses 11 legal connected-session fields and independently pools each field into 10 marginal statistics, losing which values co-occur within the same session. This motivates R1.

## 5. R1 frozen scientific question

> Does preserving within-session joint alignment of the legal issue-time connected-session state provide stable predictive information for direct aggregate current forecasting beyond the same M3 marginal pools and the same pair-feature availability pattern?

R1 is deliberately low complexity and matched-capacity. It does not train a learned set encoder.

## 6. R1 matched representations

Both arms begin with the frozen M3 311 raw features and append 55 pair positions for `C(11,2)` legal session-field pairs.

For each pair, availability is defined identically from pairwise-complete current sessions: at least two co-observed sessions and positive finite variance in both fields.

```text
R1-Control:
  defined pair -> 0.0
  undefined pair -> NaN

R1-Joint:
  defined pair -> pairwise-complete Pearson correlation
  undefined pair -> NaN
```

Thus both arms have:
- identical raw width = 366;
- identical nullable mask;
- identical missingness/availability indicators;
- identical frozen M3 horizon-specific HGB parameters;
- identical preprocessing / rolling-origin / OOS rows / target.

The only experimental difference is the within-session cross-field alignment value.

## 7. R1 frozen decisions

Primary matched comparison: `R1-Joint vs R1-Control`.

External references: M2 / M3 / Equal / S1 on identical OOS rows.

Possible decisions:

```text
PASS_JOINT_STATE_SIGNAL
MIXED_JOINT_STATE_SIGNAL
STOP_JOINT_STATE_ROUTE
```

PASS requires, among other preregistered conditions, pooled improvement vs both Control and Equal, at least 3/5 horizon wins vs both, at least 3/4 month wins vs both, 60-min improvement vs Equal, and no horizon degradation >5% vs Equal.

MIXED requires pooled Joint < Control with at least 2/5 horizon and 2/4 month wins but failure of one or more PASS conditions.

STOP is triggered if pooled Joint >= Control, or Joint wins at most 1 horizon, or at most 1 month.

Thresholds cannot change after results.

## 8. 当前唯一下一步

Implement R1-Control / R1-Joint under the frozen protocol in a dedicated code PR.

Before any local fit:
- unit tests for permutation invariance;
- unit tests for identical Control/Joint availability masks;
- test that per-field session permutations preserve M3 marginal pools but can alter Joint correlations;
- final-holdout fail-closed tests;
- full repository pytest / compileall / Ruff green;
- local launcher bound to the CI-passed reviewed head.

Only then may one development-only R1 run be authorized.

## 9. 当前禁止事项

- no final holdout access;
- no P1 rescue;
- no R1 pair selection / correlation-estimator switching / retuning;
- no clipping/calibration;
- no removal of pathological P1 rows;
- no realized future composition predictor/gate;
- no Deep Sets / Set Transformer / MoE fit before R1 outcome;
- no M2/M3 retuning or development-month reselection;
- no deletion of historical worktrees, failed statuses or private caches;
- no `reset --hard`, `clean`, blind stash or force push.

## 10. GitHub maintenance

R1 must use a separate protocol → implementation PR/CI → local status → outcome chain. Issue #29, CURRENT_STATUS, HANDOFF, experiment ledger and open-source idea ledger must remain synchronized. Private row-level outputs/cache stay outside the repository.
