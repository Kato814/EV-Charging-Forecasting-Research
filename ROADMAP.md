# Roadmap

## Phase 0 — Evidence library and problem definition

- [x] Build literature, dataset, code and decision-log structure
- [x] Complete initial EV forecasting/flexibility review
- [x] Complete adjacent-method and OOD review
- [x] Correct direction policy: OOD becomes optional validation rather than the paper core
- [x] Complete Round 3 problem-first gap search
- [x] Establish active-session/future-arrival, weak-label and peak-event gates
- [ ] Complete full-text review of all P0 nearest neighbors
- [ ] Pin P0 dataset versions, licenses and SHA-256

## Phase 1 — Primary data acquisition and semantics audit

- [ ] Download ACN-Data using official API/client
- [ ] Verify time-zone correction and chronological coverage
- [ ] Separate legal issue-time fields from future session outcomes
- [ ] Quantify pilot-limited/controlled sessions
- [ ] Download DESL-EPFL Level 3 files and pin commit/hash
- [ ] Audit P, Pset, Preq, SOC and overlapping-session power sharing

## Phase 2 — Gate 1 and Gate 2 baselines

- [ ] Build strict rolling issue-time samples
- [ ] Seasonal persistence and tabular baselines
- [ ] Direct aggregate TCN/PatchTST/TFT baseline
- [ ] Direct probabilistic quantile/density baseline
- [ ] Bottom-up mixture baseline
- [ ] Compound-Poisson/Cox baseline
- [ ] Joint occupancy-load baseline
- [ ] Active-only, arrival-only and oracle value ceilings
- [ ] Peak/ramp and forecast-time leakage audit

## Phase 3 — Candidate method only after gate pass

- [ ] Active-session conditional remaining-curve model
- [ ] Future-arrival marked event model
- [ ] Correlated probabilistic station aggregation
- [ ] Source-specific uncertainty attribution
- [ ] Calibration and scenario reduction for downstream use

## Phase 4 — Parallel gates

- [ ] Weak-label power-curve reconstruction masking experiment
- [ ] Joint peak timing–magnitude–ramp backup experiment
- [ ] Zero-activation/count/conditional-power component test
- [ ] Control-aware latent need/executed-power feasibility study

## Phase 5 — Downstream optimization and later project integration

- [ ] Small rolling power-cap/PV/storage scheduling value test
- [ ] Perfect-information and safe-baseline comparison
- [ ] Only after central mechanism is stable, consider distributed/trusted learning
- [ ] OOD/transfer tests only as robustness extensions where useful

## Phase 6 — Paper and release

- [ ] Freeze problem statement, nearest-neighbor table and stop conditions
- [ ] Lock data splits and result files
- [ ] Publish reproducible code and environment
- [ ] Prepare manuscript only after a gate produces a nontrivial, externally validated effect
