# JPL/ACN R7-C0 departure-state → future-arrival outcome

Date: 2026-09-14
Status: COMPLETE
Decision: `PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL`

## 1. Formal identity

```text
source status SHA256            deb7fc1700fccd3eb53616bbe2e65de0941b6294d60aec58e4f63953b576bce0
protocol commit                 ed427067015e60b417cd5da3838b4e0a5701b01e
reviewed CI-passed executable   24e9e69413cb4b224bd1c59cdd3725b352bd27ed
implementation merge            78e51d98d476e30098a19b67121c0658a4c848b4
launcher SHA256                 f1dbaf035055038f337f0207baba8ae0ef884ca0118c16a87ef75d7178f822e9
private manifest SHA256         172c69c71e6baef689f65ad0169b3440947675f462dd1bc9b72479e11bad6967
fit_count                       550
Departure-Aug fits              275
Full-M3 fits                    275
holdout_accessed                false
development_data_unchanged      true
reference_models_retrained      false
hyperparameter_search           false
```

Final holdout `2019-03/06/09/12` remained sealed.

## 2. Frozen primary decision support

```text
pooled arrival improvement vs Base-M2      +1.542777%
component horizon wins                      5/5
component month wins                        3/4
wins within R6 arrival-dominant horizons    3/3
max component horizon degradation          -0.172405%  (no degradation)
pooled total improvement vs S1              +0.557538%
pooled total improvement vs Equal           +1.666241%
total horizon wins vs S1                    4/5
total month wins vs S1                      3/4
max total horizon degradation vs S1         +0.568377%
```

All ten preregistered PASS conditions are satisfied.

## 3. Pooled metrics

Arrival component MAE:

```text
Base-M2       23.1051516907 A
Departure-Aug 22.7486906628 A
Full-M3       22.5561552852 A
```

Total MAE after recombination with the frozen S1 existing branch:

```text
Equal          28.9172859886 A
S1             28.5948815297 A
TotalDeparture 28.4354542901 A
TotalFullM3    28.2945240071 A
```

Secondary Full-M3 label is `FULL_M3_INCREMENTAL_SIGNAL`: its pooled arrival MAE improves 2.3761% vs Base-M2 and it wins 3/5 horizons and 3/4 months. Full-M3 total improvement vs S1 is larger in pooled magnitude (~1.05%) but less stable across horizons/months than the primary departure-only arm.

## 4. Horizon structure

Departure-Aug arrival MAE improves vs Base-M2 at every horizon:

```text
15 min   3.67925 -> 3.58344 A
30 min  10.20089 -> 10.06915 A
60 min  21.06027 -> 20.02340 A
120 min 33.18325 -> 32.74708 A
240 min 47.40210 -> 47.32038 A
```

After total recombination, Departure-Aug beats S1 at 15/30/60/120 min and slightly worsens at 240 min:

```text
15 min   8.31709 -> 8.25390 A
30 min  15.89437 -> 15.81958 A
60 min  27.18181 -> 26.43422 A
120 min 39.99124 -> 39.78645 A
240 min 51.58990 -> 51.88312 A  (+0.568%)
```

The largest practical gain is around 60 min; the 240-min arrival bottleneck remains largely unresolved.

## 5. Month structure

Departure-Aug arrival component improves in January, April and July, and worsens in October. The total recombined forecast follows the same 3/4 month pattern.

Therefore the signal is stable enough for the frozen PASS rule but is not universal across all months.

## 6. Scientific interpretation

Accepted bounded claim:

> Issue-time requested-departure state of currently connected sessions provides stable incremental predictive information for the future-arrival current component beyond the frozen M2 representation, and part of that gain survives recombination into total station-current forecasts.

The canonical departure pool contains both requested-departure timing statistics and availability/missingness statistics (`count`, `missing_count`). Therefore R7-C0 does **not** establish that the timing values alone are responsible for the gain. It also does not establish a causal connector-release mechanism, and requested departure must not be treated as actual departure.

The Full-M3 result shows that additional current-session state beyond the departure pool also carries arrival information, but its total-forecast gain is less stable.

## 7. Required next attribution step

Before promoting a capacity-release/departure-timing forecasting method, isolate whether the R7 signal comes from actual requested-departure timing or merely from departure-field availability/missingness and correlated user/session regimes.

A narrow development-only ablation should compare:

- frozen Base-M2;
- `Departure-Availability`: M2 + only departure observed-count/missing-count information;
- frozen R7 `Departure-Aug`: M2 + the full ten-stat departure pool.

This attribution must use the same learner, same M2 parameters, same rolling OOS rows and same total recombination. No final holdout, retuning, gate, neural model or post-hoc feature search is authorized.
