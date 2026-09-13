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

## 2. R4-D1 accepted run

```text
D1 source status SHA256       522af0c71236ad3da7d8de006875394420f702aa650613660e619d8dd0048c94
D1 reviewed executable        51048259f8d9c61f324db07e05ded0a3c2f9d48e
runtime                       75.3963333 s
records                        23876
fit_count                      0
R4 replay verified             true
holdout accessed               false
```

Pooled D1 shows M3 current-level gap `0.19514` vs Level `0.05693` (~3.43x farther), while M3 session-extension RMS `0.39369` vs Level `0.63620` (~38.12% closer) and complete-M3 RMS `0.46207` vs Level `0.78589` (~41.20% closer).

The geometry conflict is real, but it does not fully explain outcome heterogeneity. Geometry is almost unchanged across horizons while `D_M3-D_Level` moves from `+8.1171 A` at 15 min to `-10.7252 A` at 240 min. By month it is `+0.3039` Jan, `-10.4143` Apr, `-2.4247` Jul, `+14.1236` Oct.

Interpretation boundary: geometry trade-off is **mechanistically present but insufficient as a complete explanation**. Do not claim causality and do not alter R4-I0 MIXED.

## 3. R4-D2 frozen question

R4-D2 asks whether a target-free issue-time geometry-conflict score can stratify M3-vs-Level future advantage.

Frozen primary score:

```text
S_current = (C_M3-C_Level)/(C_M3+C_Level+1e-12)
S_session = (QE_Level-QE_M3)/(QE_Level+QE_M3+1e-12)
B         = S_session-S_current
```

Diagnostic outcome only:

```text
A = D_Level-D_M3
```

Positive `A` means M3 has less future divergence.

Pooled B quartiles use NumPy `method="higher"` and geometry only. The same cutpoints must be reused for every horizon/month/cell. No target-based cutpoint tuning is allowed.

## 4. R4-D2 requirements

Before any D2 result is accepted:

- exact replay D1 aggregates at atol `1e-12`;
- same supported rows and original analog identities;
- no new data, no new matching, no metric learning;
- no classifier/regressor/gate/forecast model fit;
- no calendar month as gating input;
- no final holdout access.

Required reports: pooled + 5 horizons + 4 months + all 20 cells, fixed B quartiles, mean/median A, M3-win fraction, Spearman(B,A), and Q4-Q1 differences.

## 5. Current execution order

```text
R4-D1 outcome archive          current docs PR
R4-D2 protocol freeze          current docs PR
R4-D2 implementation           AFTER docs merge
R4-D2 local run                NOT AUTHORIZED
Final holdout                  SEALED
```

There is currently no user-side command. After the docs PR is green and merged, create a separate zero-fit implementation PR, run full CI, then release a pinned development-only launcher for exactly one D2 run.

## 6. Asset protection

Preserve all worktrees, status files, private caches and historical outputs. Do not reset/clean/stash/force-push. Any future PowerShell instruction must be one line. Do not convert D1/D2 descriptive results into a post-hoc R4 PASS/STOP.
