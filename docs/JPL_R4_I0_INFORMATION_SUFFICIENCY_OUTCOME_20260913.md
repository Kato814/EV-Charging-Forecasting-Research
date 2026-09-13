# JPL/ACN R4-I0 information-sufficiency / state-aliasing outcome

Date: 2026-09-13

## Formal status

Source local status SHA256:

`a8b7142e0361b5cd56e53c7de99d8e699a27e1aee78728810773c127f385823f`

Frozen identities:

```text
protocol merge              fec13c28cb5d4b2490256f8a26d82f45d8af6051
reviewed executable head     d3f00320e90aeb213d97d63d3460f58d495dd34a
implementation/report merge 1590b980b50e6ac1cb2db955b102431aa0c1ad25
launcher SHA256              880a5221594b5434386d62ec1b242c915cf229802ddc5644f09b52f9ea82345e
runtime                      39.9417172 s
fit_count                    0
model_fit_attempted          false
holdout_accessed             false
```

Development data and existing worktrees were unchanged after the run. Final holdout `2019-03/06/09/12` remained sealed.

Formal decision:

`MIXED_STATE_ALIASING_SIGNAL`

No frozen threshold is changed after observing the result.

## Support gate

Support passed comfortably:

```text
pooled supported fraction       0.9409261084
supported origin-horizon rows   23876 / 25375
minimum cell supported fraction 0.8620689655
minimum cell supported records  1124
```

All 20 month × horizon cells therefore pass both the preregistered `>=0.50` supported-fraction floor and `>=250` supported-record floor. The MIXED result is not caused by inadequate analog support.

## Pooled result

```text
G_level                         43.172626 A
G_M2                            47.766515 A
G_M3                            43.853076 A
Y_scale                        147.192726 A
normalized M3 divergence         0.297930
skill M2 vs Level               -0.106407
skill M3 vs Level               -0.015761
skill M3 vs M2                   0.081928
```

Close M3 states still show materially different futures: pooled normalized M3 divergence is about 29.8%, and all five horizons exceed the frozen 0.08 material-divergence floor.

However, M3 does not stably beat Level-Control overall. Its pooled skill versus Level is slightly negative. At the same time, M3 improves materially over M2 by 8.19% pooled.

## Exact PASS audit

R4-I0 `PASS_STATE_ALIASING_SIGNAL` has 13 frozen conditions. Twelve pass. The sole failed condition is:

```text
required: pooled skill_M3_vs_M2 <= 0.02
actual:   pooled skill_M3_vs_M2 = 0.0819284863
```

Thus the result cannot be promoted to a pure state-aliasing PASS: the richer M3 session-state representation does contain stable incremental information beyond M2 under the frozen analog metric.

## Exact STOP audit

Neither preregistered STOP route is satisfied.

### Legal state resolves divergence

Neither M2 nor M3 meets the complete same-arm STOP pattern versus Level:

```text
pooled M2 vs Level  = -0.106407
pooled M3 vs Level  = -0.015761
```

Only one of five horizons reaches >=5% skill versus Level for M2, and only one of five for M3. M2 reaches >=5% skill in zero of four months; M3 reaches it in only one month. The 60-min skills are negative for both arms.

### M3 future divergence is small

This route also fails strongly:

```text
pooled normalized M3 divergence = 0.297930  (not <0.05)
horizons <0.08                  = 0/5      (requires >=4/5)
```

Therefore the formal MIXED decision is internally consistent with the frozen protocol.

## Horizon structure

| horizon | M2 vs Level | M3 vs Level | M3 vs M2 | normalized M3 divergence |
| ---: | ---: | ---: | ---: | ---: |
| 15 min | -42.34% | -29.61% | +8.94% | 0.2411 |
| 30 min | -27.70% | -16.23% | +8.99% | 0.2542 |
| 60 min | -17.61% | -6.04% | +9.83% | 0.2778 |
| 120 min | -7.65% | +3.15% | +10.03% | 0.3156 |
| 240 min | +11.51% | +15.43% | +4.44% | 0.4013 |

The M3-vs-Level result changes systematically with horizon: Level-Control is strongest at short horizons, while richer state becomes increasingly useful with horizon and clearly wins at 240 min. This is descriptive evidence of horizon-dependent state relevance, not a new forecasting rule.

M3 nevertheless improves over M2 at every pooled horizon.

## Month structure

| month | M2 vs Level | M3 vs Level | M3 vs M2 | normalized M3 divergence |
| --- | ---: | ---: | ---: | ---: |
| 2019-01 | -6.73% | -0.83% | +5.53% | 0.2938 |
| 2019-04 | -1.24% | +20.06% | +21.04% | 0.2974 |
| 2019-07 | +2.23% | +4.90% | +2.72% | 0.3104 |
| 2019-10 | -45.35% | -40.43% | +3.39% | 0.2898 |

M3 improves over M2 in all four month aggregates, but M3-vs-Level is strongly month-dependent. April is favorable to M3 across all five horizons; October is unfavorable across all five horizons.

At the 20 month × horizon cell level, M3-vs-M2 skill is positive in 19/20 cells and >=5% in 12/20. M3-vs-Level is positive in only 9/20 cells and >=5% in 8/20.

## Scientific interpretation

R4-I0 does not support either extreme interpretation:

1. **Not pure information insufficiency:** M3 consistently improves over M2, so richer issue-time session state carries real incremental information under the frozen representation.
2. **Not stable deterministic sufficiency:** M3 does not consistently beat the simple current-load analog, and substantial future divergence remains even among supported close M3 states.

The most defensible description is therefore:

> The legal issue-time state contains incremental session-state information, but the predictive value of that richer state relative to instantaneous station-current continuity is strongly horizon- and month-dependent.

This is still a descriptive development-data result. It does not prove irreducible uncertainty, does not authorize final holdout access, and does not authorize metric learning or a new deterministic model.

## Next allowed step

Per the frozen MIXED rule, the only next action is a separately preregistered zero-fit/read-only failure analysis. The next diagnostic is R4-D1 state-geometry decomposition, which asks whether frozen M3 analog selection gains session-state similarity while sacrificing current-load similarity, and whether that trade-off explains the horizon/month pattern above.
