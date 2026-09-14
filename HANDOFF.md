# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R6 outcome](docs/JPL_R6_O0_COMPONENT_ORACLE_OUTCOME_20260914.md)、[R7 protocol](docs/JPL_R7_C0_DEPARTURE_STATE_ARRIVAL_PROTOCOL_20260914.md) 和 [R7 outcome](docs/JPL_R7_C0_DEPARTURE_STATE_ARRIVAL_OUTCOME_20260914.md)。

## 1. Frozen scientific state

```text
S1    = MIXED_STRUCTURED_SIGNAL, CLOSED
P1    = STOP_MECHANISM_ROUTE, CLOSED
R1    = MIXED_JOINT_STATE_SIGNAL, CLOSED
R2    = STOP_HIGHER_ORDER_SET_ROUTE, CLOSED
R3-C0 = STOP_CONTROL_ENDOGENEITY_ROUTE, CLOSED
R4-I0 = MIXED_STATE_ALIASING_SIGNAL
R4-D1/R4-D2 = COMPLETE diagnostics
R5    = STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE, CLOSED
R6-O0 = MIXED_COMPONENT_ORACLE_SIGNAL, COMPLETE
R7-C0 = PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL, COMPLETE
```

Final holdout `2019-03/06/09/12` remains sealed. Do not rerun closed S1–R7 stages unless a separately frozen repair protocol explicitly requires it.

## 2. R7 formal identity

```text
source status SHA256            deb7fc1700fccd3eb53616bbe2e65de0941b6294d60aec58e4f63953b576bce0
protocol commit                 ed427067015e60b417cd5da3838b4e0a5701b01e
reviewed executable             24e9e69413cb4b224bd1c59cdd3725b352bd27ed
implementation merge            78e51d98d476e30098a19b67121c0658a4c848b4
launcher SHA256                 f1dbaf035055038f337f0207baba8ae0ef884ca0118c16a87ef75d7178f822e9
private manifest SHA256         172c69c71e6baef689f65ad0169b3440947675f462dd1bc9b72479e11bad6967
fit_count                       550
holdout_accessed                false
development_data_unchanged      true
reference_models_retrained      false
hyperparameter_search           false
```

## 3. R7 formal result

```text
Departure arrival MAE           22.7486906628 A
Base-M2 arrival MAE             23.1051516907 A
arrival improvement             +1.542777%
component horizon wins          5/5
component month wins            3/4
arrival-dominant horizon wins   3/3

TotalDeparture MAE              28.4354542901 A
S1 MAE                          28.5948815297 A
Equal MAE                       28.9172859886 A
total improvement vs S1         +0.557538%
total improvement vs Equal      +1.666241%
total horizon wins vs S1        4/5
total month wins vs S1          3/4
```

All preregistered PASS conditions were satisfied.

Secondary Full-M3 label is `FULL_M3_INCREMENTAL_SIGNAL`:

```text
Full-M3 arrival MAE             22.5561552852 A
Full-M3 total MAE               28.2945240071 A
```

Full-M3 has stronger pooled magnitude but less stable total improvement across horizons/months than Departure-Aug.

## 4. Horizon and month structure

Departure-Aug arrival component beats Base-M2 at all 5 horizons. TotalDeparture beats S1 at 15/30/60/120 min and slightly worsens at 240 min (+0.568%). The strongest practical gain occurs near 60 min; 240-min arrival uncertainty remains largely unresolved.

By month, Departure-Aug improves January, April and July and worsens October, for both component and total aggregate direction.

## 5. Interpretation boundary

Accepted claim:

> Current-session requested-departure state adds stable incremental predictive information for future-arrival current beyond frozen M2, and part of that signal survives total-load recombination.

Do not yet claim planned departure timing itself is the cause. Canonical requested-departure pooling contains both timing values and declaration availability (`count` / `missing_count`). Therefore R7 could partly reflect metadata availability, user/session regime or other correlated structure. Requested departure is not actual departure, and connector release has not been shown causal.

R7 PASS does not reopen closed gate/MoE, survival/TPP, higher-order set, control-endogeneity or FTAR routes.

## 6. Required next step: R7-D1 attribution ablation

Before promoting a departure-timing/capacity-release forecasting mechanism, isolate the source of the R7 signal.

Frozen planned comparison:

```text
Base-M2                 frozen S1 arrival prediction, read-only
Departure-Availability  M2 + departure observed-count/missing-count only
Departure-Aug           frozen R7 prediction, read-only
```

Only `Departure-Availability` is newly fitted, with the same frozen horizon-specific M2 HGB parameters and identical rolling OOS rows. Expected new fits: 275.

Scientific interpretation:

- if full Departure-Aug stably beats Availability, timing-distribution values carry incremental information beyond metadata availability;
- if Availability captures most of the gain and full Departure-Aug is not stably better, the R7 signal should be treated as an availability/proxy effect rather than a departure-time mechanism;
- mixed results remain attribution-limited and do not authorize a larger model.

No final holdout, retuning, feature search, clipping/calibration, gate, TPP, survival model, attention, Set Transformer or neural rescue is authorized.

## 7. GitHub Actions conservation

Full CI runs only on code/config/workflow PRs. Pure documentation and result archival do not trigger full CI. Development should use local/static checks first; one final code candidate should consume the next Actions run where possible.

Preserve all detached worktrees, status JSONs, private caches and historical outputs. Do not reset/clean/stash/force-push or automatically delete worktrees.
