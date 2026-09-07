from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from evcf.data.acn_jpl_development_months import DEVELOPMENT_MONTHS, FINAL_HOLDOUT_MONTHS
from evcf.data.acn_jpl_month_config import jpl_month_config

from scripts.acquire_jpl_development import (
    DEVELOPMENT_AUTHORIZATION_MESSAGE,
    DEVELOPMENT_MISSING_TOKEN_MESSAGE,
    build_parser,
    run_development_cli,
)


class _ForbiddenEnvironment(dict[str, str]):
    def get(self, key: str, default: Any = None) -> Any:
        raise AssertionError(f"environment must not be read: {key} {default}")


def test_unauthorized_stops_before_environment_or_executor(tmp_path: Path) -> None:
    stdout = io.StringIO()
    calls: list[str] = []

    def forbidden(**kwargs: Any) -> Any:
        calls.append("executor")
        raise AssertionError("unauthorized CLI must stop")

    status = run_development_cli(
        authorized=False,
        metadata_root=tmp_path / "metadata",
        raw_root=tmp_path / "raw",
        environ=_ForbiddenEnvironment(),
        month_executor=forbidden,
        stdout=stdout,
    )

    assert status == 2
    assert stdout.getvalue() == DEVELOPMENT_AUTHORIZATION_MESSAGE + "\n"
    assert calls == []
    assert not (tmp_path / "raw").exists()


def test_missing_token_stops_before_registry_install_or_files(tmp_path: Path) -> None:
    stdout = io.StringIO()

    status = run_development_cli(
        authorized=True,
        metadata_root=tmp_path / "metadata",
        raw_root=tmp_path / "raw",
        environ={},
        month_executor=lambda **kwargs: {},
        stdout=stdout,
    )

    assert status == 2
    assert stdout.getvalue() == DEVELOPMENT_MISSING_TOKEN_MESSAGE + "\n"
    assert not (tmp_path / "raw").exists()
    for month in DEVELOPMENT_MONTHS:
        with pytest.raises(ValueError, match="approved JPL month"):
            jpl_month_config(month)


def test_authorized_cli_uses_only_fixed_development_order_and_restores_registry(
    tmp_path: Path,
) -> None:
    stdout = io.StringIO()
    calls: list[str] = []
    token = "fixture-development-token"

    def executor(**kwargs: Any) -> dict[str, Any]:
        config = kwargs["config"]
        calls.append(config.month)
        assert kwargs["token"] == token
        assert kwargs["raw_root"] == tmp_path / "raw" / config.month
        return {
            "month": config.month,
            "acquisition_status": "COMPLETE",
            "qa_status": "PASS",
            "valid_daily_chunks": config.day_count,
            "local_records": 3,
            "carry_records": 1,
            "combined_records": 4,
            "trajectory_quarantine_count": 0,
            "trajectory_quarantine_rate": 0.0,
            "full_session_quarantine_count": 0,
            "reason_codes": [],
        }

    status = run_development_cli(
        authorized=True,
        metadata_root=tmp_path / "metadata",
        raw_root=tmp_path / "raw",
        environ={"ACN_API_TOKEN": token},
        month_executor=executor,
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert status == 0
    assert payload["status"] == "COMPLETE"
    assert payload["holdout_accessed"] is False
    assert calls == list(DEVELOPMENT_MONTHS)
    assert [row["month"] for row in payload["months"]] == list(DEVELOPMENT_MONTHS)
    assert all(row["status"] == "PASS" for row in payload["months"])
    for month in (*DEVELOPMENT_MONTHS, *FINAL_HOLDOUT_MONTHS):
        with pytest.raises(ValueError, match="approved JPL month"):
            jpl_month_config(month)


def test_failure_is_redacted_and_does_not_unlock_holdout(tmp_path: Path) -> None:
    stdout = io.StringIO()
    private = "https://private.invalid/?token=fixture-development-token"

    def executor(**kwargs: Any) -> dict[str, Any]:
        if kwargs["config"].month == "2019-04":
            raise RuntimeError(private)
        config = kwargs["config"]
        return {
            "month": config.month,
            "acquisition_status": "COMPLETE",
            "qa_status": "PASS",
            "valid_daily_chunks": config.day_count,
            "local_records": 1,
            "carry_records": 0,
            "combined_records": 1,
            "trajectory_quarantine_count": 0,
            "trajectory_quarantine_rate": 0.0,
            "full_session_quarantine_count": 0,
            "reason_codes": [],
        }

    status = run_development_cli(
        authorized=True,
        metadata_root=tmp_path / "metadata",
        raw_root=tmp_path / "raw",
        environ={"ACN_API_TOKEN": "fixture-development-token"},
        month_executor=executor,
        stdout=stdout,
    )

    rendered = stdout.getvalue()
    payload = json.loads(rendered)
    assert status == 1
    assert payload["status"] == "INCOMPLETE"
    assert payload["holdout_accessed"] is False
    assert payload["months"][1]["status"] == "FAIL"
    assert payload["months"][1]["reason_codes"] == ["UNEXPECTED_ERROR"]
    assert private not in rendered
    assert "fixture-development-token" not in rendered
    assert str(tmp_path) not in rendered
    for month in FINAL_HOLDOUT_MONTHS:
        with pytest.raises(ValueError, match="approved JPL month"):
            jpl_month_config(month)


def test_parser_has_literal_authorization_and_no_month_override() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "--authorize-development",
            "--metadata-root",
            "metadata",
        ]
    )
    assert args.authorize_development is True
    assert args.metadata_root == Path("metadata")
    assert args.raw_root == Path("data/raw/acn/jpl/development")
    assert args.concurrency == 1
    assert not hasattr(args, "month")
    assert not hasattr(args, "months")

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--authorize-development",
                "--metadata-root",
                "metadata",
                "--month",
                "2019-03",
            ]
        )


@pytest.mark.parametrize("concurrency", [0, 3, True])
def test_invalid_concurrency_rejected_before_environment(
    tmp_path: Path,
    concurrency: object,
) -> None:
    with pytest.raises(ValueError, match="1 or 2"):
        run_development_cli(
            authorized=True,
            metadata_root=tmp_path / "metadata",
            raw_root=tmp_path / "raw",
            concurrency=concurrency,  # type: ignore[arg-type]
            environ=_ForbiddenEnvironment(),
            month_executor=lambda **kwargs: {},
            stdout=io.StringIO(),
        )
