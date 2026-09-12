# JPL P1 mechanism probe outcome

Frozen outcome date: 2026-09-12

This document records the accepted development-set outcome of the preregistered P1 mechanism probe. It does not authorize final-holdout access and does not change the earlier S1 `MIXED_STRUCTURED_SIGNAL` decision.

## 1. Execution identity and safety

- Development months only: 2019-01, 2019-04, 2019-07, 2019-10.
- Final holdout remained sealed: 2019-03, 2019-06, 2019-09, 2019-12.
- PR #56 CI-passed reviewed head: `dac9d18596d8e3ba766e02f83b21d60e650e5957`.
- PR #56 merge commit: `33f391c5186650846826fdcb802e4f3e5c329d9d`.
- P1 private manifest SHA256: `df222c4731f3c3192735a6df2ccd2f692f1ea6d640a7954706e7bca17f51580f`.
- fit_count: 1090.
- No M2/M3 retraining, hyperparameter search, clipping, calibration, neural survival, neural TPP, gate, or cleanup.
- Development data and accepted baseline/S1 private caches were unchanged; existing worktrees were preserved.

## 2. Frozen formal decision

- Probe E: `NO_COMPONENT_SIGNAL`.
- Probe A: `NO_COMPONENT_SIGNAL`.
- Primary P1-EA: **`STOP_MECHANISM_ROUTE`**.

The decision is not subject to post-hoc threshold changes.

## 3. Pooled performance

| model | pooled MAE (A) |
| --- | ---: |
| Equal | 28.917286 |
| S1 | 28.594882 |
| P1-Eonly | 30.065656 |
| P1-Aonly | 172.758507 |
| P1-EA | 172.966423 |

Component MAE:

| component | MAE (A) |
| --- | ---: |
| S1 existing | 12.791178 |
| P1-E | 14.495331 |
| S1 arrival | 23.105152 |
| P1-A | 167.857291 |

Neither P1 component improves pooled MAE relative to its corresponding S1 branch.

## 4. Horizon results

P1-EA versus Equal MAE:

| horizon | Equal | P1-EA |
| ---: | ---: | ---: |
| 15 min | 8.703288 | 12.404439 |
| 30 min | 15.974630 | 517.771190 |
| 60 min | 26.141292 | 109.278945 |
| 120 min | 40.249069 | 160.449220 |
| 240 min | 53.518152 | 64.928323 |

Decision support:
- P1-EA horizon wins vs Equal: 0/5.
- P1-EA development-month wins vs Equal: 0/4.
- 60-min P1-EA does not beat Equal.
- Probe E component wins only 1/5 horizons and 0/4 pooled months.
- Probe A component wins 0/5 horizons and 0/4 pooled months.

## 5. Failure structure

The primary total failure is dominated by Probe A. The fixed Poisson count model shows severe extrapolation instability in 2019-10, especially at short/mid horizons. Representative 2019-10 count diagnostics:

| horizon | count MAE | Poisson deviance |
| ---: | ---: | ---: |
| 15 min | ~212.0 | ~424.0 |
| 30 min | ~206.3 | ~412.2 |
| 60 min | ~48.4 | ~95.7 |
| 120 min | ~7.0 | ~12.0 |
| 240 min | ~3.1 | ~2.76 |

This produces extreme P1-A/P1-EA forecasts at isolated month × horizon × local-hour cells. This behavior is an accepted P1 failure, not grounds to retune or clip after observing results.

Probe E also fails its preregistered branch-signal rule: although 240-min existing-component MAE is slightly lower than S1 existing, pooled E is worse and stability requirements fail.

## 6. Turnover-mechanism interpretation

P1 does not repair the known morning turnover weakness. Across the four development months:
- 30 min @ 07:00: P1-EA worse than Equal in 4/4 months.
- 60 min @ 07:00: worse in 4/4 months.
- 120 min @ 07:00: worse in 4/4 months.
- 60 min @ 09:00: better in 3/4 months.
- 120 min @ 09:00: better in 4/4 months.

Therefore the earlier G0/S1 evidence for horizon-conditioned turnover remains scientifically useful as descriptive/mechanism evidence, but the specific `continuation×mark existing + Poisson count×mark arrival` architecture is not promoted as the forecasting core.

## 7. What STOP means

`STOP_MECHANISM_ROUTE` applies to the preregistered P1 predictive route. It does **not** erase:
- the exact existing/future-arrival decomposition identity;
- the horizon-dependent composition shift;
- the reproducible horizon × turnover × local-hour error structure.

Those results may remain as mechanism analysis, representation insight, and error decomposition.

## 8. Next allowed work

1. Do not rerun P1, retune Poisson/Gamma/Logistic models, clip forecasts, calibrate after the fact, or access final holdout.
2. A single read-only post-mortem is allowed to verify whether the P1-A explosion is model-form/numerical extrapolation rather than an implementation/target-identity error. This audit cannot change `STOP_MECHANISM_ROUTE`.
3. After that audit, return to method-innovation selection and open-source search. Do not automatically escalate Probe E to pycox or Probe A to EasyTPP because neither branch showed stable component signal.
4. Keep final holdout sealed until a new method route is preregistered and passes development criteria.
