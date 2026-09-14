# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。当前入口为本文件与 [HANDOFF](HANDOFF.md)。正式 R7-D1 结果见 [R7-D1 outcome](docs/JPL_R7_D1_DEPARTURE_ATTRIBUTION_OUTCOME_20260914.md)，R8-C0 冻结协议见 [R8-C0 protocol](docs/JPL_R8_C0_HORIZON_ALIGNED_DEPARTURE_EXPOSURE_PROTOCOL_20260914.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`；R5=`STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`；R6-O0=`MIXED_COMPONENT_ORACLE_SIGNAL`；R7-C0=`PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL`；R7-D1=`TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL`；R8-C0 协议、实现与 pinned launcher 已冻结，正式运行尚未执行。final holdout 2019-03/06/09/12 继续封存。**

## 1. R7-D1 closed result

```text
status                         COMPLETE
decision                       TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL
R7-D1 status SHA256            48247f4ef47415c65b080584e667e9b2dba9227271ad24d93da51800756b406b
reviewed executable            2a2384781eeccf122ef43116b604f319e5637bdc
implementation merge           992a611d8c3223b895818df984fc6e4f6b4521af
private manifest SHA256        0c816334d74173e16df6e58e55de90ca3ed5723a6775e0b6287749afa479e019
fit_count                      275
holdout accessed               false
development data unchanged     true
reference models retrained     false
```

Arrival-component pooled MAE:

```text
Base-M2                 23.1051516907 A
Departure-Availability  23.0557563709 A
Departure-Aug           22.7486906628 A
```

Total pooled MAE:

```text
Equal               28.9172859886 A
S1                  28.5948815297 A
TotalAvailability   28.4546589435 A
TotalDeparture      28.4354542901 A
```

R7-D1 establishes that numerical requested-departure timing values carry stable incremental information beyond declaration availability/missingness alone. The timing gain is strongest around 60 min and is not uniform across horizons/months.

## 2. R8-C0 frozen question

R8-C0 tests whether explicit forecast-horizon alignment represents the supported timing information better than the accepted generic ten-stat Departure-Aug pool.

```text
protocol merge       de2ca2a0be462a85d61adb48f6b32c0ae9996c6d
reviewed executable  91ab4a18f776b33e00a439ab10c74fd42a04f9b5
implementation merge e67dbac395a89155042dead07b441714b4ec4f12
launcher SHA256      afa29c162dac6b8132dd6081a9a0cba9f64235362cba946a660f3d0190777777
formal run           NOT RUN
```

Final code CI on the reviewed head:

```text
pytest       PASS (1226 passed, 2 skipped)
compileall   PASS
Ruff         PASS
```

## 3. R8-C0 only newly fitted arm

For each issue time and forecast horizon `h`, start from canonical M2 and append exactly four nonnullable station-level requested-departure features:

```text
requested_departure_observed_count
requested_departure_missing_count
requested_departure_overdue_count
requested_departure_due_within_horizon_count
```

Definitions:

```text
observed_count = finite requested-departure values among currently connected sessions
missing_count  = missing requested-departure values
overdue_count  = finite d_i <= 0
due_within_horizon_count = finite 0 < d_i <= h
```

Exact width:

```text
205 raw / 208 encoded
```

No departure mean/std/quantiles, ratio/proximity score, current/pilot/energy weighting, feature search or learned embedding is permitted.

## 4. Frozen references and training budget

Read-only references from the exact accepted R7-D1 cache:

```text
Base-M2
Departure-Availability
Departure-Aug
S1
Equal
TotalAvailability
TotalDeparture
```

Only `Horizon-Exposure` is newly fitted with the exact frozen horizon-specific M2 HGB parameters and identical daily rolling OOS rows.

Expected new fits:

```text
275
```

Recombination:

```text
TotalHorizonExposure = frozen E_hat_S1 + A_hat_HorizonExposure
```

## 5. Frozen R8-C0 decisions

Possible outcomes are exhaustive:

```text
PASS_HORIZON_ALIGNED_DEPARTURE_EXPOSURE
NO_STABLE_HORIZON_ALIGNED_ADVANTAGE
MIXED_HORIZON_ALIGNED_DEPARTURE_EXPOSURE_SIGNAL
```

PASS requires pooled component and total improvement over Departure-Aug/TotalDeparture, >=3/5 horizon wins and >=3/4 month wins for both component and total, >=2/3 component wins in {60,120,240}, total improvement over S1 and Equal, and <=5% maximum horizon degradation. Thresholds are frozen and cannot change after results are observed.

## 6. Execution and safety state

```text
R8-C0 protocol             FROZEN / MERGED
R8-C0 implementation       CI PASS / MERGED
R8-C0 pinned launcher      READY
R8-C0 formal run           NOT RUN
expected new fits          275
reference retraining       forbidden
network data acquisition   forbidden
final holdout              SEALED
```

Launcher performs exact environment, reviewed-head, frozen-protocol-blob, development-data, R7-D1 private-manifest, result-shape and forbidden-action checks. It preserves all existing worktrees and private caches and performs no automatic cleanup.

## 7. Interpretation boundary

Do not claim first use of departure time, remaining parking duration, active-session information, or session decomposition. Existing EV scheduling/forecasting work already covers those concepts. The targeted literature check did not find the exact horizon-aligned station-level requested-departure exposure construction; this is negative search evidence only, not proof of novelty.

Requested departure remains user-declared intended timing, not realized disconnect. Actual disconnect/doneCharging and future-session information are prohibited predictors.

## 8. Closed routes remain closed

Do not return to gate/MoE, survival/TPP, Deep Sets/Set Transformer, control-endogeneity rescue, FTAR larger backbone, Transformer/Mamba, or post-hoc feature search.

## 9. GitHub Actions policy

Pure documentation does not trigger full CI. Code work is statically reviewed before PR; full Actions is reserved for final candidates only. Duplicate push/PR runs remain removed and `cancel-in-progress` remains enabled.
