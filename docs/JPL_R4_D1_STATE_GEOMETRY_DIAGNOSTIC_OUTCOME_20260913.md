# JPL/ACN R4-D1 state-geometry diagnostic outcome

Date: 2026-09-13
Status: COMPLETE. This diagnostic does not change the formal R4-I0 decision `MIXED_STATE_ALIASING_SIGNAL`.

## 1. Run identity and integrity

The single authorized development-only R4-D1 run completed successfully.

```text
source status SHA256          522af0c71236ad3da7d8de006875394420f702aa650613660e619d8dd0048c94
reviewed executable head      51048259f8d9c61f324db07e05ded0a3c2f9d48e
implementation merge          1a55796aa79ce976d115ac5b508ebb250a77c6a6
D1 protocol merge             e20481f304d416433ca2d30b9e3bae57a017a8f6
launcher SHA256               e84bbe7bc165b84cbe6d6f8e9df7e07fb9730a1c956dde1174fd33c09f211dfa
runtime                       75.3963333 s
supported records             23876
fit_count                     0
R4 replay verified            true
scientific decision unchanged true
holdout accessed              false
development data unchanged    true
```

No forecasting model was fitted or retrained. Final holdout `2019-03/06/09/12` remained sealed.

## 2. Pooled geometry result

| quantity | Level analogs | M2 analogs | M3 analogs |
| --- | ---: | ---: | ---: |
| current-level gap | 0.05693 | 0.20448 | 0.19514 |
| complete M2 RMS | 0.74920 | 0.35782 | 0.42044 |
| M3-extension RMS | 0.63620 | 0.65480 | 0.39369 |
| complete M3 RMS | 0.78589 | 0.58670 | 0.46207 |
| future divergence (A) | 43.17263 | 47.76651 | 43.85308 |

M3 analogs are therefore:

- about **3.43× farther** than Level analogs on instantaneous standardized station current;
- **38.12% closer** than Level analogs in the M3 session-extension space;
- **41.20% closer** than Level analogs in complete M3 geometry;
- **39.88% closer** than M2 analogs in the session-extension space and **21.24% closer** in complete M3 geometry;
- but **17.50% farther** than M2 analogs in the shared complete-M2 geometry.

M3 is slightly closer than M2 on the current-level coordinate itself (about 4.57%), so the M3-vs-M2 gain is not obtained by sacrificing current level; it mainly comes from moving toward the session-extension geometry while relaxing some of the shared M2 geometry.

Neighbor overlap is limited: mean Level-M3 overlap is `0.915/3`, while mean M2-M3 overlap is `1.908/3`. Thus the M3 metric materially changes which histories are selected.

## 3. Horizon result

The geometry quantities are almost invariant across the five horizons because the same issue-time state and frozen analog-selection mechanism are used. In contrast, future divergence changes strongly:

| horizon | D_Level | D_M3 | D_M3-D_Level |
| ---: | ---: | ---: | ---: |
| 15 min | 27.4091 | 35.5262 | +8.1171 |
| 30 min | 32.2330 | 37.4634 | +5.2304 |
| 60 min | 38.6010 | 40.9334 | +2.3324 |
| 120 min | 48.0359 | 46.5208 | -1.5152 |
| 240 min | 69.4997 | 58.7746 | -10.7252 |

This is the key D1 result: **the horizon dependence is not produced by a horizon-dependent change in neighbor geometry.** The same session-state similarity becomes progressively more useful relative to current-level continuity as the forecast horizon lengthens.

## 4. Month result

| month | D_Level | D_M3 | D_M3-D_Level |
| --- | ---: | ---: | ---: |
| 2019-01 | 36.4576 | 36.7616 | +0.3039 |
| 2019-04 | 51.9250 | 41.5107 | -10.4143 |
| 2019-07 | 49.5119 | 47.0872 | -2.4247 |
| 2019-10 | 34.9316 | 49.0552 | +14.1236 |

The geometry trade-off exists in all four months, but its magnitude does not explain the large April-versus-October performance reversal. October does not exhibit a more severe current-level sacrifice than April, yet M3 is much worse relative to Level.

Therefore the original D1 hypothesis is **mechanistically present but insufficient as a full explanation**:

> M3 does select histories that are much closer in session-state geometry and much farther in instantaneous current level than Level-Control. This explains the existence of a geometry conflict, but aggregate geometry alone cannot explain when that conflict is beneficial or harmful, especially across months.

## 5. Scientific boundary

R4-D1 is descriptive. It does not establish causality, does not optimize a distance metric, and does not justify a post-hoc R4 PASS/STOP change. Formal R4-I0 remains `MIXED_STATE_ALIASING_SIGNAL`.

The next scientific question must therefore move from aggregate geometry to **query-level regime identification**: can information visible at issue time indicate when the session-state branch should be trusted relative to current-level continuity?
