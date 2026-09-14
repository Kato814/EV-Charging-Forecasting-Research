# JPL/ACN R6-O0 component-oracle replacement outcome

Date: 2026-09-14
Status: COMPLETE

## 1. Formal identity

```text
source status SHA256            52bf3d7753b095a0faf39bc9aaefbd07b2c11f406ab05abd4bd1534e921dacce
protocol merge                  256c6fd9edf8d15700c25bfc916596c9adc342b4
reviewed executable             1bdd4cbee66b6abe7465163066e2c3d2d11174c3
implementation merge            6d43c1b05d2f51c9f7d5eb50737f46fcc19636c8
launcher SHA256                 4eb8cc59d9bb59d8841cd0beb79b3364d699a87931d120a9b77dd2e990a98eeb
fit_count                       0
record_count                    25375
holdout_accessed                false
raw_or_processed_data_accessed  false
R5 private predictions accessed false
S1 private cache unchanged      true
```

Accepted S1 private manifest remained:

```text
562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1
```

## 2. Formal descriptive decision

```text
MIXED_COMPONENT_ORACLE_SIGNAL
```

Frozen decision support:

```text
pooled G_arrival                15.8037036627 A
pooled G_existing                5.4897298390 A
arrival > existing horizons      3/5
arrival > existing months        4/4
existing > arrival horizons      2/5
existing > arrival months        0/4
positive arrival gain horizons   5/5
positive arrival gain months     4/4
positive existing gain horizons  5/5
positive existing gain months    4/4
```

The result is MIXED because the preregistered arrival-dominance rule required arrival gain to exceed existing gain in at least 4/5 horizons; the observed count is 3/5.

## 3. Pooled effect size

```text
S1 MAE                           28.5948815297 A
OracleArrival MAE                12.7911778671 A
OracleExisting MAE               23.1051516907 A
G_arrival                        15.8037036627 A  (55.27% of S1 MAE)
G_existing                        5.4897298390 A  (19.20% of S1 MAE)
```

Here `OracleArrival = E_hat + A_truth`; therefore its residual MAE is the error remaining in the existing-session branch. `OracleExisting = E_truth + A_hat`; therefore its residual MAE is the error remaining in the arrival branch.

## 4. Stable horizon transition

The pooled horizon results reveal a structured rather than random MIXED outcome:

| horizon | G_existing (A) | G_arrival (A) | larger removable component |
| ---: | ---: | ---: | --- |
| 15 min  | 4.63784 | 1.15816 | existing-session |
| 30 min  | 5.69349 | 4.38389 | existing-session |
| 60 min  | 6.12154 | 12.10481 | future-arrival |
| 120 min | 6.80800 | 23.16122 | future-arrival |
| 240 min | 4.18779 | 38.21044 | future-arrival |

The crossover occurs between 30 and 60 minutes. The month-horizon cells support the same structure:

- 15 min: existing gain > arrival gain in 4/4 months;
- 30 min: existing gain > arrival gain in 3/4 months;
- 60 min: arrival gain > existing gain in 4/4 months;
- 120 min: arrival gain > existing gain in 4/4 months;
- 240 min: arrival gain > existing gain in 4/4 months.

Thus the formal MIXED label should not be interpreted as unstructured month instability. It is primarily a forecast-horizon transition in which currently connected-session evolution dominates short horizons while future-arrival uncertainty dominates from 60 min onward.

## 5. Error interaction

Pooled interaction diagnostics:

```text
branch-error Pearson            -0.0312028
cancellation fraction            0.496079
reinforcement fraction           0.503921
total cancellation share         0.203404
mean cancellation amount         7.301448 A
```

Cancellation is substantial but not dominant in the formal sense: both oracle replacement gains are positive overall, at all five horizons, and in all four months. Therefore the main interpretation is not that S1 accuracy is sustained only by compensating branch errors.

## 6. Scientific interpretation

R6-O0 establishes three bounded claims:

1. Both S1 components retain removable error; neither branch is already saturated.
2. The dominant removable error shifts with forecast horizon: existing-session evolution at 15–30 min, future arrivals at 60–240 min.
3. At long horizons, future-arrival uncertainty is the much larger bottleneck under the accepted S1 decomposition; at 240 min its oracle replacement gain is about 38.21 A versus 4.19 A for the existing-session branch.

This does not prove information-theoretic irreducibility and does not make oracle truth a legal predictor. It does show that simply enlarging issue-time encoders is poorly targeted for the long-horizon problem.

## 7. Consequence for next method selection

Do not respond to this result with a gate/MoE or another larger backbone.

The next method-selection step should treat the problem as horizon-dependent but not necessarily router-based:

- short horizon: any new mechanism must address evolution of currently connected sessions and be distinct from closed P1/R2 routes;
- long horizon: method review should focus on legally observable future-arrival covariates or a probabilistic formulation of arrival uncertainty;
- one unified method is only justified if it has a principled way to represent these two information regimes without post-hoc horizon switching.

No final holdout access is authorized by R6-O0. No new model fit is authorized until a new scientific question and protocol are frozen.
