# Post-R3 method screening — 2026-09-13

## 1. Accepted starting point

Current development-only evidence:

- S1 = `MIXED_STRUCTURED_SIGNAL`;
- P1 = `STOP_MECHANISM_ROUTE`, closed;
- R1 = `MIXED_JOINT_STATE_SIGNAL`, diagnostic closed;
- R2 = `STOP_HIGHER_ORDER_SET_ROUTE`, closed;
- R3-C0 = `STOP_CONTROL_ENDOGENEITY_ROUTE`, closed because `INSUFFICIENT_CONTROL_STATE_SUPPORT`.

Final holdout 2019-03/06/09/12 remains sealed.

R3-C0 produced descriptive matched-pair error differences of about 7% for Equal/S1 on its valid subset, but only 36.26% of OOS issue states satisfied the frozen control-state support rule. Only January cleared the 0.50 month-level valid-fraction floor. The route therefore stops without threshold relaxation or future-control rescue.

## 2. Directions rejected as immediate core routes

### Larger session/control representations

Rejected. R1/R2 already tested low-order and nonlinear same-session joint information; R2 failed the matched marginal-preserving control. R3-C0 also showed that explicit pilot/current control-state support is sparse. No Set Transformer, attention, larger Deep Sets, MoE, trajectory encoder or control-state threshold rescue is authorized.

### Generic ramp / residual correction

Rejected as a novelty core. 2026 work already explicitly targets forecast-time-safe residual correction, ramps and peaks for EV charging validation. A new ramp-aware residual learner would be a crowded backbone/objective adaptation rather than a clean problem gap.

### Peak-profile / peak-magnitude forecasting

Rejected as an immediate core. 2026 literature already separates load-shape and peak-magnitude prediction for EV fast-charging planning and other recent work explicitly predicts EV charging peak demand.

### Latent / censored demand

Rejected for this line as a novelty core. Transportation Research Part C 2023 already directly formulates observed charging demand as censored by station supply and proposes censorship-aware latent-demand models.

### Generic probabilistic / uncertainty-aware multi-horizon forecasting

Rejected as a novelty core. DiffPLF and CUP-EV already provide EV-specific probabilistic multi-horizon forecasting and calibration/cost-aware evaluation.

### Generic horizon routing / MoE / similar-day selection

Rejected as a core novelty. These directions already have direct or adjacent EV prior art and would not explain why increasingly rich issue-time representations failed in this development chain.

## 3. Remaining high-value scientific question

The repeated pattern across S1/P1/R1/R2/R3 is not simply that one representation is missing. Increasingly detailed issue-time information has failed to produce a stable deterministic improvement over strong references.

The next question should therefore be:

> **Are materially different future station-current outcomes observed from issue-time states that are already very similar under the legal information set?**

This is an information-sufficiency / state-aliasing question. It asks whether the current forecasting task has an empirical deterministic ceiling under the frozen issue-time feature boundary.

This is not the same as claiming generic probabilistic forecasting is new. It is a development-data identifiability gate that determines whether another deterministic-model search is scientifically justified.

## 4. Nearest-neighbor novelty boundary

Relevant prior art already covers:

- user-level EV charging predictability heterogeneity (Applied Energy 2024);
- charging-site category and horizon effects on predictability (IET EST 2021);
- Bayesian/diffusion/quantile probabilistic EV load forecasts;
- similar-day selection and historical-pattern matching.

Therefore the next contribution cannot be “first predictability analysis”, “first kNN/similar-state forecast”, or “first probabilistic EV forecast”.

The narrow testable gap is whether the **frozen, causal JPL issue-time state used by this project exhibits empirical state aliasing with divergent future aggregate current**, and whether the aliasing grows with forecast horizon in a way that explains the failure of richer deterministic session representations.

Targeted searches did not identify an exact station-level JPL/ACN issue-time state-aliasing gate. This is negative search evidence only, not proof of absence.

## 5. Provisional next stage: R4-I0 information-sufficiency gate

R4-I0 should be a development-only diagnostic before any new forecasting model.

Design requirements before implementation:

1. no final holdout access;
2. no new model tuning;
3. state similarity must use only legal issue-time features;
4. similarity preprocessing must be frozen using only causally available historical rows;
5. future label divergence is diagnostic only and never enters state matching;
6. evaluate 15/30/60/120/240 min separately;
7. compare local conditional target dispersion against a matched baseline that controls current station-load level and local time;
8. preregister support, PASS/MIXED/STOP thresholds before reading diagnostic results;
9. do not use a favorable result to claim generic probabilistic forecasting novelty;
10. a positive gate only authorizes a separate uncertainty/target-design stage.

No local R4-I0 execution is authorized by this screening document. A separate protocol must first specify the exact state vector, scaling, historical-neighbor rule, support floor, null/matched control and decision thresholds.

## 6. Decision

The next research stage is **R4-I0 protocol design for issue-time information sufficiency / state aliasing**. No additional deterministic backbone, session encoder, control-state rescue, residual/ramp learner or holdout evaluation is authorized at this point.
