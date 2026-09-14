# JPL/ACN R10-R0 accepted-R7 robustness and holdout-readiness audit outcome

Date: 2026-09-14  
Status: COMPLETE  
Decision: `MIXED_DEVELOPMENT_ROBUSTNESS`

## 1. Formal identity

```text
status file                    evcf_r10_r0_status_20260914T124334Z.json
status SHA256                  058ec6b1196c76e884973e36f851e5c05831bb16fc6533b240d445c4dd82dda8
protocol commit                05dc342d376425c13f09ee68356583223203aae3
reviewed executable            753f9adc5c5bd28022d6c1ce3e4c54fb3f76c3e0
implementation merge           062fb6cee5a14a0cd5a09bf3a4e41f80cc797f9f
launcher SHA256                e4d247424274c926a07dcdee9e99eab0f3f88f5cdd1e7efec06de231ac0c6949
fit_count                      0
holdout accessed               false
network data acquisition       false
R7 candidate retrained         false
reference models retrained     false
```

Frozen source evidence:

```text
R7-D1 status SHA256            48247f4ef47415c65b080584e667e9b2dba9227271ad24d93da51800756b406b
R7-D1 private manifest         0c816334d74173e16df6e58e55de90ca3ed5723a6775e0b6287749afa479e019
R7-D1 reviewed executable      2a2384781eeccf122ef43116b604f319e5637bdc
R9 status SHA256               d3ce58b4272e0b3fea4f11c9774c7b61a11fae443cfbb4f09210e8e22bea6d98
R9 decision                    STOP_DEPARTURE_REPRESENTATION_REFINEMENT
```

The R7-D1 private-cache integrity digest was identical before and after R10:

```text
b42a5f4ccee700fe2d5fc72327dac3649e417eac8eda96989bd66b099cdf0124
```

Thus the formal audit was read-only and did not alter the accepted private evidence.

## 2. Exact pooled replay

The frozen R7 values replayed exactly:

```text
S1               28.594881529741027 A
Equal            28.917285988592520 A
TotalDeparture   28.435454290098633 A
n                25375
```

Relative pooled improvement of `TotalDeparture`:

```text
vs S1      +0.55753768197%
vs Equal   +1.66624108045%
```

The exact replay requirement therefore passed.

## 3. Local-day paired audit

There are 55 complete development local days.

```text
                         vs S1                 vs Equal
wins                     26/55                 31/55
win rate                 47.2727%              56.3636%
mean daily delta         -0.1613399025 A       -0.5681318226 A
median daily delta       +0.0572306043 A       -0.2023023543 A
top-5 positive-gain share 60.6563%             61.6789%
```

Negative delta is better. Relative to S1, the mean daily delta is favorable but the median is slightly unfavorable, and only 26/55 days are wins.

Per-month daily stability:

```text
month      wins/rate vs S1      mean delta vs S1      wins/rate vs Equal    mean delta vs Equal
2019-01     5/14 = 35.71%       -0.1929308632 A        8/14 = 57.14%         -0.0309555969 A
2019-04    10/13 = 76.92%       -0.3467334282 A        6/13 = 46.15%         +0.0912951953 A
2019-07     8/14 = 57.14%       -0.3857214323 A        9/14 = 64.29%         -1.4930056515 A
2019-10     3/14 = 21.43%       +0.2667837192 A        8/14 = 57.14%         -0.7927593074 A
```

The principal limitation is therefore day-level breadth versus S1, especially in January and October.

## 4. Leave-one-group robustness

### Leave-one-month-out

`TotalDeparture` remains better than both references after omitting any one development month:

```text
wins vs S1      4/4
wins vs Equal   4/4
```

### Leave-one-horizon-out

`TotalDeparture` remains better than both references after omitting any one forecast horizon:

```text
wins vs S1      5/5
wins vs Equal   5/5
```

This rules out the narrow explanation that the pooled improvement is produced by only one development month or one forecast horizon.

## 5. Original month/horizon stability

Original aggregate wins:

```text
                         vs S1      vs Equal
month wins               3/4        3/4
horizon wins             4/5        4/5
```

Worst original-month relative degradation:

```text
vs S1      +1.003588%
vs Equal   +1.675240%
```

Worst original-horizon relative degradation:

```text
vs S1      +0.568377%
vs Equal   +1.120563%
```

All are within the frozen 5% READY degradation ceiling.

## 6. Stratified complete-day bootstrap

Frozen settings:

```text
PCG64 seed         20260914
replicates         10000
sampling unit      complete local day within month
month weighting    equal
```

Descriptive results:

```text
             q05 delta      q50 delta      q95 delta      fraction(delta < 0)
vs S1       -0.750704 A     -0.154270 A     +0.387802 A     0.6790
vs Equal    -1.631415 A     -0.544217 A     +0.439869 A     0.8154
```

The 5th-95th percentile intervals cross zero for both references. These bootstrap quantities are descriptive only and do not modify the deterministic decision.

## 7. Frozen decision

`FRAGILE_DEVELOPMENT_SIGNAL` does not apply:

- pooled `TotalDeparture` is better than S1 and Equal;
- leave-one-month-out wins are 4/4 against both;
- local-day win rates are 47.27% vs S1 and 56.36% vs Equal, both above the 40% FRAGILE threshold.

`READY_FOR_SINGLE_SHOT_HOLDOUT_PROTOCOL` does not apply because one required condition fails:

```text
required local-day win rate vs S1   >= 50%
observed                              47.2727% = 26/55
```

All other frozen READY conditions pass. With 55 days, at least 28 day wins would have been required; the frozen result has 26.

Therefore the preregistered exhaustive decision is:

# `MIXED_DEVELOPMENT_ROBUSTNESS`

## 8. Scientific interpretation

The accepted R7 `Departure-Aug / TotalDeparture` gain is reproducible at pooled level and survives every leave-one-month-out and leave-one-horizon-out deletion. It is therefore not explained by a single favorable development month or horizon.

However, the gain is not sufficiently broad at the local-day level relative to the stronger S1 reference. The candidate improves the mean error but does not win on a majority of development days; the median daily delta versus S1 is slightly positive and the largest five favorable days account for about 60.7% of positive daily gain.

The supported statement is therefore limited to development evidence:

> Requested-departure timing provides reproducible incremental predictive information and a small pooled total-load gain, but the total-load improvement does not yet show sufficient day-level breadth to qualify for single-shot final-holdout readiness.

This is a robustness result, not a final-generalization claim.

## 9. Consequence and route closure

Final holdout `2019-03/06/09/12` remains sealed.

R10-R0 does **not** authorize:

- final-holdout access;
- further departure feature/bin/ratio/weight engineering;
- hyperparameter search or refitting;
- favorable month/horizon/day selection;
- gate/MoE/router rescue;
- survival/TPP/Transformer/Mamba/attention rescue.

R9 `STOP_DEPARTURE_REPRESENTATION_REFINEMENT` remains unchanged. R7 `Departure-Aug / TotalDeparture` remains the accepted development-stage candidate, but it is **not holdout-ready** under the frozen R10 criteria.

The next project action is documentation/scientific-route review using the frozen R10 evidence only. No additional model experiment is authorized by R10-R0.
