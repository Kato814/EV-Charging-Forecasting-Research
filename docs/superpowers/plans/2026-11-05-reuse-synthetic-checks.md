# Reuse Synthetic Checks Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Execute the approved synthetic-only scope without pausing between tasks.

**Goal:** Verify an isolated optimization environment and small information/unit/SOCP/power-flow interfaces using only hand-authored inputs.

**Architecture:** Preserve all frozen forecasting code, environments, splits and scientific protocols. Add opt-in engineering helpers and tests under a new integration package, a standalone command, a fixed environment record, and an outcome document. Publish from an isolated source snapshot on a separate branch; PR #114 is unchanged.

**Tech Stack:** Python 3.11, NumPy/Pandas/SciPy in a new venv; candidate pandapower 3.5.6 and CVXPY 1.9.3; CLARABEL; pytest. The candidate versions installed and imported successfully; no fallback or change to old environments was required.

## Scope

- User's “继续” authorizes the preceding next step: isolated environment and artificial-input checks, including toy optimization and hand-built two-bus power flow.
- No research data/API acquisition, sealed holdout, forecasting fit, HVAC identification, 33-bus scientific experiment, BOPTEST service, RL training or production dispatch.
- Runtime helpers accept only an explicitly synthetic schema. Their metadata validation cannot prove that a caller's timestamps are truthful.
- No automatic merge. Scientific CURRENT_STATUS/HANDOFF retain their existing execution role; document this separate engineering outcome without relabeling R11 results.

## Task 1: Isolated environment

- [x] Record the full installed-package metadata of the default and two frozen forecasting environments before work.
- [x] Create a new venv using the existing Python 3.11 executable, with no system-site-packages.
- [x] Resolve and install only binary wheels for the candidate dependencies and pytest/ruff; preserve exact package versions, sources and wheel hashes.
- [x] Run pip check and import/version/solver checks; report failures instead of treating resolution as a successful import.

## Task 2: Synthetic input contract

Files: code/src/evcf/integration/__init__.py, reuse_contracts.py; code/tests/test_reuse_contracts.py.

- [x] Write and run failing tests before implementation.
- [x] Validate a strict allowlisted input with schema_version=synthetic-dispatch/v1, issue_time_utc, step_seconds=900, one timestamped station_power observation in kW, and synthetic_forecast values shaped scenarios×horizon_steps (default 16, explicit positive integer override) with matching nonnegative unit-sum weights. All observed/generated availability timestamps must be at or before issue time; reject unknown keys, oracle fields, truth source kinds, bool/nonfinite numerics, malformed times, negative EV charging demand and wrong shapes/units. The default is a toy configuration, not a frozen scientific horizon.
- [x] Return immutable normalized records; make validation independent of mutable input dictionaries.
- [x] Add explicit kW→MW and interval-average kW→kWh helpers. Never infer power from A or Ah.
- [x] Verify known conversions: 1000 kW→1 MW; sixteen 4 kW quarter-hour intervals→16 kWh; include missing/zero distinctions and invalid-value cases.

## Task 3: Numerical probes

Files: code/src/evcf/integration/reuse_numerics.py; code/tests/test_reuse_numerics.py.

- [x] Write failing tests for the numerical-probe API before implementing it; run them in the new environment once installed.
- [x] Build a parameterized convex problem min t subject to norm(a,2)≤t, using cp.SOC. With a=(3,4), expected objective is 5; update a=(6,8), expected is 10. Check DCP/DPP, actual solver status, primal residuals and absolute errors.
- [x] Add t≤4 to the a=(3,4) case; require an infeasible result and no executable action. A nonoptimal or inaccurate status must not produce a valid action.
- [x] Create an artificial 0.4 kV two-bus feeder, a 0.1 km line with r=0.4 Ω/km, x=0.08 Ω/km, c=0, max_i=0.2 kA, and a 5 kW/1 kvar load. Use runpp(numba=False); verify convergence, positive losses, lower receiving voltage, and slack power=load+loss within tolerance. These ratings are synthetic, not inferred IEEE33 capacities.
- [x] Verify sign/unit behavior by repeating a modest load update; return only finite, JSON-safe aggregate evidence.

## Task 4: Runner and delivery

Files: scripts/check_reuse_synthetic.py; code/tests/test_check_reuse_synthetic_cli.py; requirements-reuse-smoke.lock.txt; docs/REUSE_SYNTHETIC_CHECKS_20261105.md; docs/evidence/reuse_synthetic_checks_20261105.json.

- [x] Provide a command requiring an explicit output path, with progress on stderr and aggregate JSON in the report. It accepts no dataset or model paths, does not contact services, never installs packages, and refuses to overwrite an existing result.
- [x] Test successful exit and failure propagation using a subprocess; run the actual command and preserve report/source hashes.
- [x] Run only new targeted tests, compile and lint checks; test a blocked-network launch if feasible. Do not launch legacy research tests or protocols.
- [x] Re-read original environment metadata and verify unchanged; compare the Git tree to ensure only allowed new engineering files differ.
- [x] Perform independent spec/code review and fix material findings. Independent review found no remaining substantive blockers.

Publication follows on a separate branch and PR. Exact commit, changed files, remote CI and no-merge status are recorded in the PR delivery record after publication; this plan is not an authority to merge.

## Acceptance

All claimed successes must have execution evidence. Package installation, tests, toy numerical feasibility and research effectiveness are separate claims. This task can pass engineering checks while A→kW semantics, dense probability forecasts, real HVAC execution and IEEE33 line ratings remain unresolved.
