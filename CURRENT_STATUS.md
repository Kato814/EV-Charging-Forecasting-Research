# 当前状态｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。当前入口为本文件与 [HANDOFF](HANDOFF.md)。正式 R8-C0 结果见 [R8-C0 outcome](docs/JPL_R8_C0_HORIZON_ALIGNED_DEPARTURE_EXPOSURE_OUTCOME_20260914.md)，R9-C0 冻结协议见 [R9-C0 protocol](docs/JPL_R9_C0_FORECAST_GRID_DEPARTURE_PROFILE_PROTOCOL_20260914.md)。

**S1=`MIXED_STRUCTURED_SIGNAL`；P1/R1/R2/R3-C0 已关闭；R4-I0=`MIXED_STATE_ALIASING_SIGNAL`；R5=`STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE`；R6-O0=`MIXED_COMPONENT_ORACLE_SIGNAL`；R7-C0=`PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL`；R7-D1=`TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL`；R8-C0=`NO_STABLE_HORIZON_ALIGNED_ADVANTAGE`；R9-C0 已实现并通过 CI，正式运行尚未执行。final holdout 2019-03/06/09/12 继续封存。**

## 1. R8-C0 closed result

```text
status                         COMPLETE
decision                       NO_STABLE_HORIZON_ALIGNED_ADVANTAGE
R8-C0 status SHA256            5f69386c62bff1314cc16de94d1667421e872aada739194e41ab41c5f5e2a6fe
private manifest SHA256        ec11e3555727259960e355b12ac1867d14adef876fedf2d7580daaa3366ff2d2
fit_count                      275
holdout accessed               false
development data unchanged     true
```

R8's single `0 < d_i <= h` exposure count loses to Departure-Aug at all 5 arrival-component horizons. It does not overturn R7-D1; it shows that useful requested-departure timing information is not preserved by this compressed horizon-local count.

## 2. R9-C0 frozen question

> Does retaining the full requested-departure distribution shape over the fixed canonical forecast grid improve future-arrival prediction relative to the accepted generic ten-stat Departure-Aug representation?

Protocol merge:

```text
35ed40105faaa82f0c9d7e6a96f805ffdf4aea35
```

Source R8 evidence:

```text
status SHA256       5f69386c62bff1314cc16de94d1667421e872aada739194e41ab41c5f5e2a6fe
private manifest    ec11e3555727259960e355b12ac1867d14adef876fedf2d7580daaa3366ff2d2
decision            NO_STABLE_HORIZON_ALIGNED_ADVANTAGE
```

## 3. R9-C0 only new representation

Append exactly nine nonnullable count features to canonical M2:

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

Bins are fixed solely by canonical forecast horizons. No data-driven binning, mean/std/quantiles, ratios, current/pilot/energy weighting, embeddings or feature search.

Exact width:

```text
210 raw / 213 encoded
```

Only one new HGB arm is fitted, with exact frozen horizon-specific M2 parameters and identical rolling OOS rows/arrival target. Expected new fits = 275. Accepted R8/R7 references are read-only.

## 4. Frozen R9 decisions

```text
STOP_DEPARTURE_REPRESENTATION_REFINEMENT
PASS_FORECAST_GRID_DEPARTURE_PROFILE
MIXED_FORECAST_GRID_DEPARTURE_PROFILE_SIGNAL
```

STOP is evaluated first. PASS requires stable component and total improvement over Departure-Aug/TotalDeparture, >=3/5 horizon wins, >=3/4 month wins, >=2/3 wins in {60,120,240}, total below S1 and Equal, and <=5% max horizon degradation.

If R9 is STOP or MIXED, departure-representation refinement closes and R7 Departure-Aug remains the accepted development candidate. No further engineered departure representation is allowed.

## 5. R9-C0 execution identity

```text
protocol merge                 35ed40105faaa82f0c9d7e6a96f805ffdf4aea35
reviewed executable            c60ed89f522bc3f9df30f10093e1216a9a9f6b2f
implementation merge           b7e2da489db13523c8d7fe46bff4799a63a64ba7
final CI                       1233 passed, 2 skipped; compileall/Ruff PASS
launcher SHA256                0efb11b2e2484ccae8c0af3ea0664ec5aaf771402621000b643894cebb143c6c
formal run                     NOT RUN
expected new fits              275
final holdout                  SEALED
```

Next action: run the pinned external R9-C0 launcher once and upload only the resulting aggregate status JSON. Do not rerun automatically after COMPLETE or INCOMPLETE.

## 6. Holdout and closed routes

Final holdout remains sealed. Do not return to gate/MoE, survival/TPP, Deep Sets/attention, control-endogeneity rescue, FTAR enlargement, Transformer/Mamba, or post-hoc feature search.

## 7. GitHub Actions policy

R9 code CI is complete; do not spend additional Actions on documentation or execution. Pure documentation/result archival remains CI-free.
