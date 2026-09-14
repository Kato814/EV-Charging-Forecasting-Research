# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R5 outcome](docs/JPL_R5_FUTURE_TRANSITION_ALIGNED_REPRESENTATION_OUTCOME_20260914.md)、[R6 protocol](docs/JPL_R6_O0_COMPONENT_ORACLE_PROTOCOL_20260914.md) 和 [R6 outcome](docs/JPL_R6_O0_COMPONENT_ORACLE_OUTCOME_20260914.md)。

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
```

Final holdout `2019-03/06/09/12` remains sealed.

## 2. R6-O0 identity

```text
source status SHA256            52bf3d7753b095a0faf39bc9aaefbd07b2c11f406ab05abd4bd1534e921dacce
protocol merge                  256c6fd9edf8d15700c25bfc916596c9adc342b4
reviewed executable             1bdd4cbee66b6abe7465163066e2c3d2d11174c3
implementation merge            6d43c1b05d2f51c9f7d5eb50737f46fcc19636c8
launcher SHA256                 4eb8cc59d9bb59d8841cd0beb79b3364d699a87931d120a9b77dd2e990a98eeb
fit_count                       0
record_count                    25375
holdout_accessed                false
raw_or_processed_data_accessed  false
S1 private cache unchanged      true
```

## 3. R6-O0 result

```text
S1 MAE                          28.5948815297 A
OracleArrival MAE               12.7911778671 A
OracleExisting MAE              23.1051516907 A
G_arrival                       15.8037036627 A
G_existing                       5.4897298390 A
arrival > existing horizons      3/5
arrival > existing months        4/4
```

Formal code is MIXED only because arrival dominance required >=4/5 horizon wins. The observed horizon structure is strong and reproducible:

```text
15 min   existing gain > arrival gain   4/4 months
30 min   existing gain > arrival gain   3/4 months
60 min   arrival gain  > existing gain  4/4 months
120 min  arrival gain  > existing gain  4/4 months
240 min  arrival gain  > existing gain  4/4 months
```

The removable-error bottleneck therefore crosses over between 30 and 60 minutes.

## 4. Interpretation boundary

Accepted interpretation:

- short horizons are more limited by forecasting the future evolution of already-connected sessions;
- long horizons are more limited by future-arrival uncertainty;
- both branches still contain positive removable error;
- branch-error cancellation is material (~20.34% total cancellation share) but not dominant.

Do not claim information-theoretic irreducibility. Oracle truth is not a legal predictor.

## 5. No-rescue boundary

Do not revive:

- Level/M3 gate, learned gate, month/horizon router or MoE;
- P1 survival/TPP/count-mark escalation;
- R2 Deep Sets / Set Transformer / attention rescue;
- R3 control-endogeneity route;
- R5 larger backbone or geometry-loss tuning.

R6 does not authorize any of them.

## 6. Next scientific step

No current model fit is authorized. The next method review must start from the horizon-dependent information structure:

1. short-horizon mechanism, if pursued, must address connected-session evolution and differ from P1/R2;
2. long-horizon mechanism should examine legal future-arrival covariates or probabilistic arrival uncertainty;
3. any unified method must explain both regimes structurally, not by adding another gate after the fact;
4. a new preregistered protocol is required before training;
5. final holdout remains sealed.

## 7. GitHub Actions conservation

Full CI now runs only on PRs touching `code/**`, `scripts/**`, `pyproject.toml`, `MANIFEST.json` or workflow files. The duplicate `push` trigger is removed, documentation/result archival does not consume full Actions, and `cancel-in-progress` remains enabled.

Preserve all detached worktrees, status JSONs, private caches and historical outputs. Do not reset/clean/stash/force-push or automatically delete worktrees.
