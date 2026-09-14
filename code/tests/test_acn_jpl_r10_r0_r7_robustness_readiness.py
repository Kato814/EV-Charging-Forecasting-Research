from __future__ import annotations

import numpy as np
import pytest
from evcf.forecasting.acn_jpl_r10_r0_r7_robustness_readiness import (
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    DEVELOPMENT_MONTHS,
    HORIZONS_MINUTES,
    R10R0Error,
    _bootstrap,
    _daily_audit,
    _leave_one,
    _original_stability,
    decide_r10,
    run_r10_r0,
)


def _synthetic_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    issue_times = np.asarray([100, 200, 86_500, 86_600], dtype=np.int64)
    day_starts = np.asarray([0, 0, 86_400, 86_400], dtype=np.int64)
    truth = np.asarray([10.0, 10.0, 20.0, 20.0])
    candidate = np.asarray([9.0, 11.0, 19.0, 21.0])
    s1 = np.asarray([8.0, 12.0, 18.0, 22.0])
    equal = np.asarray([7.0, 13.0, 17.0, 23.0])
    for month in DEVELOPMENT_MONTHS:
        for horizon in HORIZONS_MINUTES:
            records.append(
                {
                    "month": month,
                    "horizon": horizon,
                    "issue_times": issue_times,
                    "day_starts": day_starts,
                    "truth": truth,
                    "candidate": candidate,
                    "s1": s1,
                    "equal": equal,
                    "arrival_truth": truth,
                    "base_arrival": s1,
                    "availability_arrival": candidate,
                    "departure_arrival": candidate,
                }
            )
    return records


def _decision_inputs() -> tuple[dict[str, float], dict[str, float], dict[str, int], dict[str, int], dict[str, float]]:
    pooled = {"TotalDeparture_mae_a": 9.0, "S1_mae_a": 10.0, "Equal_mae_a": 11.0}
    daily = {"win_rate_vs_S1": 0.60, "win_rate_vs_Equal": 0.60}
    leave_month = {"wins_vs_S1": 4, "wins_vs_Equal": 4}
    leave_horizon = {"wins_vs_S1": 4, "wins_vs_Equal": 4}
    stability = {
        "month_wins_vs_S1": 3,
        "month_wins_vs_Equal": 3,
        "horizon_wins_vs_S1": 3,
        "horizon_wins_vs_Equal": 3,
        "worst_month_relative_degradation_vs_S1": 0.04,
        "worst_month_relative_degradation_vs_Equal": 0.03,
    }
    return pooled, daily, leave_month, leave_horizon, stability


def test_daily_audit_pairs_complete_days_across_all_horizons() -> None:
    summary, deltas = _daily_audit(_synthetic_records())
    assert summary["day_count"] == 8
    assert summary["win_rate_vs_S1"] == 1.0
    assert summary["win_rate_vs_Equal"] == 1.0
    assert len(summary["per_month"]) == 4
    assert all(item["day_count"] == 2 for item in summary["per_month"])
    assert set(deltas) == set(DEVELOPMENT_MONTHS)


def test_leave_one_and_original_stability_use_all_frozen_axes() -> None:
    records = _synthetic_records()
    leave_month = _leave_one(records, axis="month")
    leave_horizon = _leave_one(records, axis="horizon")
    stability = _original_stability(records)
    assert leave_month["wins_vs_S1"] == 4
    assert leave_month["wins_vs_Equal"] == 4
    assert leave_horizon["wins_vs_S1"] == 5
    assert leave_horizon["wins_vs_Equal"] == 5
    assert stability["month_wins_vs_S1"] == 4
    assert stability["horizon_wins_vs_Equal"] == 5


def test_bootstrap_is_deterministic_and_uses_frozen_protocol() -> None:
    deltas = {
        month: {
            "vs_S1": np.asarray([-1.0, -2.0]),
            "vs_Equal": np.asarray([-2.0, -3.0]),
        }
        for month in DEVELOPMENT_MONTHS
    }
    first = _bootstrap(deltas)
    second = _bootstrap(deltas)
    assert first == second
    assert first["seed"] == BOOTSTRAP_SEED
    assert first["replicates"] == BOOTSTRAP_REPLICATES
    assert first["vs_S1"]["fraction_delta_below_zero"] == 1.0
    assert first["vs_Equal"]["q95_delta_a"] < 0.0


def test_decision_ready_requires_all_frozen_readiness_conditions() -> None:
    decision, support = decide_r10(*_decision_inputs())
    assert decision == "READY_FOR_SINGLE_SHOT_HOLDOUT_PROTOCOL"
    assert support["leave_one_month_wins_vs_S1"] == 4
    assert support["day_win_rate_vs_Equal"] == 0.60


def test_decision_fragile_is_evaluated_before_ready() -> None:
    pooled, daily, leave_month, leave_horizon, stability = _decision_inputs()
    daily["win_rate_vs_S1"] = 0.39
    decision, _ = decide_r10(pooled, daily, leave_month, leave_horizon, stability)
    assert decision == "FRAGILE_DEVELOPMENT_SIGNAL"


def test_decision_mixed_when_not_fragile_but_not_ready() -> None:
    pooled, daily, leave_month, leave_horizon, stability = _decision_inputs()
    daily["win_rate_vs_S1"] = 0.45
    daily["win_rate_vs_Equal"] = 0.45
    decision, _ = decide_r10(pooled, daily, leave_month, leave_horizon, stability)
    assert decision == "MIXED_DEVELOPMENT_ROBUSTNESS"


def test_unauthorized_run_stops_before_private_cache_access() -> None:
    with pytest.raises(R10R0Error, match="R10_R0_NOT_AUTHORIZED"):
        run_r10_r0(
            authorized=False,
            r7_d1_private_run="does-not-exist/r7-d1",
            code_commit="0" * 40,
        )
