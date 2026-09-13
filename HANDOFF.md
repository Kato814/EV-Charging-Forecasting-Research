# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-13。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R4-I0 outcome](docs/JPL_R4_I0_INFORMATION_SUFFICIENCY_OUTCOME_20260913.md)、[R4-D1 outcome](docs/JPL_R4_D1_STATE_GEOMETRY_DIAGNOSTIC_OUTCOME_20260913.md) 和 [R4-D2 protocol](docs/JPL_R4_D2_QUERY_GEOMETRY_REGIME_PROTOCOL_20260913.md)。

## 1. 冻结科学状态

```text
S1    = MIXED_STRUCTURED_SIGNAL
P1    = STOP_MECHANISM_ROUTE, CLOSED
R1    = MIXED_JOINT_STATE_SIGNAL, CLOSED
R2    = STOP_HIGHER_ORDER_SET_ROUTE, CLOSED
R3-C0 = STOP_CONTROL_ENDOGENEITY_ROUTE, CLOSED
R4-I0 = MIXED_STATE_ALIASING_SIGNAL
R4-D1 = COMPLETE diagnostic; no decision change
```

Final holdout `2019-03/06/09/12` 继续封存。

## 2. Accepted R4-D1

```text
D1 source status SHA256       522af0c71236ad3da7d8de006875394420f702aa650613660e619d8dd0048c94
D1 reviewed executable        51048259f8d9c61f324db07e05ded0a3c2f9d48e
runtime                       75.3963333 s
records                        23876
fit_count                      0
R4 replay verified             true
holdout accessed               false
```

D1 establishes that M3 selects substantially closer session-state histories while sacrificing current-level similarity relative to Level-Control, but this aggregate trade-off cannot explain horizon/month reversal by itself. Do not turn D1 into a causal claim or a post-hoc R4 PASS/STOP.

## 3. Frozen R4-D2

Primary target-free score:

```text
S_current = (C_M3-C_Level)/(C_M3+C_Level+1e-12)
S_session = (QE_Level-QE_M3)/(QE_Level+QE_M3+1e-12)
B         = S_session-S_current
```

Outcome only: `A=D_Level-D_M3`; positive A means M3 is better.

Pooled B quartiles use NumPy `method="higher"`; identical cutpoints are reused for every horizon/month/cell. No target-based score/cutpoint tuning, no new analog, no month gating input, and no model fit.

## 4. R4-D2 implementation

```text
protocol merge                  61f00f9293d012d599d4c2f8417fc9ea7a53a58e
reviewed executable head        599982eadbf1c1ea9868ea20ad5ed0a87d19b74d
implementation merge            f5b0a2aa0576e40dcbe6b335dc206f0b7c2dce94
PR                              #86
full CI                         PASS
launcher SHA256                 a038412e716cab5fffbe8c1d557c955780b4085c943d3a2fe38d1ed4c45e481a
```

Implementation passively captures the exact D1 pooled records during the unchanged D1 run, restores the original D1 aggregator, verifies the accepted aggregate digest, then computes only the frozen D2 descriptive statistics. It reports pooled + 5 horizons + 4 months + 20 cells, B quartile bins, Spearman(B,A), M3-advantage fractions and Q4-Q1 differences.

## 5. Current execution order

```text
R4-D1 outcome                  ARCHIVED
R4-D2 protocol                 FROZEN / MERGED
R4-D2 implementation           CI PASS / MERGED
R4-D2 pinned launcher          READY
R4-D2 local run                NOT RUN YET
Final holdout                  SEALED
```

Next and only user-side action: run the pinned development-only R4-D2 launcher once and upload only the newest `evcf_r4_d2_status_*.json`. Do not begin an adaptive Level/M3 forecast model until D2 is interpreted and archived.

## 6. Asset protection

Preserve all worktrees, status files, private caches and historical outputs. Do not reset/clean/stash/force-push. PowerShell instructions must remain one line. Any D2 result is descriptive and cannot modify formal R4-I0 `MIXED_STATE_ALIASING_SIGNAL`.
