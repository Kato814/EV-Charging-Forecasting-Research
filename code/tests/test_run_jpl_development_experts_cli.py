from __future__ import annotations

import io
import json

import pytest

from scripts.run_jpl_development_experts import AUTHORIZATION_MESSAGE, build_parser, run_cli


def test_unauthorized_expert_run_stops_before_private_paths() -> None:
    stdout = io.StringIO()
    status = run_cli(
        authorized=False,
        interim_root="private-interim",
        processed_root="private-processed",
        private_output_root="private-output",
        code_commit="0" * 40,
        repo_root="private-repo",
        stdout=stdout,
    )
    assert status == 2
    assert stdout.getvalue() == AUTHORIZATION_MESSAGE + "\n"


def test_authorized_failure_redacts_paths_and_exception_text() -> None:
    stdout = io.StringIO()
    private = "C:/private/development/data"
    status = run_cli(
        authorized=True,
        interim_root=private,
        processed_root=private,
        private_output_root=private,
        code_commit="0" * 40,
        repo_root=private,
        stdout=stdout,
    )
    payload = json.loads(stdout.getvalue())
    assert status == 1
    assert payload["status"] == "FAIL"
    assert payload["reason_code"] == "UNEXPECTED_ERROR"
    assert payload["holdout_accessed"] is False
    assert private not in stdout.getvalue()


def test_parser_has_no_month_or_holdout_override() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "--authorize-development-experts",
            "--interim-root",
            "interim",
            "--processed-root",
            "processed",
            "--private-output-root",
            "private",
            "--code-commit",
            "a" * 40,
        ]
    )
    assert args.authorize_development_experts is True
    assert not hasattr(args, "month")
    assert not hasattr(args, "months")
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--authorize-development-experts",
                "--interim-root",
                "interim",
                "--processed-root",
                "processed",
                "--private-output-root",
                "private",
                "--code-commit",
                "a" * 40,
                "--month",
                "2019-03",
            ]
        )
