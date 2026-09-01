# JPL May 2019 Gate 1 Preparation Implementation Plan

> **Execution mode:** follow this plan in the existing isolated worktree with test-first, task-by-task review. Do not modify the original user `main` worktree.

**Goal:** Transform the frozen, ignored JPL May 2019 full-month `/ts` snapshot into deterministic cleaned local data, an evidence-bounded power-semantics audit, a 2,976-bin 15-minute station current trajectory, and leakage-safe M1-M4 issue-time samples, then publish only aggregate deidentified QA.

**Scope boundary:** CPU data preparation only. No acquisition, other months, model training, Gate 1 execution, optimization, GPU/driver/CUDA changes, raw mutation, or private/large Git artifacts.

**Architecture:** Use one offline pipeline and one cleaning implementation. The CLI validates the frozen raw snapshot, streams 1,645 sessions into an ignored compressed cleaned-session store, accumulates an exact one-second piecewise-constant station representation under bounded LOCF, creates 15-minute aggregates and issue-time/ragged indexes, runs privacy/leakage gates, compares raw inventory before/after, and atomically publishes a closed set of 13 aggregate artifacts. The power audit uses pinned ACN-Sim evidence plus `kWhDelivered` only in an offline audit path; online snapshots never receive final energy or future fields.

**Storage:** JSONL gzip for cleaned anonymous session records and local snapshot rows, CSV gzip for dense/ragged indexes, NPZ without object arrays for numerical matrices, JSON for local manifests. Parquet/Zarr are intentionally not introduced because no engine is declared. All local data stays under ignored `data/interim` and `data/processed`.

**Compatibility:** Python 3.10-compatible syntax and Python 3.11 CI. Existing dependencies only: NumPy, pandas, PyYAML, requests.

---

## Frozen decisions

- Raw scope: 31 local-day gzip chunks plus one carry-in gzip; 1,644 + 1 sessions.
- Analysis window: `[2019-05-01T00:00:00-07:00, 2019-06-01T00:00:00-07:00)`; internal UTC.
- Station scope: the complete JPL site, aggregating all mapped EVSE/space records.
- Global sampling mode: derive independently for current and pilot from positive timestamp differences. The production run must derive 4 seconds from this snapshot; it is not a hard-coded assumption.
- Main LOCF cap: `min(3 * current sampling mode, 60 seconds)`; production result therefore uses 12 seconds. Sensitivities use one mode (4 seconds), three modes (12 seconds), and 60 seconds.
- Main duplicate rule: retain the first exact timestamp-value pair; remove extra exact copies. A timestamp with distinct values is absent from the main series. The sensitivity series uses the last raw observation at that timestamp.
- Main active interval: `[connectionTime, disconnectTime)`. Sensitivity expands both boundaries by 60 seconds.
- Coverage: observed current session-seconds divided by connected session-seconds in a station bin; an empty-station bin has coverage 1.0. Missing current is never converted to zero or extrapolated beyond the cap.
- Fifteen-minute mean: observed station-current ampere-seconds divided by 900 seconds; the value is null when the main 90% coverage gate fails. Peak is the maximum reconstructed piecewise-constant current proxy inside the bin, not a sample average.
- Fifteen-minute connected/active counts: state at the right edge minus one second. Active-threshold sensitivities compare current `>0.1 A` and `>1.0 A`; `>0.1 A` is the main threshold because it retains low-current charging while excluding exact zero.
- Pilot fields: time-weighted station pilot sum and time-weighted mean across observed pilot-session-seconds. Pilot is a control/limit signal, never measured power.
- Issue times: every 15 minutes from analysis start + 24 hours through analysis end - 4 hours, inclusive. All five horizons must have labels for a formal row.
- Labels: target aggregate for each horizon is the future 15-minute bin ending at `issue_time + horizon`; features use only bins and observations ending no later than `issue_time`.
- Power publication: status can be `KW_RECONSTRUCTION_CANDIDATE`, `CURRENT_PROXY_ONLY`, or `POWER_SEMANTICS_FAIL`. Even a candidate does not authorize the reconstructed-kW data column; that column remains absent until main-control authorization.
- Candidate decision rule: 100% raw space mapping to the pinned network, primary audit coverage at least 90%, at least 90% of eligible sessions retained, median absolute percentage error at most 20%, P90 APE at most 40%, and absolute monthly aggregate energy error at most 10%. Otherwise use `CURRENT_PROXY_ONLY`, unless a severe contradiction triggers `POWER_SEMANTICS_FAIL` (mapping below 95%, non-finite audit statistics, or absolute monthly aggregate error above 50%). These are preparation decision thresholds, not scientific validation.

## Task 1: Deterministic inventory and common contracts

**Files:**
- Create `code/src/evcf/data/acn_jpl_preparation.py`
- Create `code/tests/test_acn_jpl_preparation.py`

**Red tests:**
- inventory digest canonicalizes relative paths with `/`, size, per-file SHA-256, sorted ordinal order, UTF-8 and final LF;
- raw snapshot expects 67 files, 32 manifests, 31 days, one carry-in, and 1,645 records;
- before/after snapshots compare exactly and fail closed;
- local/public atomic writers never target the raw root;
- public payload validation rejects private keys, identifier sentinels, tokens, host/user names, absolute paths, and unexpected files.

**Implementation:**
- Define constants for roots, analysis window, artifact allowlist, and schema versions.
- Implement streaming raw-record iteration in deterministic day/carry order.
- Validate gzip, manifest schema, manifest/data SHA, record count, remote total, and object total before processing.
- Implement canonical inventory and raw-root write guard.
- Reuse `parse_acn_datetime` and existing full-month manifest rules where possible.

## Task 2: Deterministic cleaning

**Files:**
- Create `code/src/evcf/data/acn_jpl_cleaning.py`
- Create `code/tests/test_acn_jpl_cleaning.py`

**Red tests:**
- timezone-aware UTC parsing plus LA mapping;
- exact duplicate removal and first occurrence retention;
- conflicting timestamp removal in main and last-write-wins sensitivity;
- `[connection, disconnect)` exclusion and `+/-60 s` sensitivity;
- bounded LOCF and long-gap non-coverage;
- time-weighted integral and coverage;
- raw-order linkage/digest remains available;
- user input records are sanitized and retain `modifiedAt` for later issue-time selection.

**Implementation:**
- Add immutable policy/result dataclasses.
- Derive positive-delta mode in a separate streaming pass.
- Store timestamps as integer UTC epoch seconds, values as finite floats, and retained raw ordinals.
- Store only conflict overrides for LWW rather than duplicating full arrays.
- Compute per-session current/pilot coverage, Ah, boundary distance distributions, and bounded integral contributions.
- Write ignored deterministic `cleaned_sessions.jsonl.gz` with anonymous session indexes and a local manifest/hash.

## Task 3: Power-semantics audit

**Files:**
- Create `code/src/evcf/data/acn_jpl_power_semantics.py`
- Create `code/tests/test_acn_jpl_power_semantics.py`

**Red tests:**
- fixed 208 V energy formula `Ah * 208 / 1000`;
- effective voltage is audit-only and absent from online outputs;
- final `kWhDelivered` cannot enter feature builders;
- space mapping must be complete for candidate status;
- primary/sensitivity threshold cohorts are deterministic;
- candidate/current-only/fail statuses follow closed rules.

**Implementation:**
- Record pinned repo, commit, source path/SHA, retrieval UTC time, BSD-3-Clause license evidence, default 208 V, line-to-line definitions, and topology caveat.
- Validate aggregate raw space mapping against the 52 names defined by the pinned source without publishing individual values.
- Audit quality-eligible sessions at 0.1/0.5/1.0 kWh and 0.8/0.9/0.95 coverage thresholds.
- Report Veff median/IQR/P05/P95; E208 MAE/MdAPE/P90 APE; monthly and weekday/weekend aggregate errors; aggregate-by-EVSE distribution summaries only.
- Mark static mirror `NOT_USED`.

## Task 4: Exact 15-minute current-proxy trajectory

**Files:**
- Create `code/src/evcf/data/acn_jpl_15min.py`
- Create `code/tests/test_acn_jpl_15min.py`

**Red tests:**
- exactly 2,976 left-closed/right-open LA bins;
- carry-in contributes to the first bin;
- disconnect boundary does not contribute;
- bounded holds are integrated by elapsed time, not sample mean;
- missing differs from zero and coverage gates 0.80/0.90/0.95 work;
- active thresholds 0.1/1.0 are compared;
- required schema, local calendar mapping, peak/ramp/missing-run summaries are deterministic.

**Implementation:**
- Build one-second difference arrays over the exact UTC window for connection state, observed current, current proxy, pilot, and both active thresholds.
- Convert difference arrays to second-level state, then aggregate exactly 900 seconds per bin.
- Generate the required local table with current proxy always preserved and no `kW` column unless separately authorized.
- Persist ignored CSV gzip/NPZ and snapshot hashes.

## Task 5: Leakage-safe issue-time snapshots

**Files:**
- Create `code/src/evcf/data/acn_jpl_issue_snapshots.py`
- Create `code/tests/test_acn_jpl_issue_snapshots.py`

**Red tests:**
- issue schedule excludes first 24 hours and final 4 hours;
- future current/pilot and future arrivals are invisible;
- `modifiedAt <= issue_time` selects the last known user input;
- true disconnect/done/final energy/private identifiers are absent;
- M1-M4 whitelists are nested only by explicit allowed fields;
- M4 ragged cutoff offsets never exceed issue time;
- snapshot order, shapes, horizon labels, and hashes repeat.

**Implementation:**
- M1 stores 24-hour station-current history and issue-known calendar values.
- M2 adds issue-time station/connection/active/pilot state.
- M3 writes anonymous ragged active-session summaries using only elapsed/current/recent/Ah/pilot and issue-known user request fields.
- M4 writes anonymous local trajectory cutoff indexes into the cleaned store; do not copy future trajectories.
- Persist ignored local tables/NPZ without object arrays and publish only aggregate counts/shapes/missingness.

## Task 6: Offline orchestrator and closed public release

**Files:**
- Create `scripts/prepare_jpl_gate1_data.py`
- Create `code/tests/test_prepare_jpl_gate1_data_cli.py`
- Modify `.gitignore`
- Modify `.github/workflows/library-check.yml`

**Red tests:**
- no token or network client is used;
- invalid raw/QA gate produces no data outputs;
- an existing incomplete run resumes safely while a complete release is deterministic;
- raw before/after hash mismatch blocks publication;
- exactly the 13 authorized public files are emitted and covered by `SHA256SUMS`;
- public release and stdout contain no private values or local paths;
- `TRAINING_ENVIRONMENT_FROZEN = NO` and no model results/weights exist.

**Implementation:**
- Add `--authorize-prepare`, explicit raw/interim/processed/public roots, and aggregate-only stdout.
- Stage each phase, write a local checkpoint after durable completion, and verify hashes before reuse.
- Atomically publish the 13-file closed aggregate release.
- Add only those 13 files to the `.gitignore` public allowlist.
- Change CI Ruff invocation to `python -m ruff check code/src scripts code/tests`.

## Task 7: Real snapshot execution and evidence review

**Commands:**

```powershell
python scripts/prepare_jpl_gate1_data.py --authorize-prepare --raw-root data/raw/acn/jpl/gate0/2019-05-full-ts --interim-root data/interim/acn/jpl/2019-05 --processed-root data/processed/acn/jpl/2019-05 --output-root outputs/acn_gate1_prep/jpl_2019-05
```

**Checks:**
- stop if any mandated stop condition occurs;
- independently recompute the raw inventory after processing;
- confirm 1,645 sessions, 2,976 bins, expected issue-time count, output hashes, privacy/leakage gate, and power decision;
- inspect all 13 public artifacts and local manifest schemas;
- keep reconstructed kW unavailable pending main-control authorization even if status is candidate.

## Task 8: Verification, commits, PR, and CI

**Commands:**

```powershell
python scripts/validate_library.py
python -m pytest code/tests
python -m compileall -q code/src scripts
python -m ruff check code/src scripts code/tests
git diff --check
```

**Git review:**
- confirm ignored raw/interim/processed and absence of IDs/arrays/paths/secrets in tracked diff;
- split commits by implementation concern where practical;
- push only `data/jpl-2019-05-clean-power-15min`;
- create/update PR with exact requested title, base `main`, no auto-merge;
- wait for CI and stop for main-control review.
