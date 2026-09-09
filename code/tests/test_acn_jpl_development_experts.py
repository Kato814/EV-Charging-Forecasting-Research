from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from evcf.forecasting.acn_jpl_development_experts import (
    HORIZONS_MINUTES,
    DevelopmentExpertError,
    MonthContract,
    MonthData,
    load_development_expert_protocol,
    load_month_data,
    load_selected_hgb_parameters,
    predict_task,
    verify_development_expert_implementation_commit,
)
from evcf.forecasting.acn_jpl_gate1_features import FeatureBlock, canonical_feature_schema

_ZONE = ZoneInfo("America/Los_Angeles")


class _MeanEstimator:
    def fit(self, x: np.ndarray, y: np.ndarray) -> _MeanEstimator:
        assert x.shape[0] == len(y)
        self.mean = float(np.mean(y))
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        return np.full(len(x), self.mean, dtype=np.float64)


def _feature_block(tier: str, issue_times: np.ndarray) -> FeatureBlock:
    names, nullable = canonical_feature_schema(tier)
    values = np.zeros((len(issue_times), len(names)), dtype=np.float64)
    return FeatureBlock(issue_times, values, names, nullable)


def test_frozen_protocol_and_may_selected_hgb_parameters_are_bound() -> None:
    protocol = load_development_expert_protocol()
    assert tuple(item.month for item in protocol.months) == (
        "2019-01",
        "2019-04",
        "2019-07",
        "2019-10",
    )
    params = load_selected_hgb_parameters(protocol=protocol, repo_root=Path.cwd())
    assert len(params) == 10
    assert params[("M2", 15)]["learning_rate"] == pytest.approx(0.03)
    assert params[("M2", 60)]["min_samples_leaf"] == 50
    assert params[("M3", 120)]["max_leaf_nodes"] == 31
    assert params[("M3", 240)]["l2_regularization"] == 1


def test_current_checkout_satisfies_expert_implementation_binding() -> None:
    root = Path.cwd()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    verify_development_expert_implementation_commit(head, repo_root=root)


def test_predict_task_uses_only_labels_available_by_each_local_midnight() -> None:
    issue_times: list[int] = []
    for day in range(2, 22):
        for hour in (0, 12):
            local = datetime(2019, 1, day, hour, 0, tzinfo=_ZONE)
            issue_times.append(int(local.timestamp()))
    times = np.asarray(issue_times, dtype=np.int64)
    labels = np.column_stack(
        [np.arange(len(times), dtype=np.float64) + horizon for horizon in HORIZONS_MINUTES]
    )
    data = MonthData(
        month="2019-01",
        issue_times=times,
        labels=labels,
        blocks={"M2": _feature_block("M2", times), "M3": _feature_block("M3", times)},
        processed_snapshot_sha256="a" * 64,
    )
    horizon = 240
    task = predict_task(
        data=data,
        tier="M2",
        horizon_minutes=horizon,
        params={},
        selected_parameter_sha256="b" * 64,
        test_start_local_day=18,
        native_thread_limit=1,
        estimator_factory=lambda _params: _MeanEstimator(),
    )
    first_midnight = int(datetime(2019, 1, 18, tzinfo=_ZONE).timestamp())
    expected_first_fit = int(np.sum((times < first_midnight) & (times + horizon * 60 <= first_midnight)))
    assert task.first_fit_rows == expected_first_fit
    assert task.fit_count == 4
    assert np.all(task.issue_times >= first_midnight)
    assert np.all(np.isfinite(task.predictions))


def _write_npy(path: Path, value: np.ndarray) -> tuple[str, int]:
    np.save(path, value, allow_pickle=False)
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size


def test_processed_snapshot_loader_verifies_manifest_and_row_alignment(tmp_path: Path) -> None:
    month = "2019-01"
    interim = tmp_path / "interim" / month
    processed = tmp_path / "processed" / month
    interim.mkdir(parents=True)
    processed.mkdir(parents=True)
    row_count = 4
    times = np.asarray(
        [int(datetime(2019, 1, 2, 0, minute, tzinfo=_ZONE).timestamp()) for minute in (0, 15, 30, 45)],
        dtype=np.int64,
    )
    artifacts: list[dict[str, object]] = []
    for tier in ("M2", "M3"):
        names, nullable = canonical_feature_schema(tier)
        values = np.zeros((row_count, len(names)), dtype=np.float64)
        for suffix, array in (
            ("values", values),
            ("issue_times", times),
            ("nullable_mask", nullable),
        ):
            file_name = f"{tier}.{suffix}.npy"
            digest, size = _write_npy(processed / file_name, array)
            artifacts.append(
                {"name": f"processed/{file_name}", "sha256": digest, "size": size}
            )
    labels_path = processed / "labels.jsonl.gz"
    with gzip.open(labels_path, "wt", encoding="utf-8", newline="") as handle:
        for ordinal, issue in enumerate(times):
            handle.write(
                json.dumps(
                    {
                        "issue_index": ordinal,
                        "issue_time_utc_s": int(issue),
                        "labels": {str(h): float(ordinal + h) for h in HORIZONS_MINUTES},
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
    artifacts.append(
        {
            "name": "processed/labels.jsonl.gz",
            "sha256": hashlib.sha256(labels_path.read_bytes()).hexdigest(),
            "size": labels_path.stat().st_size,
        }
    )
    manifest = {
        "schema_version": "acn-jpl-seasonal-local-snapshot/v1",
        "month": month,
        "source_inventory_sha256": "1" * 64,
        "data_snapshot_sha256": "2" * 64,
        "artifacts": artifacts,
        "tiers": ["M1", "M2", "M3"],
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (processed / "data_snapshot_manifest.json").write_bytes(manifest_bytes)
    contract = MonthContract(
        month=month,
        formal_issue_times=row_count,
        processed_snapshot_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )
    loaded = load_month_data(
        contract=contract,
        interim_root=tmp_path / "interim",
        processed_root=tmp_path / "processed",
    )
    assert np.array_equal(loaded.issue_times, times)
    assert loaded.labels.shape == (row_count, 5)
    assert loaded.blocks["M2"].values.shape == (row_count, 201)
    assert loaded.blocks["M3"].values.shape == (row_count, 311)

    tampered = processed / "M2.values.npy"
    tampered.write_bytes(tampered.read_bytes() + b"x")
    with pytest.raises(DevelopmentExpertError, match="PROCESSED_SNAPSHOT_INVALID"):
        load_month_data(
            contract=contract,
            interim_root=tmp_path / "interim",
            processed_root=tmp_path / "processed",
        )


def test_final_holdout_is_not_part_of_protocol() -> None:
    protocol = load_development_expert_protocol()
    months = {item.month for item in protocol.months}
    assert months.isdisjoint({"2019-03", "2019-06", "2019-09", "2019-12"})
