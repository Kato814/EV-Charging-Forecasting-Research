from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any

import evcf.forecasting.acn_jpl_gate1_pilot as pilot
import numpy as np
import pytest
from evcf.forecasting.acn_jpl_gate1_pilot import (
    CANONICAL_MODEL_TASKS,
    PUBLIC_FILENAMES,
    Gate1PilotExecutionError,
    assert_public_release_safe,
    build_public_release_files,
    canonical_csv_bytes,
    canonical_json_bytes,
    run_gate1_pilot,
)

EXPECTED_PUBLIC_FILENAMES = (
    "gate1_summary.json",
    "gate1_decision.md",
    "metrics_by_horizon.csv",
    "tier_comparison.csv",
    "daily_paired_errors.csv",
    "bootstrap_intervals.json",
    "peak_ramp_metrics.json",
    "model_selection_manifest.json",
    "feature_encoding_manifest.json",
    "environment_manifest.json",
    "run_manifest.json",
    "data_snapshot_manifest.json",
    "SHA256SUMS",
)


def _echo_task_from_worker(task: tuple[str, str, int]) -> SimpleNamespace:
    return SimpleNamespace(task=task)


def _aggregate_payload() -> dict[str, Any]:
    return {
        "schema_version": "acn-jpl-gate1-public-metrics/v1",
        "units": {"primary": "A"},
        "metrics_by_horizon": [
            {
                "model_kind": "learned",
                "learner": "ridge",
                "tier": "M1",
                "baseline": None,
                "horizon_minutes": 15,
                "overall": {"mae_a": 0.1, "n_available": 1329},
                "daily": [],
                "weekday": {"mae_a": 0.1},
                "weekend": {"mae_a": 0.2},
            }
        ],
        "tier_comparisons": [
            {
                "learner": "hgb",
                "parent_tier": "M2",
                "child_tier": "M3",
                "horizon_minutes": 15,
                "relative_improvement_percent": 3.0,
            }
        ],
        "daily_paired_errors": [
            {
                "learner": "hgb",
                "parent_tier": "M2",
                "child_tier": "M3",
                "horizon_minutes": 15,
                "local_date": "2019-05-18",
                "absolute_error_delta_a": 0.25,
            }
        ],
        "bootstrap": {
            "plan": {"seed": 20260902, "repetitions": 10000},
            "intervals": [
                {
                    "learner": "hgb",
                    "parent_tier": "M2",
                    "child_tier": "M3",
                    "horizon_minutes": 15,
                    "ci_lower_a": 0.0,
                    "ci_upper_a": 0.5,
                }
            ],
        },
        "peak_ramp_metrics": [
            {
                "model_kind": "learned",
                "learner": "hgb",
                "tier": "M3",
                "baseline": None,
                "horizon_minutes": 15,
                "ramp_mae_a": 0.125,
            }
        ],
        "gate": {
            "classification": "PASS_ACTIVE_SESSION_DROP_M4",
            "execution_ok": True,
            "blocking_issues": [],
        },
        "privacy": {
            "aggregate_only": True,
            "full_test_values_published": False,
            "bootstrap_draws_published": False,
            "local_paths_published": False,
            "private_identifiers_published": False,
        },
    }


def _safe_manifest(schema: str) -> dict[str, Any]:
    return {
        "schema_version": schema,
        "sha256": "a" * 64,
        "audits": {
            "aggregate_only": True,
            "local_paths_published": False,
            "model_objects_published": False,
        },
    }


def _rendered_release() -> MappingProxyType[str, bytes]:
    return pilot._render_public_release_from_aggregate(
        aggregate_payload=_aggregate_payload(),
        model_selection_manifest=_safe_manifest("model/v1"),
        feature_encoding_manifest=_safe_manifest("feature/v1"),
        environment_manifest=_safe_manifest("environment/v1"),
        run_manifest=_safe_manifest("run/v1"),
        data_snapshot_manifest=_safe_manifest("data/v1"),
    )


def test_canonical_task_order_is_exactly_the_frozen_40() -> None:
    expected = tuple(
        (learner, tier, horizon)
        for learner in ("ridge", "hgb")
        for tier in ("M1", "M2", "M3", "M4")
        for horizon in (15, 30, 60, 120, 240)
    )

    assert CANONICAL_MODEL_TASKS == expected
    assert len(CANONICAL_MODEL_TASKS) == 40
    assert len(set(CANONICAL_MODEL_TASKS)) == 40


def test_public_release_allowlist_is_exactly_13_files() -> None:
    assert PUBLIC_FILENAMES == EXPECTED_PUBLIC_FILENAMES
    assert len(PUBLIC_FILENAMES) == 13


def test_canonical_serializers_use_lf_sorted_keys_and_17_digit_floats() -> None:
    encoded = canonical_json_bytes({"z": 0.1, "a": [1.25, True, None]})
    assert encoded == (
        b'{\n  "a": [\n    1.25,\n    true,\n    null\n  ],\n  "z": 0.10000000000000001\n}\n'
    )
    rows = [
        {"b": {"nested": 0.1}, "a": 1.25},
        {"b": [1, 2], "a": -0.0},
    ]
    csv_bytes = canonical_csv_bytes(rows)
    assert b"\r\n" not in csv_bytes
    assert csv_bytes.startswith(b'a,b\n1.25,"{""nested"":0.10000000000000001}"\n')
    assert csv_bytes.endswith(b'-0,"[1,2]"\n')


@pytest.mark.parametrize(
    "payload",
    [
        {"sessionID": "abc"},
        {"_id": "abc"},
        {"sessionIDs": ["abc"]},
        {"userIDs": ["abc"]},
        {"anonymous_session_index": 4},
        {"safe": "C:\\private\\snapshot.json"},
        {"safe": "source=C:\\private\\snapshot.json"},
        {"safe": "embeddedC:\\private\\snapshot.json"},
        {"safe": "/home/user/private.json"},
        {"safe": "/data/private.json"},
        {"safe": "/etc/private.json"},
        {"safe": "file:///private/snapshot.json"},
        {"safe": "Bearer fixture-secret"},
        {"api_token": "fixture-secret"},
        {"token": "fixture-secret"},
        {"predictions": [1.0, 2.0]},
        {"complete_issue_time_predictions": [1.0, 2.0]},
        {"full_predictions_published": [1.0, 2.0]},
        {"safe": np.asarray([1.0])},
        {"safe": "fitted-model.joblib"},
    ],
)
def test_privacy_scan_rejects_identifiers_paths_secrets_predictions_arrays_and_models(
    payload: Any,
) -> None:
    with pytest.raises((TypeError, ValueError), match="forbidden|private|absolute|array|model"):
        assert_public_release_safe(payload)


def test_privacy_scan_accepts_aggregate_prediction_audit_flags() -> None:
    assert_public_release_safe(
        {
            "test_prediction_clipping": False,
            "test_prediction_calibration": False,
            "full_predictions_published": False,
            "full_test_values_published": False,
            "aggregate_mean_error_a": 0.125,
            "documentation_url": "https://example.org/gate1/v1",
        }
    )


def test_public_builder_rejects_unsealed_mapping_instead_of_accepting_self_report() -> None:
    with pytest.raises(TypeError, match="Gate1EvaluationResult|formal"):
        build_public_release_files(
            evaluation_result=_aggregate_payload(),  # type: ignore[arg-type]
            model_selection_manifest=_safe_manifest("model/v1"),
            feature_encoding_manifest=_safe_manifest("feature/v1"),
            environment_manifest=_safe_manifest("environment/v1"),
            run_manifest=_safe_manifest("run/v1"),
            data_snapshot_manifest=_safe_manifest("data/v1"),
        )


def test_rendered_public_release_has_exact_allowlist_and_sha_coverage() -> None:
    files = _rendered_release()

    assert tuple(files) == PUBLIC_FILENAMES
    assert all(name == Path(name).name for name in files)
    checksum_lines = files["SHA256SUMS"].decode("ascii").splitlines()
    assert len(checksum_lines) == 12
    expected = {
        f"{hashlib.sha256(files[name]).hexdigest()}  {name}"
        for name in PUBLIC_FILENAMES
        if name != "SHA256SUMS"
    }
    assert set(checksum_lines) == expected
    assert all(value.endswith(b"\n") for value in files.values())


def test_environment_and_run_manifests_are_path_free_and_machine_invariant() -> None:
    evidence = pilot._EnvironmentEvidence(
        python_version="3.11.16",
        operating_system="Windows",
        dependencies=MappingProxyType(
            {
                "joblib": "1.6.0",
                "numpy": "2.4.6",
                "pandas": "3.0.5",
                "pyarrow": "25.0.1",
                "pyyaml": "6.0.3",
                "pytest": "9.1.1",
                "requests": "2.34.2",
                "ruff": "0.16.5",
                "scikit-learn": "1.9.0",
                "scipy": "1.17.1",
            }
        ),
        thread_caps=MappingProxyType({name: "1" for name in pilot.THREAD_CAP_ENV_VARS}),
    )
    environment = pilot._environment_manifest(
        evidence,
        execution_commit_sha="b" * 40,
        data_snapshot_sha256="e" * 64,
        config_sha256="d" * 64,
        config_file_sha256="c" * 64,
    )
    run = pilot._run_manifest(
        execution_commit_sha="b" * 40,
        config_file_sha256="c" * 64,
        config_contract_sha256="d" * 64,
        data_snapshot_sha256="e" * 64,
        snapshot_verification_sha256="f" * 64,
        split_sha256="1" * 64,
        formal_implementation_sha256="2" * 64,
    )
    rendered = json.dumps({"environment": environment, "run": run}, sort_keys=True)

    for forbidden in ("timestamp", "hostname", "pid", "cwd", "absolute_path"):
        assert forbidden not in rendered.casefold()
    assert environment["execution_device"] == "CPU"
    assert environment["operating_system"] == "Windows"
    assert environment["execution_commit_sha"] == "b" * 40
    assert environment["data_snapshot_sha256"] == "e" * 64
    assert environment["config_sha256"] == "d" * 64
    assert environment["config_file_sha256"] == "c" * 64
    assert environment["thread_caps"] == {name: "1" for name in pilot.THREAD_CAP_ENV_VARS}
    assert run["parallelism"] == {
        "backend": "loky",
        "inner_max_num_threads": 1,
        "n_jobs": 4,
    }
    assert run["canonical_model_task_count"] == 40
    assert run["local_run_id"] == "jpl-2019-05-gate1-pilot-seed20260901"
    assert run["reproducibility"]["repeat_policy"] == "recompute_all_40_then_byte_compare"
    assert_public_release_safe(environment)
    assert_public_release_safe(run)


def test_environment_preflight_requires_exact_python_and_lock_versions() -> None:
    exact = {
        "joblib": "1.6.0",
        "numpy": "2.4.6",
        "pandas": "3.0.5",
        "pyarrow": "25.0.1",
        "pyyaml": "6.0.3",
        "pytest": "9.1.1",
        "requests": "2.34.2",
        "ruff": "0.16.5",
        "scikit-learn": "1.9.0",
        "scipy": "1.17.1",
    }
    evidence = pilot._verify_environment(
        python_version=(3, 11, 16),
        installed_versions=exact,
        operating_system="Windows",
        thread_environment={name: "1" for name in pilot.THREAD_CAP_ENV_VARS},
    )
    assert evidence.python_version == "3.11.16"

    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._verify_environment(
            python_version=(3, 13, 0),
            installed_versions=exact,
            operating_system="Windows",
            thread_environment={name: "1" for name in pilot.THREAD_CAP_ENV_VARS},
        )
    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._verify_environment(
            python_version=(3, 11, 16),
            installed_versions={**exact, "scikit-learn": "1.8.0"},
            operating_system="Windows",
            thread_environment={name: "1" for name in pilot.THREAD_CAP_ENV_VARS},
        )
    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._verify_environment(
            python_version=(3, 11, 16),
            installed_versions=exact,
            operating_system="Windows",
            thread_environment={
                **{name: "1" for name in pilot.THREAD_CAP_ENV_VARS},
                "OPENBLAS_NUM_THREADS": "8",
            },
        )


def test_root_isolation_rejects_public_local_or_processed_overlap(tmp_path: Path) -> None:
    roots = {
        "repo_root": tmp_path,
        "processed_root": tmp_path / "data" / "processed",
        "interim_root": tmp_path / "data" / "interim",
        "local_run_root": tmp_path / "outputs" / "runs" / "formal",
        "public_root": tmp_path / "outputs" / "gate1_pilot" / "public",
    }
    pilot._verify_root_isolation(**roots)

    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._verify_root_isolation(
            **{**roots, "local_run_root": roots["public_root"] / "private"}
        )
    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._verify_root_isolation(**{**roots, "public_root": roots["processed_root"]})


def test_formal_output_layout_binds_deterministic_local_id_and_public_allowlist_root(
    tmp_path: Path,
) -> None:
    local = tmp_path / "outputs" / "runs" / "jpl-2019-05-gate1-pilot-seed20260901"
    public = tmp_path / "outputs" / "gate1_pilot" / "jpl_2019-05"
    processed = tmp_path / "data" / "processed" / "acn" / "jpl" / "2019-05"
    interim = tmp_path / "data" / "interim" / "acn" / "jpl" / "2019-05"
    pilot._verify_formal_output_layout(
        repo_root=tmp_path,
        processed_root=processed,
        interim_root=interim,
        local_run_root=local,
        public_root=public,
    )

    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._verify_formal_output_layout(
            repo_root=tmp_path,
            processed_root=processed,
            interim_root=interim,
            local_run_root=tmp_path / "outputs" / "runs" / "arbitrary",
            public_root=public,
        )
    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._verify_formal_output_layout(
            repo_root=tmp_path,
            processed_root=processed,
            interim_root=interim,
            local_run_root=local,
            public_root=tmp_path / "outputs" / "gate1_pilot" / "other",
        )
    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._verify_formal_output_layout(
            repo_root=tmp_path,
            processed_root=tmp_path / "code" / "private-data",
            interim_root=interim,
            local_run_root=local,
            public_root=public,
        )


def test_git_preflight_requires_branch_clean_tracked_head_and_repeat_commit(tmp_path: Path) -> None:
    outputs = {
        ("rev-parse", "--show-toplevel"): str(tmp_path),
        ("branch", "--show-current"): "experiments/gate1-active-session-pilot",
        ("rev-parse", "HEAD"): "a" * 40,
        ("status", "--porcelain=v1", "--untracked-files=no"): "",
        ("ls-files", "--error-unmatch", "--", "config.yaml"): "config.yaml",
        ("ls-files", "--error-unmatch", "--", "environment-gate1-pilot.yml"): (
            "environment-gate1-pilot.yml"
        ),
        (
            "ls-files",
            "--error-unmatch",
            "--",
            "scripts/run_jpl_gate1_pilot.py",
        ): "scripts/run_jpl_gate1_pilot.py",
        ("ls-files", "--error-unmatch", "--", ".gitignore"): ".gitignore",
    }
    outputs.update(
        {
            ("ls-files", "--error-unmatch", "--", source_path): source_path
            for source_path in pilot._FORMAL_MODULE_PATHS.values()
        }
    )

    def query(*args: str) -> str:
        return outputs[args]

    evidence = pilot._verify_git_preflight(
        repo_root=tmp_path,
        config_relative_path="config.yaml",
        expected_repeat_commit=None,
        git_query=query,
    )
    assert evidence.execution_commit_sha == "a" * 40

    outputs[("status", "--porcelain=v1", "--untracked-files=no")] = " M tracked.py"
    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._verify_git_preflight(
            repo_root=tmp_path,
            config_relative_path="config.yaml",
            expected_repeat_commit=None,
            git_query=query,
        )
    outputs[("status", "--porcelain=v1", "--untracked-files=no")] = ""
    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._verify_git_preflight(
            repo_root=tmp_path,
            config_relative_path="config.yaml",
            expected_repeat_commit="b" * 40,
            git_query=query,
        )


def test_gitignore_contract_has_exact_public_unignore_set_and_local_ignores(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    pilot._verify_gitignore_contract(root)

    copied = (root / ".gitignore").read_text(encoding="utf-8")
    (tmp_path / ".gitignore").write_text(
        copied + "\n!outputs/gate1_pilot/jpl_2019-05/**\n",
        encoding="utf-8",
    )
    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._verify_gitignore_contract(tmp_path)


def test_gitignore_behavior_checks_real_private_and_public_probe_paths() -> None:
    ignored = set(pilot._REQUIRED_IGNORED_PROBES)

    pilot._verify_gitignore_behavior(
        repo_root=Path("."),
        is_ignored=lambda path: path in ignored,
    )

    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._verify_gitignore_behavior(
            repo_root=Path("."),
            is_ignored=lambda path: True,
        )


def test_runtime_module_binding_requires_current_worktree_paths(tmp_path: Path) -> None:
    modules = {
        module_name: SimpleNamespace(__file__=tmp_path / relative_path)
        for module_name, relative_path in pilot._FORMAL_MODULE_PATHS.items()
    }
    pilot._verify_runtime_module_binding(tmp_path, modules)

    wrong = dict(modules)
    first_name = next(iter(wrong))
    wrong[first_name] = SimpleNamespace(__file__=tmp_path.parent / "other" / "module.py")
    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._verify_runtime_module_binding(tmp_path, wrong)


def test_private_scheduler_seam_enforces_loky_four_jobs_one_inner_thread_and_order() -> None:
    observed: dict[str, Any] = {}

    def worker(task: tuple[str, str, int]) -> SimpleNamespace:
        return SimpleNamespace(task=task)

    def verifier(result: SimpleNamespace) -> str:
        assert result.task in CANONICAL_MODEL_TASKS
        return hashlib.sha256(repr(result.task).encode("ascii")).hexdigest()

    def dispatch(
        tasks: tuple[tuple[str, str, int], ...],
        task_worker: Any,
        *,
        n_jobs: int,
        backend: str,
        inner_max_num_threads: int,
    ) -> tuple[SimpleNamespace, ...]:
        observed.update(
            tasks=tasks,
            n_jobs=n_jobs,
            backend=backend,
            inner_max_num_threads=inner_max_num_threads,
        )
        return tuple(task_worker(task) for task in tasks)

    results = pilot._exercise_task_scheduler(
        task_worker=worker,
        result_verifier=verifier,
        dispatcher=dispatch,
    )

    assert tuple(result.task for result in results) == CANONICAL_MODEL_TASKS
    assert observed == {
        "tasks": CANONICAL_MODEL_TASKS,
        "n_jobs": 4,
        "backend": "loky",
        "inner_max_num_threads": 1,
    }


def test_scheduler_rejects_duplicate_or_out_of_order_result_identity() -> None:
    def dispatch(tasks: Any, worker: Any, **kwargs: Any) -> tuple[SimpleNamespace, ...]:
        del worker, kwargs
        return tuple(SimpleNamespace(task=tasks[0]) for _ in tasks)

    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._exercise_task_scheduler(
            task_worker=lambda task: SimpleNamespace(task=task),
            result_verifier=lambda result: "a" * 64,
            result_identity=lambda result: result.task,
            dispatcher=dispatch,
        )


def test_real_loky_dispatcher_round_trips_tiny_picklable_tasks() -> None:
    tasks = CANONICAL_MODEL_TASKS[:4]
    delivered = tuple(
        pilot._joblib_dispatch(
            tasks,
            _echo_task_from_worker,
            n_jobs=4,
            backend="loky",
            inner_max_num_threads=1,
        )
    )

    assert tuple(result.task for result in delivered) == tasks


def test_checkpoint_contains_only_aggregate_selection_and_local_prediction_arrays(
    tmp_path: Path,
) -> None:
    selection = SimpleNamespace(
        learner="ridge",
        tier="M1",
        horizon_minutes=15,
        candidate_validation_mae=np.asarray([1.0, 2.0]),
        selected_candidate_index=0,
        selected_param_sha256="a" * 64,
    )
    bundle = SimpleNamespace(
        issue_times=np.asarray([1, 2], dtype=np.int64),
        y_true=np.asarray([3.0, 4.0]),
        predictions=np.asarray([3.5, 4.5]),
        day_start_utc_s=np.asarray([0, 0], dtype=np.int64),
        parameter_hashes=np.asarray([b"a" * 64, b"a" * 64]),
    )
    result = SimpleNamespace(
        selection_record=selection,
        prediction_bundle=bundle,
        execution_sha256="b" * 64,
    )

    pilot._write_task_checkpoint(tmp_path, result)

    files = sorted(path.name for path in tmp_path.iterdir())
    assert files == ["ridge-M1-h015.json", "ridge-M1-h015.predictions.npz"]
    metadata = json.loads((tmp_path / files[0]).read_text(encoding="utf-8"))
    assert set(metadata) == {
        "candidate_validation_mae_a",
        "checkpoint_schema_version",
        "execution_sha256",
        "horizon_minutes",
        "learner",
        "prediction_file_sha256",
        "selected_candidate_index",
        "selected_parameter_sha256",
        "tier",
    }
    assert "model" not in json.dumps(metadata).casefold()
    assert not any(
        path.suffix.casefold() in {".pkl", ".pickle", ".joblib"} for path in tmp_path.iterdir()
    )
    pilot._verify_task_checkpoints(tmp_path, (result,))

    prediction_path = tmp_path / "ridge-M1-h015.predictions.npz"
    prediction_path.write_bytes(prediction_path.read_bytes() + b"tamper")
    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._verify_task_checkpoints(tmp_path, (result,))

    pilot._write_task_checkpoint(tmp_path, result)
    with np.load(prediction_path, allow_pickle=False) as archive:
        arrays = {name: archive[name].copy() for name in archive.files}
    arrays["issue_times"] = arrays["issue_times"].astype(np.int32)
    np.savez_compressed(prediction_path, **arrays)
    metadata["prediction_file_sha256"] = hashlib.sha256(prediction_path.read_bytes()).hexdigest()
    (tmp_path / files[0]).write_text(json.dumps(metadata), encoding="ascii")
    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._verify_task_checkpoints(tmp_path, (result,))


def test_complete_checkpoint_set_has_one_cross_task_seal_and_fails_on_mixed_generation(
    tmp_path: Path,
) -> None:
    results = []
    for task in CANONICAL_MODEL_TASKS:
        learner, tier, horizon = task
        parameter_sha = hashlib.sha256(f"parameter:{task!r}".encode("ascii")).hexdigest()
        results.append(
            SimpleNamespace(
                selection_record=SimpleNamespace(
                    learner=learner,
                    tier=tier,
                    horizon_minutes=horizon,
                    candidate_validation_mae=np.arange(
                        4 if learner == "ridge" else 16,
                        dtype=np.float64,
                    ),
                    selected_candidate_index=0,
                    selected_param_sha256=parameter_sha,
                ),
                prediction_bundle=SimpleNamespace(
                    issue_times=np.asarray([1], dtype=np.int64),
                    y_true=np.asarray([3.0], dtype=np.float64),
                    predictions=np.asarray([3.5], dtype=np.float64),
                    day_start_utc_s=np.asarray([0], dtype=np.int64),
                    parameter_hashes=np.asarray([parameter_sha.encode("ascii")]),
                ),
                execution_sha256=hashlib.sha256(f"execution:{task!r}".encode("ascii")).hexdigest(),
            )
        )
    frozen_results = tuple(results)
    for result in frozen_results:
        pilot._write_task_checkpoint(tmp_path, result)

    checkpoint_set_sha = pilot._seal_complete_checkpoint_set(tmp_path, frozen_results)

    assert len(checkpoint_set_sha) == 64
    assert {
        json.loads(path.read_text(encoding="ascii"))["checkpoint_set_sha256"]
        for path in tmp_path.glob("*.json")
    } == {checkpoint_set_sha}
    pilot._verify_task_checkpoints(tmp_path, frozen_results, require_complete_set=True)

    pilot._write_task_checkpoint(tmp_path, frozen_results[0])
    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._verify_task_checkpoints(tmp_path, frozen_results, require_complete_set=True)


def test_atomic_publication_and_repeat_comparison_are_byte_exact(tmp_path: Path) -> None:
    public_root = tmp_path / "public"
    files = _rendered_release()

    first = pilot._publish_or_compare_public_release(public_root, files)
    before = {path.name: path.read_bytes() for path in public_root.iterdir()}
    second = pilot._publish_or_compare_public_release(public_root, files)

    assert first == "REFERENCE_PUBLISHED"
    assert second == "BYTE_IDENTICAL_REPEAT"
    assert {path.name: path.read_bytes() for path in public_root.iterdir()} == before

    changed = dict(files)
    changed["gate1_summary.json"] += b" "
    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._publish_or_compare_public_release(public_root, changed)
    assert {path.name: path.read_bytes() for path in public_root.iterdir()} == before
    assert not list(tmp_path.glob(".public.staging-*"))


def test_atomic_publication_rolls_back_staging_when_final_rename_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    public_root = tmp_path / "public"

    def fail_replace(source: Any, destination: Any) -> None:
        del source, destination
        raise OSError("simulated final rename failure")

    monkeypatch.setattr(pilot.os, "replace", fail_replace)
    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._publish_or_compare_public_release(public_root, _rendered_release())

    assert not public_root.exists()
    assert not list(tmp_path.glob(".public.staging-*"))


def test_publication_rejects_extra_files_before_touching_existing_release(tmp_path: Path) -> None:
    public_root = tmp_path / "public"
    files = dict(_rendered_release())
    files["predictions.csv"] = b"private\n"

    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._publish_or_compare_public_release(public_root, files)

    assert not public_root.exists()


def test_publication_scans_csv_headers_and_cells_after_checksum_verification(
    tmp_path: Path,
) -> None:
    files = dict(_rendered_release())
    files["metrics_by_horizon.csv"] = b"safe\nC:\\private\\predictions.csv\n"
    files["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n"
        for name in PUBLIC_FILENAMES
        if name != "SHA256SUMS"
    ).encode("ascii")

    with pytest.raises(Gate1PilotExecutionError, match="EXECUTION_FAIL"):
        pilot._publish_or_compare_public_release(tmp_path / "public", files)

    assert not (tmp_path / "public").exists()


def test_two_complete_invocations_recompute_all_40_before_byte_comparison(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_calls: list[int] = []
    safe_files = _rendered_release()

    monkeypatch.setattr(pilot, "_prepare_formal_inputs", lambda **kwargs: SimpleNamespace())

    def run_tasks(prepared: Any, local_run_root: Path) -> tuple[SimpleNamespace, ...]:
        del prepared, local_run_root
        run_calls.append(40)
        return tuple(SimpleNamespace(task=task) for task in CANONICAL_MODEL_TASKS)

    monkeypatch.setattr(pilot, "_run_canonical_model_tasks", run_tasks)
    monkeypatch.setattr(
        pilot,
        "_evaluate_and_render_formal_release",
        lambda prepared, task_results: safe_files,
    )

    kwargs = {
        "authorized": True,
        "config_path": tmp_path / "config.yaml",
        "processed_root": tmp_path / "processed",
        "interim_root": tmp_path / "interim",
        "local_run_root": tmp_path / "local",
        "public_root": tmp_path / "public",
        "repo_root": tmp_path,
    }
    first = run_gate1_pilot(**kwargs)
    second = run_gate1_pilot(**kwargs)

    assert run_calls == [40, 40]
    assert first.reproducibility_status == "REFERENCE_PUBLISHED"
    assert second.reproducibility_status == "BYTE_IDENTICAL_REPEAT"
    assert first.task_count == second.task_count == 40


def test_unauthorized_library_entrypoint_touches_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        pilot,
        "_prepare_formal_inputs",
        lambda **kwargs: pytest.fail("unauthorized call reached preflight"),
    )

    with pytest.raises(PermissionError, match="authorize"):
        run_gate1_pilot(
            authorized=False,
            config_path=tmp_path / "missing-config.yaml",
            processed_root=tmp_path / "processed",
            interim_root=tmp_path / "interim",
            local_run_root=tmp_path / "local",
            public_root=tmp_path / "public",
            repo_root=tmp_path,
        )

    assert list(tmp_path.iterdir()) == []


def test_gitignore_keeps_large_local_outputs_ignored_and_allows_only_public_allowlist() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / ".gitignore").read_text(encoding="utf-8")

    assert "outputs/runs/**" in text
    assert "data/processed/**" in text
    assert "!outputs/gate1_pilot/jpl_2019-05/" in text
    for name in PUBLIC_FILENAMES:
        assert f"!outputs/gate1_pilot/jpl_2019-05/{name}" in text
    assert "!outputs/gate1_pilot/jpl_2019-05/predictions" not in text
    assert "!outputs/gate1_pilot/jpl_2019-05/models" not in text
