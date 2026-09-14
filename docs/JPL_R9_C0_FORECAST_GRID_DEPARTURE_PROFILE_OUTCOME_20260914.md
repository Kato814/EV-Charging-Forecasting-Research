# JPL/ACN R9-C0 forecast-grid requested-departure profile outcome

Date: 2026-09-14
Status: COMPLETE
Decision: `STOP_DEPARTURE_REPRESENTATION_REFINEMENT`

## 1. Formal identity

```text
status SHA256                 d3ce58b4272e0b3fea4f11c9774c7b61a11fae443cfbb4f09210e8e22bea6d98
protocol merge                35ed40105faaa82f0c9d7e6a96f805ffdf4aea35
reviewed executable           c60ed89f522bc3f9df30f10093e1216a9a9f6b2f
implementation merge          b7e2da489db13523c8d7fe46bff4799a63a64ba7
launcher SHA256               0efb11b2e2484ccae8c0af3ea0664ec5aaf771402621000b643894cebb143c6c
private manifest SHA256       a94de82891c821600f81adcaaa6c948a2bb90afc8e5c40ad2bfbcbdaabf744f1
fit_count                     275
development data unchanged    true
holdout accessed              false
reference models retrained    false
R8 references retrained       false
```

## 2. Pooled result

Arrival-component MAE:

```text
Base-M2                 23.1051516907 A
Departure-Availability  23.0557563709 A
Departure-Aug           22.7486906628 A
Horizon-Exposure        23.1408646361 A
ForecastGridProfile     22.8459204443 A
```

Total MAE:

```text
Equal                       28.9172859886 A
S1                          28.5948815297 A
TotalAvailability           28.4546589435 A
TotalDeparture              28.4354542901 A
TotalHorizonExposure        28.6358770531 A
TotalForecastGridProfile    28.4001928133 A
```

ForecastGridProfile improves strongly over the failed R8 Horizon-Exposure representation, but does not beat Departure-Aug at pooled arrival-component level. It is 0.4274% worse than Departure-Aug in pooled arrival MAE, while recombined total MAE is 0.1240% better than TotalDeparture and 0.6809% better than S1.

## 3. Frozen decision support

```text
component horizon wins vs Departure-Aug       3/5
component month wins vs Departure-Aug         1/4
component wins in {60,120,240}                2/3
total horizon wins vs TotalDeparture          3/5
total month wins vs TotalDeparture            2/4
max component horizon degradation             +2.855315%
max total horizon degradation                 +2.101392%
pooled component improvement vs DepartureAug  -0.427408%
pooled total improvement vs TotalDeparture    +0.124005%
pooled total improvement vs S1                +0.680852%
pooled total improvement vs Equal             +1.788180%
```

STOP is evaluated before PASS. Frozen STOP condition 2 applies because component month wins versus Departure-Aug are `1/4`, which is `<=1/4`. Therefore the formal decision is STOP even though the recombined pooled total is slightly better.

## 4. Horizon structure

ForecastGridProfile vs Departure-Aug arrival MAE:

```text
15 min   3.583442 -> 3.629743 A   worse by 1.2921%
30 min  10.069147 -> 9.999329 A   better by 0.6934%
60 min  20.023402 ->20.595133 A   worse by 2.8553%
120 min 32.747081 ->32.696125 A   better by 0.1556%
240 min 47.320381 ->47.309272 A   better by 0.0235%
```

The profile recovers the failed R8 representation and helps at 30/120/240 min, but the gain is too small and unstable; 60 min still degrades materially.

## 5. Month structure

Arrival-component improvement versus Departure-Aug:

```text
2019-01  -1.7647%
2019-04  +0.6717%
2019-07  -0.0394%
2019-10  -0.5340%
```

Only April improves. This cross-month instability is the direct preregistered STOP trigger.

## 6. Scientific conclusion

R7-D1 remains supported: numerical requested-departure timing contains incremental information beyond metadata availability. R8 and R9 show that two more explicit engineered encodings do not provide a stable replacement for the generic ten-stat Departure-Aug pool:

- R8 single target-window exposure count loses broadly;
- R9 full forecast-grid histogram recovers much of that loss and slightly improves the recombined pooled total, but fails the preregistered cross-month stability criterion and does not improve pooled arrival-component MAE over Departure-Aug.

Therefore departure-representation refinement is closed. Retain R7 `Departure-Aug` as the accepted development-stage departure representation. Do not create further engineered departure features, tune bins, select favorable horizons/months, or rescue with gates/weights/Transformer/Mamba/survival/TPP.

## 7. Holdout boundary

Final holdout `2019-03/06/09/12` remains sealed. R9 STOP does not authorize holdout access. Any future transition to robustness or holdout-readiness must use a separately frozen protocol centered on the accepted R7 candidate rather than further representation search.
