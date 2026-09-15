from __future__ import annotations

from evcf.forecasting.r11_s0_screen import CandidateSummary, decide_backbone


def _c(name: str, mae: float, *, h: float = 0.05, m: float = 0.05, spread: float = 0.01, p: int = 100_000):
    return CandidateSummary(name, mae, h, m, spread, p, True)


def test_selects_best_eligible_candidate():
    candidates = {
        "GRU": _c("GRU", 10.05),
        "TCN": _c("TCN", 9.90),
        "NHiTS": _c("NHiTS", 10.10),
        "PatchTST": _c("PatchTST", 10.00),
    }
    decision, selected, support = decide_backbone(10.0, candidates)
    assert decision == "SELECT_STATION_BACKBONE"
    assert selected == "TCN"
    assert support["TCN"]["eligible"] is True


def test_tie_band_prefers_smaller_parameter_count():
    candidates = {
        "GRU": _c("GRU", 10.000, p=120_000),
        "TCN": _c("TCN", 10.020, p=90_000),
        "NHiTS": _c("NHiTS", 10.10, p=110_000),
        "PatchTST": _c("PatchTST", 10.15, p=100_000),
    }
    decision, selected, _ = decide_backbone(10.0, candidates)
    assert decision == "SELECT_STATION_BACKBONE"
    assert selected == "TCN"


def test_mixed_when_pooled_is_near_but_stability_gate_fails():
    candidates = {
        "GRU": _c("GRU", 10.01, h=0.11),
        "TCN": _c("TCN", 10.10, m=0.12),
        "NHiTS": _c("NHiTS", 10.15, h=0.11),
        "PatchTST": _c("PatchTST", 10.18, m=0.11),
    }
    decision, selected, _ = decide_backbone(10.0, candidates)
    assert decision == "MIXED_STATION_BACKBONE"
    assert selected is None


def test_stop_when_every_model_is_outside_pooled_or_seed_ceiling():
    candidates = {
        "GRU": _c("GRU", 10.30),
        "TCN": _c("TCN", 10.40),
        "NHiTS": _c("NHiTS", 10.50),
        "PatchTST": _c("PatchTST", 10.60),
    }
    decision, selected, _ = decide_backbone(10.0, candidates)
    assert decision == "STOP_DEEP_CORE_ROUTE"
    assert selected is None
