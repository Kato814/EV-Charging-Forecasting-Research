# Post-R5 method screening — information bottleneck before another model

Date: 2026-09-14
Status: method screening only; no model/run authorization.

## 1. Accepted starting point

Formal development evidence now includes:

```text
S1    MIXED_STRUCTURED_SIGNAL
P1    STOP_MECHANISM_ROUTE
R1    MIXED_JOINT_STATE_SIGNAL
R2    STOP_HIGHER_ORDER_SET_ROUTE
R3-C0 STOP_CONTROL_ENDOGENEITY_ROUTE
R4-I0 MIXED_STATE_ALIASING_SIGNAL
R4-D1/D2 COMPLETE diagnostics
R5    STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE
```

R5 adds one important distinction. FTAR improves held-out latent/future-transition Spearman from 0.378605 to 0.470014 and improves that geometry measure in all four development months, but changes pooled MAE only from 35.013762 A to 35.001553 A and remains far worse than Equal/S1. Better learned geometry therefore does not solve the point-forecast problem.

Final holdout 2019-03/06/09/12 remains sealed.

## 2. Routes not selected after R5

### 2.1 Larger neural backbone

Rejected as immediate next step. R5 was a matched representation-mechanism experiment, and the frozen STOP boundary explicitly disallows rescuing the result with a larger MLP, Transformer, attention, Mamba or Neural ODE.

### 2.2 Gate / MoE / horizon or month router

Rejected. R4-D2 already showed that the target-free geometry balance is not a stable routing variable. Generic horizon/regime-aware expert routing is also established prior art. A new router would not answer the remaining information question.

### 2.3 Deep Sets / Set Transformer / individual-session attention

Rejected. R2 directly tested true same-session higher-order alignment against a marginal-preserving control and stopped the route. A more expressive set encoder would be post-hoc rescue.

### 2.4 Survival / TPP / explicit future-session generation

Rejected for the current line. P1 continuation/count-mark failed, and explicit origin-active continuation plus future-session generation is already occupied by adjacent session-replayable forecasting work.

### 2.5 Generic probabilistic / conformal forecasting as immediate novelty

Not selected as the next experiment. Recent EV charging forecasting literature already contains Bayesian deep learning, quantile/TFT multi-horizon forecasts, probabilistic residual hybrids, adaptive conformal prediction and session-replayable probabilistic forecasting. Uncertainty prediction may become appropriate if the remaining error is shown to be dominated by unavailable future information, but generic probabilistic forecasting is not itself the unresolved mechanism.

## 3. Remaining scientific question

The central unresolved question is now **where the irreducible-looking point-forecast error comes from**.

S1 gives an exact offline decomposition:

```text
y_total = y_existing + y_arrival
prediction_S1 = E_hat + A_hat
```

P1 showed that replacing those branches with simple explicit continuation/count-mark models does not work. R2/R3/R4/R5 show that richer issue-time representation, control state, analog geometry and supervised geometry alignment do not provide stable strong-baseline gains.

Before designing any new model, quantify the value of perfect information for each S1 component.

## 4. Selected next diagnostic: R6-O0 component oracle-gap analysis

R6-O0 is **read-only and zero-fit**. It reuses the already accepted S1 private OOS cache and does not touch raw/processed data unless strictly needed for cache identity verification.

For every accepted OOS row define:

```text
S1              = E_hat   + A_hat
PerfectExisting = E_truth + A_hat
PerfectArrival  = E_hat   + A_truth
Truth           = E_truth + A_truth
```

Interpretation:

- `MAE(S1) - MAE(PerfectExisting)` = value of perfect information about the future contribution of sessions already connected at issue time;
- `MAE(S1) - MAE(PerfectArrival)` = value of perfect information about sessions arriving after issue time.

This is an offline information diagnostic only. `E_truth` and `A_truth` are never legal predictors.

## 5. Required diagnostics

A later frozen R6-O0 protocol should report, on the existing common OOS rows:

1. MAE/RMSE/WAPE for S1, PerfectExisting and PerfectArrival;
2. value-of-perfect-information (VPI) for each component pooled, by 5 horizons, by 4 months and 20 month×horizon cells;
3. existing-branch error and arrival-branch error sign agreement;
4. fraction and magnitude of error cancellation versus reinforcement in `e_total=e_existing+e_arrival`;
5. horizon at which arrival VPI overtakes existing VPI, if any;
6. cross-month stability of that ordering;
7. no favorable cell selection.

Strong M3/Equal/S1 aggregates remain read-only context; no model is retrained.

## 6. Why this diagnostic matters

Possible outcomes have different consequences:

### Future-arrival information dominates

If PerfectArrival yields large and cross-month-stable gains, especially at 120/240 min, then the remaining long-horizon ceiling is primarily associated with information not available at issue time. More elaborate issue-time session encoders become hard to justify. A later probabilistic or external-known-future-covariate formulation may be scientifically appropriate, but requires a separate novelty review.

### Existing-session information dominates

If PerfectExisting yields the larger stable gain, there is still meaningful headroom in forecasting the evolution of currently connected sessions. Any new mechanism must nevertheless differ from the already closed P1/R2 routes.

### Mixed / cancellation-dominated

If neither component has stable VPI or total error is dominated by cross-component cancellation/reinforcement, the problem is not separable in the S1 sense. Another branchwise model would be unjustified; the project should consider whether the current point-forecast objective has reached a practical information limit under the available issue-time data.

## 7. Novelty boundary

R6-O0 itself is not claimed as a forecasting algorithm or a novel oracle technique. Its role is decision-theoretic: prevent another architecture search before establishing whether the remaining error is attributable to a learnable issue-time component or unavailable future information.

If a later paper uses the result, the contribution can only be the evidence chain about observability/information bottlenecks in online charging-station forecasting, not the generic concept of an oracle ablation.

## 8. Execution policy

No local command is authorized by this screening document alone.

Before R6-O0:

1. freeze exact accepted private-cache identity;
2. freeze formulas, common-row checks and aggregate-only output;
3. freeze descriptive decision categories without changing prior outcomes;
4. implement read-only diagnostic and tests in a separate PR;
5. full CI;
6. release one pinned launcher only if needed.

No model fit, no hyperparameter tuning, no new data download and no final-holdout access are permitted.