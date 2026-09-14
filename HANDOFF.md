# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R7-D1 outcome](docs/JPL_R7_D1_DEPARTURE_ATTRIBUTION_OUTCOME_20260914.md) 和 [R8-C0 protocol](docs/JPL_R8_C0_HORIZON_ALIGNED_DEPARTURE_EXPOSURE_PROTOCOL_20260914.md)。

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
R8-C0 = protocol FROZEN, implementation/run NOT STARTED
```

Final holdout `2019-03/06/09/12` remains sealed. Do not rerun closed stages unless a separately frozen repair protocol explicitly requires it.

## 2. R7-D1 accepted evidence

```text
R7-D1 status SHA256              48247f4ef47415c65b080584e667e9b2dba9227271ad24d93da51800756b406b
R7-D1 decision                   TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL
reviewed executable              2a2384781eeccf122ef43116b604f319e5637bdc
implementation merge             992a611d8c3223b895818df984fc6e4f6b4521af
private manifest SHA256          0c816334d74173e16df6e58e55de90ca3ed5723a6775e0b6287749afa479e019
fit_count                        275
holdout_accessed                 false
development_data_unchanged       true
reference_models_retrained       false
```

Main result:

```text
Arrival MAE:
Base-M2                 23.1051516907 A
Departure-Availability  23.0557563709 A
Departure-Aug           22.7486906628 A

Total MAE:
S1                  28.5948815297 A
Equal               28.9172859886 A
TotalAvailability   28.4546589435 A
TotalDeparture      28.4354542901 A
```

R7-D1 rules out the narrow explanation that R7-C0 was driven only by requested-departure metadata presence. Numerical requested-departure timing values carry stable incremental information, but the effect is horizon/month dependent.

## 3. R8-C0 protocol identity

Protocol merge commit:

```text
de2ca2a0be462a85d61adb48f6b32c0ae9996c6d
```

Scientific question:

> Does an explicit forecast-horizon-aligned requested-departure exposure representation outperform the accepted generic ten-stat Departure-Aug representation for future-arrival current and recombined station current?

## 4. Exact R8-C0 new feature block

For each issue time and forecast horizon `h`, use only issue-time-known current-session `requested_departure_minutes_from_issue` and append exactly four nonnullable station-level values to canonical M2:

```text
requested_departure_observed_count
requested_departure_missing_count
requested_departure_overdue_count
requested_departure_due_within_horizon_count
```

Definitions:

```text
observed_count = finite d_i count
missing_count  = missing d_i count
overdue_count  = finite d_i <= 0
due_within_horizon_count = finite 0 < d_i <= h
```

Audit-only quantity:

```text
due_after_horizon_count = observed_count - overdue_count - due_within_horizon_count
```

must be a nonnegative integer on every row.

The first two counts must reproduce the accepted R7-D1 canonical availability fields exactly on common rows.

Exact width:

```text
205 raw / 208 encoded
```

No extra departure statistic, ratio, proximity score, current/pilot/energy weighting, learned embedding or feature search is allowed.

## 5. R8-C0 arms and training budget

Read-only accepted references from the exact R7-D1 cache:

```text
Base-M2
Departure-Availability
Departure-Aug
S1
Equal
TotalAvailability
TotalDeparture
```

Only `Horizon-Exposure` is newly fitted.

Learner and protocol:

```text
HistGradientBoostingRegressor
same frozen horizon-specific M2 parameters
same-month daily rolling-origin
same future-arrival target
same OOS test rows
native thread limit 1
no retuning / clipping / calibration / post-hoc selection
```

Expected new fits:

```text
275
```

Recombine with frozen S1 existing-session prediction:

```text
TotalHorizonExposure = E_hat_S1 + A_hat_HorizonExposure
```

## 6. Frozen R8-C0 decision labels

```text
PASS_HORIZON_ALIGNED_DEPARTURE_EXPOSURE
NO_STABLE_HORIZON_ALIGNED_ADVANTAGE
MIXED_HORIZON_ALIGNED_DEPARTURE_EXPOSURE_SIGNAL
```

PASS requires all preregistered conditions in the protocol, including pooled component/total improvement over Departure-Aug/TotalDeparture, >=3/5 horizon wins and >=3/4 month wins for both, >=2/3 component wins in `{60,120,240}`, total improvement over S1 and Equal, and <=5% max horizon degradation.

Do not change thresholds after results are observed.

## 7. Interpretation and literature boundary

Do not claim first use of departure time, remaining parking duration, active-session state, or session decomposition. Existing scheduling and forecasting literature already uses these concepts, and 2026 session-replayable forecasting explicitly separates origin-active and future sessions.

The targeted literature check did not find the exact R8-C0 horizon-aligned station-level exposure construction. Treat this only as negative search evidence, not proof of novelty.

Requested departure is user-declared intended timing, not actual disconnect. Actual disconnect/doneCharging, future arrival identities, realized occupancy/share, or future connector state are prohibited predictors.

## 8. Next action

Implement R8-C0 in an isolated branch:

1. one production module;
2. one CLI;
3. focused tests for exact four-feature construction, width, row identity, fail-closed source/cache identity, decision exhaustiveness and unauthorized early stop;
4. static/manual review before opening any code PR;
5. one final GitHub Actions run where possible.

No formal R8 fit has occurred yet.

## 9. Closed routes remain closed

Do not return to gate/MoE, P1 survival/TPP, R2 higher-order set/attention, R3 control-endogeneity rescue, R5 geometry-backbone enlargement, Transformer/Mamba, or feature-search rescue.

## 10. Repository hygiene

Preserve detached worktrees, status JSONs, private caches and historical outputs. Do not reset/clean/stash/force-push or automatically delete worktrees.
