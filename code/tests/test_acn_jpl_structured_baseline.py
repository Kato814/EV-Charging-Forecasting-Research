from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from evcf.forecasting.acn_jpl_development_experts import (
    HORIZONS_MINUTES,
    DevelopmentExpertProtocol,
    MonthData,
)
from evcf.forecasting.acn_jpl_gate1_features import (
    FeatureBlock,
    canonical_feature_schema,
)
from evcf.forecasting.acn_jpl_structured_baseline import (
    DEVELOPMENT_MONTHS,
    FINAL_HOLDOUT_MONTHS,
    StructuredBaselineError,
    StructuredProtocol,
    _CleanCurrentSession,
    _component_label_matrices,
    _decision,
    _load_baseline_cache,
    _verify_baseline_private_run,
    load_structured_protocol,
    predict_structured_task,
)

_ZONE = ZoneInfo("America/Los_Angeles")


class _MeanEstimator:
    def fit(self, x: np.ndarray, y: np.ndarray) -> _MeanEstimator:
        assert x.shape[0] == len(y)
        self.mean = float(np.mean(y))
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        return np.full(len(x), self.mean, dtype=np.float64)


def _session(
    *,
    connection: int,
    disconnect: int,
    value: float,
) -> _CleanCurrentSession:
    starts = np.asarray(
        list(range(connection, disconnect, 60)),
        dtype=np.int64,
    )
    ends = np.minimum(starts + 60, disconnect)
    values = np.full(len(starts), value, dtype=np.float64)
    return _CleanCurrentSession(
        connection_utc_s=connection,
        disconnect_utc_s=disconnect,
        starts=starts,
        ends=ends,
        values=values,
    )


def _feature_block(tier: str, issue_times: np.ndarray) -> FeatureBlock:
    names, nullable = canonical_feature_schema(tier)
    values = np.zeros((len(issue_times), len(names)), dtype=np.float64)
    return FeatureBlock(issue_times, values, names, nullable)


def _source_protocol() -> DevelopmentExpertProtocol:
    selected = {
        tier: {horizon: (tier[-1] * 64) for horizon in HORIZONS_MINUTES}
        for tier in ("M2", "M3")
    }
    return DevelopmentExpertProtocol(
        protocol_id="synthetic",
        protocol_sha256="a" * 64,
        months=(),
        source_model_selection_manifest="unused.json",
        source_model_selection_sha256="b" * 64,
        selected_parameter_sha256=selected,
        test_start_local_day=18,
        native_thread_limit=1,
    )


def _structured_protocol(private_sha: str = "c" * 64) -> StructuredProtocol:
    return StructuredProtocol(
        protocol_id="synthetic",
        protocol_sha256="d" * 64,
        months=(),
        source_expert_protocol_sha256="a" * 64,
        source_model_selection_sha256="b" * 64,
        source_private_manifest_sha256=private_sha,
        max_horizon_degradation_fraction=0.05,
        minimum_horizon_wins=3,
        minimum_month_wins=3,
        mixed_minimum_horizon_wins=2,
        mixed_minimum_month_wins=2,
    )


def _metric(mae: float) -> dict[str, float | int | None]:
    return {
        "n": 10,
        "mae_a": mae,
        "rmse_a": mae,
        "wape_ratio": mae / 100.0,
        "negative_prediction_count": 0,
    }


def test_structured_protocol_freezes_development_and_holdout_boundaries() -> None:
    protocol = load_structured_protocol()
    assert tuple(item.month for item in protocol.months) == DEVELOPMENT_MONTHS
    assert FINAL_HOLDOUT_MONTHS == (
        "2019-03",
        "2019-06",
        "2019-09",
        "2019-12",
    )
    assert protocol.minimum_horizon_wins == 3
    assert protocol.minimum_month_wins == 3
    assert protocol.max_horizon_degradation_fraction == pytest.approx(0.05)


def test_component_labels_split_existing_and_future_arrival_and_reconstruct() -> None:
    issue = int(datetime(2019, 1, 10, 12, 0, tzinfo=_ZONE).timestamp())
    end = issue + 5 * 3600
    existing_session = _session(
        connection=issue - 3600,
        disconnect=end,
        value=10.0,
    )
    future_session = _session(
        connection=issue + 300,
        disconnect=end,
        value=20.0,
    )
    total = np.asarray(
        [[10.0 + 20.0 * 600.0 / 900.0, 30.0, 30.0, 30.0, 30.0]],
        dtype=np.float64,
    )
    existing, arrival = _component_label_matrices(
        sessions=(existing_session, future_session),
        issue_times=np.asarray([issue], dtype=np.int64),
        total_labels=total,
    )
    assert existing.shape == arrival.shape == (1, 5)
    assert np.allclose(existing, 10.0)
    assert arrival[0, 0] == pytest.approx(20.0 * 600.0 / 900.0)
    assert np.allclose(arrival[0, 1:], 20.0)
    assert np.allclose(existing + arrival, total, rtol=0.0, atol=1e-6)


def test_component_reconstruction_mismatch_fails_closed() -> None:
    issue = int(datetime(2019, 1, 10, 12, 0, tzinfo=_ZONE).timestamp())
    session = _session(
        connection=issue - 900,
        disconnect=issue + 5 * 3600,
        value=10.0,
    )
    wrong_total = np.zeros((1, 5), dtype=np.float64)
    with pytest.raises(
        StructuredBaselineError,
        match="COMPONENT_RECONSTRUCTION_INVALID",
    ):
        _component_label_matrices(
            sessions=(session,),
            issue_times=np.asarray([issue], dtype=np.int64),
            total_labels=wrong_total,
        )


def test_structured_task_reuses_m3_for_existing_and_m2_for_arrival() -> None:
    issue_times: list[int] = []
    for day in range(2, 22):
        for hour in (0, 12):
            issue_times.append(
                int(datetime(2019, 1, day, hour, 0, tzinfo=_ZONE).timestamp())
            )
    times = np.asarray(issue_times, dtype=np.int64)
    base = np.column_stack(
        [
            np.arange(len(times), dtype=np.float64) + horizon
            for horizon in HORIZONS_MINUTES
        ]
    )
    existing = base * 0.7
    arrival = base * 0.3
    data = MonthData(
        month="2019-01",
        issue_times=times,
        labels=base,
        blocks={
            "M2": _feature_block("M2", times),
            "M3": _feature_block("M3", times),
        },
        processed_snapshot_sha256="e" * 64,
    )
    source = _source_protocol()
    params = {
        (tier, horizon): {}
        for tier in ("M2", "M3")
        for horizon in HORIZONS_MINUTES
    }
    task = predict_structured_task(
        data=data,
        existing_labels=existing,
        arrival_labels=arrival,
        source_protocol=source,
        selected_params=params,
        horizon_minutes=120,
        estimator_factory=lambda _params: _MeanEstimator(),
    )
    assert task.existing_parameter_sha256 == "3" * 64
    assert task.arrival_parameter_sha256 == "2" * 64
    assert task.existing_fit_count == task.arrival_fit_count == 4
    assert np.allclose(task.existing_truth + task.arrival_truth, task.y_true)
    assert np.allclose(
        task.existing_predictions + task.arrival_predictions,
        task.structured_predictions,
    )


def test_baseline_cache_requires_exact_common_rows(tmp_path: Path) -> None:
    issue = np.asarray([1, 2], dtype=np.int64)
    truth = np.asarray([10.0, 20.0], dtype=np.float64)
    path = tmp_path / "2019-01_h015.npz"
    np.savez_compressed(
        path,
        issue_times=issue,
        day_start_utc_s=np.asarray([0, 0], dtype=np.int64),
        y_true=truth,
        m2_predictions=truth,
        m3_predictions=truth,
        equal_predictions=truth,
    )
    loaded = _load_baseline_cache(
        tmp_path,
        month="2019-01",
        horizon=15,
        expected_issue_times=issue,
        expected_truth=truth,
    )
    assert np.array_equal(loaded["y_true"], truth)
    with pytest.raises(StructuredBaselineError, match="COMMON_ROW_IDENTITY_INVALID"):
        _load_baseline_cache(
            tmp_path,
            month="2019-01",
            horizon=15,
            expected_issue_times=issue,
            expected_truth=truth + 1.0,
        )


def test_baseline_private_manifest_detects_cache_tamper(tmp_path: Path) -> None:
    files = []
    for month in DEVELOPMENT_MONTHS:
        for horizon in HORIZONS_MINUTES:
            name = f"{month}_h{horizon:03d}.npz"
            path = tmp_path / name
            np.savez_compressed(
                path,
                issue_times=np.asarray([1], dtype=np.int64),
                day_start_utc_s=np.asarray([0], dtype=np.int64),
                y_true=np.asarray([1.0]),
                m2_predictions=np.asarray([1.0]),
                m3_predictions=np.asarray([1.0]),
                equal_predictions=np.asarray([1.0]),
            )
            files.append(
                {
                    "name": name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    document = {
        "schema_version": "evcf-jpl-development-expert-private-cache/v1",
        "protocol_sha256": "a" * 64,
        "code_commit": "f" * 40,
        "source_model_selection_sha256": "b" * 64,
        "holdout_accessed": False,
        "gate_trained": False,
        "files": sorted(files, key=lambda item: item["name"]),
    }
    manifest = tmp_path / "private_manifest.json"
    manifest.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")),
        encoding="ascii",
    )
    protocol = _structured_protocol(
        hashlib.sha256(manifest.read_bytes()).hexdigest()
    )
    _verify_baseline_private_run(tmp_path, protocol=protocol)

    tampered = tmp_path / "2019-01_h015.npz"
    tampered.write_bytes(tampered.read_bytes() + b"x")
    with pytest.raises(StructuredBaselineError, match="BASELINE_CACHE_INVALID"):
        _verify_baseline_private_run(tmp_path, protocol=protocol)


@pytest.mark.parametrize(
    (
        "overall_s1",
        "overall_m3",
        "overall_equal",
        "horizon_wins",
        "month_wins",
        "expected",
    ),
    [
        (8.0, 9.0, 10.0, 4, 4, "PASS_STRUCTURED_SIGNAL"),
        (9.5, 9.0, 10.0, 2, 2, "MIXED_STRUCTURED_SIGNAL"),
        (11.0, 9.0, 10.0, 0, 0, "STOP_STRUCTURED_ROUTE"),
    ],
)
def test_decision_rules_are_frozen(
    overall_s1: float,
    overall_m3: float,
    overall_equal: float,
    horizon_wins: int,
    month_wins: int,
    expected: str,
) -> None:
    protocol = _structured_protocol()
    pooled_overall = {
        "M2": _metric(12.0),
        "M3": _metric(overall_m3),
        "equal": _metric(overall_equal),
        "S1": _metric(overall_s1),
    }
    horizons = []
    for index, horizon in enumerate(HORIZONS_MINUTES):
        s1 = 9.0 if index < horizon_wins else 10.0
        horizons.append(
            {
                "horizon_minutes": horizon,
                "metrics": {
                    "M2": _metric(12.0),
                    "M3": _metric(9.5),
                    "equal": _metric(10.0),
                    "S1": _metric(s1),
                },
            }
        )
    months = []
    for index, month in enumerate(DEVELOPMENT_MONTHS):
        s1 = 9.0 if index < month_wins else 10.0
        months.append(
            {
                "month": month,
                "metrics": {
                    "M2": _metric(12.0),
                    "M3": _metric(9.5),
                    "equal": _metric(10.0),
                    "S1": _metric(s1),
                },
            }
        )
    result = _decision(
        protocol=protocol,
        pooled_overall=pooled_overall,
        pooled_by_horizon=tuple(horizons),
        pooled_by_month=tuple(months),
    )
    assert result["decision"] == expected
