from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from evcf.data.acn_jpl_preparation import (
    DEFAULT_INTERIM_ROOT,
    DEFAULT_PROCESSED_ROOT,
    DEFAULT_PUBLIC_ROOT,
    DEFAULT_RAW_ROOT,
)

from scripts.prepare_jpl_gate1_data import (
    PREPARATION_AUTHORIZATION_MESSAGE,
    build_parser,
    run_prepare_cli,
)


def _successful_summary() -> dict[str, object]:
    return {
        "status": "PASS",
        "raw_unchanged": "PASS",
        "sessions_processed": 1645,
        "station_bins": 2976,
        "scheduled_issue_times": 2865,
        "formal_issue_times": 2810,
        "power_semantics_status": "CURRENT_PROXY_ONLY",
        "training_environment_frozen": "NO",
    }


def test_unauthorized_stops_before_runner_or_files(tmp_path: Path) -> None:
    output = io.StringIO()
    roots = [tmp_path / name for name in ("raw", "interim", "processed", "public")]

    def forbidden_runner(**kwargs: Any) -> Any:
        raise AssertionError(f"unauthorized invocation called runner: {kwargs}")

    status = run_prepare_cli(
        authorized=False,
        raw_root=roots[0],
        interim_root=roots[1],
        processed_root=roots[2],
        public_root=roots[3],
        runner=forbidden_runner,
        stdout=output,
    )

    assert status == 2
    assert output.getvalue() == PREPARATION_AUTHORIZATION_MESSAGE + "\n"
    assert all(not root.exists() for root in roots)


def test_authorized_calls_injected_runner_and_prints_only_safe_aggregates(
    tmp_path: Path,
) -> None:
    output = io.StringIO()
    roots = [tmp_path / name for name in ("private raw", "interim", "processed", "public")]
    secret = "fixture-private-token"
    observed: dict[str, Any] = {}

    def runner(**kwargs: Any) -> SimpleNamespace:
        observed.update(kwargs)
        summary = _successful_summary()
        summary.update(
            {
                "absolute_path": str(roots[0].resolve()),
                "credential": secret,
                "private_record": {"private_identifier": "sentinel"},
            }
        )
        return SimpleNamespace(summary=summary)

    status = run_prepare_cli(
        authorized=True,
        raw_root=roots[0],
        interim_root=roots[1],
        processed_root=roots[2],
        public_root=roots[3],
        runner=runner,
        stdout=output,
    )

    assert status == 0
    assert observed == {
        "raw_root": roots[0],
        "interim_root": roots[1],
        "processed_root": roots[2],
        "public_root": roots[3],
    }
    assert json.loads(output.getvalue()) == _successful_summary()
    rendered = output.getvalue()
    assert secret not in rendered
    assert str(roots[0]) not in rendered
    assert str(roots[0].resolve()) not in rendered
    assert "private_identifier" not in rendered


def test_direct_mapping_result_is_supported_and_conditional_pass_succeeds() -> None:
    output = io.StringIO()
    summary = _successful_summary()
    summary["status"] = "CONDITIONAL_PASS"
    summary["raw_unchanged"] = True

    status = run_prepare_cli(
        authorized=True,
        runner=lambda **kwargs: summary,
        stdout=output,
    )

    assert status == 0
    assert json.loads(output.getvalue()) == {
        **summary,
        "raw_unchanged": "PASS",
    }


def test_runner_failure_does_not_echo_exception_details(tmp_path: Path) -> None:
    output = io.StringIO()
    secret = "fixture-private-token"
    private_path = tmp_path / "private raw"

    def failing_runner(**kwargs: Any) -> Any:
        raise RuntimeError(f"{secret} at {private_path.resolve()}")

    status = run_prepare_cli(
        authorized=True,
        raw_root=private_path,
        runner=failing_runner,
        stdout=output,
    )

    assert status == 1
    payload = json.loads(output.getvalue())
    assert payload == {
        "formal_issue_times": 0,
        "power_semantics_status": "NOT_RUN",
        "raw_unchanged": "NOT_VERIFIED",
        "scheduled_issue_times": 0,
        "sessions_processed": 0,
        "station_bins": 0,
        "status": "FAIL",
        "training_environment_frozen": "NO",
    }
    assert secret not in output.getvalue()
    assert str(private_path) not in output.getvalue()


def test_structured_stop_exception_preserves_safe_power_and_raw_status() -> None:
    output = io.StringIO()

    class StructuredStop(RuntimeError):
        def __init__(self) -> None:
            super().__init__("safe structured stop")
            self.summary = {
                **_successful_summary(),
                "status": "FAIL",
                "raw_unchanged": True,
                "station_bins": 0,
                "scheduled_issue_times": 0,
                "formal_issue_times": 0,
                "power_semantics_status": "POWER_SEMANTICS_FAIL",
            }

    def stopped_runner(**kwargs: Any) -> Any:
        raise StructuredStop

    status = run_prepare_cli(
        authorized=True,
        runner=stopped_runner,
        stdout=output,
    )

    payload = json.loads(output.getvalue())
    assert status == 1
    assert payload["raw_unchanged"] == "PASS"
    assert payload["power_semantics_status"] == "POWER_SEMANTICS_FAIL"
    assert payload["sessions_processed"] == 1645


def test_parser_uses_closed_defaults_and_literal_authorization_flag() -> None:
    parser = build_parser()
    defaults = parser.parse_args([])
    authorized = parser.parse_args(["--authorize-prepare"])
    explicit_output = parser.parse_args(["--output-root", "aggregate-output"])

    assert defaults.authorize_prepare is False
    assert defaults.raw_root == DEFAULT_RAW_ROOT
    assert defaults.interim_root == DEFAULT_INTERIM_ROOT
    assert defaults.processed_root == DEFAULT_PROCESSED_ROOT
    assert defaults.public_root == DEFAULT_PUBLIC_ROOT
    assert authorized.authorize_prepare is True
    assert explicit_output.public_root == Path("aggregate-output")
