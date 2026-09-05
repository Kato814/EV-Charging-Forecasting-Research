# Invalid-container accounting correction implementation plan

> **For agentic workers:** Use test-driven development with independent specification and code review. Follow the existing seasonal worktree and PR #23; do not create another branch or PR.

**Goal:** Retain metadata-verified structural sessions and independent current/pilot missingness, and reject known-incomplete station-current targets before any model run.

**Architecture:** Add a narrowly scoped branchwise cleaning primitive; enable the new target gate only in seasonal aggregation. Keep May defaults and frozen published artifacts unchanged. Rebuild seasonal artifacts from immutable local raw, preserve pre-correction snapshots, and publish de-identified before/after evidence with updated closed schemas and checksums.

**Tech stack:** Existing frozen Python 3.11 environment, pytest, NumPy, repository preparation and verification entry points. No installation, network acquisition, models, M4, or scheduling.

## 1. Verify review, baseline, and metadata

- [x] Read PR #23 review at HEAD `8c0eeeaff8367dba3c4790de79ba97a018022e0a` and Issue #22 comment `5550826691`.
- [x] Verify the existing isolated seasonal branch, unchanged original main, and preserve unrelated `data.zip`.
- [x] Copy old public/interim/processed artifacts into a new private baseline directory; record source/copy SHA256 and source commit. Verified 360 files, 481,942,047 bytes.
- [x] Verify all eight invalid-container records against official metadata: 8/8 exact metadata matches; February 2 and November 6 both-invalid; no metadata anomaly or invalid-container carry-in.
- [x] Run baseline `python -m pytest code/tests` from archived old source: 895 passed, 2 private-snapshot tests skipped, exit 0.

## 2. Branchwise cleaning (test first)

Files: new `code/src/evcf/data/acn_jpl_invalid_containers.py`, new `code/tests/test_acn_jpl_invalid_containers.py`; integrate in `code/src/evcf/data/acn_jpl_seasonal_prep.py`.

- [x] RED: valid current plus invalid pilot must retain current; invalid current plus valid pilot must retain pilot; both invalid must retain structure and duration; metadata mismatch must raise; original raw must remain equal and hash-identical.
- [x] GREEN: validate official structural metadata, create empty observations for only each invalid branch in an analysis copy, and preserve structural metadata. Never create zero-valued samples.
- [x] Retain all acquisition records in cleaned order; derive each sampling mode from its valid branch. Keep the separate approved November trajectory-quarantine path unchanged.
- [x] Verify accumulator, sensitivity, and power audit include every structurally retained session in their denominators. Metadata diagnostics now run before full time-series QA; an entry-point regression proves this order.

## 3. Target gate and causal state (test first)

Files: `code/src/evcf/data/acn_jpl_15min.py`, `code/src/evcf/data/acn_jpl_issue_snapshots.py`, seasonal snapshot loader and their tests.

- [x] RED: one observed plus one entirely unobserved current session gives two connected sessions and coverage 1/2; only unknown current cannot form an effective zero target; high concurrency with coverage at least 90 percent is still rejected; measured zero remains valid; pilot-only missing does not reject a current target.
- [x] GREEN: seasonal aggregation sets `known_incomplete_current` for every positive-duration bin overlap with a wholly unobserved current trajectory. Formal validity requires both the frozen coverage threshold and absence of this flag. Incomplete current means/peaks remain null; no optional diagnostic partial-sum column was added.
- [x] Verify history masks and all five future-label horizons consume corrected validity, without interpolation, rescaling, or final-energy reconstruction.
- [x] Verify M3 unknown current/pilot/cumulative/active-derived fields and masks preserve missingness. Offline anomaly reasons and final outcomes must not enter features; future perturbation tests pass. Independent common-formal-issue perturbation checks found no causal violation.
- [x] Default May behavior and anomaly-free numeric behavior remain unchanged. May replay on Python 3.11 passes 62 checks and 15 exact NPZ array comparisons; frozen files remain untouched. Runtime provenance and sub-tolerance floating-point differences are reported honestly.

## 4. Closed reporting and provenance

Files: seasonal preparation/reporting, frozen seasonal YAML protocol, CLI, tests, and a small de-identified correction package under `outputs/seasonal_prep_corrections/jpl_2019_invalid_containers/`.

- [x] RED: reject inconsistent acquisition/structure/current/pilot/invalid-placeholder/quarantine/metadata-anomaly counts and contradictory target-gate reports.
- [x] GREEN: acquisition counts stay 1289/1509/1354; structural retention is reported independently from each analysis branch. Invalid placeholders and time-reversal quarantine remain distinct.
- [x] Record prior capture commit, original artifact producer commit, prior and corrected snapshots, affected bins, valid90/target exclusions, formal counts, connected changes, and raw before/after digests in the closed reconciliation JSON.
- [x] Update the explicit publication allowlist and SHA manifests. The core release retains its 37 closed files; the additional correction JSON and its SHA manifest raise the combined delivery to 39 files (101,100 bytes). Verified old public bytes were recoverably moved to a separate private backup before atomically installing the new core release. Old/new artifacts are not mixed and code/config provenance is not spoofed.

## 5. Offline rebuild and independent validation

- [x] Freeze and record the tested implementation commit `6ded3bdd810a8115ea5b8a51091de71fab894a03`. Offline rebuilds use existing local raw and Python 3.11.16, with no ACN credentials supplied to child processes.
- [x] Recompute February and November cleaning, coverage, target flags, M1 masks, M2/M3 state, common horizons, power denominators, and processed/public snapshots. February valid90/formal: 2640/2439 to 2604/2388; November: 2769/2524 to 2762/2517. August remains 2954/2784. Counts were derived, not locked to prior results.
- [x] Run August numerical regression; replay May without overwriting its frozen public evidence. August: all nine arrays and their SHA256 values match exactly; all 59,520 prior station fields match. May: 15 arrays match exactly; public replay byte equality is 10/13, with remaining differences limited to runtime provenance and sub-tolerance power-summary floating-point values.
- [x] Independently recompute critical before/after counts, structural intervals, known-incomplete labels, and raw hashes: 464,817 checks and zero mismatches. Structural retention is 1289/1509/1354. Coverage denominators increase by 33,259/0/28,405 session-seconds. November remains CURRENT_PROXY_ONLY at unchanged thresholds; no kW-column authorization. All 48 local artifacts, 188 raw files, 84 official-metadata files, 360 preserved baseline files and 27 original May artifacts pass final SHA verification.

## 6. Release and stop

- [x] Run `python scripts/validate_library.py`: PASS.
- [x] Run `python -m pytest code/tests`: 1035 passed on Python 3.11.16; 398.86 seconds, exit 0. Supplemental evidence specification and code review: PASS; 44 targeted tests passed independently.
- [x] Run `python -m compileall -q code/src scripts code/tests`: exit 0.
- [x] Run `python -m ruff check code/src scripts code/tests`: all checks passed.
- [x] Run `git diff --check` and privacy/allowlist/hash validation: PASS for the exact 37-plus-2 aggregate-only release. No raw tables, local arrays, identifiers, credentials or private paths are published.
- [ ] Commit only task code, tests, protocol documentation, and de-identified summaries; push the existing branch, update PR #23 and Issue #22, and wait for final-head CI.
- [ ] Report corrected numbers and outstanding blockers; stop without merge, download, model execution, M4, or dispatch.

Remote delivery and final-head CI evidence will be recorded on the existing PR #23 and Issue #22 after the final push. The later main-documentation handoff comment does not authorize branch switching or pulling main during this task; the original main worktree and unrelated data.zip remain untouched.
