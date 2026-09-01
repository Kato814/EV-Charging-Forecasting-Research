from __future__ import annotations

import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import scripts.run_jpl_gate1_pilot as cli
from scripts.run_jpl_gate1_pilot import (
    RUN_AUTHORIZATION_MESSAGE,
    THREAD_CAP_ENV_VARS,
    build_parser,
    run_pilot_cli,
)


def test_unauthorized_cli_stops_before_delayed_runner_or_files(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    stdout = io.StringIO()
    roots = [tmp_path / name for name in ("processed", "interim", "local", "public")]
    for name in THREAD_CAP_ENV_VARS:
        monkeypatch.setenv(name, "8")

    def forbidden_runner(**kwargs: Any) -> Any:
        raise AssertionError(f"unauthorized invocation called runner: {kwargs}")

    status = run_pilot_cli(
        authorized=False,
        config_path=tmp_path / "missing-config.yaml",
        processed_root=roots[0],
        interim_root=roots[1],
        local_run_root=roots[2],
        public_root=roots[3],
        runner=forbidden_runner,
        stdout=stdout,
    )

    assert status == 2
    assert stdout.getvalue() == RUN_AUTHORIZATION_MESSAGE + "\n"
    assert all(not path.exists() for path in roots)
    assert {name: os.environ.get(name) for name in THREAD_CAP_ENV_VARS} == {
        name: "8" for name in THREAD_CAP_ENV_VARS
    }


def test_authorized_cli_forwards_exact_paths_and_prints_safe_aggregate(tmp_path: Path) -> None:
    stdout = io.StringIO()
    observed: dict[str, Any] = {}
    paths = {
        "config_path": tmp_path / "config.yaml",
        "processed_root": tmp_path / "processed",
        "interim_root": tmp_path / "interim",
        "local_run_root": tmp_path / "private-run",
        "public_root": tmp_path / "public",
    }

    def runner(**kwargs: Any) -> SimpleNamespace:
        observed.update(kwargs)
        return SimpleNamespace(
            status="PASS_ACTIVE_SESSION_DROP_M4",
            task_count=40,
            public_file_count=13,
            reproducibility_status="REFERENCE_PUBLISHED",
        )

    status = run_pilot_cli(
        authorized=True,
        runner=runner,
        stdout=stdout,
        **paths,
    )

    assert status == 0
    assert observed == {"authorized": True, **paths}
    assert json.loads(stdout.getvalue()) == {
        "public_file_count": 13,
        "reproducibility_status": "REFERENCE_PUBLISHED",
        "status": "PASS_ACTIVE_SESSION_DROP_M4",
        "task_count": 40,
    }
    assert str(tmp_path) not in stdout.getvalue()


def test_authorized_cli_caps_all_native_thread_pools_before_delayed_runner(
    monkeypatch: Any,
) -> None:
    stdout = io.StringIO()
    for name in THREAD_CAP_ENV_VARS:
        monkeypatch.setenv(name, "8")

    def runner(**kwargs: Any) -> SimpleNamespace:
        del kwargs
        assert {name: os.environ.get(name) for name in THREAD_CAP_ENV_VARS} == {
            name: "1" for name in THREAD_CAP_ENV_VARS
        }
        return SimpleNamespace(
            status="FAIL_DIRECTION",
            task_count=40,
            public_file_count=13,
            reproducibility_status="REFERENCE_PUBLISHED",
        )

    assert run_pilot_cli(authorized=True, runner=runner, stdout=stdout) == 0


def test_cli_failure_has_execution_fail_precedence_and_hides_exception(tmp_path: Path) -> None:
    stdout = io.StringIO()

    def failing_runner(**kwargs: Any) -> Any:
        raise RuntimeError(f"fixture-token at {tmp_path.resolve()}")

    status = run_pilot_cli(authorized=True, runner=failing_runner, stdout=stdout)

    assert status == 1
    assert json.loads(stdout.getvalue()) == {
        "public_file_count": 0,
        "reproducibility_status": "NOT_VERIFIED",
        "status": "EXECUTION_FAIL",
        "task_count": 0,
    }
    assert "fixture-token" not in stdout.getvalue()
    assert str(tmp_path) not in stdout.getvalue()


def test_thread_cap_or_delayed_import_failure_is_reported_as_execution_fail(
    monkeypatch: Any,
) -> None:
    stdout = io.StringIO()

    def fail_caps() -> None:
        raise OSError("private environment failure")

    monkeypatch.setattr(cli, "_cap_native_threads", fail_caps)
    status = run_pilot_cli(authorized=True, stdout=stdout)

    assert status == 1
    assert json.loads(stdout.getvalue())["status"] == "EXECUTION_FAIL"
    assert "private environment failure" not in stdout.getvalue()


def test_cli_rejects_pilot_import_origin_from_another_worktree(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    stdout = io.StringIO()
    monkeypatch.setattr(
        cli.importlib.util,
        "find_spec",
        lambda name: SimpleNamespace(origin=str(tmp_path / "other" / "acn_jpl_gate1_pilot.py")),
    )

    status = run_pilot_cli(authorized=True, stdout=stdout)

    assert status == 1
    assert json.loads(stdout.getvalue())["status"] == "EXECUTION_FAIL"
    assert str(tmp_path) not in stdout.getvalue()


def test_cli_coerces_incomplete_or_forged_success_to_execution_fail() -> None:
    stdout = io.StringIO()
    forged = SimpleNamespace(
        status="PASS_ACTIVE_SESSION",
        task_count=39,
        public_file_count=13,
        reproducibility_status="REFERENCE_PUBLISHED",
    )

    status = run_pilot_cli(
        authorized=True,
        runner=lambda **kwargs: forged,
        stdout=stdout,
    )

    assert status == 1
    assert json.loads(stdout.getvalue())["status"] == "EXECUTION_FAIL"


def test_parser_uses_formal_command_defaults_and_literal_authorization() -> None:
    parser = build_parser()
    defaults = parser.parse_args([])
    authorized = parser.parse_args(["--authorize-run"])

    assert defaults.authorize_run is False
    assert defaults.config_path == Path("code/configs/acn_jpl_gate1_pilot_2019-05.yaml")
    assert defaults.processed_root == Path("data/processed/acn/jpl/2019-05")
    assert defaults.interim_root == Path("data/interim/acn/jpl/2019-05")
    assert defaults.local_run_root == Path("outputs/runs/jpl-2019-05-gate1-pilot-seed20260901")
    assert defaults.public_root == Path("outputs/gate1_pilot/jpl_2019-05")
    assert authorized.authorize_run is True


def test_cli_module_keeps_heavy_pipeline_import_behind_authorization_gate() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "scripts/run_jpl_gate1_pilot.py").read_text(encoding="utf-8")
    import_line = "from evcf.forecasting.acn_jpl_gate1_pilot import run_gate1_pilot"
    cap_call = "    _cap_native_threads()\n"

    assert source.count(import_line) == 1
    assert source.count(cap_call) == 1
    assert source.index(cap_call) < source.index(import_line)
    assert source.index("if authorized is not True:") < source.index(import_line)
    assert "requests" not in source
    assert "acnportal" not in source.casefold()
