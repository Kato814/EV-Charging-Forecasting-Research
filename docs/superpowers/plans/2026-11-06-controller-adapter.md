# Synthetic Controller Adapter Implementation Plan

> For agentic workers: use subagent-driven-development and TDD. The user approved continuation of the adapter and the 15 artificial cases from PR #116. Execute this scope without another approval pause; publication remains an unmerged update to PR #115.

**Goal:** Build a small, opt-in controller-visible view and explicit unit/identity guards, exercised by C01–C15 with hand-authored inputs only.

**Architecture:** Add standard-library-only modules under `evcf.integration`; preserve existing forecasting and synthetic numerical code. Separate event eligibility/state from physical-unit and identity checks. The top-level input explicitly declares synthetic origin; no dataset/model paths, network access or live power admission. An independent evaluator may retain future truth, but the adapter input and output have no fields for it.

**Tech Stack:** Existing isolated Python 3.11.16 environment with pytest/ruff; no installation. Tests must also work without numerical libraries. Source base is PR #115 commit `56514745918ba5a73c5560bf5a6bdadd3a4d10a2`; scientific main remains `ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c`.

## Contract

Common helpers: `AdmissionError(code, message)`, strict UTC timestamps, finite nonnegative numbers excluding bool, exact dictionary keys and nonempty identifiers.

An artificial event has exactly `event_id, session_id, device_id, kind, event_time_utc, available_at_utc, availability_basis, evidence_id, revision, payload`. Kinds are connect/disconnect/current/pilot/request. Connect/disconnect payloads are empty; current/pilot payloads have value and unit=A; request payload has energy_kwh, request_basis, departure_time_utc, delivered_at_revision_kwh. An unavailable timestamp is null, never fabricated from event time. Revision is a nonnegative integer. Time and evidence labels validate caller declarations, not their truthfulness.

Visibility selects only records with event and availability times no later than issue. Future records do not influence visible values or diagnostic counts. Unknown availability of otherwise eligible past records fails closed. Recorded-reception mode rejects assumed replay metadata; replay mode remains explicitly labeled. Conflicting duplicate event/revision identities fail; latest eligible `(event_time, revision)` controls selection, not input order. State uses received connect/disconnect events, exposes optional current/pilot/declaration, and reports age relative to last visible event; it cannot know an unreceived disconnect. Requests before connect may be retained for that session; telemetry outside a known connected session is rejected. Session/device binding cannot change silently. All returned records are immutable.

Device mapping requires the exact site/cluster/station/space key, effective interval, availability time, a source evidence label, and a synthetic mapping kind. Ambiguous or missing mappings fail. Nominal-voltage conversion only returns an assumed-proxy record in the explicit simulation profile; actual measured-power admission is absent. Single line-to-line interface configuration accepts no phase-angle-as-PF or extra line multiplier. Current observations are never checked against a pilot's minimum nonzero command.

## Task 1: Common contract helpers (root)

Files: `controller_common.py`, `test_controller_common.py`.

- [x] Add failing tests for stable error codes, invalid/naive timestamps, bool/nonfinite values and unknown/missing keys.
- [x] Implement wrappers around existing strict synthetic-contract primitives; run the same tests to green.

```python
with pytest.raises(AdmissionError) as exc:
    number(True, "current")
assert exc.value.code == "INVALID_NUMBER"
```

## Task 2: Event visibility and state (independent worker)

Files: `controller_visibility.py`, `test_controller_visibility.py`.

- [x] Write failing tests, implement `build_visible_snapshot(events, issue_time_utc, availability_mode="recorded_reception", stale_after_seconds=900)` and immutable records.
- [x] Cover late records, unknown reception, replay labeling, deterministic revisions, duplicates/conflicts, delayed disconnect, state age, actual current below pilot minimum, absent observations, pre-connect requests, and immutable output.
- [x] Verify future changes cannot affect visible snapshots; unknown/oracle fields in eligible payloads fail.

## Task 3: Unit and identity guards (independent worker)

Files: `controller_quantities.py`, `test_controller_quantities.py`.

- [x] Write failing tests then implement `resolve_device_mapping`, `current_to_power_proxy`, `interval_current_means`, `energy_increment`, `remaining_energy_kwh`, `validate_interval_support`, and `require_same_power_boundary`.
- [x] Guard exact effective device keys; proxy-only conversion; finite quantities; fixed-window versus covered-time means; reset/epoch changes; total/additional/unknown energy request; dense contiguous future intervals; matching meter boundaries/components.
- [x] For 900 A*s with interval 900s and coverage 300s, preserve means 1A and 3A separately. For total request 10kWh and delivered 3kWh, return 7kWh; for additional 5kWh at baseline 2kWh and current delivered 3kWh, return 4kWh.

## Task 4: Integrated view and C01–C15 acceptance (root)

Files: `controller_adapter.py`, `controller_acceptance.py`, `test_controller_adapter.py`, `test_controller_acceptance.py`, `scripts/check_controller_adapter.py`, `test_check_controller_adapter_cli.py`.

- [x] Write failing tests for a strict synthetic envelope and immutable mapped sessions; wire visibility and identity guards without admitting evaluator truth.
- [x] Implement 15 individually identified deterministic cases using actual functions and independent expected outcomes. C07 changes future event values and evaluator-only outcomes while requiring identical controller output.
- [x] CLI accepts only an explicit new output path; emits stage progress and finite aggregate JSON, records versions/source hashes/time and every case's actual result, fails nonzero on any failed case, preserves existing reports.
- [x] Run success with Python socket calls blocked, test subprocess failure/report handling, syntax and Ruff, then old plus new integration tests without launching scientific protocols.

## Task 5: Review and delivery

- [x] Independent spec review followed by code-quality review; resolve substantive findings.
- [x] Record actual C01–C15 results and limits in a dated outcome/evidence file; no live reception/physical calibration/optimization-benefit claim.
- Delivery check: protected package metadata has been compared; publication must preserve every prior blob and update only PR #115 via a non-force commit. The exact final commit and blob comparison are recorded in the PR body.
- Delivery check: exact remote HEAD, file list, CI outcome and unmerged state are recorded in the PR body after publication, avoiding a self-referential commit stamp here. Do not fix the previously reproduced main Ruff findings by modifying frozen scientific code.

All research titles, resources, horizon and model choices remain provisional. PR #116 remains the historical design audit; this implementation outcome links it without editing its earlier not-run statements. Current scientific authority remains CURRENT_STATUS/HANDOFF; no datasets, sealed holdouts, acquisition services, forecasting fits, HVAC simulation or new scientific protocol are authorized by these helpers.
