# JPL/ACN R5 future-transition-aligned representation outcome

Date: 2026-09-14
Status: COMPLETE / STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE

## 1. Formal execution identity

The single authorized development-only R5 run completed under the frozen pre-fit protocol and implementation:

```text
source status SHA256            d3c820d90cb4d54a56f50bd9d1293aa1a3e53da50d3418ddb34abc6fa6a8a196
launcher SHA256                 bde5df90397004304f3489afc633ed115492be8be3c9fb6a52f4bbe80dd2e975
protocol merge                  3f964696606f05bdc01b6f0b217e821d0f1933bf
geometry-audit repair merge     431e1fe2fede50216d36ab89a5e61a835a29e737
reviewed executable             4f2925cba92d606b929a25dc84468fcc16f1afc4
implementation merge            efec1cce23daf64da20afd254d92d5eb79f9cf3e
formal fits                     110
development months              2019-01 / 04 / 07 / 10
final holdout accessed          false
development data unchanged      true
reference models retrained      false
hyperparameter search           false
prediction clipping/calibration false / false
gate/MoE/Set Transformer        false / false / false
```

Formal environment matched the frozen contract: Python 3.11.16, PyTorch 2.14.0+cu132, CUDA 13.2, NVIDIA GeForce RTX 5080 / cuda:0.

## 2. Frozen decision

Formal decision:

```text
STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE
```

Frozen decision support:

```text
pooled improvement FTAR vs Direct     +0.0348677%
horizon wins vs Direct                3 / 5
month wins vs Direct                  1 / 4
max horizon degradation vs Direct     1.01985%
held-out geometry Spearman gain       +0.0914087
improvement FTAR vs Equal             -21.0402%
improvement FTAR vs S1                -22.4050%
```

The STOP trigger is the frozen month-stability rule: FTAR beats Direct in only 1/4 development months. Thresholds are not reinterpreted after the result.

## 3. Pooled forecasting result

Primary MAE:

| model | pooled MAE (A) |
| --- | ---: |
| Direct | 35.013762 |
| FTAR | 35.001553 |
| M3 | 29.190188 |
| Equal 0.5 | 28.917286 |
| S1 | 28.594882 |

FTAR therefore produces only a numerically tiny MAE gain over its matched Direct arm, while remaining materially worse than all frozen strong references.

Pooled RMSE changes from 161.996896 A for Direct to 126.469982 A for FTAR. This aggregate RMSE reduction is not stable across months: January, April and July RMSE become slightly worse, while October improves strongly. It is therefore retained as a secondary diagnostic and does not override the MAE-based frozen decision.

## 4. Horizon behavior

FTAR-vs-Direct MAE change:

| horizon | Direct MAE | FTAR MAE | FTAR relative change |
| ---: | ---: | ---: | ---: |
| 15 min | 12.441689 | 12.195209 | +1.981% |
| 30 min | 19.693474 | 19.319219 | +1.900% |
| 60 min | 29.721439 | 29.337675 | +1.291% |
| 120 min | 45.551622 | 45.805039 | -0.556% |
| 240 min | 67.660586 | 68.350625 | -1.020% |

Thus the geometry objective has a small favorable effect at 15–60 min and reverses at 120–240 min. The long-horizon regime that originally motivated richer future-transition structure is not improved.

## 5. Month behavior

FTAR-vs-Direct pooled-over-horizon MAE change:

| month | Direct MAE | FTAR MAE | FTAR relative change |
| --- | ---: | ---: | ---: |
| 2019-01 | 33.933443 | 34.116404 | -0.539% |
| 2019-04 | 30.913096 | 31.618942 | -2.283% |
| 2019-07 | 32.089813 | 32.809740 | -2.243% |
| 2019-10 | 42.754650 | 41.161126 | +3.727% |

Only October improves. The geometry mechanism is therefore not month-stable.

## 6. Geometry mechanism audit

The representation objective does achieve its direct representation-space goal.

Pooled held-out same-refit Spearman:

```text
Direct    0.378605
FTAR      0.470014
Gain     +0.091409
```

Every development month shows higher held-out latent/future-transition Spearman under FTAR:

| month | Direct | FTAR |
| --- | ---: | ---: |
| 2019-01 | 0.414743 | 0.471933 |
| 2019-04 | 0.460327 | 0.512779 |
| 2019-07 | 0.447563 | 0.522918 |
| 2019-10 | 0.219788 | 0.401636 |

Therefore R5 distinguishes two statements that must not be conflated:

1. supervised future-transition alignment can measurably reshape latent geometry in the intended direction;
2. that improved geometry does **not** translate into stable or practically competitive point-forecast MAE.

This is the main scientific conclusion from R5.

## 7. Failure interpretation

The result does not support a claim that representation learning is generally ineffective. It supports the narrower frozen conclusion that **this future-transition pairwise geometry objective, under the matched single-MLP R5 contract, is not a viable main forecasting mechanism for this task**.

The weak pooled MAE gain together with strong-reference underperformance shows that the central limitation is not solved merely by making latent distance correlate better with future-transition distance. Point prediction requires preserving conditional level/transition information that a global pairwise-distance objective does not guarantee.

R5 also does not justify post-hoc architecture enlargement. In particular, the result must not be rescued by attention, Transformer, Set Transformer, MoE/gating, a larger MLP, geometry-weight tuning, clipping, calibration or favorable month/horizon selection.

## 8. Route closure and next boundary

R5 future-transition-geometry route is CLOSED.

The following remain closed and must not be revived as rescue paths:

- Level/M3 gate or MoE routing;
- P1 continuation/count-mark escalation;
- R2 Deep Sets / Set Transformer / higher-order set rescue;
- R3 control-endogeneity route;
- R5 larger-backbone / geometry-weight retuning.

Final holdout `2019-03/06/09/12` remains SEALED. R5 does not authorize holdout access.

The next research step must return to candidate-direction selection using the accumulated S1–R5 evidence. Any new forecasting mechanism requires a new pre-registered protocol before model fitting.