# JPL/ACN R7-D1 departure attribution outcome

Date: 2026-09-14
Status: COMPLETE
Decision: `TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL`

## 1. Formal identity

```text
source R7 status SHA256          deb7fc1700fccd3eb53616bbe2e65de0941b6294d60aec58e4f63953b576bce0
source R7 private manifest       172c69c71e6baef689f65ad0169b3440947675f462dd1bc9b72479e11bad6967
R7-D1 status SHA256              48247f4ef47415c65b080584e667e9b2dba9227271ad24d93da51800756b406b
protocol commit                  5532e2f9aca90e03c580d0203aec6b193b71cda3
reviewed executable              2a2384781eeccf122ef43116b604f319e5637bdc
implementation merge             992a611d8c3223b895818df984fc6e4f6b4521af
launcher SHA256                  80242a597b5dd25b3eea5d36f1b26119ef4a7044589aca6e4fbe9b7e1573f2a4
private manifest SHA256          0c816334d74173e16df6e58e55de90ca3ed5723a6775e0b6287749afa479e019
fit_count                        275
holdout_accessed                 false
development_data_unchanged       true
reference_models_retrained       false
r7_departure_retrained           false
```

Development months were `2019-01/04/07/10`; final holdout `2019-03/06/09/12` remained sealed.

## 2. Frozen decision result

All preregistered conditions for `TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL` were satisfied.

Decision support:

```text
Availability component wins vs Base-M2       4/5 horizons, 3/4 months
Availability total wins vs S1                 5/5 horizons, 3/4 months
Departure-Aug component wins vs Availability  3/5 horizons, 3/4 months
Departure-Aug total wins vs Availability      3/5 horizons, 3/4 months
max Departure component degradation           +0.3915%
max Departure total degradation               +1.4584%
```

The frozen 5% degradation ceiling was not approached.

## 3. Pooled overall

Arrival-component MAE:

```text
Base-M2                 23.1051516907 A
Departure-Availability  23.0557563709 A
Departure-Aug           22.7486906628 A
```

Relative changes:

```text
Availability vs Base-M2        +0.213785%
Departure-Aug vs Availability  +1.331840%
Departure-Aug vs Base-M2       +1.542777%
```

Total-load MAE:

```text
S1                  28.5948815297 A
Equal               28.9172859886 A
TotalAvailability   28.4546589435 A
TotalDeparture      28.4354542901 A
```

Relative changes:

```text
TotalAvailability vs S1        +0.490377%
TotalDeparture vs Availability +0.067492%
TotalDeparture vs S1           +0.557538%
```

Thus declaration availability/missingness explains only a small part of the R7 component gain. The larger incremental component gain comes from the numerical requested-departure timing distribution.

## 4. Horizon structure

Departure-Aug relative to Departure-Availability:

```text
horizon   arrival MAE change   total MAE change
15 min       +2.4918%             +0.5303%
30 min       -0.3915%             -0.5086%
60 min       +4.5427%             +2.6429%
120 min      +1.9216%             +0.4012%
240 min      -0.2361%             -1.4584%
```

Positive means Departure-Aug is better.

The timing signal is strongest at 60 min and remains positive at 15 and 120 min. It does not dominate at 30 or 240 min. Therefore the result supports a horizon-dependent timing exposure, not a universal monotonic benefit from adding more departure statistics.

## 5. Month structure

Departure-Aug relative to Departure-Availability:

```text
month     arrival MAE change   total MAE change
2019-01      +3.2363%             +1.0000%
2019-04      +2.2267%             +0.1517%
2019-07      +1.0834%             +0.4989%
2019-10      -1.3790%             -1.2427%
```

The signal is positive in January, April and July and reverses in October. This preserves the previously observed month heterogeneity and prevents a causal interpretation.

## 6. Scientific interpretation

Accepted bounded claim:

> Numerical requested-departure timing values of currently connected sessions contain stable incremental predictive information for future-arrival current beyond declaration availability/missingness alone, and part of that information survives recombination into total station-current forecasts.

This result rules out the narrow explanation that R7-C0 was merely driven by whether requested-departure metadata happened to be present.

It does **not** establish that requested departure causes future arrivals or connector release. Requested departure is user-provided intended timing, not realized disconnect time. The October reversal and the 30/240-min horizon reversals show that the signal remains context dependent.

## 7. Consequence boundary

Per the frozen protocol, the next permissible step is to design and preregister a **horizon-aligned scheduled-departure exposure representation** using only issue-time-known requested-departure information.

The next step should remain narrow:

- preserve the accepted component decomposition;
- preserve development-only evaluation and sealed final holdout;
- use requested-departure timing relative to each forecast horizon rather than adding another generic model block;
- do not reopen gate/MoE, survival/TPP, higher-order set, control-endogeneity or FTAR routes;
- do not claim causality;
- do not retune on final holdout.

No further R7-D1 rerun is authorized unless a separately frozen repair protocol is created.
