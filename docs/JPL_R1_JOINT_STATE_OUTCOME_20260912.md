# R1 aggregate outcome — 2026-09-12

## Decision

The user-supplied R1 status reports `COMPLETE`, 550 fits and `MIXED_JOINT_STATE_SIGNAL`. Independent recomputation of its month/horizon aggregates and frozen decision-support fields agrees with that decision. This is a status-level audit, not a replay of private data.

S1 remains `MIXED_STRUCTURED_SIGNAL`; P1 remains `STOP_MECHANISM_ROUTE`. Final holdout access remains prohibited.

## Overall MAE (A)

| Model | MAE |
| --- | ---: |
| M2 | 30.164406 |
| M3 | 29.190188 |
| Equal | 28.917286 |
| S1 | 28.594882 |
| R1-Control | 29.192882 |
| R1-Joint | 29.039978 |

Joint improves Control by 0.523773% but is 0.424285% worse than Equal. Six of eight preregistered PASS requirements hold. The failed requirements are pooled improvement over Equal and at least three month wins over Equal.

| Comparison | Horizon wins | Month wins |
| --- | ---: | ---: |
| Joint vs Control | 4/5 | 3/4 |
| Joint vs Equal | 3/5 | 2/4 |

At 60 min, Joint MAE is 26.086069 A versus Equal 26.141292 A: an advantage of only 0.055223 A (0.211249%). Maximum horizon degradation versus Equal is 1.110700%.

## Failure decomposition

July: Joint is worse than Control at all five horizons. October: Joint improves Control overall, but still trails Equal. These are distinct failures: instability of the incremental representation versus insufficient recovery of the existing baseline deficit.

| Month | Control MAE | Joint MAE | Equal MAE |
| --- | ---: | ---: | ---: |
| 2019-01 | 26.316732 | 25.817078 | 25.957616 |
| 2019-04 | 28.848095 | 28.603508 | 28.725210 |
| 2019-07 | 29.644215 | 30.004171 | 29.968817 |
| 2019-10 | 31.952295 | 31.719956 | 31.022485 |

The aggregate status does not contain daily paired losses, hourly results or feature-support statistics. No significance or causal mechanism is established. The 25,375 pooled observations include repeated issue times across five horizons and must not be treated as independent samples.

## Boundary

The frozen MIXED rule allows failure-source analysis only. No refit, parameter changes, pair selection, learned set model or new local run is authorized by this audit. No private JSON or row-level prediction cache is included in this document.
