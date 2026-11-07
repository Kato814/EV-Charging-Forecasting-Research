# Synthetic Charging Loop Implementation Plan

> For agentic workers: use subagent-driven-development and test-driven-development. The user approved continuation of the small artificial charging loop. Proceed within that scope; do not merge. This is a provisional engineering design, not a scientific experiment protocol.

**Goal:** Connect the existing synthetic visible-information adapter to a simple charging rule, an independent artificial execution environment, and honest service evaluation.

**Architecture:** Policy receives only `ControllerInput`, a synchronous cumulative-energy snapshot and an explicitly assumed site/cluster power budget. The environment keeps actual arrivals/departures and evaluation targets private from policy, executes one interval transactionally and returns already-realized energy. A separate runner records decisions and evaluation. Existing files remain byte-for-byte unchanged.

**Tech Stack:** Python standard library; existing isolated Python 3.11.16 for tests. No installs, dataset paths, forecasting fits, optimization solver, HVAC service or distribution-network run. Parent PR #115 commit is `2bc213ed0ddc0f4dc09591671643192409f899f7`; main remains `ba9bbc894fd5b2dc3183ef1adb0aa3205578c85c`.

## Design and alternatives

Use a declared-departure-first greedy rule as a transparent baseline. A linear optimization scheduler could address resource allocation trade-offs later; a full distribution-network optimizer additionally requires network constraints and input evidence. This step verifies feedback and accounting before either extension. It makes no optimality, generic feasibility, battery-physics or cost-saving claim.

The example uses 900-second steps and a few hand-authored sessions; it does not freeze the thesis horizon or time step. Declared departures must lie on the control grid. Actual departures may lie inside a step. Commands are constant for the entire step; no within-step redistribution. Efficiency is explicitly 1, no battery taper, SOC, standby load or losses. Required energy belongs to evaluation only and must never cap environment delivery.

At issue: filter the event envelope using the existing adapter; ask the environment for cumulative energy only for visible session IDs; dispatch using those two structures; execute the action interval; repeat. Energy feedback is synchronous and complete at the interval boundary. Missing feedback cannot become zero; delayed energy feedback is outside this version. Delayed disconnect notifications are exercised. State age remains visible but is not a per-channel freshness guarantee or an inferred disconnect.

The existing `station_id == device_id` convention means the aggregate budget binds one explicit `(site_id, cluster_id)`, not each station_id separately. Cross-budget input is rejected.

## Shared types: `charging_types.py` (root)

Frozen records:

```python
ChargeAction(session_id: str, device_id: str, start_utc: datetime,
             end_utc: datetime, power_kw: float)
DeliveredEnergy(session_id: str, device_id: str, energy_kwh: float)
EnergySnapshot(as_of_utc: datetime, entries: tuple[DeliveredEnergy, ...])
```

`utc_datetime(value, label)` accepts only aware UTC datetime values; `step_end(issue, step_seconds)` requires a positive non-bool integer and catches date overflow. Constructors are containers, not admission gates; policy and environment validate boundary inputs. Time/energy metadata still cannot prove real-world provenance.

- [x] Write failing tests for frozen records, strict UTC, bool/nonpositive step and overflow; implement types/helpers and run green.

## Policy: `charging_policy.py` (worker A)

```python
dispatch_edf(view, feedback, *, site_id, cluster_id, device_limits_kw,
             capacity_kw, step_seconds=900) -> DispatchDecision
```

`DispatchDecision` is frozen with `issue_time_utc`, `actions: tuple[ChargeAction,...]`, `blocked: tuple[tuple[str,str],...]`, `remaining_kwh: tuple[tuple[str,float],...]`, `stale_sessions: tuple[str,...]`. Each action spans exactly `[issue, issue+step)` and has positive power. The policy has no environment/target/future-truth parameter.

Validate exact types, times, finite nonnegative capacity/energy/limits, IDs, duplicate feedback and binding to visible devices. Feedback time must equal issue; extra feedback IDs are rejected. Missing per-session feedback blocks that session with `UNKNOWN_DELIVERED_ENERGY`. Missing device limit, invalid declaration, unknown request semantics, expired/unaligned departure likewise block explicitly. Use existing `remaining_energy_kwh` for total/additional semantics; an additional declaration needs its delivered-energy baseline. No absent item is inferred as zero.

Order eligible sessions by `(declared departure, session_id)`. For each, allocate `min(device_limit, remaining_kwh/(step_seconds/3600), remaining aggregate capacity)`, then subtract allocated kW from the shared budget. A zero remainder makes no action. Recompute next issue from actual cumulative feedback. Stale session IDs are exposed, not silently removed based on age alone.

- [x] Write failing tests for deterministic 2/2 then 0/4 kW allocation, tie order, total/additional requests, missing/duplicate/stale/future feedback, mismatched identities/budget, unknown/expired/non-grid requests and invalid numbers.
- [x] Implement and run green, standard-library-only tests and Ruff. Do not edit old adapter/helper files.

## Environment: `charging_plant.py` (worker B)

```python
TruthSession(session_id, device_id, arrival_utc, departure_utc,
             required_energy_kwh, max_power_kw)
SyntheticPlant(sessions: tuple[TruthSession,...], *, start_utc, capacity_kw)
plant.feedback(session_ids: tuple[str,...], *, issue_time_utc) -> EnergySnapshot
plant.execute(actions: tuple[ChargeAction,...], *, issue_time_utc,
              step_seconds=900) -> StepResult
plant.evaluate() -> Evaluation
```

All truth/result records are frozen. `StepResult` fields: `start_utc`, `end_utc`, `commanded_kw`, `delivered_kwh`, `increments: tuple[DeliveredEnergy,...]`. `Evaluation` fields: `complete: bool`, `delivered_kwh`, `shortfall_kwh`, `overdelivery_kwh`, `sessions: tuple[SessionEvaluation,...]`; per-session fields: `session_id`, `departed`, `required_kwh`, `delivered_kwh`, `shortfall_kwh`, `overdelivery_kwh`. Pending sessions make `complete=false`; deficiencies are current values, not final failure proofs.

Start with zero cumulative energy and cursor=start; sessions may not arrive before start. Unique session IDs, no overlapping use of one device, positive stay duration, finite nonnegative targets/limits/capacity. Copy inputs into immutable/private state. Feedback reveals only requested existing, already-arrived session IDs and their realized cumulative energy, at the exact cursor; no target or actual departure.

Execute only at cursor. Validate the complete action batch before mutation: exact interval, known unique session/device, nonnegative finite power, per-device and aggregate limits, finite increments and cumulative totals. Rejected batches leave time and all energies unchanged. Actual delivery is `power_kw * seconds(intersection(action interval, true connected interval))/3600`. A departed device can receive a stale command but delivers zero. Do not clip to required target. Advance cursor once, including empty batches. Re-execution of an interval is rejected.

- [x] Write failing tests for partial connection, zero delivery after departure, target-independent delivery, feedback privacy, transactional rejection, duplicate steps, finite arithmetic and pending evaluations.
- [x] Implement and run green, standard-library-only tests and Ruff.

## Runner and evidence: root

Create `charging_loop.py`, `test_charging_loop.py`, `scripts/check_charging_loop.py`, `test_check_charging_loop_cli.py`.

`run_loop(envelope, plant, *, site_id, cluster_id, device_limits_kw, capacity_kw, steps, step_seconds=900)` repeatedly builds the visible view, obtains only visible energy feedback, dispatches and executes, returning immutable decisions, executions and final evaluation. It copies the envelope and only advances issue_time; it does not edit the source event archive or read evaluator results before decisions. A separate `run_acceptance(progress=None)` returns observed PASS/FAIL for L01–L08, continuing after a case fails.

| Case | Hand calculation / required outcome |
| --- | --- |
| L01 feasible | Group 4 kW, A 0.5 kWh due15min, B 1.5 due30min, each4kW: actions 2/2 then B4; delivered2, shortfall0. |
| L02 capacity shortfall | Group4, A/B each2kWh due30min: A4 both steps, B0; delivered2, shortfall2. |
| L03 rule counterexample | Group8, A2kWh/8kW/due30, B3kWh/4kW/due45: EDF B shortfall1; separately execute manual 4/4,4/4,0/4 and obtain shortfall0. This disproves equating rule deficit with infeasibility. |
| L04 delayed disconnect | Group/device6, declared3kWh due45, actual leave10, disconnect received30: commands6 at0 and15; actual energies1 and0; removed at30; shortfall2. |
| L05 unknown request | Unknown declaration basis: blocked, no action, delivered0; report unmet evaluation demand honestly. |
| L06 hidden truth | Mutating only evaluation target leaves all commands/delivery identical; future departure changes leave action prefix identical until physical feedback or received events diverge. |
| L07 invalid action | Group/device limit exceeded: reject atomically; energy and cursor unchanged; valid retry at same issue works exactly once. |
| L08 additional revision | Initial total2kWh; at15min add5 with baseline2; group/device8, due60: powers8,8,8,4; delivered7, shortfall0. |

- [x] Write failing integration tests for loop isolation and all eight cases, then implement.
- [x] Write failing CLI tests, then implement an explicit new-output-only command with finite JSON, source hashes, times, Python version, every case result, CPU/stdlib scope and nonzero failure exit. Block Python sockets in a test; verify `-S`, `-O`, no overwrite and injected failure reporting.
- [x] Run independent spec then quality reviews; fix substantive findings and preserve remaining limits in the dated outcome.
- [x] Run old + new PR engineering tests once after integration, new-file Ruff/syntax, and actual L01–L08 report; compare protected package metadata.

## Delivery

Add a dated Chinese outcome and two evidence JSON files under docs. Use a non-force append to existing PR #115; verify all 534 parent blobs and main's 505 blobs unchanged, exact remote bytes, changed-file allowlist and final-HEAD CI. Publication status belongs in PR body to avoid self-referential commit stamping. Do not change CURRENT_STATUS/HANDOFF or prior scientific/data protocols. Do not fix old scientific files merely to clear existing Ruff findings. No automatic merge.
