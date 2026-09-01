from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from scripts.acn_jpl_full_month_ts import (
    DEFAULT_OUTPUT_ROOT,
    FULL_MONTH_AUTHORIZATION_MESSAGE,
    FULL_MONTH_MISSING_TOKEN_MESSAGE,
    build_parser,
    run_full_month_cli,
)


def _complete_acquisition() -> dict[str, Any]:
    return {
        "status": "COMPLETE",
        "daily": {
            "requested_days": 31,
            "completed_days": 31,
            "pending_days": 0,
            "failed_days": 0,
        },
        "linkage": {"status": "PASS"},
        "carry_in": {"status": "SKIPPED"},
    }


def _qa_result(status: str = "PASS") -> SimpleNamespace:
    return SimpleNamespace(
        gate_status=status,
        qa={
            "integrity": {
                "daily_chunks": {"valid": 31, "failed_or_incomplete": 0},
                "local_month": {"observed_records": 1644},
                "carry_in": {"observed_records": 1},
                "combined": {"observed_records": 1645},
            },
            "gate": {
                "status": status,
                "ready_for_cleaning": status == "PASS",
                "ready_for_15_min": ("YES_CURRENT_PROXY_ONLY" if status == "PASS" else "NO"),
                "gate1_ready": "NO",
            },
        },
    )


class _ForbiddenEnvironment(dict[str, str]):
    def get(self, key: str, default: Any = None) -> Any:
        raise AssertionError(f"environment must not be read: {key} {default}")


def test_unauthorized_refuses_before_environment_client_or_files(tmp_path: Path) -> None:
    output = io.StringIO()
    metadata_root = tmp_path / "metadata-must-not-exist"
    raw_root = tmp_path / "raw-must-not-exist"
    public_root = tmp_path / "public-must-not-exist"

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("unauthorized invocation must stop immediately")

    status = run_full_month_cli(
        authorized=False,
        metadata_root=metadata_root,
        raw_root=raw_root,
        output_root=public_root,
        environ=_ForbiddenEnvironment(),
        client_factory=forbidden,
        acquisition_runner=forbidden,
        qa_runner=forbidden,
        stdout=output,
    )

    assert status == 2
    assert output.getvalue() == FULL_MONTH_AUTHORIZATION_MESSAGE + "\n"
    assert not metadata_root.exists()
    assert not raw_root.exists()
    assert not public_root.exists()


def test_missing_token_is_static_and_stops_before_client_or_files(tmp_path: Path) -> None:
    output = io.StringIO()

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("missing credential must stop immediately")

    status = run_full_month_cli(
        authorized=True,
        metadata_root=tmp_path / "metadata",
        raw_root=tmp_path / "raw",
        output_root=tmp_path / "public",
        environ={},
        client_factory=forbidden,
        acquisition_runner=forbidden,
        qa_runner=forbidden,
        stdout=output,
    )

    assert status == 2
    assert output.getvalue() == FULL_MONTH_MISSING_TOKEN_MESSAGE + "\n"
    assert "None" not in output.getvalue()
    assert not (tmp_path / "raw").exists()
    assert not (tmp_path / "public").exists()


def test_authorized_run_calls_acquisition_then_qa_and_prints_aggregates_only(
    tmp_path: Path,
) -> None:
    output = io.StringIO()
    sentinel = "fixture-secret-token"
    metadata_root = tmp_path / "private metadata"
    raw_root = tmp_path / "private raw"
    public_root = tmp_path / "public artifacts"
    calls: list[str] = []
    observed: dict[str, Any] = {}
    fake_client = object()

    def acquisition_runner(**kwargs: Any) -> dict[str, Any]:
        calls.append("acquisition")
        observed["acquisition"] = kwargs
        assert kwargs["client_factory"]() is fake_client
        return _complete_acquisition()

    def qa_runner(**kwargs: Any) -> SimpleNamespace:
        calls.append("qa")
        observed["qa"] = kwargs
        return _qa_result()

    status = run_full_month_cli(
        authorized=True,
        metadata_root=metadata_root,
        raw_root=raw_root,
        output_root=public_root,
        environ={"ACN_API_TOKEN": sentinel},
        client_factory=lambda: fake_client,
        acquisition_runner=acquisition_runner,
        qa_runner=qa_runner,
        stdout=output,
    )

    payload = json.loads(output.getvalue())
    assert status == 0
    assert calls == ["acquisition", "qa"]
    assert observed["acquisition"]["authorized"] is True
    assert observed["acquisition"]["metadata_root"] == metadata_root
    assert observed["acquisition"]["raw_root"] == raw_root
    assert observed["qa"]["output_root"] == public_root
    assert observed["qa"]["acquisition_result"]["status"] == "COMPLETE"
    assert tuple(observed["qa"]["sensitive_values"]) == (sentinel,)
    assert payload == {
        "acquisition_status": "COMPLETE",
        "carry_records": 1,
        "combined_records": 1645,
        "failed_daily_chunks": 0,
        "gate1_ready": "NO",
        "local_records": 1644,
        "qa_status": "PASS",
        "ready_for_15_min": "YES_CURRENT_PROXY_ONLY",
        "ready_for_cleaning": True,
        "valid_daily_chunks": 31,
    }
    rendered = output.getvalue()
    assert sentinel not in rendered
    assert str(metadata_root) not in rendered
    assert str(raw_root) not in rendered
    assert str(public_root) not in rendered
    assert "sessionID" not in rendered
    assert "query_condition" not in rendered


def test_incomplete_acquisition_or_failed_qa_returns_one(tmp_path: Path) -> None:
    output = io.StringIO()
    incomplete = _complete_acquisition()
    incomplete["status"] = "INCOMPLETE"

    status = run_full_month_cli(
        authorized=True,
        metadata_root=tmp_path / "metadata",
        raw_root=tmp_path / "raw",
        output_root=tmp_path / "public",
        environ={"ACN_API_TOKEN": "fixture-secret-token"},
        client_factory=object,
        acquisition_runner=lambda **kwargs: incomplete,
        qa_runner=lambda **kwargs: _qa_result("FAIL"),
        stdout=output,
    )

    assert status == 1
    payload = json.loads(output.getvalue())
    assert payload["acquisition_status"] == "INCOMPLETE"
    assert payload["qa_status"] == "FAIL"
    assert payload["ready_for_15_min"] == "NO"
    assert payload["gate1_ready"] == "NO"


def test_parser_requires_roots_and_literal_authorization_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "--metadata-root",
            "metadata",
            "--raw-root",
            "raw",
            "--authorize-full-month",
        ]
    )
    assert args.metadata_root == Path("metadata")
    assert args.raw_root == Path("raw")
    assert args.output_root == DEFAULT_OUTPUT_ROOT
    assert args.authorize_full_month is True


def test_config_keeps_full_month_disabled_without_runtime_opt_in() -> None:
    config = yaml.safe_load(Path("code/configs/acn_gate0.yaml").read_text(encoding="utf-8"))
    protocol = config["jpl_2019_05_full_month_timeseries"]
    assert protocol == {
        "timezone": "America/Los_Angeles",
        "analysis_start": "2019-05-01T00:00:00-07:00",
        "analysis_end_exclusive": "2019-06-01T00:00:00-07:00",
        "expected_local_sessions": 1644,
        "expected_utc_sessions": 1645,
        "expected_carry_in_sessions": 1,
        "quality_denominator_sessions": 1645,
        "invalid_charging_current_rate_limit": 0.10,
        "invalid_pilot_signal_rate_limit": 0.10,
        "full_month_timeseries_authorized": False,
        "required_cli_flag": "--authorize-full-month",
        "gate1_authorized": False,
        "generate_15_min_data": False,
    }


def test_gitignore_allowlists_only_the_seven_public_files_and_environment_record() -> None:
    lines = set(Path(".gitignore").read_text(encoding="utf-8").splitlines())
    public_root = "!outputs/acn_gate0/jpl_2019-05-full-ts/"
    required = {
        public_root,
        "!outputs/acn_gate0/jpl_2019-05-full-ts/qa_full_month_timeseries.json",
        "!outputs/acn_gate0/jpl_2019-05-full-ts/acquisition_summary.json",
        "!outputs/acn_gate0/jpl_2019-05-full-ts/acquisition_summary.md",
        "!outputs/acn_gate0/jpl_2019-05-full-ts/daily_chunk_summary.csv",
        "!outputs/acn_gate0/jpl_2019-05-full-ts/failed_or_incomplete_chunks.csv",
        "!outputs/acn_gate0/jpl_2019-05-full-ts/cleaning_rule_manifest.json",
        "!outputs/acn_gate0/jpl_2019-05-full-ts/SHA256SUMS",
        "!outputs/environment/",
        "!outputs/environment/local_rtx5080.json",
    }
    assert required <= lines
    assert "!outputs/acn_gate0/jpl_2019-05-full-ts/**" not in lines
    assert "!data/raw/**" not in lines


def test_ci_lints_full_month_controller_qa_cli_and_tests() -> None:
    workflow = Path(".github/workflows/library-check.yml").read_text(encoding="utf-8")
    assert "python -m ruff check code/src scripts code/tests" in workflow
