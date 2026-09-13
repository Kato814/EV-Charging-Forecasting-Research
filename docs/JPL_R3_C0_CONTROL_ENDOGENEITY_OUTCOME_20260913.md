# JPL/ACN R3-C0 control-endogeneity gate outcome

## Formal status

- launcher: `evcf_r3_c0_launcher_v1.py`
- launcher SHA256: `962dc62f28744ae765ae60efc30c2b67c9a6ce4ff6b0a208998fe55ba4b10521`
- reviewed implementation head: `3ab1692536c7713ac780288b49607fdc09bf4e2c`
- implementation PR: #76
- implementation merge: `587200ed0b3ad81c494d24231255ad40fcd0aa94`
- protocol merge: `a1b6fb1773860448cedd0335841b3e9c4f9a69fe`
- runtime: 10.9733355 s
- fit count: 0
- model fit attempted: false
- reference models retrained: false
- final holdout accessed: false
- development data unchanged: true
- R2 private cache unchanged: true

Formal decision:

`STOP_CONTROL_ENDOGENEITY_ROUTE`

Formal stop reason:

`INSUFFICIENT_CONTROL_STATE_SUPPORT`

## Support result

Overall valid control-state issue fraction was only 0.3625615764, below the preregistered 0.70 floor.

| month | valid issue fraction | matched pairs | low-U mean | high-U mean |
| --- | ---: | ---: | ---: | ---: |
| 2019-01 | 0.530268 | 345 | 0.536368 | 0.862221 |
| 2019-04 | 0.248305 | 145 | 0.726659 | 0.939779 |
| 2019-07 | 0.277434 | 179 | 0.639657 | 0.928585 |
| 2019-10 | 0.382716 | 246 | 0.643902 | 0.905256 |

Only January clears the preregistered 0.50 month-level valid-fraction floor. Therefore support fails before any effect-size interpretation can promote the route.

The rank-based current-level matching also left non-negligible within-pair current gaps, especially in January and April. This is reported as a descriptive limitation only; the frozen matching rule is not changed after observing results.

## Descriptive error contrasts

Sign convention is `low-U absolute error - high-U absolute error`.

Pooled matched-pair contrasts:

| reference | base MAE (A) | delta MAE (A) | delta fraction |
| --- | ---: | ---: | ---: |
| Equal | 35.672959 | -2.540967 | -0.071229 |
| S1 | 35.216742 | -2.600573 | -0.073845 |
| R1-Joint | 36.096740 | -3.129307 | -0.086692 |

Within the supported subset, lower-U states therefore had lower matched forecast error on average than higher-U states. This is not sufficient evidence for a control-endogeneity mechanism because the preregistered support gate failed and no causal claim is authorized.

Horizon direction is also not uniformly stable. Equal changes sign at 15/30 min versus 60/120/240 min, while S1 remains negative across all five horizons but is nearly zero at 15 min. At 60 min, both primary references match their pooled negative sign in only 2/4 months, below the PASS requirement.

Month-level pooled signs are negative for Equal in 4/4 months and for S1 in 3/4 months; October is near zero/opposite for S1. These are descriptive observations only.

## Scientific disposition

R3-C0 is closed under the frozen rule. Do not:

- lower the 0.80 pairwise coverage threshold;
- lower the 6 A pilot-sum floor;
- change the 5 current-level bins;
- redesign the matching after inspecting this result;
- promote pilot/current utilization as a paper-core mechanism;
- train a future-control predictor as a rescue of this gate;
- access final holdout.

The main lesson is narrower: control-related issue-time state may stratify forecast error on a limited observable subset, but the observable support is too sparse and the horizon/model direction is not sufficiently stable for a main method route.

## Next-stage boundary

Post-R3 method selection must move away from repeated session/control-state representation rescue. Candidate directions should focus on a different problem class, especially target/event definition or operational forecastability, and must again pass a transparent minimum gate before model development.
