from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from evcf.forecasting.acn_jpl_structured_baseline import _CleanCurrentSession
from evcf.forecasting.acn_jpl_structured_mechanism_p1 import MechanismP1Error
from evcf.forecasting.acn_jpl_structured_mechanism_p1_runtime import (
    _RuntimeIndexedSession,
    _build_candidate_table,
    _load_m3_session_features_runtime,
    _pooled_extension,
)


def _empty_runtime_session() -> _RuntimeIndexedSession:
    empty_i = np.asarray([], dtype=np.int64)
    empty_f = np.asarray([], dtype=np.float64)
    current = _CleanCurrentSession(
        connection_utc_s=900,
        disconnect_utc_s=5_000,
        starts=empty_i,
        ends=empty_i.copy(),
        values=empty_f,
    )
    return _RuntimeIndexedSession(
        session_index=0,
        connection_utc_s=900,
        disconnect_utc_s=5_000,
        current=current,
        current_times=empty_i,
        current_values=empty_f,
        pilot_times=empty_i.copy(),
        pilot_values=empty_f.copy(),
        user_inputs=[],
    )


def _write_frozen_m3(
    month_root: Path,
    *,
    issue_times: np.ndarray,
    extension: np.ndarray,
) -> None:
    month_root.mkdir()
    values = np.zeros((len(issue_times), 311), dtype=np.float64)
    values[:, 201:] = extension
    np.save(month_root / "M3.issue_times.npy", issue_times, allow_pickle=False)
    np.save(month_root / "M3.values.npy", values, allow_pickle=False)


def test_runtime_rebuild_does_not_require_ragged_m3_file(tmp_path: Path) -> None:
    issue_times = np.asarray([1_000], dtype=np.int64)
    sessions = (_empty_runtime_session(),)
    expected = _build_candidate_table(
        issue_times=issue_times,
        sessions=sessions,
        preserve_unobserved_trajectory_missingness=True,
    )
    extension = _pooled_extension(expected, issue_count=1)
    month_root = tmp_path / "2019-01"
    _write_frozen_m3(month_root, issue_times=issue_times, extension=extension)

    ragged_path = month_root / "m3.jsonl.gz"
    assert not ragged_path.exists()
    rebuilt = _load_m3_session_features_runtime(
        ragged_path,
        issue_times=issue_times,
        sessions=sessions,
    )

    assert np.array_equal(rebuilt.issue_indices, expected.issue_indices)
    assert np.array_equal(rebuilt.session_indices, expected.session_indices)
    assert np.allclose(
        rebuilt.raw_features,
        expected.raw_features,
        rtol=0,
        atol=0,
        equal_nan=True,
    )


def test_runtime_rebuild_fails_closed_on_frozen_m3_mismatch(tmp_path: Path) -> None:
    issue_times = np.asarray([1_000], dtype=np.int64)
    sessions = (_empty_runtime_session(),)
    expected = _build_candidate_table(
        issue_times=issue_times,
        sessions=sessions,
        preserve_unobserved_trajectory_missingness=True,
    )
    extension = _pooled_extension(expected, issue_count=1)
    extension[0, 0] += 1.0
    month_root = tmp_path / "2019-01"
    _write_frozen_m3(month_root, issue_times=issue_times, extension=extension)

    with pytest.raises(MechanismP1Error, match="SESSION_FEATURE_RECONSTRUCTION_INVALID"):
        _load_m3_session_features_runtime(
            month_root / "m3.jsonl.gz",
            issue_times=issue_times,
            sessions=sessions,
        )
