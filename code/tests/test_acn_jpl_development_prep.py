from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from evcf.data.acn_jpl_development_months import DEVELOPMENT_MONTHS, FINAL_HOLDOUT_MONTHS
from evcf.data.acn_jpl_development_prep import (
    DevelopmentPreparationResult,
    prepare_jpl_development_data,
    verify_development_implementation_commit,
)
from evcf.data.acn_jpl_month_config import jpl_month_config
from evcf.data.acn_jpl_seasonal_prep import (
    MonthPreparationResult,
    SeasonalPreparationError,
    load_seasonal_preparation_protocol,
)


def _fake_month_result(
    *,
    month: str,
    code_commit: str,
    config_sha256: str,
    trajectory_count: int = 0,
) -> MonthPreparationResult:
    result = object.__new__(MonthPreparationResult)
    values = {
        "month": month,
        "status": "CONDITIONAL_PASS",
        "official_total": 10,
        "local_session_count": 10,
        "carry_in_count": 0,
        "sessions_processed": 10,
        "cleaned_session_count": 10,
        "invalid_skipped_session_count": 0,
        "trajectory_quarantine_count": trajectory_count,
        "full_session_quarantine_count": 0,
        "station_bins": 100,
        "valid_bin_90_count": 90,
        "scheduled_issue_times": 80,
        "formal_issue_times": 70,
        "power_semantics_status": "CURRENT_PROXY_ONLY",
        "grid_policy": "continuous_physical_utc",
        "raw_dimensions": (195, 201, 311),
        "encoded_dimensions": (195, 204, 391),
        "config_sha256": config_sha256,
        "code_commit": code_commit,
        "metadata_source_inventory_sha256": "1" * 64,
        "metadata_record_inventory_sha256": "2" * 64,
        "raw_inventory_sha256": "3" * 64,
        "processed_snapshot_sha256": "4" * 64,
        "raw_unchanged": True,
        "artifacts": (),
    }
    for name, value in values.items():
        object.__setattr__(result, name, value)
    return result


def _roots(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    metadata = tmp_path / "metadata"
    raw = tmp_path / "raw-development"
    interim = tmp_path / "interim-development"
    processed = tmp_path / "processed-development"
    metadata.mkdir()
    raw.mkdir()
    return metadata, raw, interim, processed


def test_unauthorized_stops_before_filesystem_or_verifier(tmp_path: Path) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"must not run: {args} {kwargs}")

    with pytest.raises(SeasonalPreparationError) as caught:
        prepare_jpl_development_data(
            authorized=False,
            metadata_root=tmp_path / "missing-metadata",
            raw_root=tmp_path / "missing-raw",
            interim_root=tmp_path / "interim",
            processed_root=tmp_path / "processed",
            code_commit="0" * 40,
            month_runner=forbidden,  # type: ignore[arg-type]
            implementation_verifier=forbidden,
        )
    assert caught.value.reason_code == "PREPARATION_NOT_AUTHORIZED"


def test_fixed_order_uses_development_months_only_and_restores_holdout(tmp_path: Path) -> None:
    metadata, raw, interim, processed = _roots(tmp_path)
    protocol = load_seasonal_preparation_protocol()
    code_commit = "a" * 40
    calls: list[str] = []

    def runner(**kwargs: object) -> MonthPreparationResult:
        config = kwargs["config"]
        month = config.month  # type: ignore[union-attr]
        calls.append(month)
        assert kwargs["raw_root"] == raw / month
        assert kwargs["interim_root"] == interim / month
        assert kwargs["processed_root"] == processed / month
        return _fake_month_result(
            month=month,
            code_commit=code_commit,
            config_sha256=protocol.config_sha256,
        )

    result = prepare_jpl_development_data(
        authorized=True,
        metadata_root=metadata,
        raw_root=raw,
        interim_root=interim,
        processed_root=processed,
        code_commit=code_commit,
        month_runner=runner,
        implementation_verifier=lambda *_args, **_kwargs: None,
    )

    assert type(result) is DevelopmentPreparationResult
    assert result.status == "COMPLETE"
    assert tuple(item.month for item in result.months) == DEVELOPMENT_MONTHS
    assert calls == list(DEVELOPMENT_MONTHS)
    assert result.holdout_accessed is False
    for month in (*DEVELOPMENT_MONTHS, *FINAL_HOLDOUT_MONTHS):
        with pytest.raises(ValueError, match="approved JPL month"):
            jpl_month_config(month)


def test_unapproved_quarantine_result_fails_and_restores_registry(tmp_path: Path) -> None:
    metadata, raw, interim, processed = _roots(tmp_path)
    protocol = load_seasonal_preparation_protocol()
    code_commit = "b" * 40

    def runner(**kwargs: object) -> MonthPreparationResult:
        config = kwargs["config"]
        month = config.month  # type: ignore[union-attr]
        return _fake_month_result(
            month=month,
            code_commit=code_commit,
            config_sha256=protocol.config_sha256,
            trajectory_count=1 if month == "2019-04" else 0,
        )

    with pytest.raises(SeasonalPreparationError) as caught:
        prepare_jpl_development_data(
            authorized=True,
            metadata_root=metadata,
            raw_root=raw,
            interim_root=interim,
            processed_root=processed,
            code_commit=code_commit,
            month_runner=runner,
            implementation_verifier=lambda *_args, **_kwargs: None,
        )
    assert caught.value.reason_code == "MONTH_RESULT_BINDING_INVALID"
    for month in (*DEVELOPMENT_MONTHS, *FINAL_HOLDOUT_MONTHS):
        with pytest.raises(ValueError, match="approved JPL month"):
            jpl_month_config(month)


def test_output_roots_cannot_overlap_raw(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata"
    raw = tmp_path / "raw"
    metadata.mkdir()
    raw.mkdir()
    with pytest.raises(SeasonalPreparationError) as caught:
        prepare_jpl_development_data(
            authorized=True,
            metadata_root=metadata,
            raw_root=raw,
            interim_root=raw / "interim",
            processed_root=tmp_path / "processed",
            code_commit="c" * 40,
            month_runner=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("no run")),
            implementation_verifier=lambda *_args, **_kwargs: None,
        )
    assert caught.value.reason_code == "OUTPUT_TOPOLOGY_INVALID"


def test_current_checkout_satisfies_development_implementation_binding() -> None:
    root = Path.cwd()
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
    ).strip()
    assert len(head) == 40
    verify_development_implementation_commit(head, repo_root=root)
