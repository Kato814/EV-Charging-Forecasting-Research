# JPL/ACN R8-C0 horizon-aligned requested-departure exposure outcome

Date: 2026-09-14
Status: COMPLETE
Decision: `NO_STABLE_HORIZON_ALIGNED_ADVANTAGE`

## 1. Formal identity

```text
R8-C0 status SHA256              5f69386c62bff1314cc16de94d1667421e872aada739194e41ab41c5f5e2a6fe
protocol merge                    de2ca2a0be462a85d61adb48f6b32c0ae9996c6d
reviewed executable               91ab4a18f776b33e00a439ab10c74fd42a04f9b5
implementation merge              e67dbac395a89155042dead07b441714b4ec4f12
launcher SHA256                   afa29c162dac6b8132dd6081a9a0cba9f64235362cba946a660f3d0190777777
source R7-D1 status SHA256        48247f4ef47415c65b080584e667e9b2dba9227271ad24d93da51800756b406b
source R7-D1 private manifest     0c816334d74173e16df6e58e55de90ca3ed5723a6775e0b6287749afa479e019
private manifest SHA256           ec11e3555727259960e355b12ac1867d14adef876fedf2d7580daaa3366ff2d2
fit_count                         275
holdout_accessed                  false
development_data_unchanged        true
reference_models_retrained        false
R7-D1 references retrained        false
```

Development months remain `2019-01/04/07/10`; final holdout `2019-03/06/09/12` remained sealed.

## 2. Frozen decision support

```text
component wins vs Departure-Aug          0/5 horizons, 1/4 months
component wins in {60,120,240}           0/3
total wins vs TotalDeparture             2/5 horizons, 1/4 months
component wins vs Availability           2/5 horizons, 1/4 months
total wins vs TotalAvailability          0/5 horizons, 1/4 months
max component horizon degradation        +5.288667%
max total horizon degradation            +2.986383%
```

Pooled relative changes:

```text
HorizonExposure vs Departure-Aug arrival       -1.723941%
HorizonExposure vs Departure-Availability      -0.369141%
TotalHorizonExposure vs TotalDeparture         -0.704834%
TotalHorizonExposure vs TotalAvailability      -0.636866%
```

Negative values denote worse MAE.

## 3. Pooled overall results

Arrival-component MAE:

```text
Base-M2                 23.1051516907 A
Departure-Availability  23.0557563709 A
Departure-Aug           22.7486906628 A
Horizon-Exposure        23.1408646361 A
```

Total-load MAE:

```text
Equal                   28.9172859886 A
S1                      28.5948815297 A
TotalAvailability       28.4546589435 A
TotalDeparture          28.4354542901 A
TotalHorizonExposure    28.6358770531 A
```

The new horizon-aligned four-count representation is worse than the accepted generic Departure-Aug representation at pooled component and total levels. It is also worse than Departure-Availability at pooled component and total levels, and worse than S1 at pooled total level.

## 4. Horizon structure

HorizonExposure relative to Departure-Aug:

```text
horizon   arrival change   total change
15 min      -2.3194%        -0.6957%
30 min      -0.6664%        +0.3782%
60 min      -5.2887%        -2.9864%
120 min     -1.6906%        -0.8640%
240 min     -0.4186%        +0.2480%
```

The component loses at all five horizons. The largest failure occurs at 60 min, exactly where R7-D1 had shown the strongest incremental timing-distribution value. Thus the R8 single-window count does not preserve the useful timing information identified by R7-D1.

## 5. Month structure

HorizonExposure relative to Departure-Aug:

```text
month      arrival change   total change
2019-01       -3.4633%        -1.4481%
2019-04       -3.0773%        -1.6254%
2019-07       -2.2224%        -1.2982%
2019-10       +1.9016%        +1.3033%
```

Only October improves. The representation therefore does not resolve the month heterogeneity observed in R7-D1.

## 6. Scientific interpretation

Accepted bounded conclusion:

> The R7-D1 requested-departure timing signal cannot be reduced to a single forecast-window exposure count plus overdue/availability counts. The useful signal depends on richer timing-distribution structure than `0 < d_i <= h` alone.

R8-C0 does **not** invalidate R7-C0 or R7-D1. Those stages established that requested-departure state, and specifically numerical timing values beyond metadata availability, contain stable incremental information. R8 only rejects this particular compressed horizon-aligned representation.

Do not claim:

- horizon alignment itself is useless;
- requested departure has no predictive value;
- actual connector release is causal;
- a weighted current/pilot/energy version should be rescued post hoc.

The tested four-count representation should not be promoted as the final method.

## 7. Consequence boundary

Do not rescue R8 by adding current/pilot/energy weighting, ratios, learned gates, feature search, attention, Transformer/Mamba, survival/TPP, or post-hoc month/horizon routing.

One final narrow representation question remains scientifically justified: whether the missing information is the **shape of the requested-departure distribution across the full canonical forecast grid**, rather than the count inside the single target horizon.

A subsequent probe, if authorized and preregistered, should use one fixed forecast-grid histogram/CDF representation whose bins are determined solely by the canonical horizons `{15,30,60,120,240}`. It must keep the same HGB learner, parameters, rolling OOS rows, target, and read-only R7-D1 references. If that final distribution-shape probe fails, the departure-representation refinement route should close and R7 Departure-Aug should remain the accepted development candidate.
