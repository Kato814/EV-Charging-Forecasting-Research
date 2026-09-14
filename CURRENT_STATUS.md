# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。当前入口为本文件与 [HANDOFF](HANDOFF.md)。正式 R5 结果见 [R5 outcome](docs/JPL_R5_FUTURE_TRANSITION_ALIGNED_REPRESENTATION_OUTCOME_20260914.md)，R6-O0 协议见 [R6 protocol](docs/JPL_R6_O0_COMPONENT_ORACLE_PROTOCOL_20260914.md)，正式 R6-O0 结果见 [R6 outcome](docs/JPL_R6_O0_COMPONENT_ORACLE_OUTCOME_20260914.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`；R5=`STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`；R6-O0=`MIXED_COMPONENT_ORACLE_SIGNAL`。final holdout 2019-03/06/09/12 继续封存。**

## 1. R6-O0 formal result

```text
status                         COMPLETE
decision                       MIXED_COMPONENT_ORACLE_SIGNAL
source status SHA256           52bf3d7753b095a0faf39bc9aaefbd07b2c11f406ab05abd4bd1534e921dacce
reviewed executable            1bdd4cbee66b6abe7465163066e2c3d2d11174c3
fit_count                      0
record_count                   25375
holdout accessed               false
raw/processed accessed         false
S1 private cache unchanged     true
```

Pooled replacement gains:

```text
S1 MAE                         28.5948815297 A
G_existing                      5.4897298390 A   (19.20%)
G_arrival                      15.8037036627 A   (55.27%)
arrival > existing horizons    3/5
arrival > existing months      4/4
```

Formal ARRIVAL dominance did not trigger because its preregistered threshold required at least 4/5 horizon wins.

## 2. Main R6 scientific finding

The MIXED label is structured by forecast horizon rather than random month instability.

| horizon | G_existing (A) | G_arrival (A) | larger component |
| ---: | ---: | ---: | --- |
| 15 min  | 4.63784 | 1.15816 | existing-session |
| 30 min  | 5.69349 | 4.38389 | existing-session |
| 60 min  | 6.12154 | 12.10481 | future-arrival |
| 120 min | 6.80800 | 23.16122 | future-arrival |
| 240 min | 4.18779 | 38.21044 | future-arrival |

Cross-month direction is strong:

- 15 min: existing > arrival in 4/4 months;
- 30 min: existing > arrival in 3/4 months;
- 60/120/240 min: arrival > existing in 4/4 months at every horizon.

Thus the dominant removable error crosses over between 30 and 60 minutes. Short-horizon error is more associated with evolution of already-connected sessions; long-horizon error is much more associated with sessions not yet arrived at issue time.

## 3. Error interaction

```text
branch-error Pearson          -0.0312
cancellation fraction          49.61%
reinforcement fraction         50.39%
total cancellation share       20.34%
```

Cancellation is material but not dominant: both replacement gains are positive overall, at all 5 horizons, and in all 4 months.

## 4. Closed routes

Do not return to:

- Level/M3 hard/neural gate or MoE router;
- P1 survival/count-mark rescue;
- R2 Deep Sets / Set Transformer / attention rescue;
- R3 control-endogeneity route;
- R5 larger MLP/Transformer/Mamba/geometry-loss tuning.

R6 does not reopen any of these routes.

## 5. Next method-selection boundary

No new model is authorized yet.

The next scientific question must account for the horizon transition without post-hoc switching:

- short horizons: if modeling continues, target currently connected-session evolution with a mechanism distinct from P1/R2;
- long horizons: prioritize legally observable future-arrival covariates or probabilistic arrival uncertainty;
- a unified method is justified only if it represents both information regimes by construction rather than by an added gate.

Final holdout remains sealed.

## 6. GitHub Actions policy

To conserve the remaining Actions allowance, full CI now runs only for pull requests that change code/scripts/pyproject/workflow/MANIFEST. Pure documentation and result archiving no longer trigger full CI, and duplicate push-triggered runs have been removed. `cancel-in-progress` remains enabled.
