"""Offline, fail-closed orchestration for the frozen JPL Gate 1 pilot.

The formal entry point has no injectable model or publication implementation.
All issue-level predictions and encoded matrices remain under ignored local
roots; the closed publisher accepts only a sealed aggregate evaluation and
emits the thirteen predeclared public files.
"""

from __future__ import annotations

import csv
import hashlib
import importlib
import importlib.metadata
import io
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Protocol, TypeVar

import numpy as np

PUBLIC_FILENAMES = (
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
LEARNERS = ("ridge", "hgb")
TIERS = ("M1", "M2", "M3", "M4")
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
CANONICAL_MODEL_TASKS = tuple(
    (learner, tier, horizon)
    for learner in LEARNERS
    for tier in TIERS
    for horizon in HORIZONS_MINUTES
)

EXPECTED_BRANCH = "experiments/gate1-active-session-pilot"
EXPECTED_PYTHON = (3, 11, 16)
N_JOBS = 4
PARALLEL_BACKEND = "loky"
INNER_MAX_NUM_THREADS = 1
EXECUTION_FAIL = "EXECUTION_FAIL"
LOCAL_RUN_ID = "jpl-2019-05-gate1-pilot-seed20260901"
_LOCAL_RUN_RELATIVE = Path("outputs/runs") / LOCAL_RUN_ID
_PUBLIC_ROOT_RELATIVE = Path("outputs/gate1_pilot/jpl_2019-05")
_PROCESSED_ROOT_RELATIVE = Path("data/processed/acn/jpl/2019-05")
_INTERIM_ROOT_RELATIVE = Path("data/interim/acn/jpl/2019-05")
THREAD_CAP_ENV_VARS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
)

_EXPECTED_DEPENDENCIES = MappingProxyType(
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
)
_DISTRIBUTION_NAMES = MappingProxyType(
    {
        "joblib": "joblib",
        "numpy": "numpy",
        "pandas": "pandas",
        "pyarrow": "pyarrow",
        "pyyaml": "PyYAML",
        "pytest": "pytest",
        "requests": "requests",
        "ruff": "ruff",
        "scikit-learn": "scikit-learn",
        "scipy": "scipy",
    }
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)[a-z]:[\\/]")
_UNC_ABSOLUTE_PATH = re.compile(r"\\\\[^\\\s]+\\")
_POSIX_ABSOLUTE_PATH = re.compile(r"(?:^|[\s'\"(=])/(?!/)[^\s'\")]+")
_FILE_URI = re.compile(r"(?i)\bfile:(?://)?[\\/]")
_URI_SCHEME = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://")
_BEARER_SECRET = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_MODEL_FILE = re.compile(r"(?i)\.(?:joblib|pickle|pkl|onnx|pt|pth|ckpt)(?:\b|$)")
_PRIVATE_IDENTIFIER_TEXT = re.compile(
    r"(?i)\b(?:anonymous[_ -]?session[_ -]?index|cluster|session|site|space|station|user)"
    r"[_ -]?ids?\b"
)
_FORBIDDEN_PRIVATE_KEY_PARTS = (
    "anonymoussessionindex",
    "clusterid",
    "sessionid",
    "siteid",
    "spaceid",
    "stationid",
    "userid",
)
_FORBIDDEN_ARRAY_KEY_PARTS = (
    "issuetimes",
    "parameterhashes",
    "prediction",
    "yhat",
    "ypred",
    "ytrue",
)
_ALLOWED_PREDICTION_AUDIT_KEYS = frozenset(
    {
        "testpredictionclipping",
        "testpredictioncalibration",
        "fullpredictionspublished",
    }
)
_FORBIDDEN_SECRET_KEY_PARTS = (
    "apikey",
    "apitoken",
    "accesstoken",
    "authorization",
    "credential",
    "password",
    "privatekey",
    "refreshtoken",
    "secret",
    "token",
)
_FORMAL_MODULE_PATHS = MappingProxyType(
    {
        "evcf.forecasting.acn_jpl_gate1_pilot": (
            "code/src/evcf/forecasting/acn_jpl_gate1_pilot.py"
        ),
        "evcf.forecasting.acn_jpl_gate1_contracts": (
            "code/src/evcf/forecasting/acn_jpl_gate1_contracts.py"
        ),
        "evcf.forecasting.acn_jpl_gate1_data": "code/src/evcf/forecasting/acn_jpl_gate1_data.py",
        "evcf.forecasting.acn_jpl_gate1_features": (
            "code/src/evcf/forecasting/acn_jpl_gate1_features.py"
        ),
        "evcf.forecasting.acn_jpl_gate1_models": (
            "code/src/evcf/forecasting/acn_jpl_gate1_models.py"
        ),
        "evcf.evaluation.acn_jpl_gate1_metrics": (
            "code/src/evcf/evaluation/acn_jpl_gate1_metrics.py"
        ),
    }
)
_REQUIRED_IGNORED_PROBES = (
    "data/processed/acn/jpl/2019-05/gate1_pilot/M4.values.npy",
    "data/interim/acn/jpl/2019-05/gate1-private-probe.json",
    f"outputs/runs/{LOCAL_RUN_ID}/ridge-M1-h015.predictions.npz",
    "outputs/gate1_pilot/jpl_2019-05/predictions.csv",
)
_REQUIRED_PUBLIC_PROBES = tuple(
    f"outputs/gate1_pilot/jpl_2019-05/{name}" for name in PUBLIC_FILENAMES
)
_SUCCESS_CLASSIFICATIONS = frozenset(
    {
        "PASS_ACTIVE_SESSION",
        "PASS_SIMPLE_STATE_ONLY",
        "PASS_ACTIVE_SESSION_DROP_M4",
        "FAIL_DIRECTION",
    }
)


class Gate1PilotExecutionError(RuntimeError):
    """Sanitized fail-closed error; private exception details stay in the cause."""

    status = EXECUTION_FAIL

    def __init__(self, phase: str = "formal Gate 1 execution failed") -> None:
        self.phase = phase
        super().__init__(f"{EXECUTION_FAIL}: {phase}")


@dataclass(frozen=True, slots=True)
class Gate1PilotOutcome:
    """Small deidentified outcome suitable for CLI output."""

    status: str
    task_count: int
    public_file_count: int
    reproducibility_status: str

    def __post_init__(self) -> None:
        if self.status not in _SUCCESS_CLASSIFICATIONS:
            raise ValueError("formal outcome requires one frozen scientific classification")
        if self.task_count != len(CANONICAL_MODEL_TASKS):
            raise ValueError("formal outcome requires all 40 model tasks")
        if self.public_file_count != len(PUBLIC_FILENAMES):
            raise ValueError("formal outcome requires exactly 13 public files")
        if self.reproducibility_status not in {
            "REFERENCE_PUBLISHED",
            "BYTE_IDENTICAL_REPEAT",
        }:
            raise ValueError("formal outcome has an invalid reproducibility status")


@dataclass(frozen=True, slots=True)
class _EnvironmentEvidence:
    python_version: str
    operating_system: str
    dependencies: Mapping[str, str]
    thread_caps: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.python_version != ".".join(str(value) for value in EXPECTED_PYTHON):
            raise ValueError("environment evidence Python version is not frozen")
        if dict(self.dependencies) != dict(_EXPECTED_DEPENDENCIES):
            raise ValueError("environment evidence dependency versions are not frozen")
        if not isinstance(self.operating_system, str) or not self.operating_system:
            raise ValueError("environment evidence operating system is invalid")
        if dict(self.thread_caps) != {name: "1" for name in THREAD_CAP_ENV_VARS}:
            raise ValueError("environment evidence native thread caps are not frozen")
        object.__setattr__(self, "dependencies", MappingProxyType(dict(self.dependencies)))
        object.__setattr__(self, "thread_caps", MappingProxyType(dict(self.thread_caps)))


@dataclass(frozen=True, slots=True)
class _GitEvidence:
    execution_commit_sha: str
    branch: str

    def __post_init__(self) -> None:
        if not _COMMIT_SHA.fullmatch(self.execution_commit_sha):
            raise ValueError("execution commit is not a full lowercase Git SHA")
        if self.branch != EXPECTED_BRANCH:
            raise ValueError("execution branch is not the frozen Gate 1 branch")


@dataclass(frozen=True, slots=True)
class _PreparedFormalInputs:
    config: Mapping[str, Any]
    config_file_sha256: str
    snapshot: Any
    split: Any
    feature_blocks: Mapping[str, Any]
    persistence_by_horizon: Mapping[int, Mapping[str, Any]]
    environment: _EnvironmentEvidence
    git: _GitEvidence


def _compact_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _render_json(value: Any, *, level: int, compact: bool) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON forbids non-finite numbers")
        return format(value, ".17g")
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical JSON object keys must be strings")
        items = [(key, value[key]) for key in sorted(value)]
        if not items:
            return "{}"
        if compact:
            return (
                "{"
                + ",".join(
                    f"{json.dumps(key, ensure_ascii=True)}:{_render_json(item, level=0, compact=True)}"
                    for key, item in items
                )
                + "}"
            )
        child_indent = "  " * (level + 1)
        rendered = ",\n".join(
            f"{child_indent}{json.dumps(key, ensure_ascii=True)}: "
            f"{_render_json(item, level=level + 1, compact=False)}"
            for key, item in items
        )
        return "{\n" + rendered + "\n" + "  " * level + "}"
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        if compact:
            return "[" + ",".join(_render_json(item, level=0, compact=True) for item in value) + "]"
        child_indent = "  " * (level + 1)
        rendered = ",\n".join(
            child_indent + _render_json(item, level=level + 1, compact=False) for item in value
        )
        return "[\n" + rendered + "\n" + "  " * level + "]"
    raise TypeError(f"canonical JSON forbids values of type {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize plain public JSON with sorted keys, LF, and ``.17g`` floats."""

    assert_public_release_safe(value)
    return (_render_json(value, level=0, compact=False) + "\n").encode("ascii")


def _canonical_local_json_bytes(value: Any) -> bytes:
    """Canonical JSON for ignored local state, without the public privacy filter."""

    return (_render_json(value, level=0, compact=False) + "\n").encode("ascii")


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical CSV forbids non-finite numbers")
        return format(value, ".17g")
    if isinstance(value, str):
        return value
    if isinstance(value, (Mapping, list, tuple)):
        return _render_json(value, level=0, compact=True)
    raise TypeError(f"canonical CSV forbids values of type {type(value).__name__}")


def canonical_csv_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    """Serialize aggregate rows with stable columns, LF, and ``.17g`` floats."""

    frozen_rows = tuple(rows)
    if not frozen_rows:
        return b""
    for row in frozen_rows:
        assert_public_release_safe(row)
    fieldnames = sorted({key for row in frozen_rows for key in row})
    if any(not isinstance(key, str) for key in fieldnames):
        raise TypeError("canonical CSV columns must be strings")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in frozen_rows:
        writer.writerow({key: _csv_cell(row.get(key)) for key in fieldnames})
    return stream.getvalue().encode("utf-8")


def _assert_public_key(key: str, *, path: str) -> None:
    compact = _compact_key(key)
    if compact == "id" or any(fragment in compact for fragment in _FORBIDDEN_PRIVATE_KEY_PARTS):
        raise ValueError(f"{path} contains a forbidden private identifier key")
    if any(fragment in compact for fragment in _FORBIDDEN_ARRAY_KEY_PARTS) and (
        compact not in _ALLOWED_PREDICTION_AUDIT_KEYS
    ):
        raise ValueError(f"{path} contains a forbidden prediction or row-array key")
    if any(fragment in compact for fragment in _FORBIDDEN_SECRET_KEY_PARTS):
        raise ValueError(f"{path} contains a forbidden credential key")


def _contains_windows_absolute_path(value: str) -> bool:
    uri_scheme_spans = tuple(match.span() for match in _URI_SCHEME.finditer(value))
    return any(
        not any(start <= match.start() and match.end() <= end for start, end in uri_scheme_spans)
        for match in _WINDOWS_ABSOLUTE_PATH.finditer(value)
    )


def _assert_public_string(value: str, *, path: str) -> None:
    if _PRIVATE_IDENTIFIER_TEXT.search(value):
        raise ValueError(f"{path} contains a forbidden private identifier")
    if _contains_windows_absolute_path(value):
        raise ValueError(f"{path} contains a forbidden Windows absolute path")
    if _UNC_ABSOLUTE_PATH.search(value):
        raise ValueError(f"{path} contains a forbidden UNC absolute path")
    if _POSIX_ABSOLUTE_PATH.search(value):
        raise ValueError(f"{path} contains a forbidden POSIX absolute path")
    if _FILE_URI.search(value):
        raise ValueError(f"{path} contains a forbidden file URI")
    if _BEARER_SECRET.search(value):
        raise ValueError(f"{path} contains a forbidden credential")
    if _MODEL_FILE.search(value):
        raise ValueError(f"{path} contains a forbidden model artifact")


def assert_public_release_safe(value: Any, *, _path: str = "payload") -> None:
    """Reject identifiers, predictions, models, secrets, paths, arrays, and NaN."""

    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{_path} contains a non-finite public number")
        return
    if isinstance(value, str):
        _assert_public_string(value, path=_path)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{_path} contains a non-string public key")
            _assert_public_key(key, path=f"{_path}.key")
            if _compact_key(key) in _ALLOWED_PREDICTION_AUDIT_KEYS and item is not False:
                raise ValueError(f"{_path}.{key} contains a forbidden prediction audit value")
            assert_public_release_safe(item, _path=f"{_path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            assert_public_release_safe(item, _path=f"{_path}[{index}]")
        return
    if isinstance(value, np.ndarray):
        raise TypeError(f"{_path} contains a forbidden private array")
    raise TypeError(f"{_path} contains a forbidden model or object value")


def _flatten_summary(aggregate_payload: Mapping[str, Any]) -> dict[str, Any]:
    gate = aggregate_payload.get("gate")
    privacy = aggregate_payload.get("privacy")
    if not isinstance(gate, Mapping) or not isinstance(privacy, Mapping):
        raise TypeError("aggregate payload is missing gate or privacy evidence")
    return {
        "schema_version": "acn-jpl-gate1-summary/v1",
        "status": gate.get("classification"),
        "execution_ok": gate.get("execution_ok"),
        "blocking_issues": gate.get("blocking_issues"),
        "gate": dict(gate),
        "metric_record_count": len(aggregate_payload.get("metrics_by_horizon", [])),
        "tier_comparison_count": len(aggregate_payload.get("tier_comparisons", [])),
        "daily_paired_error_count": len(aggregate_payload.get("daily_paired_errors", [])),
        "privacy": dict(privacy),
        "units": aggregate_payload.get("units", {}),
    }


def _decision_markdown(gate: Mapping[str, Any]) -> bytes:
    classification = gate.get("classification")
    execution_ok = gate.get("execution_ok")
    issues = gate.get("blocking_issues")
    if not isinstance(classification, str) or not isinstance(execution_ok, bool):
        raise TypeError("aggregate gate decision is incomplete")
    if not isinstance(issues, list) or any(not isinstance(item, str) for item in issues):
        raise ValueError("aggregate gate blocking issues are invalid")
    lines = [
        "# JPL Gate 1 pilot decision",
        "",
        f"- Classification: `{classification}`",
        f"- Execution complete: `{'YES' if execution_ok else 'NO'}`",
        "- Scope: frozen JPL 2019-05 screening gate; not a final paper conclusion.",
        "- Public release: aggregate and deidentified only.",
    ]
    if issues:
        lines.extend(("", "## Blocking issues", ""))
        lines.extend(f"- {item}" for item in issues)
    rendered = "\n".join(lines) + "\n"
    assert_public_release_safe(rendered)
    return rendered.encode("utf-8")


def _render_public_release_from_aggregate(
    *,
    aggregate_payload: Mapping[str, Any],
    model_selection_manifest: Mapping[str, Any],
    feature_encoding_manifest: Mapping[str, Any],
    environment_manifest: Mapping[str, Any],
    run_manifest: Mapping[str, Any],
    data_snapshot_manifest: Mapping[str, Any],
) -> MappingProxyType[str, bytes]:
    """Private deterministic renderer; it cannot certify an evaluation result."""

    expected_aggregate_keys = {
        "schema_version",
        "units",
        "metrics_by_horizon",
        "tier_comparisons",
        "daily_paired_errors",
        "bootstrap",
        "peak_ramp_metrics",
        "gate",
        "privacy",
    }
    if set(aggregate_payload) != expected_aggregate_keys:
        raise ValueError("aggregate payload differs from the closed public metrics schema")
    assert_public_release_safe(aggregate_payload)
    for manifest in (
        model_selection_manifest,
        feature_encoding_manifest,
        environment_manifest,
        run_manifest,
        data_snapshot_manifest,
    ):
        assert_public_release_safe(manifest)
    gate = aggregate_payload["gate"]
    if not isinstance(gate, Mapping):
        raise TypeError("aggregate gate decision must be a mapping")
    files: dict[str, bytes] = {
        "gate1_summary.json": canonical_json_bytes(_flatten_summary(aggregate_payload)),
        "gate1_decision.md": _decision_markdown(gate),
        "metrics_by_horizon.csv": canonical_csv_bytes(aggregate_payload["metrics_by_horizon"]),
        "tier_comparison.csv": canonical_csv_bytes(aggregate_payload["tier_comparisons"]),
        "daily_paired_errors.csv": canonical_csv_bytes(aggregate_payload["daily_paired_errors"]),
        "bootstrap_intervals.json": canonical_json_bytes(aggregate_payload["bootstrap"]),
        "peak_ramp_metrics.json": canonical_json_bytes(
            {
                "schema_version": "acn-jpl-gate1-peak-ramp/v1",
                "records": aggregate_payload["peak_ramp_metrics"],
            }
        ),
        "model_selection_manifest.json": canonical_json_bytes(model_selection_manifest),
        "feature_encoding_manifest.json": canonical_json_bytes(feature_encoding_manifest),
        "environment_manifest.json": canonical_json_bytes(environment_manifest),
        "run_manifest.json": canonical_json_bytes(run_manifest),
        "data_snapshot_manifest.json": canonical_json_bytes(data_snapshot_manifest),
    }
    checksums = "".join(
        f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n"
        for name in PUBLIC_FILENAMES
        if name != "SHA256SUMS"
    )
    files["SHA256SUMS"] = checksums.encode("ascii")
    ordered = {name: files[name] for name in PUBLIC_FILENAMES}
    _validate_public_file_map(ordered)
    return MappingProxyType(ordered)


def build_public_release_files(
    *,
    evaluation_result: Any,
    model_selection_manifest: Mapping[str, Any],
    feature_encoding_manifest: Mapping[str, Any],
    environment_manifest: Mapping[str, Any],
    run_manifest: Mapping[str, Any],
    data_snapshot_manifest: Mapping[str, Any],
) -> Mapping[str, bytes]:
    """Certify and render public files from one sealed aggregate evaluation only."""

    from evcf.evaluation.acn_jpl_gate1_metrics import (
        Gate1EvaluationResult,
        build_public_aggregate_payload,
    )

    if type(evaluation_result) is not Gate1EvaluationResult:
        raise TypeError("public release requires an exact formal Gate1EvaluationResult")
    aggregate_payload = build_public_aggregate_payload(evaluation_result)
    return _render_public_release_from_aggregate(
        aggregate_payload=aggregate_payload,
        model_selection_manifest=model_selection_manifest,
        feature_encoding_manifest=feature_encoding_manifest,
        environment_manifest=environment_manifest,
        run_manifest=run_manifest,
        data_snapshot_manifest=data_snapshot_manifest,
    )


def _validate_public_file_map(files: Mapping[str, bytes]) -> None:
    if tuple(files) != PUBLIC_FILENAMES:
        raise Gate1PilotExecutionError("public file allowlist verification failed")
    if any(Path(name).name != name for name in files):
        raise Gate1PilotExecutionError("public filename verification failed")
    if any(not isinstance(value, bytes) or not value.endswith(b"\n") for value in files.values()):
        raise Gate1PilotExecutionError("public encoding verification failed")
    for name in PUBLIC_FILENAMES:
        if _MODEL_FILE.search(name):
            raise Gate1PilotExecutionError("public model artifact verification failed")
    expected_lines = [
        f"{hashlib.sha256(files[name]).hexdigest()}  {name}"
        for name in PUBLIC_FILENAMES
        if name != "SHA256SUMS"
    ]
    actual_lines = files["SHA256SUMS"].decode("ascii").splitlines()
    if actual_lines != expected_lines:
        raise Gate1PilotExecutionError("public checksum verification failed")
    try:
        for name, content in files.items():
            if name.endswith(".json"):
                payload = json.loads(content.decode("ascii"))
                assert_public_release_safe(payload)
            elif name.endswith(".csv"):
                text = content.decode("utf-8")
                if "\r" in text:
                    raise ValueError("CSV contains CR characters")
                reader = csv.DictReader(io.StringIO(text))
                if reader.fieldnames is None:
                    raise ValueError("CSV header is missing")
                for fieldname in reader.fieldnames:
                    _assert_public_key(fieldname, path=f"{name}.header")
                    _assert_public_string(fieldname, path=f"{name}.header")
                for row_index, row in enumerate(reader):
                    assert_public_release_safe(row, _path=f"{name}.row[{row_index}]")
            else:
                assert_public_release_safe(content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise Gate1PilotExecutionError("public privacy or schema verification failed") from exc


def _assert_narrow_public_root(public_root: Path) -> Path:
    resolved = public_root.resolve()
    if resolved == Path(resolved.anchor) or resolved == resolved.parent or not resolved.name:
        raise Gate1PilotExecutionError("public destination scope is unsafe")
    return resolved


def _safe_remove_staging(path: Path, *, parent: Path, destination_name: str) -> None:
    resolved = path.resolve()
    if resolved.parent != parent.resolve() or not resolved.name.startswith(
        f".{destination_name}.staging-"
    ):
        raise Gate1PilotExecutionError("staging cleanup scope is unsafe")
    if resolved.exists():
        shutil.rmtree(resolved)


def _existing_public_files(public_root: Path) -> dict[str, bytes]:
    if not public_root.is_dir():
        raise Gate1PilotExecutionError("existing public release is not a directory")
    names = tuple(sorted(path.name for path in public_root.iterdir()))
    if names != tuple(sorted(PUBLIC_FILENAMES)):
        raise Gate1PilotExecutionError("existing public release differs from the 13-file allowlist")
    return {name: (public_root / name).read_bytes() for name in PUBLIC_FILENAMES}


def _publish_or_compare_public_release(
    public_root: str | Path,
    files: Mapping[str, bytes],
) -> str:
    """Atomically publish once; subsequent invocations compare all bytes."""

    _validate_public_file_map(files)
    destination = _assert_narrow_public_root(Path(public_root))
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        existing = _existing_public_files(destination)
        if any(existing[name] != files[name] for name in PUBLIC_FILENAMES):
            raise Gate1PilotExecutionError("repeat public release is not byte-identical")
        return "BYTE_IDENTICAL_REPEAT"

    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent))
    try:
        for name in PUBLIC_FILENAMES:
            (staging / name).write_bytes(files[name])
        staged = {name: (staging / name).read_bytes() for name in PUBLIC_FILENAMES}
        _validate_public_file_map(staged)
        os.replace(staging, destination)
    except Exception as exc:
        if staging.exists():
            _safe_remove_staging(
                staging,
                parent=destination.parent,
                destination_name=destination.name,
            )
        if isinstance(exc, Gate1PilotExecutionError):
            raise
        raise Gate1PilotExecutionError("atomic public publication failed") from exc
    return "REFERENCE_PUBLISHED"


def _verify_environment(
    *,
    python_version: tuple[int, int, int] | None = None,
    installed_versions: Mapping[str, str] | None = None,
    operating_system: str | None = None,
    thread_environment: Mapping[str, str] | None = None,
) -> _EnvironmentEvidence:
    observed_python = sys.version_info[:3] if python_version is None else python_version
    if tuple(observed_python) != EXPECTED_PYTHON:
        raise Gate1PilotExecutionError("formal Python environment verification failed")
    if installed_versions is None:
        try:
            observed = {
                name: importlib.metadata.version(distribution)
                for name, distribution in _DISTRIBUTION_NAMES.items()
            }
        except importlib.metadata.PackageNotFoundError as exc:
            raise Gate1PilotExecutionError(
                "formal dependency environment verification failed"
            ) from exc
    else:
        observed = dict(installed_versions)
    if observed != dict(_EXPECTED_DEPENDENCIES):
        raise Gate1PilotExecutionError("formal dependency environment verification failed")
    observed_thread_caps = (
        {name: os.environ.get(name, "") for name in THREAD_CAP_ENV_VARS}
        if thread_environment is None
        else dict(thread_environment)
    )
    if observed_thread_caps != {name: "1" for name in THREAD_CAP_ENV_VARS}:
        raise Gate1PilotExecutionError("native thread-cap environment verification failed")
    observed_operating_system = platform.system() if operating_system is None else operating_system
    if not isinstance(observed_operating_system, str) or not observed_operating_system:
        raise Gate1PilotExecutionError("operating-system environment verification failed")
    return _EnvironmentEvidence(
        python_version=".".join(str(value) for value in observed_python),
        operating_system=observed_operating_system,
        dependencies=MappingProxyType(observed),
        thread_caps=MappingProxyType(observed_thread_caps),
    )


def _default_git_query(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _verify_runtime_module_binding(
    repo_root: str | Path,
    modules: Mapping[str, Any],
) -> None:
    """Prove every formal module was imported from this exact worktree."""

    root = Path(repo_root).resolve()
    if set(modules) != set(_FORMAL_MODULE_PATHS):
        raise Gate1PilotExecutionError("formal runtime module set verification failed")
    for module_name, relative_path in _FORMAL_MODULE_PATHS.items():
        module_file = getattr(modules[module_name], "__file__", None)
        if not isinstance(module_file, (str, os.PathLike)):
            raise Gate1PilotExecutionError("formal runtime module path verification failed")
        if Path(module_file).resolve() != (root / relative_path).resolve():
            raise Gate1PilotExecutionError("formal runtime module path verification failed")


def _verify_git_preflight(
    *,
    repo_root: str | Path,
    config_relative_path: str,
    expected_repeat_commit: str | None,
    git_query: Callable[..., str] | None = None,
) -> _GitEvidence:
    root = Path(repo_root).resolve()
    relative = PurePosixPath(config_relative_path)
    if relative.is_absolute() or ".." in relative.parts or str(relative) in {"", "."}:
        raise Gate1PilotExecutionError("tracked config scope verification failed")
    query = git_query
    if query is None:
        query = partial(_default_git_query, root)
    try:
        top = Path(query("rev-parse", "--show-toplevel")).resolve()
        branch = query("branch", "--show-current")
        commit = query("rev-parse", "HEAD")
        dirty = query("status", "--porcelain=v1", "--untracked-files=no")
        query("ls-files", "--error-unmatch", "--", relative.as_posix())
        query("ls-files", "--error-unmatch", "--", "environment-gate1-pilot.yml")
        for source_path in _FORMAL_MODULE_PATHS.values():
            query("ls-files", "--error-unmatch", "--", source_path)
        query(
            "ls-files",
            "--error-unmatch",
            "--",
            "scripts/run_jpl_gate1_pilot.py",
        )
        query("ls-files", "--error-unmatch", "--", ".gitignore")
    except (KeyError, OSError, subprocess.SubprocessError) as exc:
        raise Gate1PilotExecutionError("Git provenance preflight failed") from exc
    if top != root or branch != EXPECTED_BRANCH or not _COMMIT_SHA.fullmatch(commit):
        raise Gate1PilotExecutionError("Git branch or HEAD preflight failed")
    if dirty:
        raise Gate1PilotExecutionError("tracked worktree must be clean before formal execution")
    if expected_repeat_commit is not None and commit != expected_repeat_commit:
        raise Gate1PilotExecutionError("repeat execution commit differs from the reference")
    return _GitEvidence(execution_commit_sha=commit, branch=branch)


def _expected_repeat_commit(public_root: Path) -> str | None:
    manifest_path = public_root / "run_manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        assert_public_release_safe(manifest)
        commit = manifest["execution_commit_sha"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise Gate1PilotExecutionError("reference run manifest verification failed") from exc
    if not isinstance(commit, str) or not _COMMIT_SHA.fullmatch(commit):
        raise Gate1PilotExecutionError("reference execution commit verification failed")
    return commit


def _repo_relative_file(path: Path, root: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise Gate1PilotExecutionError("formal config must be inside the repository") from exc
    return relative.as_posix()


def _verify_gitignore_contract(repo_root: str | Path) -> None:
    """Require exactly the thirteen public exceptions and ignored local artifacts."""

    try:
        lines = {
            line.strip()
            for line in (Path(repo_root) / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
    except OSError as exc:
        raise Gate1PilotExecutionError("Git ignore contract could not be read") from exc
    required_ignored = {"outputs/**", "outputs/runs/**", "data/processed/**"}
    if not required_ignored.issubset(lines):
        raise Gate1PilotExecutionError("local Gate 1 artifacts are not fully ignored")
    public_prefix = "!outputs/gate1_pilot"
    actual_public = {line for line in lines if line.startswith(public_prefix)}
    expected_public = {
        "!outputs/gate1_pilot/",
        "!outputs/gate1_pilot/jpl_2019-05/",
        *{f"!outputs/gate1_pilot/jpl_2019-05/{name}" for name in PUBLIC_FILENAMES},
    }
    if actual_public != expected_public:
        raise Gate1PilotExecutionError("public Git allowlist is not the exact 13-file contract")


def _verify_gitignore_behavior(
    repo_root: str | Path,
    *,
    is_ignored: Callable[[str], bool] | None = None,
) -> None:
    """Verify Git's effective rules, not only the text of ``.gitignore``."""

    root = Path(repo_root).resolve()

    def git_reports_ignored(relative_path: str) -> bool:
        try:
            completed = subprocess.run(
                ["git", "check-ignore", "--quiet", "--no-index", "--", relative_path],
                cwd=root,
                check=False,
                capture_output=True,
            )
        except OSError as exc:
            raise Gate1PilotExecutionError("Git ignore behavior verification failed") from exc
        if completed.returncode not in {0, 1}:
            raise Gate1PilotExecutionError("Git ignore behavior verification failed")
        return completed.returncode == 0

    probe = git_reports_ignored if is_ignored is None else is_ignored
    try:
        private_ok = all(probe(path) is True for path in _REQUIRED_IGNORED_PROBES)
        public_ok = all(probe(path) is False for path in _REQUIRED_PUBLIC_PROBES)
    except Gate1PilotExecutionError:
        raise
    except Exception as exc:
        raise Gate1PilotExecutionError("Git ignore behavior verification failed") from exc
    if not private_ok or not public_ok:
        raise Gate1PilotExecutionError("Git ignore behavior differs from the privacy allowlist")


def _anchor_repo_path(repo_root: Path, value: str | Path) -> Path:
    path = Path(value)
    return (repo_root / path).resolve() if not path.is_absolute() else path.resolve()


def _verify_root_isolation(
    *,
    repo_root: str | Path,
    processed_root: str | Path,
    interim_root: str | Path,
    local_run_root: str | Path,
    public_root: str | Path,
) -> None:
    """Keep data, local predictions, and the public aggregate tree disjoint."""

    repository = Path(repo_root).resolve()
    named = {
        "processed": _anchor_repo_path(repository, processed_root),
        "interim": _anchor_repo_path(repository, interim_root),
        "local_run": _anchor_repo_path(repository, local_run_root),
        "public": _anchor_repo_path(repository, public_root),
    }
    try:
        for value in named.values():
            value.relative_to(repository)
    except ValueError as exc:
        raise Gate1PilotExecutionError("formal roots must remain inside the repository") from exc
    if any(value == repository or value == Path(value.anchor) for value in named.values()):
        raise Gate1PilotExecutionError("formal output or data root scope is unsafe")
    pairs = tuple(named.items())
    for position, (left_name, left) in enumerate(pairs):
        for right_name, right in pairs[position + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise Gate1PilotExecutionError(
                    f"formal {left_name} and {right_name} roots are not isolated"
                )


def _verify_formal_output_layout(
    *,
    repo_root: str | Path,
    processed_root: str | Path,
    interim_root: str | Path,
    local_run_root: str | Path,
    public_root: str | Path,
) -> None:
    """Bind the path-free run id and public allowlist to their tracked layout."""

    repository = Path(repo_root).resolve()

    if (
        _anchor_repo_path(repository, processed_root)
        != (repository / _PROCESSED_ROOT_RELATIVE).resolve()
    ):
        raise Gate1PilotExecutionError("processed root differs from the frozen snapshot layout")
    if (
        _anchor_repo_path(repository, interim_root)
        != (repository / _INTERIM_ROOT_RELATIVE).resolve()
    ):
        raise Gate1PilotExecutionError("interim root differs from the frozen snapshot layout")
    if (
        _anchor_repo_path(repository, local_run_root)
        != (repository / _LOCAL_RUN_RELATIVE).resolve()
    ):
        raise Gate1PilotExecutionError("local run root differs from the deterministic run id")
    if _anchor_repo_path(repository, public_root) != (repository / _PUBLIC_ROOT_RELATIVE).resolve():
        raise Gate1PilotExecutionError("public root differs from the tracked 13-file allowlist")


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _atomic_write_npy(path: Path, value: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            np.save(stream, np.asarray(value), allow_pickle=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _write_feature_matrices(root: Path, blocks: Mapping[str, Any]) -> None:
    if tuple(blocks) != TIERS:
        raise Gate1PilotExecutionError("feature matrix tier order verification failed")
    root.mkdir(parents=True, exist_ok=True)
    for tier in TIERS:
        block = blocks[tier]
        _atomic_write_npy(root / f"{tier}.values.npy", np.asarray(block.values))
        _atomic_write_npy(root / f"{tier}.issue_times.npy", np.asarray(block.issue_times))
        _atomic_write_npy(root / f"{tier}.nullable_mask.npy", np.asarray(block.nullable_mask))


def _prepare_formal_inputs(
    *,
    config_path: str | Path,
    processed_root: str | Path,
    interim_root: str | Path,
    local_run_root: str | Path,
    public_root: str | Path,
    repo_root: str | Path,
) -> _PreparedFormalInputs:
    """Run all immutable environment/Git/config/data gates before model execution."""

    from evcf.forecasting.acn_jpl_gate1_contracts import config_sha256, load_gate1_config
    from evcf.forecasting.acn_jpl_gate1_data import (
        verified_snapshot_provenance,
        verify_and_load_snapshot,
    )
    from evcf.forecasting.acn_jpl_gate1_features import (
        M4FeatureAccumulator,
        build_feature_blocks,
    )
    from evcf.forecasting.acn_jpl_gate1_models import (
        Gate1TimeSplit,
        persistence_predictions,
    )

    root = Path(repo_root).resolve()
    processed_path = _anchor_repo_path(root, processed_root)
    interim_path = _anchor_repo_path(root, interim_root)
    local_run_path = _anchor_repo_path(root, local_run_root)
    public_path = _anchor_repo_path(root, public_root)
    _verify_root_isolation(
        repo_root=root,
        processed_root=processed_path,
        interim_root=interim_path,
        local_run_root=local_run_path,
        public_root=public_path,
    )
    _verify_formal_output_layout(
        repo_root=root,
        processed_root=processed_path,
        interim_root=interim_path,
        local_run_root=local_run_path,
        public_root=public_path,
    )
    config_file = Path(config_path)
    if not config_file.is_absolute():
        config_file = root / config_file
    config_relative = _repo_relative_file(config_file, root)
    environment = _verify_environment()
    expected_commit = _expected_repeat_commit(public_path)
    git_evidence = _verify_git_preflight(
        repo_root=root,
        config_relative_path=config_relative,
        expected_repeat_commit=expected_commit,
    )
    _verify_gitignore_contract(root)
    _verify_gitignore_behavior(root)
    formal_modules = {
        module_name: importlib.import_module(module_name) for module_name in _FORMAL_MODULE_PATHS
    }
    _verify_runtime_module_binding(root, formal_modules)
    try:
        config = load_gate1_config(config_file)
        config_file_digest = config_sha256(config_file)
        accumulator = M4FeatureAccumulator()
        snapshot = verify_and_load_snapshot(
            processed_path,
            interim_path,
            causal_prefix_consumer=accumulator,
        )
        verified_snapshot_provenance(snapshot)
        if snapshot.data_snapshot_sha256 != config["data_snapshot_sha256"]:
            raise ValueError("snapshot and frozen config hashes differ")
        split = Gate1TimeSplit.from_config(snapshot.issue_times, config)
        feature_blocks = build_feature_blocks(snapshot, accumulator)
        persistence = MappingProxyType(
            {
                horizon: persistence_predictions(
                    snapshot,
                    split.test_rows,
                    horizon_minutes=horizon,
                )
                for horizon in HORIZONS_MINUTES
            }
        )
        _write_feature_matrices(processed_path / "gate1_pilot", feature_blocks)
    except Gate1PilotExecutionError:
        raise
    except Exception as exc:
        raise Gate1PilotExecutionError("frozen config or data preflight failed") from exc
    return _PreparedFormalInputs(
        config=MappingProxyType(dict(config)),
        config_file_sha256=config_file_digest,
        snapshot=snapshot,
        split=split,
        feature_blocks=feature_blocks,
        persistence_by_horizon=persistence,
        environment=environment,
        git=git_evidence,
    )


_ResultT = TypeVar("_ResultT")


class _Dispatcher(Protocol[_ResultT]):
    def __call__(
        self,
        tasks: tuple[tuple[str, str, int], ...],
        task_worker: Callable[[tuple[str, str, int]], _ResultT],
        *,
        n_jobs: int,
        backend: str,
        inner_max_num_threads: int,
    ) -> Iterable[_ResultT]: ...


def _generic_result_identity(result: Any) -> tuple[str, str, int]:
    if hasattr(result, "task"):
        value = result.task
    else:
        record = result.selection_record
        value = (record.learner, record.tier, record.horizon_minutes)
    if not isinstance(value, tuple) or len(value) != 3:
        raise TypeError("task result identity is invalid")
    return (str(value[0]), str(value[1]), int(value[2]))


def _exercise_task_scheduler(
    *,
    task_worker: Callable[[tuple[str, str, int]], _ResultT],
    result_verifier: Callable[[_ResultT], str],
    dispatcher: _Dispatcher[_ResultT],
    result_identity: Callable[[_ResultT], tuple[str, str, int]] = _generic_result_identity,
    on_verified_result: Callable[[_ResultT], None] | None = None,
) -> tuple[_ResultT, ...]:
    """Private scheduler seam used to test the fixed outer-parallel contract."""

    try:
        delivered = dispatcher(
            CANONICAL_MODEL_TASKS,
            task_worker,
            n_jobs=N_JOBS,
            backend=PARALLEL_BACKEND,
            inner_max_num_threads=INNER_MAX_NUM_THREADS,
        )
        results: list[_ResultT] = []
        for expected, result in zip(CANONICAL_MODEL_TASKS, delivered, strict=True):
            provenance = result_verifier(result)
            if not isinstance(provenance, str) or not _SHA256.fullmatch(provenance):
                raise ValueError("formal task provenance is invalid")
            if result_identity(result) != expected:
                raise ValueError(
                    "formal task result order or identity differs from canonical order"
                )
            if on_verified_result is not None:
                on_verified_result(result)
            results.append(result)
    except Exception as exc:
        if isinstance(exc, Gate1PilotExecutionError):
            raise
        raise Gate1PilotExecutionError("canonical model task execution failed") from exc
    if len(results) != len(CANONICAL_MODEL_TASKS):
        raise Gate1PilotExecutionError("canonical model task execution was incomplete")
    return tuple(results)


def _joblib_dispatch(
    tasks: tuple[tuple[str, str, int], ...],
    task_worker: Callable[[tuple[str, str, int]], _ResultT],
    *,
    n_jobs: int,
    backend: str,
    inner_max_num_threads: int,
) -> Iterable[_ResultT]:
    from joblib import Parallel, delayed, parallel_config

    with parallel_config(
        backend=backend,
        n_jobs=n_jobs,
        inner_max_num_threads=inner_max_num_threads,
    ):
        return Parallel(return_as="generator", batch_size=1)(
            delayed(task_worker)(task) for task in tasks
        )


def _formal_task_worker(
    task: tuple[str, str, int],
    *,
    snapshot: Any,
    split: Any,
    feature_blocks: Mapping[str, Any],
    config: Mapping[str, Any],
) -> Any:
    from evcf.forecasting.acn_jpl_gate1_models import run_model_task

    learner, tier, horizon = task
    return run_model_task(
        learner=learner,
        tier=tier,
        horizon_minutes=horizon,
        feature_block=feature_blocks[tier],
        snapshot=snapshot,
        split=split,
        config=config,
    )


def _formal_result_identity(result: Any) -> tuple[str, str, int]:
    record = result.selection_record
    return (record.learner, record.tier, record.horizon_minutes)


def _checkpoint_name(result: Any) -> str:
    learner, tier, horizon = _formal_result_identity(result)
    if (learner, tier, horizon) not in CANONICAL_MODEL_TASKS:
        raise Gate1PilotExecutionError("checkpoint task identity is not canonical")
    return f"{learner}-{tier}-h{horizon:03d}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_task_checkpoint(local_run_root: str | Path, result: Any) -> None:
    """Publish the ignored NPZ first and its hashed completion record last."""

    root = Path(local_run_root)
    root.mkdir(parents=True, exist_ok=True)
    record = result.selection_record
    bundle = result.prediction_bundle
    stem = _checkpoint_name(result)
    target = root / f"{stem}.predictions.npz"
    handle, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=root)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            np.savez_compressed(
                stream,
                issue_times=np.asarray(bundle.issue_times),
                y_true=np.asarray(bundle.y_true),
                predictions=np.asarray(bundle.predictions),
                day_start_utc_s=np.asarray(bundle.day_start_utc_s),
                parameter_hashes=np.asarray(bundle.parameter_hashes),
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        metadata = {
            "checkpoint_schema_version": "acn-jpl-gate1-task-checkpoint/v1",
            "learner": record.learner,
            "tier": record.tier,
            "horizon_minutes": record.horizon_minutes,
            "candidate_validation_mae_a": [
                float(value) for value in np.asarray(record.candidate_validation_mae)
            ],
            "selected_candidate_index": record.selected_candidate_index,
            "selected_parameter_sha256": record.selected_param_sha256,
            "execution_sha256": result.execution_sha256,
            "prediction_file_sha256": _sha256_file(target),
        }
        _atomic_write_bytes(
            root / f"{stem}.json",
            _canonical_local_json_bytes(metadata),
        )
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _verify_task_checkpoints(
    local_run_root: str | Path,
    results: Sequence[Any],
    *,
    require_complete_set: bool = False,
) -> None:
    """Revalidate each local JSON/NPZ pair against its sealed in-memory result."""

    root = Path(local_run_root)
    try:
        frozen_results = tuple(results)
        checkpoint_set_sha = (
            _checkpoint_set_sha256(root, frozen_results) if require_complete_set else None
        )
        expected_files: set[str] = set()
        seen_stems: set[str] = set()
        for result in frozen_results:
            stem = _checkpoint_name(result)
            if stem in seen_stems:
                raise ValueError("duplicate checkpoint task identity")
            seen_stems.add(stem)
            metadata_name = f"{stem}.json"
            prediction_name = f"{stem}.predictions.npz"
            expected_files.update((metadata_name, prediction_name))
            metadata_path = root / metadata_name
            prediction_path = root / prediction_name
            if (
                metadata_path.is_symlink()
                or prediction_path.is_symlink()
                or not metadata_path.is_file()
                or not prediction_path.is_file()
            ):
                raise ValueError("checkpoint pair is missing or unsafe")
            metadata = json.loads(metadata_path.read_text(encoding="ascii"))
            record = result.selection_record
            expected_metadata = {
                "checkpoint_schema_version": "acn-jpl-gate1-task-checkpoint/v1",
                "learner": record.learner,
                "tier": record.tier,
                "horizon_minutes": record.horizon_minutes,
                "candidate_validation_mae_a": [
                    float(value) for value in np.asarray(record.candidate_validation_mae)
                ],
                "selected_candidate_index": record.selected_candidate_index,
                "selected_parameter_sha256": record.selected_param_sha256,
                "execution_sha256": result.execution_sha256,
                "prediction_file_sha256": _sha256_file(prediction_path),
            }
            if checkpoint_set_sha is not None:
                expected_metadata.update(
                    {
                        "checkpoint_set_sha256": checkpoint_set_sha,
                        "checkpoint_set_task_count": len(CANONICAL_MODEL_TASKS),
                    }
                )
            if metadata != expected_metadata:
                raise ValueError("checkpoint metadata or prediction hash differs")
            bundle = result.prediction_bundle
            expected_arrays = {
                "issue_times": np.asarray(bundle.issue_times),
                "y_true": np.asarray(bundle.y_true),
                "predictions": np.asarray(bundle.predictions),
                "day_start_utc_s": np.asarray(bundle.day_start_utc_s),
                "parameter_hashes": np.asarray(bundle.parameter_hashes),
            }
            with np.load(prediction_path, allow_pickle=False) as archive:
                if tuple(archive.files) != tuple(expected_arrays):
                    raise ValueError("checkpoint prediction array schema differs")
                if any(
                    archive[name].dtype != expected.dtype
                    or archive[name].shape != expected.shape
                    or not np.array_equal(archive[name], expected)
                    for name, expected in expected_arrays.items()
                ):
                    raise ValueError("checkpoint prediction arrays differ from formal result")
        actual_files = {path.name for path in root.iterdir()}
        if actual_files != expected_files:
            raise ValueError("checkpoint directory contains an incomplete or extra task artifact")
    except Gate1PilotExecutionError:
        raise
    except Exception as exc:
        raise Gate1PilotExecutionError("local task checkpoint verification failed") from exc


def _checkpoint_set_sha256(root: Path, results: Sequence[Any]) -> str:
    frozen_results = tuple(results)
    if tuple(_formal_result_identity(result) for result in frozen_results) != CANONICAL_MODEL_TASKS:
        raise ValueError("complete checkpoint seal requires the canonical 40 task order")
    tasks = []
    for result in frozen_results:
        stem = _checkpoint_name(result)
        tasks.append(
            {
                "task_name": stem,
                "execution_sha256": result.execution_sha256,
                "prediction_file_sha256": _sha256_file(root / f"{stem}.predictions.npz"),
            }
        )
    payload = {
        "checkpoint_set_schema_version": "acn-jpl-gate1-checkpoint-set/v1",
        "canonical_task_count": len(CANONICAL_MODEL_TASKS),
        "tasks": tasks,
    }
    return hashlib.sha256(_canonical_local_json_bytes(payload)).hexdigest()


def _seal_complete_checkpoint_set(
    local_run_root: str | Path,
    results: Sequence[Any],
) -> str:
    """Mark all 40 pairs as one complete generation without adding a 81st file."""

    root = Path(local_run_root)
    frozen_results = tuple(results)
    _verify_task_checkpoints(root, frozen_results)
    try:
        checkpoint_set_sha = _checkpoint_set_sha256(root, frozen_results)
        for result in frozen_results:
            stem = _checkpoint_name(result)
            metadata_path = root / f"{stem}.json"
            metadata = json.loads(metadata_path.read_text(encoding="ascii"))
            metadata.update(
                {
                    "checkpoint_set_sha256": checkpoint_set_sha,
                    "checkpoint_set_task_count": len(CANONICAL_MODEL_TASKS),
                }
            )
            _atomic_write_bytes(metadata_path, _canonical_local_json_bytes(metadata))
        _verify_task_checkpoints(root, frozen_results, require_complete_set=True)
    except Gate1PilotExecutionError:
        raise
    except Exception as exc:
        raise Gate1PilotExecutionError("complete checkpoint set sealing failed") from exc
    return checkpoint_set_sha


def _run_canonical_model_tasks(
    prepared: _PreparedFormalInputs,
    local_run_root: str | Path,
) -> tuple[Any, ...]:
    from evcf.forecasting.acn_jpl_gate1_models import (
        verified_formal_model_task_provenance,
    )

    worker = partial(
        _formal_task_worker,
        snapshot=prepared.snapshot,
        split=prepared.split,
        feature_blocks=dict(prepared.feature_blocks),
        config=dict(prepared.config),
    )
    checkpoint_root = Path(local_run_root)
    results = _exercise_task_scheduler(
        task_worker=worker,
        result_verifier=verified_formal_model_task_provenance,
        result_identity=_formal_result_identity,
        dispatcher=_joblib_dispatch,
        on_verified_result=partial(_write_task_checkpoint, checkpoint_root),
    )
    _seal_complete_checkpoint_set(checkpoint_root, results)
    return results


def _environment_manifest(
    evidence: _EnvironmentEvidence,
    *,
    execution_commit_sha: str,
    data_snapshot_sha256: str,
    config_sha256: str,
    config_file_sha256: str,
) -> dict[str, Any]:
    if not _COMMIT_SHA.fullmatch(execution_commit_sha) or any(
        not _SHA256.fullmatch(value)
        for value in (data_snapshot_sha256, config_sha256, config_file_sha256)
    ):
        raise ValueError("environment manifest provenance is invalid")
    return {
        "schema_version": "acn-jpl-gate1-environment/v1",
        "environment_name": "evcf-gate1-pilot",
        "operating_system": evidence.operating_system,
        "python_version": evidence.python_version,
        "dependencies": dict(evidence.dependencies),
        "thread_caps": dict(evidence.thread_caps),
        "execution_device": "CPU",
        "gpu_used": False,
        "network_access": False,
        "execution_commit_sha": execution_commit_sha,
        "data_snapshot_sha256": data_snapshot_sha256,
        "config_sha256": config_sha256,
        "config_file_sha256": config_file_sha256,
        "parallelism": {
            "backend": PARALLEL_BACKEND,
            "n_jobs": N_JOBS,
            "inner_max_num_threads": INNER_MAX_NUM_THREADS,
        },
    }


def _run_manifest(
    *,
    execution_commit_sha: str,
    config_file_sha256: str,
    config_contract_sha256: str,
    data_snapshot_sha256: str,
    snapshot_verification_sha256: str,
    split_sha256: str,
    formal_implementation_sha256: str,
) -> dict[str, Any]:
    digests = (
        config_file_sha256,
        config_contract_sha256,
        data_snapshot_sha256,
        snapshot_verification_sha256,
        split_sha256,
        formal_implementation_sha256,
    )
    if not _COMMIT_SHA.fullmatch(execution_commit_sha) or any(
        not _SHA256.fullmatch(value) for value in digests
    ):
        raise ValueError("run manifest provenance is invalid")
    return {
        "schema_version": "acn-jpl-gate1-run/v1",
        "execution_commit_sha": execution_commit_sha,
        "config_file_sha256": config_file_sha256,
        "config_contract_sha256": config_contract_sha256,
        "data_snapshot_sha256": data_snapshot_sha256,
        "snapshot_verification_sha256": snapshot_verification_sha256,
        "split_sha256": split_sha256,
        "formal_implementation_sha256": formal_implementation_sha256,
        "model_seed": 20260901,
        "bootstrap_seed": 20260902,
        "bootstrap_repetitions": 10000,
        "local_run_id": LOCAL_RUN_ID,
        "canonical_model_task_count": len(CANONICAL_MODEL_TASKS),
        "parallelism": {
            "backend": PARALLEL_BACKEND,
            "n_jobs": N_JOBS,
            "inner_max_num_threads": INNER_MAX_NUM_THREADS,
        },
        "reproducibility": {
            "repeat_policy": "recompute_all_40_then_byte_compare",
            "public_comparison": "all 13 files byte-for-byte",
        },
        "audits": {
            "tracked_worktree_clean": True,
            "formal_branch_verified": True,
            "complete_task_count": True,
            "models_serialized": False,
            "full_test_values_published": False,
            "local_paths_published": False,
        },
    }


def _data_snapshot_manifest(prepared: _PreparedFormalInputs) -> dict[str, Any]:
    snapshot = prepared.snapshot
    artifacts = [
        {"artifact_name": name, "sha256": digest}
        for name, digest in sorted(snapshot.artifact_sha256.items())
    ]
    manifest = {
        "schema_version": "acn-jpl-gate1-data-snapshot/v1",
        "data_snapshot_sha256": snapshot.data_snapshot_sha256,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "issue_time_count": len(snapshot.issue_times),
        "horizons_minutes": list(HORIZONS_MINUTES),
        "target": "station_current_mean_a",
        "audits": {
            "snapshot_verified": True,
            "five_horizon_common_cohort": True,
            "raw_data_published": False,
            "private_identifiers_published": False,
            "local_paths_published": False,
        },
    }
    assert_public_release_safe(manifest)
    return manifest


def _evaluate_formal_results(prepared: _PreparedFormalInputs, task_results: Sequence[Any]) -> Any:
    """Single adapter point for Task 5's sealed formal evaluation API."""

    from evcf.evaluation.acn_jpl_gate1_metrics import evaluate_gate1

    return evaluate_gate1(
        task_results=task_results,
        persistence_by_horizon=prepared.persistence_by_horizon,
        snapshot=prepared.snapshot,
        split=prepared.split,
    )


def _evaluate_and_render_formal_release(
    prepared: _PreparedFormalInputs,
    task_results: Sequence[Any],
) -> Mapping[str, bytes]:
    from evcf.forecasting.acn_jpl_gate1_data import verified_snapshot_provenance
    from evcf.forecasting.acn_jpl_gate1_features import feature_encoding_manifest
    from evcf.forecasting.acn_jpl_gate1_models import build_model_selection_manifest

    evaluation = _evaluate_formal_results(prepared, task_results)
    decision = evaluation.gate_decision
    if decision.execution_ok is not True or decision.classification == EXECUTION_FAIL:
        raise Gate1PilotExecutionError("formal evaluation reported an execution failure")
    model_manifest = build_model_selection_manifest(
        config=prepared.config,
        snapshot=prepared.snapshot,
        split=prepared.split,
        feature_blocks=prepared.feature_blocks,
        task_results=task_results,
        persistence_by_horizon=prepared.persistence_by_horizon,
    )
    provenance = model_manifest["provenance"]
    run_manifest = _run_manifest(
        execution_commit_sha=prepared.git.execution_commit_sha,
        config_file_sha256=prepared.config_file_sha256,
        config_contract_sha256=provenance["config_sha256"],
        data_snapshot_sha256=prepared.snapshot.data_snapshot_sha256,
        snapshot_verification_sha256=verified_snapshot_provenance(prepared.snapshot),
        split_sha256=prepared.split.frozen_provenance_sha256,
        formal_implementation_sha256=provenance["formal_implementation_sha256"],
    )
    return build_public_release_files(
        evaluation_result=evaluation,
        model_selection_manifest=model_manifest,
        feature_encoding_manifest=feature_encoding_manifest(prepared.feature_blocks),
        environment_manifest=_environment_manifest(
            prepared.environment,
            execution_commit_sha=prepared.git.execution_commit_sha,
            data_snapshot_sha256=prepared.snapshot.data_snapshot_sha256,
            config_sha256=provenance["config_sha256"],
            config_file_sha256=prepared.config_file_sha256,
        ),
        run_manifest=run_manifest,
        data_snapshot_manifest=_data_snapshot_manifest(prepared),
    )


def run_gate1_pilot(
    *,
    authorized: bool,
    config_path: str | Path,
    processed_root: str | Path,
    interim_root: str | Path,
    local_run_root: str | Path,
    public_root: str | Path,
    repo_root: str | Path = Path("."),
) -> Gate1PilotOutcome:
    """Run one complete formal pass; never reuse a prior task checkpoint."""

    if authorized is not True:
        raise PermissionError("explicit --authorize-run approval is required")
    try:
        prepared = _prepare_formal_inputs(
            config_path=config_path,
            processed_root=processed_root,
            interim_root=interim_root,
            local_run_root=local_run_root,
            public_root=public_root,
            repo_root=repo_root,
        )
        task_results = _run_canonical_model_tasks(prepared, Path(local_run_root))
        if len(task_results) != len(CANONICAL_MODEL_TASKS):
            raise Gate1PilotExecutionError("formal model task result count is incomplete")
        files = _evaluate_and_render_formal_release(prepared, task_results)
        reproducibility = _publish_or_compare_public_release(public_root, files)
        summary = json.loads(files["gate1_summary.json"].decode("ascii"))
        status = summary.get("status")
        if status not in _SUCCESS_CLASSIFICATIONS:
            raise Gate1PilotExecutionError("formal scientific classification is invalid")
        return Gate1PilotOutcome(
            status=status,
            task_count=len(task_results),
            public_file_count=len(files),
            reproducibility_status=reproducibility,
        )
    except PermissionError:
        raise
    except Gate1PilotExecutionError:
        raise
    except Exception as exc:
        raise Gate1PilotExecutionError() from exc


__all__ = [
    "CANONICAL_MODEL_TASKS",
    "EXECUTION_FAIL",
    "LOCAL_RUN_ID",
    "PUBLIC_FILENAMES",
    "THREAD_CAP_ENV_VARS",
    "Gate1PilotExecutionError",
    "Gate1PilotOutcome",
    "assert_public_release_safe",
    "build_public_release_files",
    "canonical_csv_bytes",
    "canonical_json_bytes",
    "run_gate1_pilot",
]
