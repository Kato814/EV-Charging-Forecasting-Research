# JPL P1-A read-only post-mortem outcome

Date: 2026-09-12

## 1. Scope and safety

This is the single read-only post-mortem authorized after the frozen P1 decision `STOP_MECHANISM_ROUTE`.

Execution identity:
- PR #58 CI-passed head: `9bc752f1b416e0dce4cb59942d3ecb07315b9273`
- PR #58 merge: `6df5cc836635fedb2034f27cdb34e7dda6e8a885`
- accepted P1 private manifest: `df222c4731f3c3192735a6df2ccd2f692f1ea6d640a7954706e7bca17f51580f`

Safety audit:
- status = `COMPLETE`
- analysis_only = true
- model_fit_attempted = false
- raw_or_processed_data_accessed = false
- holdout_accessed = false
- P1 private cache unchanged
- existing worktrees preserved
- no cleanup, tuning, clipping, calibration or model rescue

The scientific decision remains `STOP_MECHANISM_ROUTE`.

## 2. Overall P1-A failure concentration

Across 25,375 development OOS rows:
- P1-A component MAE = 167.857291 A
- prediction median = 10.396828 A
- prediction q99 = 518.312153 A
- prediction q99.9 = 976.436690 A
- prediction max = 2,526,912.316702 A
- arrival-truth max = 742.980111 A
- predictions >100 A: 2,997
- predictions >500 A: 280
- predictions >1,000 A: 22
- predictions >5,000 A: 3
- predictions >10,000 A: 3

Absolute-error concentration:
- worst single row = 59.33% of total absolute error
- worst 5 rows = 81.99%
- worst 10 rows = 82.09%
- worst 1% rows = 84.67%

Therefore the catastrophic pooled P1-A MAE is dominated by a very small extreme tail rather than a uniformly huge error on all rows.

## 3. Dominant pathological issue time

The strongest failures are concentrated at local time `2019-10-29 12:00`:

| horizon | P1-A prediction | arrival truth | absolute error |
| ---: | ---: | ---: | ---: |
| 15 min | 1,379.274154 A | 0.000000 A | 1,379.274154 A |
| 30 min | 2,526,912.316702 A | 0.000000 A | 2,526,912.316702 A |
| 60 min | 390,526.984821 A | 49.241222 A | 390,477.743599 A |
| 120 min | 572,604.896131 A | 165.778444 A | 572,439.117687 A |

The same local issue time producing extreme outputs across multiple horizons strongly supports an OOS feature/extrapolation pathology in the fixed Poisson-count route. It is inconsistent with a simple random aggregate-error explanation.

The private P1 cache does not contain the underlying predicted count or Poisson linear predictor, so this post-mortem does not claim coefficient-level causality. The strongest supportable interpretation is: the fixed standardized-feature + log-link Poisson count formulation is numerically/extrapolatively fragile under some development OOS states.

## 4. Failure is not only the catastrophic tail

The catastrophic tail explains most of P1-A's pooled numerical collapse, but the structured P1 route still fails scientifically even if those extreme rows are not used to reinterpret the result:
- Probe E pooled component MAE = 14.495331 A vs S1 existing = 12.791178 A;
- Probe E has only 1/5 horizon wins and 0/4 month wins;
- P1-Eonly pooled MAE = 30.065656 A, worse than S1 = 28.594882 A and Equal = 28.917286 A.

Therefore P1 cannot be rescued by clipping, changing Poisson alpha, removing one date, or replacing only the arrival branch after observing the results. Such actions would be post-hoc and would not repair the independent Probe-E failure.

## 5. Scientific interpretation

Accepted conclusions:
1. The descriptive horizon-dependent composition / turnover phenomenon remains valid evidence.
2. The P1 parameterization `continuation×mark + Poisson count×mark` is rejected as the core forecasting route.
3. P1-A suffers an extreme-tail OOS extrapolation failure concentrated mainly in one 2019-10 issue state, while also showing ordinary count/arrival errors elsewhere.
4. P1-E independently lacks stable component improvement.
5. Final holdout remains sealed.

Not authorized:
- rerunning P1 after clipping the extreme outputs;
- retuning Poisson/Gamma/logistic hyperparameters;
- deleting 2019-10 or the pathological timestamp;
- upgrading P1-A directly to a neural TPP as a rescue;
- upgrading P1-E directly to neural survival as a rescue;
- changing `STOP_MECHANISM_ROUTE`.

## 6. Next research phase

P1 is now closed. The next phase is new-method selection.

The next candidate must target the empirically supported forecasting difficulty rather than preserve the failed P1 decomposition. Priority is given to methods that can represent horizon-dependent and time-of-day-dependent regime specialization under the existing causal feature boundary, with explicit comparison against M2/M3/Equal/S1 and without realized future-composition oracle inputs.
