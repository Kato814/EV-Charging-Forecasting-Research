# JPL/ACN R4-D2 query-geometry regime diagnostic outcome

Date: 2026-09-13
Status: accepted single development-only run; descriptive diagnostic only.

## 1. Run identity and validity

```text
status                         COMPLETE
source status SHA256           d04a5f185b193e7b2dd3bafbafe3e095a054de3c71e9a69143f7a8d58f84bdfa
reviewed executable head       599982eadbf1c1ea9868ea20ad5ed0a87d19b74d
protocol merge                 61f00f9293d012d599d4c2f8417fc9ea7a53a58e
implementation merge           f5b0a2aa0576e40dcbe6b335dc206f0b7c2dce94
runtime                        70.5320704 s
records                        23876
D1 replay verified             true
fit_count                      0
forecast model fit             false
gate/classifier/regressor fit  false
holdout accessed               false
development data unchanged     true
```

Final holdout `2019-03/06/09/12` remained sealed. R4-I0 remains `MIXED_STATE_ALIASING_SIGNAL`.

## 2. Frozen D2 question

D2 asked whether the target-free issue-time geometry balance

```text
S_current = (C_M3-C_Level)/(C_M3+C_Level+1e-12)
S_session = (QE_Level-QE_M3)/(QE_Level+QE_M3+1e-12)
B         = S_session-S_current
```

could stratify future M3-vs-Level advantage

```text
A = D_Level-D_M3
```

without using future targets in the score or cutpoints.

The frozen pooled quartile cutpoints were:

```text
q25 = -0.5530489261
q50 = -0.2190578656
q75 =  0.0000000000
```

## 3. Pooled result

```text
Spearman(B,A)                 0.2324946715
Q4-Q1 mean A                +13.4288871834 A
Q4-Q1 M3-win fraction        -0.0877410218
```

The mean advantage increases from low-B to high-B regions, but M3 wins less frequently in Q4 than Q1. The mean signal is therefore tail-sensitive and does not provide a reliable binary or monotone expert-selection rule.

## 4. Horizon stability

| horizon | Spearman(B,A) | Q4-Q1 mean A (A) | Q4-Q1 M3-win fraction |
| ---: | ---: | ---: | ---: |
| 15 min | 0.485689 | +12.4997 | -0.07274 |
| 30 min | 0.343193 | +9.6509 | -0.09914 |
| 60 min | 0.212002 | +8.2744 | -0.11990 |
| 120 min | 0.107482 | +11.0211 | -0.12334 |
| 240 min | 0.109922 | +25.6157 | -0.02518 |

The rank association decays sharply as horizon increases. D2 therefore does not support one fixed issue-time geometry score as a stable routing variable across forecast horizons.

## 5. Month stability

| month | Spearman(B,A) | Q4-Q1 mean A (A) | Q4-Q1 M3-win fraction |
| --- | ---: | ---: | ---: |
| 2019-01 | 0.286295 | +9.8479 | -0.18673 |
| 2019-04 | 0.105662 | -20.9472 | -0.26432 |
| 2019-07 | 0.191755 | +6.8847 | -0.00483 |
| 2019-10 | 0.280980 | +40.2125 | +0.01226 |

The same score has materially different outcome relations by month, including opposite Q4-Q1 mean signs in April and October.

## 6. Accepted interpretation

R4-D1 established that raw M3 geometry trades instantaneous-current similarity for session-state similarity. R4-D2 now shows that a hand-constructed scalar balance of those two geometries is not a stable prediction-time routing signal.

D2 had no PASS/MIXED/STOP code. The project-level consequence is narrower:

- do not advance to a Level/M3 hard gate, neural gate, MoE router or month gate from this evidence;
- do not change R4-I0 thresholds or decision;
- do not infer that M3 has no predictive information;
- the unresolved modeling problem is that raw issue-time geometry is not sufficiently aligned with future load-transition similarity.

This motivates a separately preregistered representation-learning question rather than a more complicated gate.
