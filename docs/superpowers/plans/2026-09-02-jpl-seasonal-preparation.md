# JPL 2019 Seasonal Preparation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Acquire and prepare the official ACN JPL local-calendar months 2019-02, 2019-08, and 2019-11 through the frozen May cleaning and M1-M3 contracts, without training any model or publishing private data.

**Architecture:** Add a month configuration and seasonal controller around the reviewed ACN client and deterministic preparation primitives. Preserve every May entry point and byte-level scientific contract as a compatibility wrapper, while the seasonal path derives local-month counts from the complete historical metadata, requires one matching official `_meta.total` probe before `/ts`, supports zero or multiple carry-in sessions, and publishes an exact aggregate-only allowlist. Store raw/interim/processed material only under ignored roots; commit code, tests, configuration, and 37 closed public files.

**Tech Stack:** Python 3.11, NumPy, pandas, SciPy, scikit-learn feature encoders, PyYAML, pytest, Ruff, ACN official REST API, gzip JSONL, SHA-256.

---

## Frozen decisions and invariants

- Months run only in this order: `2019-02`, `2019-08`, `2019-11`.
- Time zone is `America/Los_Angeles`; all month intervals are local half-open intervals.
- November keeps the continuous physical UTC grid across the 2019-11-03 fall-back hour: 2,884 bins and 2,773 scheduled issue times. Repeated local wall-clock quarters remain distinct through UTC timestamp and offset; no fold is deleted or collapsed.
- February has 2,688 bins and 2,577 scheduled issue times; August has 2,976 bins and 2,865 scheduled issue times.
- Seasonal output contains M1, M2, and M3 only. No M4 tier, row, feature, file, manifest entry, or hash may exist. The only permitted public references are the negative audit `m4_generated=false` and the final human-readable statement `M4 generated: NO`.
- Raw and processed data remain ignored. No session, user, station, space, object identifier, trajectory, prediction, model, credential, or local absolute path is public.
- Severe 208 V evidence contradictions set seasonal `power_semantics_status=CURRENT_PROXY_ONLY` and `e208_authorized=false`; the current-proxy M1-M3 pipeline continues. A passing evidence rule may report `KW_RECONSTRUCTION_CANDIDATE`, but the local execution pipeline still records `e208_authorized=false`: candidate status is not research authorization. The legacy May wrapper keeps its existing stop behavior and artifacts.
- May regression remains: local sessions 1,644; UTC sessions 1,645; carry-in 1; bins 2,976; scheduled/formal issue times 2,865/2,853; raw inventory and published hashes unchanged.

### Closed monthly QA schema

- Acquisition: local/UTC/left/right/carry counts, official total and exactly-one-request proof, daily/carry chunk totals, manifest/SHA/JSON status, daily and combined unique counts, metadata-`/ts` match/missing/orphan counts, partial-file count, and raw inventory before/after hashes.
- Cleaning: raw/usable/retained samples and rate for current and pilot; exact duplicates; conflicting timestamps; invalid containers; nonmonotonic timestamps; boundary-positive points/sessions; boundary current integral and share; primary-versus-last-write and ±60 s sensitivity; actual sampling modes; derived bounded holds; bounded observed coverage; retrospective doneChargingTime status; and userInputs truncation status.
- Power: pinned repository/commit/208 V formula, mapping coverage, eligible/retained counts and rate for the fixed `kWhDelivered >= 0.5 kWh` and current-coverage `>= 0.90` cohort, median effective voltage, Q1/Q3/IQR, 208 V MdAPE, P90 APE, monthly aggregate energy error, finite-statistics status, `power_semantics_status`, and `e208_authorized`.
- Station 15-minute data: total bins; every frozen May field (`station_current_mean_a`, `station_current_peak_a`, `connected_session_count`, `active_charging_session_count`, `pilot_sum_a`, `pilot_mean_a`, `arrival_count`, `disconnect_count`, `observed_coverage_ratio`, `valid_bin_80`, `valid_bin_90`, `valid_bin_95`); valid counts/rates and missing rate at each threshold; longest missing run; peak and ramp summaries; weekday/weekend summaries; physical-grid/DST evidence; and time-weighted-integral status.
- Snapshots/features: scheduled and formal issue counts; valid labels by each 15/30/60/120/240 min horizon; M1/M2/M3 samples; raw and encoded shapes; missing rates; feature/index whitelist and blacklist status; future-field, temporal, and private-identifier violation counts; userInputs truncation status; snapshot SHA; and an explicit `m4_generated=false`.

Every public JSON is validated against a closed schema: required keys must all be present, unexpected/private keys are rejected, rates are finite or explicitly null only when their denominator is zero, and no per-session values are permitted. The root CSV has a frozen column list covering every month-level decision/count/rate/hash used in the report; the Markdown has fixed Acquisition, Cleaning, Power, 15-minute, M1-M3, Security, and Decision sections. Cross-file tests require every duplicated value in JSON, CSV, and Markdown to agree.

### Frozen top-level decision matrix

- `PASS`: all three months complete every acquisition, integrity, cleaning, valid-bin, leakage, privacy, snapshot, local-test, and final-head CI gate, and every month independently reaches `KW_RECONSTRUCTION_CANDIDATE`. This does not set `e208_authorized=true`; formal authorization remains a main-controller decision.
- `CONDITIONAL_PASS`: all three months pass every data/security/test/CI gate and are ready for current-proxy M1-M3 replication, but at least one month is conservatively downgraded to `CURRENT_PROXY_ONLY`; nominal 208 V kW reporting is not authorized for that month.
- `FAIL`: any target month is incomplete or fails a required data/security/test/CI gate. A previously completed month remains preserved, but the three-month package is not declared ready.

## Task 1: Month configuration and complete-metadata scope

**Files:**
- Create: `code/src/evcf/data/acn_jpl_month_config.py`
- Create: `code/tests/test_acn_jpl_month_config.py`
- Modify: `code/src/evcf/data/acn_jpl_official_reference.py`
- Modify: `code/tests/test_acn_jpl_official_reference.py`

- [ ] **Step 1: Write failing month-boundary and DST tests**

```python
def test_seasonal_month_contracts_use_physical_utc_bins() -> None:
    feb, aug, nov = (jpl_month_config(m) for m in SEASONAL_MONTHS)
    assert (feb.day_count, feb.expected_bins, feb.expected_scheduled_issue_times) == (28, 2688, 2577)
    assert (aug.day_count, aug.expected_bins, aug.expected_scheduled_issue_times) == (31, 2976, 2865)
    assert (nov.day_count, nov.expected_bins, nov.expected_scheduled_issue_times) == (30, 2884, 2773)
    assert nov.local_start.utcoffset() == timedelta(hours=-7)
    assert nov.local_end.utcoffset() == timedelta(hours=-8)

def test_complete_metadata_scope_distinguishes_local_and_utc_months() -> None:
    scope = summarize_complete_metadata(records, jpl_month_config("2019-08"))
    assert scope.utc_month_session_count == 1511
    assert scope.left_boundary_count == 2
    assert scope.right_boundary_count == 0
    assert scope.local_month_session_count == 1509
    assert scope.carry_in_session_count == 0
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `E:\Anaconda\envs\evcf-gate1-pilot\python.exe -m pytest code/tests/test_acn_jpl_month_config.py code/tests/test_acn_jpl_official_reference.py -q`

Expected: imports or generic month arguments fail because the month contract does not exist yet.

- [ ] **Step 3: Implement immutable month and metadata-scope contracts**

```python
SEASONAL_MONTHS = ("2019-02", "2019-08", "2019-11")

@dataclass(frozen=True)
class JPLMonthConfig:
    month: str
    timezone_name: str
    local_start: datetime
    local_end: datetime
    utc_start: datetime
    utc_end: datetime
    day_count: int
    day_windows: Sequence[tuple[datetime, datetime]]
    expected_bins: int
    expected_scheduled_issue_times: int
    grid_policy: str = "continuous_physical_utc"
    tiers: Sequence[str] = ("M1", "M2", "M3")

@dataclass(frozen=True)
class CompleteMetadataScope:
    local_month_records: Sequence[Mapping[str, Any]]
    carry_in_records: Sequence[Mapping[str, Any]]
    local_month_session_count: int
    utc_month_session_count: int
    left_boundary_count: int
    right_boundary_count: int
    carry_in_session_count: int
    inventory_sha256: str
```

`jpl_month_config()` must derive offsets with `ZoneInfo`, derive bin counts from UTC duration, enforce the approved 2,884-bin November contract, and reject months outside the fixed allowlist in the seasonal controller. `summarize_complete_metadata()` is the pure classifier; the production loader separately validates the frozen 42-file/33,638-record metadata inventory and seals the resulting scope to the canonical month config, source digest, record digest, selected records, and counts. Only `scope.is_verified_for(config)` may cross the production acquisition gate; a synthetic, replaced, or wrong-month scope must fail. Local-month membership is exactly `local_start <= connectionTime < local_end`; UTC-month diagnostics use the corresponding UTC calendar-month bounds; left/right differences are the two set differences; carry-in is exactly `connectionTime < local_start < disconnectTime`. The function returns private record tuples only to ignored local code.

- [ ] **Step 4: Generalize the official local-month total probe**

```python
@dataclass(frozen=True)
class OfficialLocalMonthTotalResult:
    total: int
    reference_path: Path
    month: str
    local_start_inclusive: str
    local_end_exclusive: str
    request_count: int

def probe_official_local_month_total(
    client: ACNClient,
    destination: str | Path,
    *,
    month: JPLMonthConfig = MAY_2019,
) -> OfficialLocalMonthTotalResult:
    query = ACNQuery(
        site="jpl",
        start=month.local_start,
        end=month.local_end,
        timeseries=False,
    )
    total = client.fetch_total_once(query)
    reference_path = Path(destination)
    payload = {
        "schema_version": "acn-jpl-official-local-month-total/v1",
        "source": "ACN-Data official REST API",
        "endpoint": query.endpoint,
        "site": "jpl",
        "timezone": month.timezone_name,
        "interval_semantics": "[start,end)",
        "local_start_inclusive": month.local_start.isoformat(),
        "local_end_exclusive": month.local_end.isoformat(),
        "utc_start_inclusive": month.utc_start.isoformat(),
        "utc_end_exclusive": month.utc_end.isoformat(),
        "query_condition": query.condition,
        "official_meta_total": total,
        "request_count": 1,
        "response_fields_consumed": ["_meta.total"],
        "token_stored": False,
    }
    _atomic_write_reference(reference_path, payload)
    return OfficialLocalMonthTotalResult(
        total=total,
        reference_path=reference_path,
        month=month.month,
        local_start_inclusive=month.local_start.isoformat(),
        local_end_exclusive=month.local_end.isoformat(),
        request_count=1,
    )
```

The existing positional `destination` argument and May default must remain compatible. The probe may consume only `_meta.total`, and the existing atomic writer may persist only the secret-free aggregate reference—not the response body or token. Trust is deliberately split: the strict offline loader may prove only that a saved reference has the exact closed schema/hash for a month; it cannot create live provenance. Only a successful current-process `fetch_total_once` followed by atomic reference validation may set the live-probe seal. Acquisition requires `result.is_live_verified_for(config)` (the compatibility alias `is_verified_for` has the same live meaning); synthetic JSON, a reloaded old reference, a replaced result, another interval, or any request count other than one is invalid.

- [ ] **Step 5: Run focused and May regression tests**

Run: `E:\Anaconda\envs\evcf-gate1-pilot\python.exe -m pytest code/tests/test_acn_jpl_month_config.py code/tests/test_acn_jpl_official_reference.py code/tests/test_acn_jpl_metadata_qa.py -q`

Expected: PASS, including May 1,644/1,645/1 and November 2,884.

- [ ] **Step 6: Commit**

```text
refactor: add generic JPL local-month contracts
```

## Task 2: Fail-closed seasonal acquisition and full-month QA

**Files:**
- Create: `code/src/evcf/data/acn_jpl_seasonal_acquisition.py`
- Create: `code/tests/test_acn_jpl_seasonal_acquisition.py`
- Create: `scripts/acquire_jpl_seasonal.py`
- Create: `code/tests/test_acquire_jpl_seasonal_cli.py`
- Modify: `code/src/evcf/data/acn_jpl_full_month_ts.py`
- Modify: `code/src/evcf/data/acn_jpl_full_month_qa.py`

- [ ] **Step 1: Write failing gate, carry-in, resume, and month-isolation tests**

```python
def test_official_total_mismatch_prevents_ts_client_and_files(tmp_path: Path) -> None:
    month_root = tmp_path / "2019-02"
    probe = RecordedOfficialProbe(result=official_result(feb, total=1287, request_count=1))
    ts_factory = ForbiddenTSClientFactory()
    result = acquire_jpl_month(config=feb, scope=scope_1288, official_probe=probe,
                               raw_root=month_root, ts_client_factory=ts_factory)
    assert result.status == "METADATA_GATE_FAIL"
    assert probe.call_count == 1
    assert ts_factory.call_count == 0
    assert not (month_root / "timeseries").exists()
    assert not (month_root / "manifests" / "timeseries").exists()

@pytest.mark.parametrize("carry_count", [0, 1, 2])
def test_carry_in_zero_one_many_uses_private_ordinal_chunks(carry_count: int, tmp_path: Path) -> None:
    scope = scope_with_carry(carry_count)
    probe = RecordedOfficialProbe(result=official_result(
        month, total=scope.local_month_session_count, request_count=1,
    ))
    result = acquire_jpl_month(config=month, scope=scope, official_probe=probe,
                               raw_root=tmp_path / month.month,
                               ts_client_factory=FakeTSClientFactory(scope))
    assert result.carry_in_completed == carry_count
    assert all("session" not in path.name.lower() for path in result.carry_paths)

def test_completed_month_is_not_redownloaded_when_later_month_fails(tmp_path: Path) -> None:
    before = inventory(tmp_path / "2019-02")
    run_seasonal_acquisition(months=(feb, aug), runners={feb.month: skip, aug.month: fail})
    assert inventory(tmp_path / "2019-02") == before
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `E:\Anaconda\envs\evcf-gate1-pilot\python.exe -m pytest code/tests/test_acn_jpl_seasonal_acquisition.py code/tests/test_acquire_jpl_seasonal_cli.py -q`

Expected: seasonal acquisition symbols are absent.

- [ ] **Step 3: Implement the generic acquisition controller**

```python
@dataclass(frozen=True)
class MonthAcquisitionResult:
    month: str
    status: str
    local_session_count: int
    official_total: int
    carry_in_count: int
    valid_daily_chunks: int
    failed_chunks: Sequence[str]
    raw_inventory_sha256: str | None

def acquire_jpl_month(*, config: JPLMonthConfig, scope: CompleteMetadataScope,
                      official_probe: Callable[[JPLMonthConfig], OfficialLocalMonthTotalResult],
                      raw_root: Path,
                      ts_client_factory: Callable[[], ACNClient]) -> MonthAcquisitionResult:
    official = official_probe(config)
    gate_is_exact = (
        scope.is_verified_for(config)
        and official.is_live_verified_for(config)
        and official.total == scope.local_month_session_count
    )
    if not gate_is_exact:
        return MonthAcquisitionResult(
            month=config.month,
            status="METADATA_GATE_FAIL",
            local_session_count=scope.local_month_session_count,
            official_total=official.total,
            carry_in_count=scope.carry_in_session_count,
            valid_daily_chunks=0,
            failed_chunks=(),
            raw_inventory_sha256=None,
        )
    # Only after this equality gate: create the /ts client and resumable daily/carry chunks.
```

Tests must also reject an offline-reference-only result, probe results reporting zero or two requests, a result bound to a different month or interval, an unsealed/wrong-month metadata scope, and a production controller that tries to omit the live probe. Reuse HATEOAS iteration, `Retry-After`, five bounded attempts, exponential backoff, `.partial` replacement, SHA-256, manifest validation, and completed-chunk skipping. Default to one request stream and reject concurrency above two. Carry files use stable private ordinals such as `carry-0001.jsonl.gz`; no identifier appears in a file name or public output.

- [ ] **Step 4: Parameterize full-month QA without changing May defaults**

The generic QA must derive 28/31/30 daily dates, validate every data/manifest pair and remote total, require the **daily-chunk** unique `_id` and `sessionID` counts to equal the local metadata count, require metadata-`/ts` match 100%, and require missing/orphan zero. Carry-in ordinals are validated separately against the complete overlap set; the combined analysis inventory must contain exactly `local_month_session_count + carry_in_session_count` unique sessions with no collision. QA must verify raw inventory before and after reading it. Existing May CLI and QA artifacts must remain byte-compatible.

- [ ] **Step 5: Add the explicit seasonal CLI authorization boundary**

```python
parser.add_argument("--authorize-seasonal", action="store_true")
parser.add_argument("--metadata-root", type=Path, required=True)
parser.add_argument("--raw-root", type=Path, default=Path("data/raw/acn/jpl/seasonal"))
```

The production CLI has no month-order override: it always considers all three allowlisted months and internally filters/skips completed work in `SEASONAL_MONTHS` order. The CLI must read `ACN_API_TOKEN` only after literal authorization, print only month/status/count aggregates, and never echo exceptions that may contain URLs, queries, paths, or credentials. Tests must prove callers cannot reorder or duplicate months, inject a sentinel token, and scan stdout, stderr, ignored manifests, retry state, logs, and leftover partial files to prove that neither the token nor authorization-bearing URLs are written anywhere.

- [ ] **Step 6: Run acquisition, CLI, API-client, and May QA tests**

Run: `E:\Anaconda\envs\evcf-gate1-pilot\python.exe -m pytest code/tests/test_acn_jpl_seasonal_acquisition.py code/tests/test_acquire_jpl_seasonal_cli.py code/tests/test_acn_jpl_full_month_ts.py code/tests/test_acn_jpl_full_month_qa.py code/tests/test_acn_jpl_full_month_cli.py -q`

Expected: PASS with no network access in tests.

- [ ] **Step 7: Commit**

```text
refactor: generalize JPL monthly acquisition and QA
```

## Task 3: Parameterized raw validation, cleaning, and seasonal power decision

**Files:**
- Modify: `code/src/evcf/data/acn_jpl_preparation.py`
- Modify: `code/src/evcf/data/acn_jpl_gate1_prep.py`
- Modify: `code/src/evcf/data/acn_jpl_power_semantics.py`
- Create: `code/tests/test_acn_jpl_seasonal_cleaning.py`
- Modify: `code/tests/test_acn_jpl_preparation.py`
- Modify: `code/tests/test_acn_jpl_gate1_prep.py`
- Modify: `code/tests/test_acn_jpl_power_semantics.py`

- [ ] **Step 1: Write failing dynamic-contract and power-fallback tests**

```python
def test_raw_contract_accepts_dynamic_days_and_zero_carry() -> None:
    contract = RawSnapshotContract.for_month(aug, local_records=1509, carry_records=0)
    assert contract.day_count == 31
    assert contract.carry_count == 0

def test_sampling_hold_is_derived_per_month() -> None:
    assert seasonal_cleaning_policy(current_mode_seconds=10).max_hold_seconds == 30
    assert seasonal_cleaning_policy(current_mode_seconds=30).max_hold_seconds == 60

def test_severe_power_conflict_keeps_current_pipeline_but_disables_e208() -> None:
    decision = seasonal_power_decision(PowerDecisionInputs(
        mapping_rate=1.0,
        primary_audit_coverage=1.0,
        eligible_session_count=100,
        retained_session_count=100,
        median_absolute_percentage_error=0.10,
        p90_absolute_percentage_error=0.20,
        monthly_relative_energy_error=0.60,
        statistics_finite=True,
    ))
    assert decision.power_semantics_status == "CURRENT_PROXY_ONLY"
    assert decision.e208_authorized is False
    assert decision.continue_current_pipeline is True
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `E:\Anaconda\envs\evcf-gate1-pilot\python.exe -m pytest code/tests/test_acn_jpl_seasonal_cleaning.py code/tests/test_acn_jpl_preparation.py code/tests/test_acn_jpl_power_semantics.py -q`

Expected: dynamic raw and seasonal power contracts are absent.

- [ ] **Step 3: Parameterize raw validation and deterministic cleaning**

`RawSnapshotContract.for_month()` must accept dynamic day/carry/file/record counts and post-acquisition inventory digest. Generic raw iteration must yield all carry ordinals then daily records in stable order. Cleaning must preserve May rules exactly: timezone-aware UTC, exact duplicate removal, conflicting timestamp missing in primary and last-write only in sensitivity, `[connection, disconnect)`, boundary-positive exclusion, actual current/pilot sampling modes, `min(3*mode,60s)` holds, no unbounded interpolation, retrospective doneChargingTime, and `modifiedAt <= issue_time` inputs.

Add closed-schema assertions for every cleaning field frozen above, including the ±60 s boundary sensitivity, both actual sampling modes and derived holds, bounded observation coverage, duplicate/conflict counts, and boundary-positive point/integral evidence. No missing required statistic may be silently replaced by a generic status.

- [ ] **Step 4: Split seasonal power reporting from May compatibility behavior**

```python
@dataclass(frozen=True)
class SeasonalPowerDecision:
    power_semantics_status: Literal["KW_RECONSTRUCTION_CANDIDATE", "CURRENT_PROXY_ONLY"]
    e208_authorized: bool
    continue_current_pipeline: bool = True
```

Keep pinned repository `zach401/acnportal` and commit `14e723b11339e56ca3afd2bf4969f9e4bc8c2623`. Compute `Ah`, `E208`, and `Veff` offline only. Never expose `kWhDelivered` to online features or use per-session `Veff` calibration.

The primary audit cohort is fixed before seeing seasonal results: `kWhDelivered >= 0.5 kWh` and current coverage `>= 0.90`. Add closed-schema tests for mapping coverage, eligible/retained counts and rate, median Veff, Q1/Q3/IQR, 208 V MdAPE, P90 APE, aggregate energy error, and the resulting status/authorization pair.

`seasonal_power_decision()` must first call the unchanged legacy `classify_power_semantics()` rule. Mapping below 0.95, any non-finite statistic or zero retained-rate denominator, or absolute monthly relative energy error above 0.50 remains a legacy severe failure; the seasonal adapter maps that result to `CURRENT_PROXY_ONLY`, `e208_authorized=false`, and `continue_current_pipeline=true`. The candidate boundary remains exactly mapping 1.0, primary audit coverage at least 0.90, retained rate at least 0.90, MdAPE at most 0.20, P90 APE at most 0.40, and absolute monthly error at most 0.10. A candidate preserves the candidate status but also keeps `e208_authorized=false` until main-controller review. All other finite non-severe cases remain `CURRENT_PROXY_ONLY`. Add threshold, equality-boundary, negative-error, NaN, infinity, zero-denominator, and candidate-without-authorization tests; do not invent a second classifier.

- [ ] **Step 5: Run cleaning/power suites and May regression**

Run: `E:\Anaconda\envs\evcf-gate1-pilot\python.exe -m pytest code/tests/test_acn_jpl_cleaning.py code/tests/test_acn_jpl_seasonal_cleaning.py code/tests/test_acn_jpl_power_semantics.py code/tests/test_acn_jpl_preparation.py code/tests/test_acn_jpl_gate1_prep.py -q`

Expected: PASS and legacy May public hashes remain unchanged.

- [ ] **Step 6: Commit**

```text
refactor: parameterize JPL cleaning and power audit
```

## Task 4: Physical-time aggregation and M1-M3-only snapshots

**Files:**
- Modify: `code/src/evcf/data/acn_jpl_15min.py`
- Modify: `code/src/evcf/data/acn_jpl_issue_snapshots.py`
- Modify: `code/src/evcf/forecasting/acn_jpl_gate1_features.py`
- Create: `code/tests/test_acn_jpl_seasonal_snapshots.py`
- Modify: `code/tests/test_acn_jpl_15min.py`
- Modify: `code/tests/test_acn_jpl_issue_snapshots.py`
- Modify: `code/tests/test_acn_jpl_gate1_features.py`

- [ ] **Step 1: Write failing November fold and M1-M3-only tests**

```python
def test_november_grid_preserves_both_folds_as_2884_physical_bins() -> None:
    grid = build_local_15min_grid(nov.local_start, nov.local_end)
    repeated = [b for b in grid if b.local_date == "2019-11-03" and b.timestamp_local.hour == 1]
    assert len(grid) == 2884
    assert len(repeated) == 8
    assert {b.timestamp_local.utcoffset() for b in repeated} == {timedelta(hours=-7), timedelta(hours=-8)}
    assert all((b.end_utc - b.start_utc).total_seconds() == 900 for b in repeated)

def test_seasonal_snapshot_contains_only_m1_m2_m3() -> None:
    result = build_issue_snapshots(
        station_rows,
        cleaned_sessions,
        start_utc=nov.utc_start,
        end_utc=nov.utc_end,
        policy=SnapshotPolicy(tiers=("M1", "M2", "M3")),
    )
    assert set(result.tier_rows) == {"M1", "M2", "M3"}
    assert result.qa["m4_generated"] is False
    assert not structural_m4_references(result.qa)
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `E:\Anaconda\envs\evcf-gate1-pilot\python.exe -m pytest code/tests/test_acn_jpl_seasonal_snapshots.py code/tests/test_acn_jpl_15min.py code/tests/test_acn_jpl_issue_snapshots.py -q`

Expected: tier selection is absent and November contract is not explicit.

- [ ] **Step 3: Make physical-time DST and requested-tier contracts explicit**

Keep UTC 900-second stepping. Add QA fields `grid_policy=continuous_physical_utc`, `dst_fold_extra_bins=4`, and `repeated_local_quarter_count=4` for November. Parameterize `SnapshotPolicy.tiers`; default remains `("M1","M2","M3","M4")`, seasonal calls pass exactly `("M1","M2","M3")`. Whitelist, leakage audit, canonical hash, sample counts, and ragged rows must contain only requested tiers and reject any extra tier.

Closed-schema tests must cover every station field and the time-weighted-integral assertion, valid 80/90/95 counts/rates, missing rate, longest missing run, peak, ramp, and weekday/weekend summaries. Snapshot tests must cover scheduled/formal counts, per-horizon valid-label counts, per-tier counts/shapes/missingness, userInputs truncation, whitelist/blacklist, future/private/temporal zero counts, and the sealed SHA.

Extend `IssueSnapshotResult` with an immutable requested-tier mapping/property while retaining the legacy `m1_rows`, `m2_rows`, `m3_rows`, and `m4_rows` attributes used by May. For an M1-M3 seasonal result, the legacy `m4_rows` attribute is an empty tuple; M4 tier material is omitted from seasonal serialization, manifests, and hashes, while QA contains only the closed negative boolean `m4_generated=false`. Add regression tests proving the old default still returns and serializes all four tiers and the seasonal path exposes exactly three.

- [ ] **Step 4: Materialize fixed M1-M3 feature blocks locally**

```python
blocks = build_feature_blocks(snapshot, tiers=("M1", "M2", "M3"))
assert {name: block.values.shape[1] for name, block in blocks.items()} == {
    "M1": 195, "M2": 201, "M3": 311,
}
assert {
    name: block.values.shape[1] + int(block.nullable_mask.sum())
    for name, block in blocks.items()
} == {
    "M1": 195, "M2": 204, "M3": 391,
}
```

Change the feature-builder signature compatibly to `build_feature_blocks(snapshot, m4_accumulator=None, *, tiers=DEFAULT_TIERS)`: existing May positional calls with an accumulator remain valid and default to M1-M4; M1-M3 calls do not require or access an accumulator or M4 rows; requesting M4 without an accumulator fails closed. The generic seasonal snapshot loader/constructor verifies only requested tiers and supplies empty legacy M4 tuples, while the frozen May loader and snapshot hashes remain unchanged. Issue times remain index arrays only. Preserve the May field order, pooling order, missing semantics, and strict active threshold. No M4 file or manifest entry may be generated.

- [ ] **Step 5: Run aggregation, snapshot, and feature suites**

Run: `E:\Anaconda\envs\evcf-gate1-pilot\python.exe -m pytest code/tests/test_acn_jpl_15min.py code/tests/test_acn_jpl_issue_snapshots.py code/tests/test_acn_jpl_gate1_features.py code/tests/test_acn_jpl_seasonal_snapshots.py -q`

Expected: PASS with February/August/November bins 2,688/2,976/2,884 and dimensions 195/201/311 raw, 195/204/391 encoded.

Include explicit regressions for the unchanged legacy positional call `build_feature_blocks(snapshot, accumulator)` and the new accumulator-free seasonal call. The first must still return M1-M4; the second must return only M1-M3.

- [ ] **Step 6: Commit**

```text
feat: build seasonal JPL M1-M3 snapshots
```

## Task 5: Seasonal preparation controller, closed publication, and CLI

**Files:**
- Create: `code/src/evcf/data/acn_jpl_seasonal_prep.py`
- Create: `scripts/prepare_jpl_seasonal_data.py`
- Create: `code/configs/acn_jpl_seasonal_prep_2019.yaml`
- Create: `code/tests/test_acn_jpl_seasonal_prep.py`
- Create: `code/tests/test_prepare_jpl_seasonal_data_cli.py`
- Modify: `.gitignore`
- Modify: `code/tests/test_repository_integrity.py`

- [ ] **Step 1: Write failing orchestration, privacy, and exact-allowlist tests**

```python
MONTH_FILES = {
    "acquisition_summary.json", "cleaning_qa.json", "cleaning_sensitivity.json",
    "boundary_current_audit.json", "power_semantics_audit.json",
    "station_15min_qa.json", "issue_snapshot_qa.json", "leakage_audit.json",
    "data_snapshot_manifest.json", "run_manifest.json", "SHA256SUMS",
}
ROOT_FILES = {
    "seasonal_prep_summary.csv", "seasonal_snapshot_manifest.json",
    "seasonal_prep_report.md", "SHA256SUMS",
}

def test_release_is_exactly_37_files_and_contains_no_m4_or_private_material(tmp_path: Path) -> None:
    publish_seasonal_release(results, tmp_path)
    assert release_paths(tmp_path) == expected_37_paths()
    validate_public_artifacts(tmp_path, expected_relative_paths=expected_37_paths())
    assert not structural_m4_references_in_release(tmp_path)
    assert all_negative_m4_audits_are_false(tmp_path)
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `E:\Anaconda\envs\evcf-gate1-pilot\python.exe -m pytest code/tests/test_acn_jpl_seasonal_prep.py code/tests/test_prepare_jpl_seasonal_data_cli.py code/tests/test_repository_integrity.py -q`

Expected: seasonal preparation and allowlist do not exist.

- [ ] **Step 3: Implement per-month fail-closed preparation**

`prepare_jpl_seasonal_month()` receives an explicit `JPLMonthConfig` plus raw,
interim, and processed roots. It records the canonical raw inventory, validates
the derived monthly raw contract, cleans every validated record with the
month-derived cleaning policy, applies the offline power audit, aggregates on
the configured UTC interval, builds snapshots with
`SnapshotPolicy(tiers=("M1", "M2", "M3"))`, and materializes only the three
corresponding fixed feature blocks. It then proves the raw inventory is
unchanged before returning a closed `MonthPreparationResult` containing only
aggregate counts, statuses, dimensions, and hashes.

Stop a month if acquisition integrity, raw immutability, invalid-container rate, main valid-bin rate, leakage, or privacy gates fail. For each of `chargingCurrent` and `pilotSignal`, an invalid container is one whose field is absent/non-mapping, whose timestamps or values are not lists, or whose timestamp/value lengths differ; divide its count by all combined analysis sessions (local sessions plus carry-in). Each rate must be finite and at most 0.10; a rate above 0.10 fails the month. The main station gate is specifically `count(valid_bin_90) / total_bins >= 0.80`, with the expected positive monthly bin count as denominator and a finite ratio; neither `valid_bin_80` nor `valid_bin_95` may substitute. Keep already completed month roots byte-identical when a later month fails.

- [ ] **Step 4: Implement deterministic aggregate-only publication**

Per-month `SHA256SUMS` covers its ten payload files. Root `SHA256SUMS` covers the three root payloads and all 33 per-month files using normalized `/` separators. `seasonal_snapshot_manifest.json` binds config, code commit, metadata inventory, raw inventory, processed snapshot, and public hashes without paths or identifiers.

- [ ] **Step 5: Add the local-only preparation CLI and exact Git allowlist**

The CLI requires `--authorize-prepare`, imports no model runner, accepts explicit raw/interim/processed/public roots, prints only month status/counts, and rejects months outside the frozen order. `.gitignore` must keep all `data/raw`, `data/interim`, `data/processed`, local checkpoints, features, and predictions ignored while allowing only `outputs/seasonal_prep/jpl_2019/**` and rejecting extra public files through repository tests.

- [ ] **Step 6: Run controller, privacy, and repository tests**

Run: `E:\Anaconda\envs\evcf-gate1-pilot\python.exe -m pytest code/tests/test_acn_jpl_seasonal_prep.py code/tests/test_prepare_jpl_seasonal_data_cli.py code/tests/test_repository_integrity.py -q`

Expected: PASS, exact 37-file release, zero M4/private/path/token/model/prediction fields.

- [ ] **Step 7: Commit**

```text
feat: orchestrate JPL seasonal data preparation
```

## Task 6: Freeze implementation and prove May regression before network access

**Files:**
- Modify: `docs/superpowers/plans/2026-09-02-jpl-seasonal-preparation.md`
- Test: all files under `code/tests/`

- [ ] **Step 1: Run the full local verification suite**

```powershell
E:\Anaconda\envs\evcf-gate1-pilot\python.exe scripts/validate_library.py
E:\Anaconda\envs\evcf-gate1-pilot\python.exe -m pytest code/tests
E:\Anaconda\envs\evcf-gate1-pilot\python.exe -m compileall -q code/src scripts
E:\Anaconda\envs\evcf-gate1-pilot\python.exe -m ruff check code/src scripts code/tests
git diff --check
```

- [ ] **Step 2: Re-run May compatibility in an isolated temporary output root**

Require local/UTC/carry 1,644/1,645/1, 2,976 bins, 2,865/2,853 scheduled/formal samples, and exact existing public SHA-256 values. Do not replace the existing May raw/interim/processed/public roots.

- [ ] **Step 3: Audit the staged tree before credential use**

Require no token value, authorization-bearing URL, URL query containing identifiers, private ID, raw payload, local absolute path, `.partial`, model, prediction, or unignored data file. Scan both the staged tree and every generated ignored manifest/log/state file using a sentinel-token test. Confirm the original `main` worktree status is unchanged.

- [ ] **Step 4: Commit the frozen implementation**

```text
test: preserve May contract and cover seasonal months
```

Record this commit as the seasonal execution commit.

## Task 7: Official metadata gates and sequential `/ts` acquisition

**Files:**
- Local ignored: `data/raw/acn/jpl/seasonal/{2019-02,2019-08,2019-11}/`
- Local ignored logs/state only; no tracked file is modified during acquisition.

- [ ] **Step 1: Capture the complete historical metadata inventory read-only**

Require 42 JPL gzip files, 42 valid manifests, 33,638 records, unique `_id` and `sessionID`, and the frozen inventory digest. Compute local/UTC/boundary/carry counts without emitting identifiers.

- [ ] **Step 2: Run 2019-02 metadata probe then acquisition**

Compute the local count from the validated complete metadata, invoke the official probe exactly once in the current execution, require live provenance and exact equality before creating the `/ts` client, and do not compare against a predeclared numeric expectation. Download 28 daily chunks and every independently identified carry-in ordinal, validate SHA/JSON/remote counts/linkage, and freeze the raw inventory.

- [ ] **Step 3: Run 2019-08 metadata probe then acquisition**

Recompute the August local and carry-in counts from the validated complete metadata, invoke the official probe exactly once in the current execution, and require live provenance plus exact equality without a predeclared numeric expectation. Download 31 daily chunks and the computed carry-in set, validate independently, and do not touch February.

- [ ] **Step 4: Run 2019-11 metadata probe then acquisition**

Recompute the November local and carry-in counts from the validated complete metadata, invoke the official probe exactly once in the current execution, and require live provenance plus exact equality without a predeclared numeric expectation. Download 30 daily chunks and the computed carry-in set, validate independently, and do not touch February or August.

- [ ] **Step 5: Independently audit all raw trees**

For every month require all daily chunks, manifests, SHA, JSONL, and remote totals; daily unique identifiers must equal the official/local metadata count with 100% metadata-`/ts` linkage and zero missing/orphan sessions. Require the independently validated carry-in set to be complete, the combined unique count to equal local plus carry-in, zero partial files, and unchanged inventories across read-only QA.

## Task 8: Deterministic cleaning, aggregation, and M1-M3 preparation

**Files:**
- Local ignored: `data/interim/acn/jpl/{2019-02,2019-08,2019-11}/`
- Local ignored: `data/processed/acn/jpl/{2019-02,2019-08,2019-11}/`
- Public: `outputs/seasonal_prep/jpl_2019/`

- [ ] **Step 1: Prepare February and require every data gate**

Require 2,688 bins, `count(valid_bin_90) / 2688 >= 0.80`, zero leakage/private fields, M1-M3 only, raw/encoded dimensions 195/201/311 and 195/204/391, and a sealed snapshot SHA.

- [ ] **Step 2: Prepare August and require every data gate**

Require 2,976 bins with the same rules and frozen feature definitions.

- [ ] **Step 3: Prepare November and require physical-time DST evidence**

Require 2,884 bins, eight physical 15-minute rows mapping to the four repeated local 01:xx quarters, 2,773 scheduled issue times, stable UTC ordering, and no fold collapse.

- [ ] **Step 4: Independently recompute QA and privacy from ignored artifacts**

Recompute every field in the closed monthly QA schema without importing publication aggregation functions: all retention/duplicate/conflict/invalid/nonmonotonic statistics; boundary points, integrals, shares, ±60 s sensitivity; sampling modes, holds, and bounded coverage; every power cohort/count/rate/quantile/error/decision; every station field, threshold count/rate, gap, peak, ramp, weekday/weekend and DST statistic; every scheduled/formal/per-horizon/per-tier count, shape, missing rate, whitelist/truncation/leakage result; and all snapshot/public hashes. Require exact cross-file agreement.

- [ ] **Step 5: Publish and commit one month at a time, then the root report**

```text
data: add February seasonal preparation evidence
data: add August seasonal preparation evidence
data: add November seasonal preparation evidence
docs: summarize seasonal data readiness
```

## Task 9: Final verification, PR, and stop

**Files:**
- Verify the entire branch and exact 37-file public release.

- [ ] **Step 1: Run all required checks fresh in the frozen environment**

Run the five Task 6 verification commands and require every exit code zero.

- [ ] **Step 2: Audit release and Git boundaries**

Require public SHA files valid, all raw/interim/processed/local features ignored, no M4/model/prediction/private/path/token material tracked, task worktree clean, and original `main` unchanged.

- [ ] **Step 3: Push and create the requested PR**

Base `main`, head `data/jpl-2019-seasonal-replication`, title `季节复核准备：完成JPL 2019-02/08/11数据获取与M1-M3构造`. Do not merge.

- [ ] **Step 4: Wait for Python 3.11 CI and report**

Require final-head CI success, comment aggregate results on Issue #22, report `PASS`, `CONDITIONAL_PASS`, or `FAIL`, and stop without running any seasonal forecasting model.

- [ ] **Step 5: Use the frozen final response contract**

Report `JPL_SEASONAL_PREPARATION = PASS | CONDITIONAL_PASS | FAIL`, followed by exactly these eight sections: (1) Git—branch, commits, PR, CI, and `main modified: NO`; (2) Monthly acquisition—each local/carry count, all metadata-`/ts` matches, failed chunks; (3) Cleaning—per-month retained rates, duplicates, conflicts, boundary integral shares, raw unchanged; (4) Power semantics—per-month median Veff, MdAPE, P90 APE, aggregate energy error, statuses; (5) 15-minute data—bins, 90% valid bins, missing rates, longest gaps; (6) M1-M3 snapshots—formal samples, feature dimensions, leakage audits, SHAs, `M4 generated: NO`; (7) Security—token/raw/identifiers/local paths/models each `NO`; and (8) Decision—all months ready, blocking months, readiness for seasonal Gate 1 replication, next action. Then stop.
