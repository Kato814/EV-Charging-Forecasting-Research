# 主控交付说明｜JPL/ACN 充电站结构化负荷预测研究

更新：2026-09-14。接管时先读 [CURRENT_STATUS](CURRENT_STATUS.md)、[R6 outcome](docs/JPL_R6_O0_COMPONENT_ORACLE_OUTCOME_20260914.md)、[Post-R6 screening](docs/JPL_POST_R6_METHOD_SCREENING_20260914.md) 和 [R7-C0 protocol](docs/JPL_R7_C0_DEPARTURE_STATE_ARRIVAL_PROTOCOL_20260914.md)。

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
R7-C0 = READY FOR ONE FORMAL DEVELOPMENT RUN
```

Final holdout `2019-03/06/09/12` remains sealed. Do not rerun closed S1–R6 stages unless a separately frozen repair protocol explicitly requires it.

## 2. R6-O0 accepted finding

```text
source status SHA256            52bf3d7753b095a0faf39bc9aaefbd07b2c11f406ab05abd4bd1534e921dacce
S1 MAE                          28.5948815297 A
G_arrival                       15.8037036627 A
G_existing                       5.4897298390 A
arrival > existing horizons      3/5
arrival > existing months        4/4
```

The dominant removable-error source crosses over between 30 and 60 minutes:

```text
15 min    existing > arrival   4/4 months
30 min    existing > arrival   3/4 months
60 min    arrival > existing   4/4 months
120 min   arrival > existing   4/4 months
240 min   arrival > existing   4/4 months
```

This is a forecasting-information diagnostic, not an information-theoretic irreducibility result.

## 3. R7-C0 scientific question

R7-C0 tests one narrow issue-time information channel left untested by S1/P1:

> Does the current connected-session `requested_departure_minutes_from_issue` state add stable predictive information for future-arrival current beyond frozen M2, and does the component gain survive recombination with the frozen S1 existing-session prediction?

Canonical requested-departure pooling contains both declaration availability (`count` / `missing_count`) and timing-distribution statistics. Therefore a positive result supports only **requested-departure state (availability + distribution)** as an incremental predictor. It does not establish actual departure time, connector release or a causal capacity mechanism.

## 4. Frozen R7 arms and learner

```text
Base-M2        frozen S1 arrival prediction, read-only
Departure-Aug  M2 + exactly 10 requested-departure pooled statistics
               + 7 fixed nullable indicators
               211 raw / 221 encoded
Full-M3        full canonical M3, 311 raw / 391 encoded, secondary only
```

Both newly fitted arms use:

- `HistGradientBoostingRegressor`;
- exact frozen horizon-specific **M2** selected hyperparameters;
- same-month daily rolling origin;
- exact frozen S1 future-arrival target;
- no retuning, clipping, calibration, projection, feature selection, gate, MoE or neural model.

Candidate total predictions:

```text
Total_Departure = frozen S1 existing + Departure-Aug arrival
Total_FullM3    = frozen S1 existing + Full-M3 arrival
```

Frozen total references are S1 and Equal.

## 5. R7 primary decision

`PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL` requires all frozen conditions: pooled Departure arrival beats Base-M2; >=3/5 component horizon wins; >=3/4 component month wins; >=2/3 wins in {60,120,240}; component max horizon degradation <=5%; pooled Total_Departure beats both S1 and Equal; >=3/5 total horizon wins and >=3/4 total month wins vs S1; total max horizon degradation <=5%.

If PASS fails but pooled arrival or pooled total improves, decision is `MIXED_DEPARTURE_STATE_ARRIVAL_SIGNAL`. If neither pooled quantity improves, decision is `STOP_DEPARTURE_STATE_ARRIVAL_ROUTE`.

Full-M3 produces only the secondary label `FULL_M3_INCREMENTAL_SIGNAL` or `NO_STABLE_FULL_M3_INCREMENT`; it cannot change the primary R7 decision.

## 6. R7 reviewed execution identity

```text
protocol commit                  ed427067015e60b417cd5da3838b4e0a5701b01e
reviewed CI-passed executable    24e9e69413cb4b224bd1c59cdd3725b352bd27ed
implementation merge             78e51d98d476e30098a19b67121c0658a4c848b4
PR #94 final CI                  1211 passed, 2 skipped; compileall PASS; Ruff PASS
expected fits                    550 = 275 Departure-Aug + 275 Full-M3
launcher                         evcf_r7_c0_launcher_v1.py
launcher SHA256                  f1dbaf035055038f337f0207baba8ae0ef884ca0118c16a87ef75d7178f822e9
```

The formal run must execute the reviewed head above, not a later docs-only main commit.

## 7. Launcher and asset contract

The external pinned launcher:

- requires explicit `--authorize-r7-c0`;
- creates/reuses a detached worktree at reviewed head without reset/clean/stash/delete;
- auto-locates the four accepted development snapshots by exact identity;
- auto-locates accepted baseline and S1 private caches by exact manifest SHA;
- blocks traversal into final-holdout month directories;
- verifies development data integrity before and after execution;
- performs no new data acquisition;
- expects exactly 550 formal HGB fits;
- emits only aggregate `evcf_r7_c0_status_*.json` for upload.

Preserve all detached worktrees, status JSONs, private caches and historical outputs.

## 8. Current execution order

```text
R7 protocol          FROZEN / COMMITTED
R7 implementation    CI PASS / MERGED
R7 pinned launcher   READY
R7 formal run        NOT RUN YET
Final holdout        SEALED
```

Next and only user-side action: run the pinned R7 launcher exactly once and upload only the newest `evcf_r7_c0_status_*.json`. After a COMPLETE result, do not rerun or retune before formal interpretation and archival.

## 9. GitHub Actions conservation

Full CI now runs only on pull requests touching code/scripts/pyproject/workflow/MANIFEST files. Pure documentation and result archiving do not trigger full CI; duplicate push-triggered runs are removed; `cancel-in-progress` remains enabled. Development should use local/static checks first and reserve Actions for the final code candidate.
