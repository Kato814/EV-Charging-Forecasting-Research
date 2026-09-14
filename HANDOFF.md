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
R8-C0 = READY; formal run NOT RUN
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

R7-D1 proves numerical requested-departure timing adds stable information beyond declaration availability/missingness, while remaining horizon/month dependent.

## 3. R8-C0 frozen identity

```text
protocol merge       de2ca2a0be462a85d61adb48f6b32c0ae9996c6d
reviewed executable  91ab4a18f776b33e00a439ab10c74fd42a04f9b5
implementation merge e67dbac395a89155042dead07b441714b4ec4f12
launcher filename    evcf_r8_c0_launcher_v1.py
launcher SHA256      afa29c162dac6b8132dd6081a9a0cba9f64235362cba946a660f3d0190777777
final code CI        1226 passed, 2 skipped; compileall PASS; Ruff PASS
```

Formal R8-C0 has not yet run.

## 4. R8-C0 scientific question

> Does an explicit forecast-horizon-aligned requested-departure exposure representation outperform the accepted generic ten-stat Departure-Aug representation for future-arrival current and recombined station current?

## 5. Exact R8-C0 feature block

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

Audit-only:

```text
due_after_horizon_count = observed_count - overdue_count - due_within_horizon_count
```

must be a nonnegative integer. `observed_count` and `missing_count` must exactly reproduce accepted R7-D1 canonical availability fields on common rows.

Exact width:

```text
205 raw / 208 encoded
```

No other departure statistics, ratios, proximity scores, current/pilot/energy weighting, embeddings or feature search are authorized.

## 6. R8-C0 arms and training budget

Read-only accepted references from exact R7-D1 private cache:

```text
Base-M2
Departure-Availability
Departure-Aug
S1
Equal
TotalAvailability
TotalDeparture
```

Only `Horizon-Exposure` is newly fitted using exact frozen horizon-specific M2 HGB parameters, same future-arrival target and identical daily rolling OOS rows.

```text
expected new fits = 275
TotalHorizonExposure = frozen E_hat_S1 + A_hat_HorizonExposure
```

## 7. Frozen decisions

```text
PASS_HORIZON_ALIGNED_DEPARTURE_EXPOSURE
NO_STABLE_HORIZON_ALIGNED_ADVANTAGE
MIXED_HORIZON_ALIGNED_DEPARTURE_EXPOSURE_SIGNAL
```

PASS requires all conditions in the frozen protocol: pooled component and total improvement over Departure-Aug/TotalDeparture, >=3/5 horizon wins and >=3/4 month wins for both, >=2/3 component wins in `{60,120,240}`, total below S1 and Equal, and <=5% max horizon degradation.

Do not change thresholds after observing results.

## 8. Launcher behavior

The pinned launcher:

- verifies Python/scientific package versions;
- verifies repository identity and fetches only PR #98 head if the reviewed commit is absent;
- creates/reuses a detached reviewed-head worktree without reset/clean/stash/delete;
- verifies the protocol blob equals the frozen protocol merge;
- locates the exact four development snapshot manifests and verifies processed/interim artifacts;
- locates the exact R7-D1 private manifest `0c816334...`;
- checks development-data integrity before and after formal execution;
- runs only the reviewed R8 CLI;
- audits 275 fits, 20 private task files, 25375 records, frozen references, allowed decision and all forbidden-action flags;
- writes only aggregate status next to the launcher;
- preserves all worktrees and private outputs and performs no automatic cleanup;
- performs no data acquisition.

## 9. Interpretation boundary

Requested departure is user-declared intended timing, not actual disconnect. Actual disconnect/doneCharging, future arrivals/occupancy/share or future connector state are prohibited predictors.

Do not claim first use of departure time, remaining parking duration, active-session state or session decomposition. Existing literature already covers those concepts. Current negative search evidence did not find the exact R8 station-level horizon-aligned exposure construction, but this is not proof of novelty.

## 10. Next action

Run the pinned R8-C0 launcher exactly once on the user machine. Upload only the newest `evcf_r8_c0_status_*.json`, whether COMPLETE or INCOMPLETE. Do not debug or rerun before inspecting that status.

Final holdout remains sealed regardless of R8 development result.

## 11. Closed routes and hygiene

Do not return to gate/MoE, survival/TPP, higher-order set/attention, control-endogeneity rescue, FTAR enlargement, Transformer/Mamba or post-hoc feature search. Preserve detached worktrees, status JSONs, private caches and historical outputs. Do not reset/clean/stash/force-push or automatically delete worktrees.
