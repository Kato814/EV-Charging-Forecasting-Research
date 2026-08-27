# Research Gap Map — Problem-First Revision

> A gap is retained only if it names a forecasting failure, nearest neighbors, observable evidence and a stop condition. OOD is an optional validation axis, not the core problem.

| Problem fragment | Existing work already covers | Candidate unresolved detail | Minimum falsification test |
|---|---|---|---|
| Rolling issue-time information | remaining occupation, partial DCFC curve prediction, aggregate rolling forecasts | joint probabilistic station load from active-session remainder + future arrivals | strict issue-time active/arrival decomposition on ACN and EPFL |
| Session-driven uncertainty | compound Poisson/Cox, queue-to-load, bottom-up mixture models | source-resolved uncertainty and correlations when some sessions are already observed | direct vs bottom-up vs decomposed model with CRPS and variance attribution |
| Weak power labels | constant-power reconstruction, nonlinear profile assessment | multi-fidelity latent curve distribution from energy/duration plus metered anchors | mask true traces and test recovery on held-out metered sessions |
| Peak operational error | post-hoc peak error reports, generic peak timing/shape methods | EV-specific joint curve–peak–ramp probability model | event metrics plus transformer/reserve decision value |
| Zero/intermittent demand | compound event models and multi-task outputs | coherent zero activation–count–conditional power forecast | low-utilization station stratified proper scoring |
| Controlled-load labels | pilot/setpoint/realized power datasets, managed-charging field evidence | latent need versus policy-conditioned executed power | cross-policy or known-control counterfactual validation |
| Supply-censored demand | censored regression/GNN and queue models | multiple censoring mechanisms and partial identification | real fault/queue/abandon/substitution fields required |
| Multi-resolution output | temporal reconciliation methods | preserve EV peaks/ramps while reconciling energy totals | 5/15/60 min joint evaluation |

## Current priority

G01 dual-source rolling power forecast is the first experiment. G02 and G03 are parallel fallback gates. No paper title or method is frozen before these tests.
