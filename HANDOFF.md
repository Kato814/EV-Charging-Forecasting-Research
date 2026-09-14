# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R8-C0 outcome](docs/JPL_R8_C0_HORIZON_ALIGNED_DEPARTURE_EXPOSURE_OUTCOME_20260914.md) 和 [R9-C0 protocol](docs/JPL_R9_C0_FORECAST_GRID_DEPARTURE_PROFILE_PROTOCOL_20260914.md)。

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
R7-D1 = TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL, COMPLETE
R8-C0 = NO_STABLE_HORIZON_ALIGNED_ADVANTAGE, COMPLETE
R9-C0 = protocol FROZEN, implementation/run NOT STARTED
```

Final holdout `2019-03/06/09/12` remains sealed.

## 2. R8 closed evidence

```text
R8-C0 status SHA256             5f69386c62bff1314cc16de94d1667421e872aada739194e41ab41c5f5e2a6fe
R8 private manifest             ec11e3555727259960e355b12ac1867d14adef876fedf2d7580daaa3366ff2d2
reviewed executable             91ab4a18f776b33e00a439ab10c74fd42a04f9b5
implementation merge            e67dbac395a89155042dead07b441714b4ec4f12
fit_count                       275
holdout_accessed                false
development_data_unchanged      true
```

R8 Horizon-Exposure arrival MAE = 23.1408646361 A versus Departure-Aug = 22.7486906628 A; component wins vs Departure-Aug = 0/5 horizons and 1/4 months. The single target-window count representation is rejected.

## 3. R9-C0 frozen identity and question

Protocol merge:

```text
35ed40105faaa82f0c9d7e6a96f805ffdf4aea35
```

Question:

> Does retaining the full issue-time requested-departure distribution shape over the fixed canonical forecast grid improve future-arrival prediction relative to Departure-Aug?

## 4. Exact R9-C0 new feature block

Append exactly nine nonnullable counts to canonical M2:

```text
requested_departure_observed_count
requested_departure_missing_count
requested_departure_overdue_count
requested_departure_bin_0_15_count
requested_departure_bin_15_30_count
requested_departure_bin_30_60_count
requested_departure_bin_60_120_count
requested_departure_bin_120_240_count
requested_departure_beyond_240_count
```

Intervals are fixed exactly by canonical forecast horizons. Required row identities:

```text
observed = overdue + bin_0_15 + bin_15_30 + bin_30_60
           + bin_60_120 + bin_120_240 + beyond_240
connected = observed + missing
```

Exact width:

```text
210 raw / 213 encoded
```

No data-driven bins, departure moments/quantiles, ratio/proximity features, current/pilot/energy weighting, embedding or feature search.

## 5. Training and references

Only `ForecastGridProfile` is newly fitted:

```text
learner             HistGradientBoostingRegressor
parameters          exact frozen horizon-specific M2 params
rolling protocol    same-month daily rolling-origin
arrival target      unchanged
new fits            275
```

Replay accepted R8 cache read-only for Base-M2, Departure-Availability, Departure-Aug, Horizon-Exposure, S1, Equal, TotalAvailability, TotalDeparture and TotalHorizonExposure.

Recombination:

```text
TotalForecastGridProfile = frozen E_hat_S1 + A_hat_ForecastGridProfile
```

## 6. Frozen decisions and final route boundary

```text
STOP_DEPARTURE_REPRESENTATION_REFINEMENT
PASS_FORECAST_GRID_DEPARTURE_PROFILE
MIXED_FORECAST_GRID_DEPARTURE_PROFILE_SIGNAL
```

STOP is evaluated first. PASS requires pooled and stable horizon/month improvement over Departure-Aug/TotalDeparture, >=2/3 component wins in `{60,120,240}`, total below S1 and Equal, and <=5% max horizon degradation.

This is the final engineered departure-representation probe:

- PASS: ForecastGridProfile advances to robustness/holdout-readiness review; no holdout access yet.
- STOP or MIXED: close departure-representation refinement and retain R7 Departure-Aug as the accepted development candidate. No further departure feature-engineering rescue.

## 7. Closed routes and hygiene

Do not return to gate/MoE, survival/TPP, Deep Sets/attention, control-endogeneity rescue, FTAR enlargement, Transformer/Mamba or post-hoc feature search. Preserve all worktrees/status/private caches; no reset/clean/stash/force-push/automatic deletion.

Use GitHub Actions only after R9 implementation is complete and statically reviewed.
