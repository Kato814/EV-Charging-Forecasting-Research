from __future__ import annotations

import csv
import gzip
import hashlib
import json
import pickle
from dataclasses import fields, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import evcf.forecasting.acn_jpl_gate1_data as gate1_data
import numpy as np
import pytest
from evcf.forecasting.acn_jpl_gate1_data import (
    CausalSessionSeries,
    group_by_canonical_issue_time,
    verified_snapshot_provenance,
    verify_and_load_snapshot,
)
from evcf.forecasting.acn_jpl_gate1_features import (
    M4FeatureAccumulator,
    encode_m1,
    verified_feature_block_provenance,
)
from joblib import Parallel, delayed

_ISSUE_COUNT = 2_853
_STATION_COUNT = 2_976
_HORIZONS = np.asarray([15, 30, 60, 120, 240], dtype=np.int16)
_FIRST_ISSUE = 1_556_780_400
_SOURCE_SHA256 = "1" * 64
_PROTOCOL_SHA256 = "2" * 64
_SNAPSHOT_SHA256 = "3" * 64
_ARTIFACTS = (
    "cleaned_sessions.jsonl.gz",
    "cleaned_sessions.jsonl.gz.manifest.json",
    "station_15min.csv.gz",
    "station_15min.npz",
    "m1.npz",
    "m2.npz",
    "labels.npz",
    "m3.jsonl.gz",
    "m4.jsonl.gz",
)


def _verify_feature_block_in_worker(block: Any, snapshot: Any) -> tuple[str, bool]:
    seal = verified_feature_block_provenance(block, snapshot, tier="M1")
    immutable = all(
        not array.flags.writeable
        for array in (block.issue_times, block.values, block.nullable_mask)
    )
    return seal, immutable


class SnapshotFixture:
    def __init__(self, root: Path, *, future_value: float = 999.0) -> None:
        self.processed = root / "processed"
        self.interim = root / "interim"
        self.processed.mkdir(parents=True)
        self.interim.mkdir(parents=True)
        self.issue_times = _FIRST_ISSUE + np.arange(_ISSUE_COUNT, dtype=np.int64) * 900
        self.station_times = (
            self.issue_times[0] - 86_400 + np.arange(_STATION_COUNT, dtype=np.int64) * 900
        )
        self.source_inventory_sha256 = _SOURCE_SHA256
        self.protocol_sha256 = _PROTOCOL_SHA256
        self.prepared_snapshot_sha256 = _SNAPSHOT_SHA256
        self._write_dense()
        self.write_m3([self.m3_row()])
        self.write_m4([self.m4_row()])
        self.write_cleaned([self.cleaned_row(future_value=future_value)])
        self.refresh_manifest()

    @staticmethod
    def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
        with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _write_dense(self) -> None:
        calendar = np.zeros((_ISSUE_COUNT, 3), dtype=np.int16)
        history = np.zeros((_ISSUE_COUNT, 96), dtype=np.float32)
        mask = np.ones((_ISSUE_COUNT, 96), dtype=np.bool_)
        np.savez_compressed(
            self.processed / "m1.npz",
            issue_time_utc_s=self.issue_times,
            history_station_current_mean_a=history,
            history_observed_mask=mask,
            calendar=calendar,
        )
        np.savez_compressed(
            self.processed / "m2.npz",
            issue_time_utc_s=self.issue_times,
            history_station_current_mean_a=history,
            history_observed_mask=mask,
            current_state=np.zeros((_ISSUE_COUNT, 6), dtype=np.float32),
        )
        np.savez_compressed(
            self.processed / "labels.npz",
            issue_time_utc_s=self.issue_times,
            horizons_minutes=_HORIZONS,
            station_current_mean_a=np.ones((_ISSUE_COUNT, 5), dtype=np.float32),
        )

        station_calendar = np.zeros((_STATION_COUNT, 3), dtype=np.int16)
        station_numeric = np.zeros((_STATION_COUNT, 13), dtype=np.float32)
        station_validity = np.ones((_STATION_COUNT, 3), dtype=np.bool_)
        np.savez_compressed(
            self.processed / "station_15min.npz",
            timestamp_utc_s=self.station_times,
            calendar=station_calendar,
            numeric=station_numeric,
            validity=station_validity,
        )
        columns = (
            "timestamp_utc",
            "timestamp_local",
            "local_date",
            "quarter_hour_index",
            "day_of_week",
            "is_weekend",
            "station_current_mean_a",
            "station_current_peak_a",
            "connected_session_count",
            "active_charging_session_count",
            "active_charging_session_count_gt_1a",
            "pilot_sum_a",
            "pilot_mean_a",
            "arrival_count",
            "disconnect_count",
            "observed_coverage_ratio",
            "pilot_observed_coverage_ratio",
            "valid_bin_80",
            "valid_bin_90",
            "valid_bin_95",
        )
        local_zone = ZoneInfo("America/Los_Angeles")
        with gzip.open(
            self.processed / "station_15min.csv.gz", "wt", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            for stamp in self.station_times:
                utc = datetime.fromtimestamp(int(stamp), timezone.utc)
                local = utc.astimezone(local_zone)
                writer.writerow(
                    {
                        "timestamp_utc": utc.isoformat().replace("+00:00", "Z"),
                        "timestamp_local": local.isoformat(),
                        "local_date": local.date().isoformat(),
                        "quarter_hour_index": 0,
                        "day_of_week": 0,
                        "is_weekend": False,
                        "station_current_mean_a": 0.0,
                        "station_current_peak_a": 0.0,
                        "connected_session_count": 0.0,
                        "active_charging_session_count": 0.0,
                        "active_charging_session_count_gt_1a": 0.0,
                        "pilot_sum_a": 0.0,
                        "pilot_mean_a": 0.0,
                        "arrival_count": 0.0,
                        "disconnect_count": 0.0,
                        "observed_coverage_ratio": 0.0,
                        "pilot_observed_coverage_ratio": 0.0,
                        "valid_bin_80": True,
                        "valid_bin_90": True,
                        "valid_bin_95": True,
                    }
                )

    def m3_row(self, **updates: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "issue_index": 0,
            "issue_time_utc_s": int(self.issue_times[0]),
            "anonymous_session_index": 0,
            "elapsed_connection_s": 100,
            "elapsed_charging_time_proxy_s": 12,
            "current_current_a": 1.0,
            "recent_current_mean_a": 1.0,
            "recent_current_peak_a": 1.0,
            "recent_current_observed_ratio": 0.5,
            "cumulative_current_ah": 0.1,
            "cumulative_current_observed_ratio": 0.5,
            "current_pilot_a": 8.0,
            "user_input_modified_utc_s": int(self.issue_times[0] - 10),
            "requested_departure_minutes_from_issue": 60.0,
            "known_kwh_requested": 10.0,
        }
        row.update(updates)
        return row

    def m4_row(self, **updates: Any) -> dict[str, Any]:
        visible = int(self.issue_times[0] - 5)
        row: dict[str, Any] = {
            "issue_index": 0,
            "issue_time_utc_s": int(self.issue_times[0]),
            "anonymous_session_index": 0,
            "current_start_offset_inclusive": 0,
            "current_end_offset_exclusive": 1,
            "pilot_start_offset_inclusive": 0,
            "pilot_end_offset_exclusive": 1,
            "min_visible_timestamp_utc_s": visible,
            "max_visible_timestamp_utc_s": visible,
            "partial_current_trajectory_ref": "cleaned_current_prefix",
            "partial_pilot_trajectory_ref": "cleaned_pilot_prefix",
        }
        row.update(updates)
        return row

    def cleaned_row(self, *, future_value: float = 999.0, **updates: Any) -> dict[str, Any]:
        past = int(self.issue_times[0] - 5)
        future = int(self.issue_times[0] + 5)

        def series(field_name: str, values: list[float]) -> dict[str, Any]:
            return {
                "field_name": field_name,
                "timestamps_utc_s": [past, future],
                "values": values,
                "raw_ordinals": [0, 1],
                "boundary_positive_points": [],
                "boundary_sensitivity_points": [],
                "conflict_lww_overrides": [],
                "audit": {},
                "locf_cap_s": 12,
                "main_integral": {},
            }

        row: dict[str, Any] = {
            "schema_version": "acn-jpl-clean-session/v1",
            "session_index": 0,
            "timezone": "America/Los_Angeles",
            "site_id": "poison-site",
            "station_id": "poison-station",
            "space_id": "poison-space",
            "cluster_id": "poison-cluster",
            "connection_utc_s": past - 95,
            "disconnect_utc_s": future + 95,
            "connection_local": "poison-connection",
            "disconnect_local": "poison-disconnect",
            "retrospective_done_raw": "poison-done",
            "retrospective_done_utc_s": future + 50,
            "offline_kwh_delivered": 999_999.0,
            "current": series("chargingCurrent", [1.0, future_value]),
            "pilot": series("pilotSignal", [8.0, future_value]),
            "user_inputs": [{"future": "poison"}],
        }
        row.update(updates)
        return row

    def write_m3(self, rows: list[dict[str, Any]]) -> None:
        self._jsonl(self.processed / "m3.jsonl.gz", rows)

    def write_m4(self, rows: list[dict[str, Any]]) -> None:
        self._jsonl(self.processed / "m4.jsonl.gz", rows)

    def write_cleaned(self, rows: list[dict[str, Any]]) -> None:
        data_path = self.interim / "cleaned_sessions.jsonl.gz"
        self._jsonl(data_path, rows)
        manifest = {
            "anonymous_session_indexes": True,
            "data_file": data_path.name,
            "policy": {
                "boundary_sensitivity_s": 60,
                "current_mode_s": 4,
                "locf_cap_s": 60,
                "locf_mode_multiplier": 3,
                "pilot_mode_s": 4,
            },
            "private_identifiers_stored": False,
            "record_count": len(rows),
            "schema_version": "acn-jpl-cleaned-sessions/v1",
            "sha256": self._sha256(data_path),
            "source_inventory_sha256": _SOURCE_SHA256,
        }
        (self.interim / "cleaned_sessions.jsonl.gz.manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    def refresh_manifest(self) -> None:
        entries = []
        for name in _ARTIFACTS:
            path = (
                self.interim / name
                if name.startswith("cleaned_sessions")
                else self.processed / name
            )
            entries.append(
                {
                    "artifact_name": name,
                    "size_bytes": path.stat().st_size,
                    "sha256": self._sha256(path),
                }
            )
        manifest = {
            "schema_version": "acn-jpl-local-data-snapshot/v1",
            "source_inventory_sha256": _SOURCE_SHA256,
            "data_snapshot_sha256": "pending",
            "artifact_count": len(entries),
            "artifacts": entries,
            "cleaning_policy": {
                "boundary_sensitivity_s": 60,
                "current_mode_s": 4,
                "locf_cap_s": 60,
                "locf_mode_multiplier": 3,
                "pilot_mode_s": 4,
            },
            "protocol_sha256": _PROTOCOL_SHA256,
            "power_column_present": False,
            "power_label_type": "none",
            "snapshot_sha256": _SNAPSHOT_SHA256,
        }
        canonical = (
            json.dumps(
                {"protocol_sha256": _PROTOCOL_SHA256, "artifacts": entries},
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        self.data_snapshot_sha256 = hashlib.sha256(canonical).hexdigest()
        manifest["data_snapshot_sha256"] = self.data_snapshot_sha256
        (self.processed / "data_snapshot_manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )

    def rewrite_npz(self, name: str, arrays: dict[str, np.ndarray]) -> None:
        np.savez_compressed(self.processed / name, **arrays)
        self.refresh_manifest()

    def load(
        self,
        causal_prefix_consumer: Any | None = None,
    ) -> gate1_data.Gate1Snapshot:
        expected = {
            "EXPECTED_DATA_SNAPSHOT_SHA256": self.data_snapshot_sha256,
            "EXPECTED_SOURCE_INVENTORY_SHA256": self.source_inventory_sha256,
            "EXPECTED_PROTOCOL_SHA256": self.protocol_sha256,
            "EXPECTED_PREPARED_SNAPSHOT_SHA256": self.prepared_snapshot_sha256,
        }
        missing = object()
        production = {name: getattr(gate1_data, name, missing) for name in expected}
        for name, value in expected.items():
            setattr(gate1_data, name, value)
        try:
            if causal_prefix_consumer is None:
                return verify_and_load_snapshot(self.processed, self.interim)
            return verify_and_load_snapshot(
                self.processed,
                self.interim,
                causal_prefix_consumer=causal_prefix_consumer,
            )
        finally:
            for name, value in production.items():
                if value is missing:
                    delattr(gate1_data, name)
                else:
                    setattr(gate1_data, name, value)


@pytest.fixture
def snapshot_fixture(tmp_path: Path) -> SnapshotFixture:
    return SnapshotFixture(tmp_path)


def test_snapshot_gate_requires_exact_hashes_and_common_issue_times(
    snapshot_fixture: SnapshotFixture,
) -> None:
    snapshot = snapshot_fixture.load()

    assert snapshot.data_snapshot_sha256 == snapshot_fixture.data_snapshot_sha256
    assert snapshot.issue_times.shape == (2_853,)
    assert snapshot.horizons.tolist() == [15, 30, 60, 120, 240]
    assert snapshot.labels.shape == (2_853, 5)
    assert snapshot.feature_index_names == ("issue_time_utc_s",)
    assert len(snapshot.m3_by_issue_time) == 2_853
    assert snapshot.m3_by_issue_time[1] == ()
    assert not hasattr(snapshot, "causal_sessions")
    assert "causal_sessions" not in {field.name for field in fields(snapshot)}
    assert not hasattr(gate1_data, "CausalSessionStore")


def test_snapshot_verification_seal_survives_checkpoint_but_not_replacement(
    snapshot_fixture: SnapshotFixture,
) -> None:
    snapshot = snapshot_fixture.load()
    provenance = verified_snapshot_provenance(snapshot)
    restored = pickle.loads(pickle.dumps(snapshot))
    assert verified_snapshot_provenance(restored) == provenance

    changed_labels = snapshot.labels.copy()
    changed_labels[0, 0] += 1.0
    changed = replace(snapshot, labels=changed_labels)
    with pytest.raises(ValueError, match="verified|seal|loader"):
        verified_snapshot_provenance(changed)

    tampered = pickle.loads(pickle.dumps(snapshot))
    changed_history = tampered.m1_history.copy()
    changed_history[0, 0] += 1.0
    changed_history = np.frombuffer(changed_history.tobytes(), dtype=changed_history.dtype).reshape(
        changed_history.shape
    )
    object.__setattr__(tampered, "m1_history", changed_history)
    with pytest.raises(ValueError, match="feature source|content|seal"):
        verified_snapshot_provenance(tampered)


def test_verified_m4_rejects_non_loader_causal_series(
    snapshot_fixture: SnapshotFixture,
) -> None:
    accumulator = M4FeatureAccumulator()
    poisoned = False

    def consume(position: int, issue: int, series: CausalSessionSeries) -> None:
        nonlocal poisoned
        delivered = series
        if not poisoned and len(series.current_values_a):
            values = series.current_values_a.copy()
            values[0] += 7.0
            delivered = replace(series, current_values_a=values)
            poisoned = True
        accumulator(position, issue, delivered)

    snapshot = snapshot_fixture.load(consume)
    assert poisoned
    with pytest.raises(ValueError, match="causal prefix|loader delivery|provenance"):
        accumulator.encode(snapshot)


def test_verified_feature_block_survives_pickle_and_loky_read_only(
    snapshot_fixture: SnapshotFixture,
) -> None:
    snapshot = snapshot_fixture.load()
    block = encode_m1(snapshot)
    expected = verified_feature_block_provenance(block, snapshot, tier="M1")
    restored = pickle.loads(pickle.dumps(block))
    assert _verify_feature_block_in_worker(restored, snapshot) == (expected, True)
    assert Parallel(n_jobs=2, backend="loky")(
        delayed(_verify_feature_block_in_worker)(block, snapshot) for _ in range(2)
    ) == [(expected, True), (expected, True)]

    changed_values = restored.values.copy()
    changed_values[0, 0] += 1.0
    object.__setattr__(restored, "values", gate1_data._readonly(changed_values))
    with pytest.raises(ValueError, match="content|seal"):
        verified_feature_block_provenance(restored, snapshot, tier="M1")


def test_frozen_preparation_hash_constants_are_exact() -> None:
    assert gate1_data.EXPECTED_DATA_SNAPSHOT_SHA256 == (
        "7066ffc8ba42a98f73246acfbc62352fe55a1433a43cba80957c6034e3aeaa5d"
    )
    assert gate1_data.EXPECTED_SOURCE_INVENTORY_SHA256 == (
        "63e3f88fcbd4c0d8b87392267cdbe5ad383d89468f10ac3de5e181837b18dcac"
    )
    assert gate1_data.EXPECTED_PROTOCOL_SHA256 == (
        "2b95e9b09d31fdd30c559be80f9db64b22e33822b08a25de3715e168f3697bf3"
    )
    assert gate1_data.EXPECTED_PREPARED_SNAPSHOT_SHA256 == (
        "d3ef2d6e5a4a1dee4f71c716714c29ed8e1624cdfcb070cd96c00155aca082c0"
    )


@pytest.mark.parametrize(
    ("field", "match"),
    [
        ("source_inventory_sha256", "source inventory"),
        ("protocol_sha256", "protocol"),
        ("snapshot_sha256", "prepared snapshot"),
    ],
)
def test_snapshot_gate_rejects_frozen_preparation_hash_drift(
    snapshot_fixture: SnapshotFixture, field: str, match: str
) -> None:
    path = snapshot_fixture.processed / "data_snapshot_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest[field] = "0" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match=match):
        snapshot_fixture.load()


@pytest.mark.parametrize("mode", ["sha", "size"])
def test_snapshot_gate_rejects_hash_or_size_mismatch(
    snapshot_fixture: SnapshotFixture, mode: str
) -> None:
    path = snapshot_fixture.processed / "labels.npz"
    if mode == "sha":
        payload = bytearray(path.read_bytes())
        payload[-1] ^= 1
        path.write_bytes(payload)
    else:
        path.write_bytes(path.read_bytes() + b"x")

    with pytest.raises(ValueError, match="(SHA-256|size)"):
        snapshot_fixture.load()


@pytest.mark.parametrize("problem", ["duplicate", "extra", "missing", "snapshot_hash"])
def test_snapshot_gate_rejects_manifest_artifact_drift(
    snapshot_fixture: SnapshotFixture, problem: str
) -> None:
    path = snapshot_fixture.processed / "data_snapshot_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if problem == "duplicate":
        manifest["artifacts"].append(dict(manifest["artifacts"][0]))
        manifest["artifact_count"] += 1
    elif problem == "extra":
        manifest["artifacts"][-1]["artifact_name"] = "unexpected.bin"
    elif problem == "missing":
        manifest["artifacts"].pop()
        manifest["artifact_count"] -= 1
    else:
        manifest["data_snapshot_sha256"] = "0" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="(artifact|snapshot SHA-256)"):
        snapshot_fixture.load()


@pytest.mark.parametrize("problem", ["unsorted", "unequal"])
def test_snapshot_gate_rejects_invalid_dense_issue_times(
    snapshot_fixture: SnapshotFixture, problem: str
) -> None:
    with np.load(snapshot_fixture.processed / "m2.npz", allow_pickle=False) as stored:
        arrays = {name: stored[name] for name in stored.files}
    times = arrays["issue_time_utc_s"].copy()
    if problem == "unsorted":
        times[[0, 1]] = times[[1, 0]]
    else:
        times[0] += 1
    arrays["issue_time_utc_s"] = times
    snapshot_fixture.rewrite_npz("m2.npz", arrays)

    with pytest.raises(ValueError, match="issue_time"):
        snapshot_fixture.load()


@pytest.mark.parametrize("problem", ["horizons", "target_nan"])
def test_snapshot_gate_rejects_label_contract_drift(
    snapshot_fixture: SnapshotFixture, problem: str
) -> None:
    with np.load(snapshot_fixture.processed / "labels.npz", allow_pickle=False) as stored:
        arrays = {name: stored[name] for name in stored.files}
    if problem == "horizons":
        arrays["horizons_minutes"] = np.asarray([15, 30, 60, 120, 241], dtype=np.int16)
    else:
        target = arrays["station_current_mean_a"].copy()
        target[0, 0] = np.nan
        arrays["station_current_mean_a"] = target
    snapshot_fixture.rewrite_npz("labels.npz", arrays)

    with pytest.raises(ValueError, match="(horizons|labels)"):
        snapshot_fixture.load()


@pytest.mark.parametrize("problem", ["outside", "duplicate", "late_input", "schema", "bool_type"])
def test_snapshot_gate_rejects_invalid_m3_rows(
    snapshot_fixture: SnapshotFixture, problem: str
) -> None:
    row = snapshot_fixture.m3_row()
    if problem == "outside":
        row["issue_time_utc_s"] = int(snapshot_fixture.issue_times[-1] + 900)
        rows = [row]
    elif problem == "duplicate":
        rows = [row, dict(row)]
    elif problem == "late_input":
        row["user_input_modified_utc_s"] = row["issue_time_utc_s"] + 1
        rows = [row]
    elif problem == "schema":
        del row["current_pilot_a"]
        rows = [row]
    else:
        row["issue_index"] = True
        rows = [row]
    snapshot_fixture.write_m3(rows)
    snapshot_fixture.refresh_manifest()

    with pytest.raises(
        (TypeError, ValueError), match="(canonical|duplicate|user input|schema|integer)"
    ):
        snapshot_fixture.load()


@pytest.mark.parametrize("problem", ["future_cutoff", "bad_ref", "missing_session", "offset_drift"])
def test_snapshot_gate_rejects_invalid_m4_rows(
    snapshot_fixture: SnapshotFixture, problem: str
) -> None:
    row = snapshot_fixture.m4_row()
    if problem == "future_cutoff":
        row["max_visible_timestamp_utc_s"] = row["issue_time_utc_s"] + 1
    elif problem == "bad_ref":
        row["partial_current_trajectory_ref"] = "complete_session"
    elif problem == "missing_session":
        row["anonymous_session_index"] = 99
    else:
        row["current_end_offset_exclusive"] = 0
    snapshot_fixture.write_m4([row])
    snapshot_fixture.refresh_manifest()

    with pytest.raises(ValueError, match="(cutoff|reference|session)"):
        snapshot_fixture.load()


@pytest.mark.parametrize("problem", ["duplicate", "schema"])
def test_snapshot_gate_rejects_invalid_cleaned_session_store(
    snapshot_fixture: SnapshotFixture, problem: str
) -> None:
    first = snapshot_fixture.cleaned_row()
    if problem == "duplicate":
        rows = [first, dict(first)]
    else:
        first["schema_version"] = "drifted"
        rows = [first]
    snapshot_fixture.write_cleaned(rows)
    snapshot_fixture.refresh_manifest()

    with pytest.raises(ValueError, match="(session index|schema)"):
        snapshot_fixture.load()


def test_causal_consumer_never_returns_future_or_retrospective_fields(tmp_path: Path) -> None:
    first_fixture = SnapshotFixture(tmp_path / "first", future_value=999.0)
    second_fixture = SnapshotFixture(tmp_path / "second", future_value=123_456.0)
    poisoned = second_fixture.cleaned_row(future_value=123_456.0)
    for name in ("current", "pilot"):
        poisoned[name]["timestamps_utc_s"].append(int(second_fixture.issue_times[0] + 10))
        poisoned[name]["values"].append(999_999.0)
        poisoned[name]["raw_ordinals"].append(2)
    second_fixture.write_cleaned([poisoned])
    second_fixture.refresh_manifest()
    first_seen: list[tuple[int, int, CausalSessionSeries]] = []
    second_seen: list[tuple[int, int, CausalSessionSeries]] = []
    first = first_fixture.load(
        lambda position, issue, series: first_seen.append((position, issue, series))
    )
    second = second_fixture.load(
        lambda position, issue, series: second_seen.append((position, issue, series))
    )
    issue = int(first.issue_times[0])

    assert not hasattr(first, "causal_sessions")
    assert not hasattr(second, "causal_sessions")
    assert len(first_seen) == len(second_seen) == 1
    assert first_seen[0][:2] == second_seen[0][:2] == (0, issue)
    first_series = first_seen[0][2]
    second_series = second_seen[0][2]

    assert isinstance(first_series, CausalSessionSeries)
    assert {field.name for field in fields(first_series)} == {
        "anonymous_session_index",
        "current_timestamps_utc_s",
        "current_values_a",
        "pilot_timestamps_utc_s",
        "pilot_values_a",
    }
    np.testing.assert_array_equal(first_series.current_timestamps_utc_s, [issue - 5])
    np.testing.assert_array_equal(first_series.current_values_a, second_series.current_values_a)
    np.testing.assert_array_equal(first_series.pilot_values_a, second_series.pilot_values_a)
    assert int(first_series.current_timestamps_utc_s.max()) <= issue
    assert int(first_series.pilot_timestamps_utc_s.max()) <= issue
    assert first_series.current_values_a.flags.writeable is False
    forbidden = {
        "sessionID",
        "userID",
        "_id",
        "disconnect_utc_s",
        "retrospective_done_utc_s",
        "offline_kwh_delivered",
        "user_inputs",
    }
    assert forbidden.isdisjoint(dir(first_series))


def test_snapshot_and_causal_arrays_are_bytes_backed_immutable(
    snapshot_fixture: SnapshotFixture,
) -> None:
    causal: list[CausalSessionSeries] = []
    snapshot = snapshot_fixture.load(lambda _position, _issue, series: causal.append(series))

    arrays = [
        snapshot.issue_times,
        snapshot.horizons,
        snapshot.labels,
        snapshot.m1_history,
        snapshot.m1_history_mask,
        snapshot.m1_calendar,
        snapshot.m2_current_state,
        snapshot.station_times,
        snapshot.station_current_mean_a,
        snapshot.station_valid_90,
        causal[0].current_timestamps_utc_s,
        causal[0].current_values_a,
        causal[0].pilot_timestamps_utc_s,
        causal[0].pilot_values_a,
    ]
    for array in arrays:
        assert array.flags.writeable is False
        with pytest.raises(ValueError):
            array.setflags(write=True)


def test_cleaned_store_uses_streaming_iterator_not_list_reader(
    snapshot_fixture: SnapshotFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = gate1_data._read_jsonl

    def guarded(path: Path, context: str) -> list[dict[str, Any]]:
        if Path(path).name == "cleaned_sessions.jsonl.gz":
            raise AssertionError("cleaned store must not use the list JSONL reader")
        return original(path, context)

    monkeypatch.setattr(gate1_data, "_read_jsonl", guarded)

    snapshot_fixture.load()


def test_grouping_keeps_canonical_empty_groups_and_rejects_duplicate_pair() -> None:
    canonical = np.asarray([900, 1800, 2700], dtype=np.int64)
    rows = [
        {"issue_time_utc_s": 900, "anonymous_session_index": 7},
        {"issue_time_utc_s": 2700, "anonymous_session_index": 8},
    ]

    grouped = group_by_canonical_issue_time(canonical, rows)

    assert tuple(len(group) for group in grouped) == (1, 0, 1)
    with pytest.raises(ValueError, match="duplicate"):
        group_by_canonical_issue_time(canonical, [rows[0], dict(rows[0])])


def test_real_jpl_snapshot_passes_read_only_when_present() -> None:
    processed = Path("data/processed/acn/jpl/2019-05")
    interim = Path("data/interim/acn/jpl/2019-05")
    if not (processed / "data_snapshot_manifest.json").is_file():
        pytest.skip("local ignored JPL snapshot is absent")

    calls = 0
    previous_position = -1

    def consume(position: int, issue: int, series: CausalSessionSeries) -> None:
        nonlocal calls, previous_position
        assert position >= previous_position
        previous_position = position
        for timestamps in (
            series.current_timestamps_utc_s,
            series.pilot_timestamps_utc_s,
        ):
            if len(timestamps):
                assert int(timestamps[-1]) <= issue
        calls += 1

    snapshot = verify_and_load_snapshot(processed, interim, causal_prefix_consumer=consume)

    assert snapshot.issue_times.shape == (2_853,)
    assert len(snapshot.m3_rows) == 43_506
    assert len(snapshot.m4_rows) == 22_427
    assert sum(not group for group in snapshot.m3_by_issue_time) == 699
    assert sum(not group for group in snapshot.m4_by_issue_time) == 1_060
    assert calls == 43_506
    assert not hasattr(snapshot, "causal_sessions")
