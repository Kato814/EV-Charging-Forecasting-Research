from __future__ import annotations

import ast
from pathlib import Path

import numpy as np

import evcf.forecasting.acn_jpl_r2_session_set_probe as r2


def _row(index: int, offset: float = 0.0):
    values = {}
    for field_index, field in enumerate(r2.M3_SESSION_FIELDS):
        values[field] = offset + field_index * 10.0 + index
    values["anonymous_session_index"] = index
    return values


def _metrics(value: float):
    return {"mae_a": value}


def _summary_row(horizon: int, joint: float, permuted: float, equal: float, s1: float, r1: float):
    return {
        "horizon_minutes": horizon,
        "R2_Joint": _metrics(joint),
        "R2_Permuted": _metrics(permuted),
        "Equal": _metrics(equal),
        "S1": _metrics(s1),
        "R1_Joint": _metrics(r1),
    }


def test_permuted_control_preserves_every_field_marginal_and_is_reproducible():
    rows = [_row(index) for index in range(6)]
    rows[1][r2.M3_SESSION_FIELDS[2]] = None
    rows[4][r2.M3_SESSION_FIELDS[7]] = None
    issues = np.asarray([1_600_000_000], dtype=np.int64)
    joint, permuted = r2.build_joint_and_permuted((tuple(rows),), issues)
    joint2, permuted2 = r2.build_joint_and_permuted((tuple(reversed(rows)),), issues)
    assert np.allclose(joint[0], joint2[0], equal_nan=True)
    assert np.allclose(permuted[0], permuted2[0], equal_nan=True)
    repeated = r2.build_joint_and_permuted((tuple(rows),), issues)[1][0]
    assert np.allclose(permuted[0], repeated, equal_nan=True)
    changed = False
    for column in range(r2.SESSION_FIELD_COUNT):
        a = joint[0][:, column]
        b = permuted[0][:, column]
        assert np.sum(np.isnan(a)) == np.sum(np.isnan(b))
        assert np.array_equal(np.sort(a[np.isfinite(a)]), np.sort(b[np.isfinite(b)]))
        changed |= not np.allclose(a, b, equal_nan=True)
    assert changed


def test_single_and_empty_sets_are_retained_without_fabricated_rows():
    issue_times = np.asarray([1, 2], dtype=np.int64)
    single = _row(3)
    joint, permuted = r2.build_joint_and_permuted((tuple(), (single,)), issue_times)
    assert joint[0].shape == (0, 11) and permuted[0].shape == (0, 11)
    assert np.allclose(joint[1], permuted[1], equal_nan=True)


def test_m2_fold_preprocessing_is_train_only_and_has_fixed_width():
    raw = np.zeros((4, r2.M2_RAW_WIDTH), dtype=np.float64)
    _names, nullable = r2.canonical_feature_schema("M2")
    raw[0, 0] = 1.0
    raw[1, 0] = 3.0
    raw[2, 0] = 100.0
    raw[2, -1] = np.nan
    raw[0, 5] = np.nan
    train, test = r2._m2_fold_transform(
        raw,
        nullable,
        np.asarray([0, 1], dtype=np.int64),
        np.asarray([2, 3], dtype=np.int64),
    )
    assert train.shape == (2, r2.M2_CONTEXT_WIDTH)
    assert test.shape == (2, r2.M2_CONTEXT_WIDTH)
    assert np.isclose(test[0, 0], 98.0)
    assert test[0, -1] == 1.0
    assert test[1, -1] == 0.0
    assert train[0, 5] == 0.0


def test_session_stats_use_training_sessions_only_and_encoding_keeps_masks():
    groups = (
        np.asarray([[1.0] * 11, [3.0] * 11]),
        np.asarray([[100.0] * 11]),
    )
    means, scales = r2._session_fold_stats(groups, np.asarray([0], dtype=np.int64))
    assert np.allclose(means, 2.0)
    assert np.allclose(scales, 1.0)
    raw = np.asarray([[2.0] * 11], dtype=np.float64)
    raw[0, 4] = np.nan
    encoded = r2._encode_session_groups((raw,), np.asarray([0]), means, scales)[0]
    assert encoded.shape == (1, 22)
    assert encoded[0, 4] == 0.0
    assert encoded[0, 11 + 4] == 0.0
    assert encoded[0, 11] == 1.0


def test_decision_pass_mixed_stop_match_frozen_rules():
    horizons = [
        _summary_row(h, joint=8.0, permuted=9.0, equal=10.0, s1=9.0, r1=9.5)
        for h in r2.HORIZONS_MINUTES
    ]
    months = [
        {
            "month": m,
            "R2_Joint": _metrics(8.0),
            "R2_Permuted": _metrics(9.0),
            "Equal": _metrics(10.0),
            "S1": _metrics(9.0),
            "R1_Joint": _metrics(9.5),
        }
        for m in r2.DEVELOPMENT_MONTHS
    ]
    pooled = {
        "R2_Joint": _metrics(8.0),
        "R2_Permuted": _metrics(9.0),
        "Equal": _metrics(10.0),
        "S1": _metrics(9.0),
        "R1_Joint": _metrics(9.5),
    }
    decision, support = r2.decide(pooled, horizons, months)
    assert decision == "PASS_HIGHER_ORDER_SET_SIGNAL"
    assert support["joint_horizon_wins_vs_permuted"] == 5

    mixed = dict(pooled)
    mixed["S1"] = _metrics(7.5)
    decision, _ = r2.decide(mixed, horizons, months)
    assert decision == "MIXED_HIGHER_ORDER_SET_SIGNAL"

    stop = dict(pooled)
    stop["R2_Joint"] = _metrics(9.5)
    decision, _ = r2.decide(stop, horizons, months)
    assert decision == "STOP_HIGHER_ORDER_SET_ROUTE"


def test_fold_and_permutation_seeds_are_stable_and_scoped():
    assert r2._fold_seed("2019-01", 60, "2019-01-18") == r2._fold_seed(
        "2019-01", 60, "2019-01-18"
    )
    assert r2._fold_seed("2019-01", 60, "2019-01-18") != r2._fold_seed(
        "2019-01", 120, "2019-01-18"
    )
    assert r2._permutation_seed(1_600_000_000, 0) != r2._permutation_seed(1_600_000_000, 1)


def test_protocol_constants_and_holdout_boundary_are_frozen():
    assert r2.DEVELOPMENT_MONTHS == ("2019-01", "2019-04", "2019-07", "2019-10")
    assert r2.FINAL_HOLDOUT_MONTHS == ("2019-03", "2019-06", "2019-09", "2019-12")
    assert set(r2.DEVELOPMENT_MONTHS).isdisjoint(r2.FINAL_HOLDOUT_MONTHS)
    assert r2.M2_RAW_WIDTH == 201 and r2.M2_CONTEXT_WIDTH == 204
    assert r2.SESSION_INPUT_WIDTH == 22
    assert r2.EPOCHS == 30 and r2.BATCH_SIZE == 256
    assert r2.EXPECTED_FIT_COUNT == 550


def test_module_does_not_import_torch_at_module_import_time():
    tree = ast.parse(Path(r2.__file__).read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert "torch" not in imports


def test_joint_input_does_not_contain_session_identifier():
    source = Path(r2.__file__).read_text()
    start = source.index("def _raw_session_group")
    end = source.index("def build_joint_and_permuted")
    raw_group_source = source[start:end]
    assert "M3_SESSION_FIELDS" in raw_group_source
    assert "anonymous_session_index" in raw_group_source
    assert "matrix[r, c]" in raw_group_source
    assert "matrix[r," not in raw_group_source.split("for c, field", 1)[0]
