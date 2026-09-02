from __future__ import annotations

import ast
import io
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import prepare_jpl_seasonal_data as cli_module
from scripts.prepare_jpl_seasonal_data import (
    PREPARATION_AUTHORIZATION_MESSAGE,
    build_parser,
    run_prepare_cli,
)


class _ForbiddenPath:
    def __fspath__(self) -> str:
        raise AssertionError("path conversion happened before authorization")


def _seasonal_result():
    from evcf.data.acn_jpl_seasonal_prep import SeasonalPreparationResult
    from test_acn_jpl_seasonal_prep import _month_result

    months = tuple(_month_result(month) for month in ("2019-02", "2019-08", "2019-11"))
    return SeasonalPreparationResult(
        status="CONDITIONAL_PASS",
        months=months,
        config_sha256="1" * 64,
        code_commit="a" * 40,
    )


def test_unauthorized_stops_before_path_import_runner_or_output_mutation() -> None:
    stdout = io.StringIO()
    calls: list[str] = []

    def forbidden(**kwargs: Any) -> object:
        calls.append("runner")
        raise AssertionError("runner called before authorization")

    status = run_prepare_cli(
        authorized=False,
        metadata_root=_ForbiddenPath(),
        raw_root=_ForbiddenPath(),
        interim_root=_ForbiddenPath(),
        processed_root=_ForbiddenPath(),
        public_root=_ForbiddenPath(),
        code_commit="not-read",
        repo_root=_ForbiddenPath(),
        protocol_path=_ForbiddenPath(),
        runner=forbidden,
        stdout=stdout,
    )

    assert status == 2
    assert calls == []
    assert stdout.getvalue() == PREPARATION_AUTHORIZATION_MESSAGE + "\n"


def test_authorized_cli_accepts_only_typed_result_and_prints_safe_aggregates(
    tmp_path: Path,
) -> None:
    stdout = io.StringIO()
    calls: list[dict[str, object]] = []

    def runner(**kwargs: object) -> object:
        calls.append(kwargs)
        return _seasonal_result()

    status = run_prepare_cli(
        authorized=True,
        metadata_root=tmp_path / "metadata",
        raw_root=tmp_path / "raw",
        interim_root=tmp_path / "interim",
        processed_root=tmp_path / "processed",
        public_root=tmp_path / "public",
        code_commit="a" * 40,
        repo_root=tmp_path,
        protocol_path=tmp_path / "protocol.yaml",
        runner=runner,
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert status == 0
    assert len(calls) == 1
    assert calls[0]["authorized"] is True
    assert payload == {
        "status": "CONDITIONAL_PASS",
        "months": [
            {
                "month": month,
                "status": "CONDITIONAL_PASS",
                "sessions_processed": 10,
                "cleaned_session_count": 9,
                "invalid_skipped_session_count": 1,
                "station_bins": bins,
                "valid_bin_90_count": (4 * bins + 4) // 5,
                "scheduled_issue_times": scheduled,
                "formal_issue_times": scheduled,
            }
            for month, bins, scheduled in (
                ("2019-02", 2688, 2577),
                ("2019-08", 2976, 2865),
                ("2019-11", 2884, 2773),
            )
        ],
    }
    rendered = stdout.getvalue()
    assert str(tmp_path) not in rendered
    assert "sha256" not in rendered.lower()
    assert "sessionID" not in rendered


@pytest.mark.parametrize("malformed", [{}, {"status": "PASS", "months": []}])
def test_cli_rejects_mapping_results_and_redacts_exception_material(
    tmp_path: Path,
    malformed: object,
) -> None:
    stdout = io.StringIO()
    secret = f"{tmp_path} https://private.invalid/?token=sentinel"

    def runner(**kwargs: object) -> object:
        if malformed:
            return malformed
        raise RuntimeError(secret)

    status = run_prepare_cli(
        authorized=True,
        metadata_root="metadata",
        raw_root="raw",
        interim_root="interim",
        processed_root="processed",
        public_root="public",
        code_commit="a" * 40,
        repo_root=".",
        protocol_path="protocol.yaml",
        runner=runner,
        stdout=stdout,
    )

    assert status == 1
    assert json.loads(stdout.getvalue()) == {
        "status": "FAIL",
        "months": [],
        "reason_code": "UNEXPECTED_ERROR",
    }
    assert secret not in stdout.getvalue()
    assert "sentinel" not in stdout.getvalue()


def test_parser_is_fixed_scope_and_module_has_no_evcf_import_before_authorization() -> None:
    parser = build_parser()
    args = parser.parse_args(["--authorize-prepare"])
    assert args.authorize_prepare is True
    for forbidden in ("month", "months", "model", "network", "token"):
        assert not hasattr(args, forbidden)
    with pytest.raises(SystemExit):
        parser.parse_args(["--authorize-prepare", "--month", "2019-08"])

    source = Path(cli_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert not any(
        (isinstance(node, ast.ImportFrom) and (node.module or "").startswith("evcf"))
        or (
            isinstance(node, ast.Import)
            and any(alias.name.startswith("evcf") for alias in node.names)
        )
        for node in imports
    )
