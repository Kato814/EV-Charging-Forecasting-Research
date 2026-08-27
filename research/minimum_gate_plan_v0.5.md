# Minimum Gate Plan — v0.5

## Gate 1 — Forecast-time state value

### Question

Does the exact state of sessions already active at issue time improve future station-power prediction beyond aggregate history and occupancy?

### Data

ACN-Data first; DESL-EPFL Level 3 as external high-resolution check.

### Protocol

For issue times every 15 minutes or 5 minutes:

- freeze all observations at the issue time;
- identify active sessions without using their future end time;
- build horizons from 15 minutes to 4 hours;
- compare aggregate-only, aggregate+occupancy, aggregate+active-state, and oracle-active-state models.

### Pass condition

A consistent improvement in near-horizon probabilistic score and peak/ramp metrics that cannot be reproduced by adding one occupancy ratio feature.

## Gate 2 — Two-source decomposition value

### Question

Does separate modelling of active-session continuation and future arrivals outperform one undifferentiated station model?

### Ablations

1. direct aggregate model;
2. active branch only;
3. arrival branch only;
4. active + arrival with independent aggregation;
5. active + arrival with correlated aggregation;
6. oracle arrivals and/or oracle active remainder to estimate value ceilings.

### Pass condition

The full decomposition improves CRPS/energy score and at least one operational metric, with interpretable horizon-dependent error attribution.

## Gate 3 — Label and control audit

### Question

Are the target traces measured, reconstructed or controlled?

### Required checks

- distinguish `chargingCurrent/P` from `pilotSignal/Pset/Preq`;
- quantify sessions affected by station control;
- exclude future `doneChargingTime`, total duration or final energy from issue-time inputs;
- verify ACN timestamp corrections and time zones;
- document any constant-power or rated-power reconstruction.

### Stop condition

If target semantics cannot be established, no forecast claim is accepted.

## Gate 4 — Weak-label identifiability pilot

### Question

Can latent power curves be recovered from energy, duration and limited metadata when metered curves are hidden?

### Test

Use metered ACN/EPFL sessions, mask the trace, retain weak labels, and compare:

- constant rectangle;
- justified bilinear curve;
- clustering/template model;
- multi-fidelity latent-curve model.

### Pass condition

The proposed model improves true curve, peak and aggregate errors on held-out metered sessions and provides calibrated reconstruction uncertainty.

## Gate 5 — Peak/ramp backup

### Question

Do conventional direct models fail materially on peak timing, intensity or ramp events?

### Pass condition

A structured joint model must improve event metrics without degrading overall probabilistic performance and must change a reserve/capacity decision.

## Gate 6 — Small downstream scheduling value

Use the same station-power scenarios in a deliberately simple rolling optimization:

- power-cap or transformer-limit management;
- optional PV/storage coordination;
- asymmetric penalty for underprediction;
- no attempt to make optimization the forecasting paper’s main novelty.

Compare realized cost/risk with perfect information, direct forecasts and the proposed scenarios.
