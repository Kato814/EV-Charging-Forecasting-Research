from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from evcf.data.acn_jpl_development_prep import DevelopmentPreparationResult

from scripts.prepare_jpl_development import (
    DEVELOPMENT_PREPARATION_AUTHORIZATION_MESSAGE,
    build_parser,
    run_development_prepare_cli,
)


def _fake_result() -> DevelopmentPreparationResult:
    result = object.__new__(DevelopmentPreparationResult)
    months = tuple(
        SimpleNamespace(
            month=month,
            status="CONDITIONAL_PASS",
            sessions_processed=100 + index,
            cleaned_session_count=100 + index,
            invalid_skipped_session_count=0,
            trajectory_quarantine_count=0,
            full_session_quarantine_count=0,
            station_bins=2976 if month != "2019-04" else 2880,
            valid_bin_90_count=2500,
            scheduled_issue_times=2865 if month != "2019-04" else 2769,
            formal_issue_times=2400,
            power_semantics_status="CURRENT_PROXY_ONLY",
            processed_snapshot_sha256=str(index + 1) * 64,
            raw_unchanged=True,
        )
        for index, month in enumerate(("2019-01", "2019-04", "2019-07", "2019-10"))
    )
    for name, value in {
        "status": "COMPLETE",
        "months": months,
        "protocol_sha256": "a" * 64,
        "code_commit": "b" * 40,
        "holdout_accessed": False,
    }.items():
        object.__setattr__(result, name, value)
    return result


def test_unauthorized_stops_before_runner_or_paths() -> None:
    stdout = io.StringIO()

    def forbidden(**kwargs: object) -> object:
        raise AssertionError(f"runner must not be called: {kwargs}")

    status = run_development_prepare_cli(
        authorized=False,
        metadata_root="private-metadata",
        raw_root="private-raw",
        interim_root="private-interim",
        processed_root="private-processed",
        code_commit="0" * 40,
        runner=forbidden,
        stdout=stdout,
    )

    assert status == 2
    assert stdout.getvalue() == DEVELOPMENT_PREPARATION_AUTHORIZATION_MESSAGE + "\n"


def test_success_stdout_is_aggregate_only_and_has_fixed_months() -> None:
    stdout = io.StringIO()
    calls: list[dict[str, object]] = []

    def runner(**kwargs: object) -> object:
        calls.append(kwargs)
        return _fake_result()

    status = run_development_prepare_cli(
        authorized=True,
        metadata_root="private-metadata",
        raw_root="private-raw",
        interim_root="private-interim",
        processed_root="private-processed",
        code_commit="b" * 40,
        repo_root="private-repo",
        runner=runner,
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert status == 0
    assert len(calls) == 1
    assert payload["status"] == "COMPLETE"
    assert [item["month"] for item in payload["months"]] == [
        "2019-01",
        "2019-04",
        "2019-07",
        "2019-10",
    ]
    assert payload["holdout_accessed"] is False
    assert payload["models_trained"] is False
    assert payload["public_seasonal_release_created"] is False
    rendered = stdout.getvalue()
    for private in (
        "private-metadata",
        "private-raw",
        "private-interim",
        "private-processed",
        "private-repo",
    ):
        assert private not in rendered


def test_failure_redacts_exception_and_emits_static_reason() -> None:
    stdout = io.StringIO()
    private = "C:/private/session/identifier"

    class Failure(RuntimeError):
        reason_code = "VALID_BIN_90_GATE_FAILED"

    def runner(**_kwargs: object) -> object:
        raise Failure(private)

    status = run_development_prepare_cli(
        authorized=True,
        metadata_root="private-metadata",
        raw_root="private-raw",
        interim_root="private-interim",
        processed_root="private-processed",
        code_commit="c" * 40,
        runner=runner,
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert status == 1
    assert payload["status"] == "FAIL"
    assert payload["reason_code"] == "VALID_BIN_90_GATE_FAILED"
    assert payload["holdout_accessed"] is False
    assert private not in stdout.getvalue()


def test_parser_requires_explicit_roots_and_has_no_month_override() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "--authorize-development-prepare",
            "--metadata-root",
            "metadata",
            "--raw-root",
            "raw",
            "--interim-root",
            "interim",
            "--processed-root",
            "processed",
            "--code-commit",
            "d" * 40,
        ]
    )
    assert args.authorize_development_prepare is True
    assert args.protocol_path == Path("code/configs/acn_jpl_development_prep_2019.yaml")
    assert not hasattr(args, "month")
    assert not hasattr(args, "months")
    assert not hasattr(args, "public_root")

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--authorize-development-prepare",
                "--metadata-root",
                "metadata",
                "--raw-root",
                "raw",
                "--interim-root",
                "interim",
                "--processed-root",
                "processed",
                "--code-commit",
                "d" * 40,
                "--month",
                "2019-03",
            ]
        )
