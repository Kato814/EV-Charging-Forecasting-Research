# JPL Gate 1 Active-Session Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the frozen Issue #19 deterministic CPU pilot that measures the incremental forecasting value of M2, M3, and M4 over a common 2,853-sample JPL May 2019 snapshot.

**Architecture:** A fail-closed snapshot loader separates issue-time indexes from model features, then builds cumulative fixed-width M1-M4 matrices. A modeling layer selects the frozen Ridge/HGB grids on May 15-17 only and performs daily rolling-origin refits for May 18-31. An evaluation layer computes the frozen metrics, paired day-block bootstrap, and Gate classification before a closed publisher emits exactly 13 aggregate, deidentified files.

**Tech Stack:** Python 3.11, NumPy, pandas, SciPy, scikit-learn, joblib, PyArrow, PyYAML, pytest, Ruff; CPU only.

---

## Frozen implementation interpretations

- The authority order is Issue #19 body, its owner freeze comment, then this plan. Older broad research-roadmap material is out of scope.
- Use `data_snapshot_sha256=7066ffc8ba42a98f73246acfbc62352fe55a1433a43cba80957c6034e3aeaa5d`; verify every one of the nine local artifacts before feature encoding.
- Join all dense and ragged tables by `issue_time_utc_s`, never by dense row offset or the original 2,865-schedule `issue_index`.
- The canonical row universe is the ordered 2,853 timestamps in `labels.npz`; empty M3/M4 groups remain rows with fixed empty-pool semantics.
- M4 uses the same connected-session set as M3. The 22,427 active-only PR #18 M4 references are audited but are not the model cohort. Missing connected-session cutoffs are reconstructed from the verified cleaned store through a loader that returns only current/pilot series; retrospective outcomes and identifiers have no accepted return path.
- Model matrices never contain `issue_time_utc_s`, anonymous session indexes, raw issue indexes, trajectory references, final energy, real disconnect/done time, post-issue current/pilot, or post-issue user-input revisions.
- M4 window statistics use bounded left-continuous hold with a 12-second cap on `[issue-window, issue)`. Current mean/std/nonzero use covered current seconds; current observed ratio uses full window seconds; pilot-current gap uses joint coverage; slope is A/min between the first and last visible current observations and is missing with fewer than two distinct timestamps.
- M1/M2/M3/M4 raw dimensions are 195/201/311/671. Fixed missing indicators are added only for nullable features without an existing explicit mask, yielding Ridge/HGB input dimensions 195/204/391/1003.
- Ridge uses `solver=cholesky`, training-only medians, fixed missing indicators, and training-only standardization. HGB retains NaN and appends the same indicators without imputation or scaling.
- Validation ties select the first candidate in declared grid order. Test predictions are not clipped, calibrated, or used for retuning.
- Test-day fit rows must satisfy both `issue_time < day_start` and `issue_time + horizon <= day_start`. Models refit once at local midnight, using fixed selected parameters.
- Persistence definitions: most recent completed observed bin; prior local-day target-clock bin; prior local-week target-clock bin. Missing references are unavailable and are never silently replaced.
- Bootstrap delta is parent absolute error minus child absolute error, so positive favors the child. Reuse one 10,000 x 14 PCG64(20260902) local-day index matrix for all comparisons.
- M3 and M4 Gate thresholds are exactly those in Issue #19. The issue supplies no numeric M2 threshold; for the classification label only, literal “M2 improves” means the unrounded mean HGB MAE over 15/30/60 minutes is lower for M2 than M1. This is a diagnostic zero-crossing, not a new Gate threshold.
- No model binaries are persisted. Full issue-time predictions remain only in ignored local output.

## Task 1: Freeze configuration and Python 3.11 dependency surface

**Files:**
- Create: `code/configs/acn_jpl_gate1_pilot_2019-05.yaml`
- Create: `code/src/evcf/forecasting/acn_jpl_gate1_contracts.py`
- Create: `environment-gate1-pilot.yml`
- Modify: `pyproject.toml`
- Modify: `.github/workflows/library-check.yml`
- Test: `code/tests/test_acn_jpl_gate1_contracts.py`

- [x] **Step 1: Write failing contract tests**

```python
def test_frozen_gate1_grid_and_seeds(load_gate1_config):
    cfg = load_gate1_config()
    assert cfg["seeds"] == {"model": 20260901, "bootstrap": 20260902}
    assert cfg["bootstrap_repetitions"] == 10000
    assert cfg["ridge"]["alpha"] == [0.1, 1.0, 10.0, 100.0]
    assert len(cfg["hgb_grid"]) == 16
    assert cfg["windows_minutes"] == [5, 15, 30, 60]
```

- [x] **Step 2: Run the contract test and confirm it fails because the config loader is absent**

Run: `E:\Anaconda\envs\evcf-gate1-pilot\python.exe -m pytest code/tests/test_acn_jpl_gate1_contracts.py -q`

- [x] **Step 3: Add the exact frozen YAML, its strict loader/grid expander, a path-free pinned environment YAML, a `gate1` optional dependency group, and CI installation of `.[dev,gate1]`**

The Gate 1 group contains SciPy, scikit-learn, joblib, and PyArrow without adding PyTorch. The environment YAML pins the versions used by the formal run and omits `prefix`.

- [x] **Step 4: Run the contract test and Ruff, then commit**

Commit: `chore: freeze Gate 1 pilot protocol and environment`

## Task 2: Fail-closed prepared-snapshot loader

**Files:**
- Create: `code/src/evcf/forecasting/acn_jpl_gate1_data.py`
- Create: `code/tests/test_acn_jpl_gate1_data.py`

- [x] **Step 1: Write failing tests for the complete snapshot gate**

```python
def test_snapshot_gate_requires_exact_hashes_and_common_issue_times(snapshot_fixture):
    snapshot = verify_and_load_snapshot(snapshot_fixture)
    assert snapshot.data_snapshot_sha256 == EXPECTED_DATA_SNAPSHOT_SHA256
    assert snapshot.issue_times.shape == (2853,)
    assert snapshot.horizons.tolist() == [15, 30, 60, 120, 240]
    assert snapshot.labels.shape == (2853, 5)
    assert snapshot.feature_index_names == ("issue_time_utc_s",)
```

Also fail on any size/SHA mismatch, extra/missing artifact, unsorted or unequal dense issue time, ragged time outside the canonical universe, duplicate `(issue_time, session_index)`, post-issue user input, invalid M4 cutoff, or forbidden field entering the causal session object.

- [x] **Step 2: Run tests and verify the missing loader failure**

- [x] **Step 3: Implement immutable `Gate1Snapshot`, `CausalSessionSeries`, `verify_and_load_snapshot`, and `group_by_canonical_issue_time`**

Use explicit artifact-name-to-root mapping for seven processed and two interim files. The causal cleaned-store reader returns only session index and current/pilot timestamp/value arrays.

- [x] **Step 4: Verify focused tests pass and commit**

Commit: `feat: add fail-closed Gate 1 snapshot loader`

## Task 3: Fixed M1-M4 encoders

**Files:**
- Create: `code/src/evcf/forecasting/acn_jpl_gate1_features.py`
- Create: `code/tests/test_acn_jpl_gate1_features.py`

- [x] **Step 1: Write failing pooling and feature-name tests**

```python
def test_fixed_pool_order_and_empty_semantics():
    assert fixed_pool([1.0, None, 3.0], total_count=3).tolist() == [
        2.0, 4.0, 2.0, 1.0, 1.0, 3.0, 1.5, 2.0, 2.5, 1.0
    ]

def test_issue_time_and_structural_keys_never_enter_features(encoded_fixture):
    forbidden = {"issue_time_utc_s", "issue_index", "anonymous_session_index"}
    assert forbidden.isdisjoint(encoded_fixture.all_feature_names)
```

Add red tests for M1 history mask preservation, M2 calendar merge, M3 11 x 10 pooling, all 2,853 rows including empty groups, exact cumulative feature nesting, and dimensions 195/201/311.

- [x] **Step 2: Run tests and verify expected failures**

- [x] **Step 3: Implement M1, M2, and M3 encoders with declared feature order and formulas**

Return `FeatureBlock(issue_times, values, feature_names, nullable_mask)` and reject any issue-time mismatch.

- [x] **Step 4: Write failing causal M4 tests**

Poison all current/pilot values after issue time and assert unchanged output; test 5/15/30/60-minute boundaries, 12-second hold, joint gap coverage, single-point slope, inactive connected sessions, and exact 671 raw dimensions.

- [x] **Step 5: Implement causal trajectory summaries and M4 pooling over the M3 connected set**

Audit active-only stored references against reconstructed prefixes. Fail if a connected session cannot be found or if any returned timestamp exceeds issue time.

- [x] **Step 6: Generate a machine-readable encoding manifest, run focused tests, and commit**

Commit: `feat: add fixed M1-M4 Gate 1 encoders`

## Task 4: Frozen model selection and rolling-origin predictions

**Files:**
- Create: `code/src/evcf/forecasting/acn_jpl_gate1_models.py`
- Create: `code/tests/test_acn_jpl_gate1_models.py`

- [x] **Step 1: Write failing split and availability tests**

```python
def test_rolling_fit_rows_are_available_before_test_day(split_fixture):
    for horizon in (15, 30, 60, 120, 240):
        for day, rows in split_fixture.rolling_fit_rows(horizon).items():
            assert np.all(split_fixture.issue_times[rows] + horizon * 60 <= day)
```

Require 1,248 train, 276 validation, 1,329 test, exactly 14 test days, no overlap, and identical per-horizon tier rows.

- [x] **Step 2: Run tests and verify failures**

- [x] **Step 3: Implement fixed preprocessing**

`RidgePreprocessor.fit` computes medians and scaler statistics only from the supplied fit rows and fails on an all-NaN nullable column. `HGBPreprocessor` preserves NaN and appends the same predeclared indicators.

- [x] **Step 4: Write failing selection/rolling tests**

Test 4 Ridge and 16 HGB candidates per tier/horizon, validation-MAE selection, grid-order tie breaking, constant selected-parameter hash throughout testing, no current-day fit rows, and deterministic predictions.

- [x] **Step 5: Implement persistence baselines, grid selection, and daily refitting**

Fit one fixed-parameter model per local test day, tier, learner, and horizon. Persist predictions locally with issue time as an index column, never as a model feature.

- [x] **Step 6: Run focused tests and commit**

Commit: `feat: add rolling-origin Gate 1 baselines`

## Task 5: Metrics, paired bootstrap, and Gate rules

**Files:**
- Create: `code/src/evcf/evaluation/acn_jpl_gate1_metrics.py`
- Create: `code/tests/test_acn_jpl_gate1_metrics.py`

- [x] **Step 1: Write failing exact-metric tests**

Cover MAE/RMSE/WAPE including zero WAPE denominator, nominal 0.208 linear conversion, earliest peak tie, target-bin time, no cross-day/gap ramp, daily/weekday/weekend grouping, and unavailable persistence counts.

- [x] **Step 2: Implement deterministic aggregate and daily metrics**

Peak amplitude is daily `abs(max(pred)-max(actual))`; peak time error is absolute minutes between earliest argmax target-bin starts. Ramp errors use only adjacent 15-minute issue rows inside one local day.

- [x] **Step 3: Write failing bootstrap and Gate truth-table tests**

Test exactly 10,000 resamples, PCG64 seed, shared block matrix, percentile endpoints, positive-delta direction, CI lower equal to zero, 3%/1%/-2% boundaries, 9/14 and 10/14 wins, four scientific classes, and `EXECUTION_FAIL` precedence.

- [x] **Step 4: Implement bootstrap and automatic classification**

M3 day wins use the equal-weight mean of daily 15/30/60-minute MAE deltas. M2's classification-only diagnostic is the unrounded equal-weight mean near-horizon HGB MAE improvement.

- [x] **Step 5: Run focused tests and commit**

Commit: `test: cover time split leakage metrics and gate rules`

## Task 6: Offline orchestrator and closed public release

**Files:**
- Create: `code/src/evcf/forecasting/acn_jpl_gate1_pilot.py`
- Create: `scripts/run_jpl_gate1_pilot.py`
- Create: `code/tests/test_acn_jpl_gate1_pilot.py`
- Create: `code/tests/test_run_jpl_gate1_pilot_cli.py`
- Modify: `.gitignore`

- [x] **Step 1: Write failing CLI, privacy, and publication tests**

Require explicit `--authorize-run`, the formal Python 3.11 environment, CPU execution, clean data gate, no network client, deterministic local run id, no model serialization, exact 13-file public allowlist, SHA coverage, aggregate-only outputs, and rejection of identifiers, credentials, absolute paths, predictions, arrays, or model extensions.

- [x] **Step 2: Implement checkpointed orchestration and local-only artifacts**

Write encoded matrices under `data/processed/acn/jpl/2019-05/gate1_pilot/` and complete predictions under ignored `outputs/runs/jpl-2019-05-gate1-pilot-seed20260901/`. Do not persist fitted estimators.

- [x] **Step 3: Implement the exact public release**

Emit only `gate1_summary.json`, `gate1_decision.md`, `metrics_by_horizon.csv`, `tier_comparison.csv`, `daily_paired_errors.csv`, `bootstrap_intervals.json`, `peak_ramp_metrics.json`, `model_selection_manifest.json`, `feature_encoding_manifest.json`, `environment_manifest.json`, `run_manifest.json`, `data_snapshot_manifest.json`, and `SHA256SUMS`.

- [x] **Step 4: Verify focused tests and commit**

Commit: `feat: orchestrate the JPL Gate 1 pilot`

## Task 7: Formal frozen run and independent result audit

**Commands:**

```powershell
E:\Anaconda\envs\evcf-gate1-pilot\python.exe scripts/run_jpl_gate1_pilot.py --authorize-run --config code/configs/acn_jpl_gate1_pilot_2019-05.yaml --processed-root data/processed/acn/jpl/2019-05 --interim-root data/interim/acn/jpl/2019-05 --local-run-root outputs/runs/jpl-2019-05-gate1-pilot-seed20260901 --public-root outputs/gate1_pilot/jpl_2019-05
```

- [x] **Step 1: Commit all code/config/tests before running and record that commit as the execution commit**
- [x] **Step 2: Re-run the data gate and record config/data/environment hashes**
- [x] **Step 3: Run the full fixed grid and rolling test without test-time retuning**
- [x] **Step 4: Independently recompute key MAEs, comparisons, bootstrap direction, day wins, and Gate classification from ignored local predictions**
- [x] **Step 5: Run the identical command a second time and require identical aggregate/public hashes**
- [ ] **Step 6: Commit the 13 aggregate result files**

Commit: `data: add deidentified Gate 1 pilot results`

## Task 8: Verification, PR, and stop

- [ ] **Step 1: Run all required checks in the formal environment**

```powershell
E:\Anaconda\envs\evcf-gate1-pilot\python.exe scripts/validate_library.py
E:\Anaconda\envs\evcf-gate1-pilot\python.exe -m pytest code/tests
E:\Anaconda\envs\evcf-gate1-pilot\python.exe -m compileall -q code/src scripts
E:\Anaconda\envs\evcf-gate1-pilot\python.exe -m ruff check code/src scripts code/tests
git diff --check
```

- [ ] **Step 2: Audit tracked paths, public privacy, file sizes, SHA256SUMS, ignored predictions/data/models, original worktree state, and branch**
- [ ] **Step 3: Push only `experiments/gate1-active-session-pilot` and create the requested PR against `main`**
- [ ] **Step 4: Wait for Python 3.11 CI; do not merge**
- [ ] **Step 5: Report the exact frozen final classification and stop without seasonal acquisition, probability models, GPU work, or scheduling**
