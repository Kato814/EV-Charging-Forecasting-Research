from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import evcf.forecasting.acn_jpl_r11_s0_backbone as controller
import evcf.forecasting.acn_jpl_r11_s0_common as common
import evcf.forecasting.acn_jpl_r11_s0_data as data_module
import evcf.forecasting.acn_jpl_r11_s0_models as models
from evcf.forecasting.acn_jpl_gate1_features import canonical_feature_schema


def _fake_month_data(row_count: int = 3):
    names, nullable = canonical_feature_schema("M2")
    values = np.zeros((row_count, len(names)), dtype=np.float64)
    values[:, :96] = np.arange(96, dtype=np.float64)[None, :]
    values[:, 96:192] = 1.0
    values[:, 192:] = 99_999.0
    issue_times = np.arange(1_546_300_800, 1_546_300_800 + row_count * 900, 900, dtype=np.int64)
    block = SimpleNamespace(
        issue_times=issue_times,
        values=values,
        feature_names=names,
        nullable_mask=nullable,
    )
    return SimpleNamespace(
        month="2019-01",
        issue_times=issue_times,
        labels=np.tile(np.arange(1.0, 6.0, dtype=np.float64), (row_count, 1)),
        blocks={"M2": block},
    )


def _anchor(mae: float = 10.0):
    return {
        "pooled": {"mae_a": mae},
        "by_horizon": [
            {"horizon_minutes": h, "mae_a": mae} for h in common.HORIZONS_MINUTES
        ],
        "by_month": [{"month": m, "mae_a": mae} for m in common.DEVELOPMENT_MONTHS],
    }


def _deep_entry(
    pooled: float, *, cell: float | None = None, spread: float = 0.01, params: int = 100_000
):
    cell = pooled if cell is None else cell
    return {
        "parameter_count": params,
        "median": {
            "pooled_mae_a": pooled,
            "pooled_seed_spread": spread,
            "by_horizon": [
                {"horizon_minutes": h, "mae_a": cell} for h in common.HORIZONS_MINUTES
            ],
            "by_month": [{"month": m, "mae_a": cell} for m in common.DEVELOPMENT_MONTHS],
        },
    }


def test_protocol_constants_and_holdout_boundary_are_frozen():
    assert common.DEVELOPMENT_MONTHS == ("2019-01", "2019-04", "2019-07", "2019-10")
    assert common.FINAL_HOLDOUT_MONTHS == ("2019-03", "2019-06", "2019-09", "2019-12")
    assert set(common.DEVELOPMENT_MONTHS).isdisjoint(common.FINAL_HOLDOUT_MONTHS)
    assert common.HORIZONS_MINUTES == (15, 30, 60, 120, 240)
    assert common.CONTEXT_LENGTH == 96
    assert common.DEEP_ARCHITECTURES == ("gru", "tcn", "nhits", "patchtst")
    assert common.DEEP_SEEDS == (2026091401, 2026091402, 2026091403)
    assert common.EXPECTED_FIT_COUNT == 68


def test_station_input_contract_reads_only_history_and_mask_from_m2():
    station = data_module.station_month_from_frozen_data(_fake_month_data())
    assert station.history_raw.shape == (3, 96)
    assert station.history_mask.shape == (3, 96)
    assert np.all(station.history_mask == 1.0)
    assert np.max(station.history_raw) < 1000.0
    assert station.issue_context.shape == (3, 5)
    assert station.target_context.shape == (3, 5, 6)
    assert station.labels.shape == (3, 5)


def test_train_only_scaler_zero_fills_unobserved_after_standardization():
    history = np.zeros((2, 96), dtype=np.float64)
    history[0, :2] = [1.0, 2.0]
    history[1, :2] = [3.0, 1000.0]
    mask = np.zeros_like(history)
    mask[0, :2] = 1.0
    mask[1, 0] = 1.0
    labels = np.ones((2, 5), dtype=np.float64)
    scaler = data_module.fit_scaler(history, mask, labels)
    transformed = data_module.transform_history(history, mask, scaler)
    assert transformed.shape == (2, 96, 2)
    assert transformed[1, 1, 0] == 0.0
    assert transformed[1, 1, 1] == 0.0


def test_calendar_context_is_horizon_conditioned():
    issue = np.asarray([1_546_300_800], dtype=np.int64)
    issue_context, target_context = data_module.calendar_context(issue)
    assert issue_context.shape == (1, 5)
    assert target_context.shape == (1, 5, 6)
    assert np.allclose(target_context[0, :, -1], np.asarray(common.HORIZONS_MINUTES) / 240.0)
    assert not np.allclose(target_context[0, 0], target_context[0, -1])


def test_decision_select_mixed_and_stop_match_frozen_rules():
    deep = {name: _deep_entry(12.0) for name in common.DEEP_ARCHITECTURES}
    deep["tcn"] = _deep_entry(9.9, params=120_000)
    decision, selected, support = controller.decide_backbone(
        station_hgb=_anchor(), deep_models=deep
    )
    assert decision == "SELECT_STATION_BACKBONE"
    assert selected == "tcn"
    assert support["tcn"]["eligible"] is True

    mixed = {name: _deep_entry(10.1, cell=11.5) for name in common.DEEP_ARCHITECTURES}
    decision, selected, _ = controller.decide_backbone(station_hgb=_anchor(), deep_models=mixed)
    assert decision == "MIXED_STATION_BACKBONE"
    assert selected is None

    stop = {name: _deep_entry(10.3) for name in common.DEEP_ARCHITECTURES}
    decision, selected, _ = controller.decide_backbone(station_hgb=_anchor(), deep_models=stop)
    assert decision == "STOP_DEEP_CORE_ROUTE"
    assert selected is None


def test_tie_breaker_prefers_smaller_model_inside_quarter_percent():
    deep = {name: _deep_entry(12.0) for name in common.DEEP_ARCHITECTURES}
    deep["gru"] = _deep_entry(9.9000, params=150_000)
    deep["tcn"] = _deep_entry(9.9150, params=100_000)
    decision, selected, _ = controller.decide_backbone(station_hgb=_anchor(), deep_models=deep)
    assert decision == "SELECT_STATION_BACKBONE"
    assert selected == "tcn"


def test_torch_is_lazy_imported():
    tree = ast.parse(Path(models.__file__).read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert "torch" not in imports


def test_deep_shapes_and_frozen_parameter_counts():
    torch = pytest.importorskip("torch")
    counts = dict(models.parameter_count_report(torch))
    assert counts == {
        "gru": 93697,
        "tcn": 118785,
        "nhits": 116133,
        "patchtst": 76737,
    }
    history = torch.zeros((2, 96, 2), dtype=torch.float32)
    issue = torch.zeros((2, 5), dtype=torch.float32)
    target = torch.zeros((2, 5, 6), dtype=torch.float32)
    for name in common.DEEP_ARCHITECTURES:
        output = models.make_deep_model(torch, name)(history, issue, target)
        assert output.shape == (2, 5)
        assert common.MIN_PARAMETER_COUNT <= counts[name] <= common.MAX_PARAMETER_COUNT


def test_implementation_paths_include_all_r11_runtime_modules():
    assert "code/src/evcf/forecasting/acn_jpl_r11_s0_common.py" in controller.IMPLEMENTATION_PATHS
    assert "code/src/evcf/forecasting/acn_jpl_r11_s0_data.py" in controller.IMPLEMENTATION_PATHS
    assert "code/src/evcf/forecasting/acn_jpl_r11_s0_models.py" in controller.IMPLEMENTATION_PATHS
    assert "scripts/run_jpl_r11_s0_backbone.py" in controller.IMPLEMENTATION_PATHS
