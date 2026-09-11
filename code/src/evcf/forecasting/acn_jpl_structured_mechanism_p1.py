"""Frozen development-only P1 structured mechanism probe for JPL current forecasting.

P1 is intentionally low complexity. It reuses the accepted development snapshots,
baseline cache, S1 cache, rolling-origin boundaries, and S1 physical component
reconstruction. It adds only two pre-registered mechanism probes:

* existing-session contribution = continuation probability x positive-current mark;
* future-arrival contribution = contributing-session count x positive-current mark.

No final-holdout data, hyperparameter search, reliability/composition gate, clipping,
calibration, formal survival model, or neural TPP is used here.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import yaml
from sklearn.impute import SimpleImputer
from sklearn.linear_model import GammaRegressor, LogisticRegression, PoissonRegressor
from sklearn.metrics import mean_poisson_deviance
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from evcf.forecasting.acn_jpl_development_experts import (
    DevelopmentExpertProtocol,
    MonthData,
)
from evcf.forecasting.acn_jpl_development_experts_compat import (
    load_development_expert_protocol,
    load_month_data,
)
from evcf.forecasting.acn_jpl_gate1_features import M3_SESSION_FIELDS
from evcf.forecasting.acn_jpl_structured_baseline import (
    _CleanCurrentSession,
    _session_integral,
)

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
TIMEZONE_NAME = "America/Los_Angeles"
_ZONE = ZoneInfo(TIMEZONE_NAME)

DEFAULT_PROTOCOL_PATH = Path(
    "code/configs/acn_jpl_structured_mechanism_p1_2019.yaml"
)
SOURCE_EXPERT_PROTOCOL_PATH = Path(
    "code/configs/acn_jpl_development_experts_2019.yaml"
)
EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256 = (
    "02c7809f1113aeaf20723030c96006ee0831b20ff219106da7d6968df535d71a"
)
EXPECTED_SOURCE_MODEL_SELECTION_SHA256 = (
    "a43ac609629d0dfa1568ce19d8e51666cbeb8392d96cbe976927f9397f19cb0d"
)
EXPECTED_BASELINE_PRIVATE_MANIFEST_SHA256 = (
    "2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd"
)
EXPECTED_S1_PRIVATE_MANIFEST_SHA256 = (
    "562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1"
)
EXPECTED_S1_PROTOCOL_SHA256 = (
    "74af85044d12f3c68fe4156e6ad1ae67b6e5486b47aecd5637cd67d6539c1902"
)
_RECONSTRUCTION_TOLERANCE_A = 1e-6
_NATIVE_THREAD_LIMIT = 1
_E_RAW_DIMENSION = 14
_E_MISSING_INDICATORS = 11
_A_RAW_DIMENSION = 201
_A_MISSING_INDICATORS = 3

IMPLEMENTATION_PATHS = (
    "code/configs/acn_jpl_development_experts_2019.yaml",
    "code/configs/acn_jpl_structured_baseline_2019.yaml",
    "code/configs/acn_jpl_structured_mechanism_p1_2019.yaml",
    "code/src/evcf/data/acn_jpl_cleaning.py",
    "code/src/evcf/data/acn_jpl_issue_snapshots.py",
    "code/src/evcf/forecasting/acn_jpl_development_experts.py",
    "code/src/evcf/forecasting/acn_jpl_development_experts_compat.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_features.py",
    "code/src/evcf/forecasting/acn_jpl_structured_baseline.py",
    "code/src/evcf/forecasting/acn_jpl_structured_mechanism_p1.py",
    "docs/JPL_STRUCTURED_MECHANISM_PROBE_PROTOCOL_20260911.md",
    "scripts/run_jpl_structured_mechanism_p1.py",
)


class MechanismP1Error(RuntimeError):
    """Static path-free failure code safe for aggregate reporting."""

    def __init__(self, reason_code: str) -> None:
        if (
            not isinstance(reason_code, str)
            or not reason_code
            or not reason_code.replace("_", "").isalnum()
        ):
            reason_code = "UNEXPECTED_ERROR"
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class MonthContract:
    month: str
    formal_issue_times: int
    cleaned_session_count: int
    processed_snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class MechanismP1Protocol:
    protocol_id: str
    protocol_sha256: str
    months: tuple[MonthContract, ...]
    source_expert_protocol_sha256: str
    source_model_selection_sha256: str
    baseline_private_manifest_sha256: str
    s1_private_manifest_sha256: str
    s1_protocol_sha256: str
    test_start_local_day: int
    branch_min_horizon_wins: int
    branch_min_month_wins: int
    pass_min_horizon_wins: int
    pass_min_month_wins: int
    pass_max_horizon_degradation_fraction: float


@dataclass(frozen=True, slots=True)
class _IndexedSession:
    session_index: int
    connection_utc_s: int
    disconnect_utc_s: int
    current: _CleanCurrentSession


@dataclass(frozen=True, slots=True)
class _SessionFeatureTable:
    issue_indices: np.ndarray
    issue_times: np.ndarray
    session_indices: np.ndarray
    raw_features: np.ndarray


@dataclass(frozen=True, slots=True)
class _MonthTargets:
    existing_total: np.ndarray
    arrival_total: np.ndarray
    session_contribution: np.ndarray
    arrival_count: np.ndarray
    arrival_mark: np.ndarray


@dataclass(frozen=True, slots=True)
class _TaskResult:
    month: str
    horizon_minutes: int
    issue_times: np.ndarray
    day_starts: np.ndarray
    y_true: np.ndarray
    existing_truth: np.ndarray
    arrival_truth: np.ndarray
    p1_existing: np.ndarray
    p1_arrival: np.ndarray
    p1_eonly: np.ndarray
    p1_aonly: np.ndarray
    p1_ea: np.ndarray
    continuation_truth: np.ndarray
    continuation_probability: np.ndarray
    existing_positive_mark_truth: np.ndarray
    existing_positive_mark_prediction: np.ndarray
    arrival_count_truth: np.ndarray
    arrival_count_prediction: np.ndarray
    arrival_positive_mark_truth: np.ndarray
    arrival_positive_mark_prediction: np.ndarray
    e_logistic_fits: int
    e_gamma_fits: int
    a_poisson_fits: int
    a_gamma_fits: int


@dataclass(frozen=True, slots=True)
class MechanismP1RunResult:
    status: str
    protocol_sha256: str
    code_commit: str
    source_expert_protocol_sha256: str
    baseline_private_manifest_sha256: str
    s1_private_manifest_sha256: str
    decision: str
    existing_branch_decision: str
    arrival_branch_decision: str
    fit_counts: Mapping[str, int]
    private_cache_file_count: int
    private_manifest_sha256: str
    month_summaries: tuple[Mapping[str, Any], ...]
    pooled_by_horizon: tuple[Mapping[str, Any], ...]
    pooled_by_month: tuple[Mapping[str, Any], ...]
    pooled_overall: Mapping[str, Any]
    holdout_accessed: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "evcf-jpl-structured-mechanism-p1-summary/v1",
            "status": self.status,
            "protocol_sha256": self.protocol_sha256,
            "code_commit": self.code_commit,
            "source_expert_protocol_sha256": self.source_expert_protocol_sha256,
            "baseline_private_manifest_sha256": self.baseline_private_manifest_sha256,
            "s1_private_manifest_sha256": self.s1_private_manifest_sha256,
            "decision": self.decision,
            "existing_branch_decision": self.existing_branch_decision,
            "arrival_branch_decision": self.arrival_branch_decision,
            "fit_counts": dict(self.fit_counts),
            "private_cache_file_count": self.private_cache_file_count,
            "private_manifest_sha256": self.private_manifest_sha256,
            "months": [dict(item) for item in self.month_summaries],
            "pooled_by_horizon": [dict(item) for item in self.pooled_by_horizon],
            "pooled_by_month": [dict(item) for item in self.pooled_by_month],
            "pooled_overall": dict(self.pooled_overall),
            "holdout_accessed": self.holdout_accessed,
            "development_only": True,
            "hyperparameter_search": False,
            "prediction_clipping": False,
            "prediction_calibration": False,
            "reliability_gate": False,
            "composition_gate": False,
            "formal_survival_hazard": False,
            "neural_tpp": False,
        }


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise MechanismP1Error("PUBLIC_RESULT_INVALID") from exc


def _validate_sha256(value: Any, reason: str = "PROTOCOL_INVALID") -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise MechanismP1Error(reason)
    return value


def _mapping(value: Any, keys: Sequence[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or tuple(value) != tuple(keys):
        raise MechanismP1Error("PROTOCOL_INVALID")
    return value


def load_mechanism_p1_protocol(
    path: str | Path = DEFAULT_PROTOCOL_PATH,
) -> MechanismP1Protocol:
    source = Path(path)
    try:
        raw = source.read_bytes()
        doc = yaml.safe_load(raw.decode("utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise MechanismP1Error("PROTOCOL_INVALID") from exc
    top = _mapping(
        doc,
        (
            "schema_version",
            "protocol_id",
            "target",
            "development_months",
            "final_holdout",
            "source_identities",
            "horizons_minutes",
            "rolling_origin",
            "component_targets",
            "probe_e",
            "probe_a",
            "preprocessing",
            "degenerate_folds",
            "prediction",
            "variants",
            "evaluation",
            "decision",
            "publication",
        ),
    )
    if top["schema_version"] != "acn-jpl-structured-mechanism-p1-protocol/v1":
        raise MechanismP1Error("PROTOCOL_INVALID")
    if top["target"] != {"name": "station_current_mean_a", "unit": "A"}:
        raise MechanismP1Error("PROTOCOL_INVALID")
    months_doc = top["development_months"]
    if not isinstance(months_doc, Mapping) or tuple(months_doc) != DEVELOPMENT_MONTHS:
        raise MechanismP1Error("PROTOCOL_INVALID")
    months: list[MonthContract] = []
    expected_counts = {
        "2019-01": (2836, 1372),
        "2019-04": (2552, 1524),
        "2019-07": (2742, 1489),
        "2019-10": (2742, 1673),
    }
    for month in DEVELOPMENT_MONTHS:
        item = _mapping(
            months_doc[month],
            ("formal_issue_times", "cleaned_session_count", "processed_snapshot_sha256"),
        )
        formal, cleaned = expected_counts[month]
        if (
            item["formal_issue_times"] != formal
            or item["cleaned_session_count"] != cleaned
        ):
            raise MechanismP1Error("PROTOCOL_INVALID")
        months.append(
            MonthContract(
                month=month,
                formal_issue_times=formal,
                cleaned_session_count=cleaned,
                processed_snapshot_sha256=_validate_sha256(
                    item["processed_snapshot_sha256"]
                ),
            )
        )
    if top["final_holdout"] != {
        "months": list(FINAL_HOLDOUT_MONTHS),
        "access_allowed": False,
    }:
        raise MechanismP1Error("PROTOCOL_INVALID")
    identities = _mapping(
        top["source_identities"],
        (
            "source_expert_protocol_sha256",
            "source_model_selection_sha256",
            "baseline_private_manifest_sha256",
            "s1_private_manifest_sha256",
            "s1_protocol_sha256",
        ),
    )
    expected_identities = {
        "source_expert_protocol_sha256": EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256,
        "source_model_selection_sha256": EXPECTED_SOURCE_MODEL_SELECTION_SHA256,
        "baseline_private_manifest_sha256": EXPECTED_BASELINE_PRIVATE_MANIFEST_SHA256,
        "s1_private_manifest_sha256": EXPECTED_S1_PRIVATE_MANIFEST_SHA256,
        "s1_protocol_sha256": EXPECTED_S1_PROTOCOL_SHA256,
    }
    if dict(identities) != expected_identities:
        raise MechanismP1Error("PROTOCOL_INVALID")
    if top["horizons_minutes"] != list(HORIZONS_MINUTES):
        raise MechanismP1Error("PROTOCOL_INVALID")
    rolling = top["rolling_origin"]
    if rolling != {
        "timezone": TIMEZONE_NAME,
        "test_start_local_day": 18,
        "refit_frequency": "local_midnight_daily",
        "use_same_month_history_only": True,
        "fit_issue_rule": "issue_time_utc_s < refit_cutoff_utc_s",
        "fit_label_rule": "issue_time_utc_s + horizon_minutes * 60 <= refit_cutoff_utc_s",
        "test_rule": "all_formal_rows_on_local_test_day",
    }:
        raise MechanismP1Error("PROTOCOL_INVALID")
    component = top["component_targets"]
    if component != {
        "target_window": "[issue+h-15min, issue+h)",
        "positive_contribution_rule": "contribution_a > 0",
        "existing_rule": "connection_time_utc_s <= issue_time_utc_s",
        "arrival_rule": "connection_time_utc_s > issue_time_utc_s",
        "reconstruction_absolute_tolerance_a": 0.000001,
    }:
        raise MechanismP1Error("PROTOCOL_INVALID")
    probe_e = top["probe_e"]
    if (
        not isinstance(probe_e, Mapping)
        or probe_e.get("continuation_model")
        != {
            "family": "logistic_regression",
            "penalty": "l2",
            "C": 1.0,
            "solver": "lbfgs",
            "max_iter": 1000,
            "class_weight": None,
        }
        or probe_e.get("positive_mark_model")
        != {"family": "gamma_regressor", "alpha": 1.0, "max_iter": 1000}
    ):
        raise MechanismP1Error("PROTOCOL_INVALID")
    predictors = probe_e.get("predictors")
    if (
        not isinstance(predictors, Mapping)
        or tuple(predictors.get("session_fields", ())) != tuple(M3_SESSION_FIELDS)
        or predictors.get("calendar_fields")
        != ["quarter_hour_index", "day_of_week", "is_weekend"]
        or tuple(predictors.get("fixed_missing_indicator_fields", ()))
        != tuple(M3_SESSION_FIELDS)
    ):
        raise MechanismP1Error("PROTOCOL_INVALID")
    probe_a = top["probe_a"]
    if (
        not isinstance(probe_a, Mapping)
        or probe_a.get("input_tier") != "M2"
        or probe_a.get("count_model")
        != {"family": "poisson_regressor", "alpha": 1.0, "max_iter": 1000}
        or probe_a.get("positive_mark_model")
        != {"family": "gamma_regressor", "alpha": 1.0, "max_iter": 1000}
    ):
        raise MechanismP1Error("PROTOCOL_INVALID")
    preprocessing = top["preprocessing"]
    if preprocessing != {
        "imputer": "median",
        "keep_empty_features": True,
        "scaler": "standard",
        "fit_on_training_fold_only": True,
        "probe_e_raw_dimension": _E_RAW_DIMENSION,
        "probe_e_missing_indicator_count": _E_MISSING_INDICATORS,
        "probe_a_raw_dimension": _A_RAW_DIMENSION,
        "probe_a_missing_indicator_count": _A_MISSING_INDICATORS,
    }:
        raise MechanismP1Error("PROTOCOL_INVALID")
    if top["degenerate_folds"] != {
        "continuation_one_class": "predict_training_class_probability",
        "count_all_zero": "predict_zero",
        "positive_mark_zero_rows": "predict_zero",
        "positive_mark_one_row": "predict_single_training_mark",
    }:
        raise MechanismP1Error("PROTOCOL_INVALID")
    if top["prediction"] != {
        "clipping": False,
        "calibration": False,
        "hyperparameter_search": False,
        "reliability_gate": False,
        "composition_gate": False,
        "formal_survival_hazard": False,
        "neural_tpp": False,
        "native_thread_limit": 1,
    }:
        raise MechanismP1Error("PROTOCOL_INVALID")
    if top["variants"] != {
        "primary": "P1-EA",
        "attribution_only": ["P1-Eonly", "P1-Aonly"],
    }:
        raise MechanismP1Error("PROTOCOL_INVALID")
    decision = _mapping(top["decision"], ("branch_stable", "pass", "stop"))
    branch = decision["branch_stable"]
    pass_rule = decision["pass"]
    stop_rule = decision["stop"]
    if branch != {
        "pooled_component_mae_better_than_s1_branch": True,
        "min_horizons_better_than_s1_branch": 3,
        "min_months_better_than_s1_branch": 3,
    }:
        raise MechanismP1Error("PROTOCOL_INVALID")
    if pass_rule != {
        "pooled_mae_better_than_equal": True,
        "pooled_mae_better_than_s1": True,
        "min_horizons_better_than_equal": 3,
        "min_months_better_than_equal": 3,
        "max_horizon_mae_degradation_vs_equal_fraction": 0.05,
        "require_60min_better_than_equal": True,
    }:
        raise MechanismP1Error("PROTOCOL_INVALID")
    if stop_rule != {
        "require_no_pooled_component_improvement": True,
        "require_primary_not_better_than_equal": True,
        "require_primary_not_better_than_s1": True,
    }:
        raise MechanismP1Error("PROTOCOL_INVALID")
    protocol_id = top["protocol_id"]
    if not isinstance(protocol_id, str) or not protocol_id:
        raise MechanismP1Error("PROTOCOL_INVALID")
    return MechanismP1Protocol(
        protocol_id=protocol_id,
        protocol_sha256=_sha256_bytes(raw),
        months=tuple(months),
        source_expert_protocol_sha256=EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256,
        source_model_selection_sha256=EXPECTED_SOURCE_MODEL_SELECTION_SHA256,
        baseline_private_manifest_sha256=EXPECTED_BASELINE_PRIVATE_MANIFEST_SHA256,
        s1_private_manifest_sha256=EXPECTED_S1_PRIVATE_MANIFEST_SHA256,
        s1_protocol_sha256=EXPECTED_S1_PROTOCOL_SHA256,
        test_start_local_day=18,
        branch_min_horizon_wins=3,
        branch_min_month_wins=3,
        pass_min_horizon_wins=3,
        pass_min_month_wins=3,
        pass_max_horizon_degradation_fraction=0.05,
    )


def verify_mechanism_p1_implementation_commit(
    code_commit: str,
    *,
    repo_root: str | Path,
) -> None:
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise MechanismP1Error("IMPLEMENTATION_DRIFT")
    root = Path(repo_root).resolve(strict=True)
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
        encoding="ascii",
        errors="ignore",
    )
    if completed.returncode != 0 or completed.stdout.strip() != code_commit:
        raise MechanismP1Error("IMPLEMENTATION_DRIFT")
    for relative in IMPLEMENTATION_PATHS:
        path = root / PurePosixPath(relative)
        if not path.is_file() or path.is_symlink():
            raise MechanismP1Error("IMPLEMENTATION_DRIFT")
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{code_commit}:{relative}"],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if exists.returncode != 0:
            raise MechanismP1Error("IMPLEMENTATION_DRIFT")
    diff = subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            "--no-ext-diff",
            code_commit,
            "--",
            *IMPLEMENTATION_PATHS,
        ],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if diff.returncode != 0:
        raise MechanismP1Error("IMPLEMENTATION_DRIFT")


def _expected_cache_names() -> set[str]:
    return {
        f"{month}_h{horizon:03d}.npz"
        for month in DEVELOPMENT_MONTHS
        for horizon in HORIZONS_MINUTES
    }


def _verify_private_cache(
    root: Path,
    *,
    expected_manifest_sha256: str,
    schema_version: str,
    entries_key: str,
) -> Mapping[str, Any]:
    manifest_path = root / "private_manifest.json"
    if (
        not root.is_dir()
        or root.is_symlink()
        or not manifest_path.is_file()
        or manifest_path.is_symlink()
        or _sha256_file(manifest_path) != expected_manifest_sha256
    ):
        raise MechanismP1Error("PRIVATE_CACHE_INVALID")
    try:
        doc = json.loads(manifest_path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MechanismP1Error("PRIVATE_CACHE_INVALID") from exc
    entries = doc.get(entries_key) if isinstance(doc, Mapping) else None
    if doc.get("schema_version") != schema_version or not isinstance(entries, list):
        raise MechanismP1Error("PRIVATE_CACHE_INVALID")
    expected = _expected_cache_names()
    seen: set[str] = set()
    for item in entries:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"name", "sha256"}
            or not isinstance(item["name"], str)
            or not isinstance(item["sha256"], str)
        ):
            raise MechanismP1Error("PRIVATE_CACHE_INVALID")
        name = item["name"]
        path = root / name
        if (
            name in seen
            or name not in expected
            or not path.is_file()
            or path.is_symlink()
            or _sha256_file(path) != item["sha256"]
        ):
            raise MechanismP1Error("PRIVATE_CACHE_INVALID")
        seen.add(name)
    if seen != expected:
        raise MechanismP1Error("PRIVATE_CACHE_INVALID")
    return doc


def _load_npz(path: Path, required: set[str]) -> dict[str, np.ndarray]:
    try:
        with np.load(path, allow_pickle=False) as archive:
            if set(archive.files) != required:
                raise MechanismP1Error("PRIVATE_CACHE_INVALID")
            output = {name: np.asarray(archive[name]) for name in required}
    except MechanismP1Error:
        raise
    except (OSError, ValueError) as exc:
        raise MechanismP1Error("PRIVATE_CACHE_INVALID") from exc
    return output


def _load_source_caches(
    *,
    baseline_root: Path,
    s1_root: Path,
    month: str,
    horizon: int,
) -> dict[str, np.ndarray]:
    baseline = _load_npz(
        baseline_root / f"{month}_h{horizon:03d}.npz",
        {
            "issue_times",
            "day_start_utc_s",
            "y_true",
            "m2_predictions",
            "m3_predictions",
            "equal_predictions",
        },
    )
    s1 = _load_npz(
        s1_root / f"{month}_h{horizon:03d}.npz",
        {
            "issue_times",
            "day_start_utc_s",
            "y_true",
            "existing_truth",
            "arrival_truth",
            "existing_predictions",
            "arrival_predictions",
            "structured_predictions",
        },
    )
    n = len(s1["issue_times"])
    if (
        n == 0
        or any(array.shape != (n,) for array in s1.values())
        or any(array.shape != (n,) for array in baseline.values())
        or not np.array_equal(baseline["issue_times"], s1["issue_times"])
        or not np.array_equal(baseline["day_start_utc_s"], s1["day_start_utc_s"])
        or not np.allclose(
            baseline["y_true"],
            s1["y_true"],
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
        or not np.allclose(
            s1["existing_truth"] + s1["arrival_truth"],
            s1["y_true"],
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
        or not np.allclose(
            s1["existing_predictions"] + s1["arrival_predictions"],
            s1["structured_predictions"],
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
    ):
        raise MechanismP1Error("COMMON_ROW_IDENTITY_INVALID")
    numeric = [
        array
        for key, array in {**baseline, **s1}.items()
        if key not in {"issue_times", "day_start_utc_s"}
    ]
    if not all(np.isfinite(array).all() for array in numeric):
        raise MechanismP1Error("PRIVATE_CACHE_INVALID")
    return {**baseline, **s1}


def _load_indexed_sessions(
    path: Path,
    *,
    expected_count: int,
) -> tuple[_IndexedSession, ...]:
    sessions: list[_IndexedSession] = []
    seen: set[int] = set()
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for line in handle:
                if not line.strip():
                    raise MechanismP1Error("CLEANED_SESSION_INVALID")
                item = json.loads(line)
                if (
                    not isinstance(item, Mapping)
                    or item.get("schema_version") != "acn-jpl-clean-session/v1"
                ):
                    raise MechanismP1Error("CLEANED_SESSION_INVALID")
                session_index = item.get("session_index")
                connection = item.get("connection_utc_s")
                disconnect = item.get("disconnect_utc_s")
                current = item.get("current")
                if (
                    isinstance(session_index, bool)
                    or not isinstance(session_index, int)
                    or session_index < 0
                    or session_index in seen
                    or isinstance(connection, bool)
                    or not isinstance(connection, int)
                    or isinstance(disconnect, bool)
                    or not isinstance(disconnect, int)
                    or disconnect <= connection
                    or not isinstance(current, Mapping)
                    or current.get("field_name") != "chargingCurrent"
                ):
                    raise MechanismP1Error("CLEANED_SESSION_INVALID")
                timestamps = current.get("timestamps_utc_s")
                values = current.get("values")
                ordinals = current.get("raw_ordinals")
                hold_cap = current.get("locf_cap_s")
                if (
                    not isinstance(timestamps, list)
                    or not isinstance(values, list)
                    or not isinstance(ordinals, list)
                    or len(timestamps) != len(values)
                    or len(values) != len(ordinals)
                    or isinstance(hold_cap, bool)
                    or not isinstance(hold_cap, int)
                    or hold_cap <= 0
                ):
                    raise MechanismP1Error("CLEANED_SESSION_INVALID")
                parsed_times: list[int] = []
                parsed_values: list[float] = []
                previous: int | None = None
                for timestamp, value, ordinal in zip(
                    timestamps, values, ordinals, strict=True
                ):
                    if (
                        isinstance(timestamp, bool)
                        or not isinstance(timestamp, int)
                        or isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or isinstance(ordinal, bool)
                        or not isinstance(ordinal, int)
                    ):
                        raise MechanismP1Error("CLEANED_SESSION_INVALID")
                    parsed = float(value)
                    if (
                        timestamp < connection
                        or timestamp >= disconnect
                        or not math.isfinite(parsed)
                        or parsed < 0
                        or (previous is not None and timestamp <= previous)
                    ):
                        raise MechanismP1Error("CLEANED_SESSION_INVALID")
                    parsed_times.append(timestamp)
                    parsed_values.append(parsed)
                    previous = timestamp
                starts = np.asarray(parsed_times, dtype=np.int64)
                current_values = np.asarray(parsed_values, dtype=np.float64)
                ends = np.empty_like(starts)
                for index, timestamp in enumerate(starts):
                    next_timestamp = (
                        int(starts[index + 1])
                        if index + 1 < len(starts)
                        else disconnect
                    )
                    ends[index] = min(
                        next_timestamp,
                        int(timestamp) + hold_cap,
                        disconnect,
                    )
                keep = ends > starts
                base = _CleanCurrentSession(
                    connection_utc_s=connection,
                    disconnect_utc_s=disconnect,
                    starts=starts[keep],
                    ends=ends[keep],
                    values=current_values[keep],
                )
                sessions.append(
                    _IndexedSession(
                        session_index=session_index,
                        connection_utc_s=connection,
                        disconnect_utc_s=disconnect,
                        current=base,
                    )
                )
                seen.add(session_index)
    except MechanismP1Error:
        raise
    except (OSError, UnicodeError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
        raise MechanismP1Error("CLEANED_SESSION_INVALID") from exc
    if len(sessions) != expected_count:
        raise MechanismP1Error("CLEANED_SESSION_COUNT_INVALID")
    return tuple(sorted(sessions, key=lambda item: item.session_index))


def _parse_optional_number(value: Any) -> float:
    if value is None:
        return float("nan")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MechanismP1Error("SESSION_FEATURE_INVALID")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise MechanismP1Error("SESSION_FEATURE_INVALID")
    return parsed


def _load_m3_session_features(
    path: Path,
    *,
    issue_times: np.ndarray,
    sessions: tuple[_IndexedSession, ...],
) -> _SessionFeatureTable:
    session_lookup = {item.session_index: item for item in sessions}
    issue_lookup = {int(value): index for index, value in enumerate(issue_times)}
    issue_indices: list[int] = []
    row_times: list[int] = []
    session_indices: list[int] = []
    raw_rows: list[list[float]] = []
    expected_keys = {
        "issue_index",
        "issue_time_utc_s",
        "anonymous_session_index",
        *M3_SESSION_FIELDS,
        "user_input_modified_utc_s",
    }
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for line in handle:
                if not line.strip():
                    raise MechanismP1Error("SESSION_FEATURE_INVALID")
                row = json.loads(line)
                if not isinstance(row, Mapping) or set(row) != expected_keys:
                    raise MechanismP1Error("SESSION_FEATURE_INVALID")
                issue = row["issue_time_utc_s"]
                session_index = row["anonymous_session_index"]
                if (
                    isinstance(issue, bool)
                    or not isinstance(issue, int)
                    or issue not in issue_lookup
                    or isinstance(session_index, bool)
                    or not isinstance(session_index, int)
                    or session_index not in session_lookup
                ):
                    raise MechanismP1Error("SESSION_FEATURE_INVALID")
                session = session_lookup[session_index]
                if not (
                    session.connection_utc_s <= issue < session.disconnect_utc_s
                ):
                    raise MechanismP1Error("SESSION_FEATURE_INVALID")
                local = datetime.fromtimestamp(issue, timezone.utc).astimezone(_ZONE)
                values = [_parse_optional_number(row[field]) for field in M3_SESSION_FIELDS]
                values.extend(
                    [
                        float(local.hour * 4 + local.minute // 15),
                        float(local.weekday()),
                        float(local.weekday() >= 5),
                    ]
                )
                if len(values) != _E_RAW_DIMENSION:
                    raise MechanismP1Error("SESSION_FEATURE_INVALID")
                issue_indices.append(issue_lookup[issue])
                row_times.append(issue)
                session_indices.append(session_index)
                raw_rows.append(values)
    except MechanismP1Error:
        raise
    except (OSError, UnicodeError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
        raise MechanismP1Error("SESSION_FEATURE_INVALID") from exc
    raw = np.asarray(raw_rows, dtype=np.float64)
    if raw.ndim != 2 or raw.shape[1] != _E_RAW_DIMENSION:
        raise MechanismP1Error("SESSION_FEATURE_INVALID")
    result = _SessionFeatureTable(
        issue_indices=np.asarray(issue_indices, dtype=np.int64),
        issue_times=np.asarray(row_times, dtype=np.int64),
        session_indices=np.asarray(session_indices, dtype=np.int64),
        raw_features=raw,
    )
    if len(result.issue_indices):
        pairs = np.column_stack([result.issue_indices, result.session_indices])
        if len(np.unique(pairs, axis=0)) != len(pairs):
            raise MechanismP1Error("SESSION_FEATURE_INVALID")
    return result


def _build_contribution_index(
    *,
    sessions: tuple[_IndexedSession, ...],
    issue_times: np.ndarray,
) -> Mapping[int, tuple[tuple[int, int, float], ...]]:
    target_starts = {
        int(issue) + horizon * 60 - 900
        for issue in issue_times
        for horizon in HORIZONS_MINUTES
    }
    contributions: dict[int, list[tuple[int, int, float]]] = {}
    if not target_starts:
        return MappingProxyType({})
    low = min(target_starts)
    high = max(target_starts)
    for session in sessions:
        base = session.current
        if base.starts.size == 0:
            continue
        first = max(
            low,
            int(math.floor(int(base.starts[0]) / 900.0) * 900),
        )
        last = min(
            high,
            int(math.floor((int(base.ends[-1]) - 1e-9) / 900.0) * 900),
        )
        if last < first:
            continue
        for start in range(first, last + 1, 900):
            if start not in target_starts:
                continue
            eligible_start = max(start, session.connection_utc_s)
            eligible_end = min(start + 900, session.disconnect_utc_s)
            if eligible_end <= eligible_start:
                continue
            contribution = (
                _session_integral(base, eligible_start, eligible_end) / 900.0
            )
            if contribution > 0:
                contributions.setdefault(start, []).append(
                    (
                        session.session_index,
                        session.connection_utc_s,
                        contribution,
                    )
                )
    return MappingProxyType(
        {
            start: tuple(sorted(rows, key=lambda item: (item[1], item[0])))
            for start, rows in contributions.items()
        }
    )


def _build_month_targets(
    *,
    data: MonthData,
    session_table: _SessionFeatureTable,
    contributions: Mapping[int, tuple[tuple[int, int, float], ...]],
) -> _MonthTargets:
    n = len(data.issue_times)
    existing = np.zeros((n, len(HORIZONS_MINUTES)), dtype=np.float64)
    arrival = np.zeros_like(existing)
    arrival_count = np.zeros_like(existing)
    arrival_mark = np.zeros_like(existing)
    session_contribution = np.zeros(
        (len(session_table.issue_indices), len(HORIZONS_MINUTES)),
        dtype=np.float64,
    )
    rows_by_issue: dict[int, list[int]] = {}
    for row_index, issue_index in enumerate(session_table.issue_indices):
        rows_by_issue.setdefault(int(issue_index), []).append(row_index)
    for issue_index, issue_raw in enumerate(data.issue_times):
        issue = int(issue_raw)
        session_rows = rows_by_issue.get(issue_index, ())
        row_index_by_session = {
            int(session_table.session_indices[row]): row for row in session_rows
        }
        for column, horizon in enumerate(HORIZONS_MINUTES):
            start = issue + horizon * 60 - 900
            target_rows = contributions.get(start, ())
            existing_rows = [
                item for item in target_rows if item[1] <= issue
            ]
            arrival_rows = [
                item for item in target_rows if item[1] > issue
            ]
            existing_value = math.fsum(item[2] for item in existing_rows)
            arrival_value = math.fsum(item[2] for item in arrival_rows)
            existing[issue_index, column] = existing_value
            arrival[issue_index, column] = arrival_value
            arrival_count[issue_index, column] = len(arrival_rows)
            if arrival_rows:
                arrival_mark[issue_index, column] = (
                    arrival_value / len(arrival_rows)
                )
            for session_index, _connection, contribution in existing_rows:
                destination = row_index_by_session.get(session_index)
                if destination is None:
                    raise MechanismP1Error("SESSION_TARGET_IDENTITY_INVALID")
                session_contribution[destination, column] = contribution
    reconstructed = existing + arrival
    if (
        not np.allclose(
            reconstructed,
            data.labels,
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
        or np.any(existing < 0)
        or np.any(arrival < 0)
        or np.any(session_contribution < 0)
        or np.any(arrival_count < 0)
        or np.any(arrival_mark < 0)
    ):
        raise MechanismP1Error("COMPONENT_RECONSTRUCTION_INVALID")
    for column in range(len(HORIZONS_MINUTES)):
        issue_sums = np.zeros(n, dtype=np.float64)
        np.add.at(
            issue_sums,
            session_table.issue_indices,
            session_contribution[:, column],
        )
        if not np.allclose(
            issue_sums,
            existing[:, column],
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        ):
            raise MechanismP1Error("SESSION_TARGET_IDENTITY_INVALID")
        rebuilt_arrival = arrival_count[:, column] * arrival_mark[:, column]
        if not np.allclose(
            rebuilt_arrival,
            arrival[:, column],
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        ):
            raise MechanismP1Error("ARRIVAL_TARGET_IDENTITY_INVALID")
    return _MonthTargets(
        existing_total=existing,
        arrival_total=arrival,
        session_contribution=session_contribution,
        arrival_count=arrival_count,
        arrival_mark=arrival_mark,
    )


def _local_midnight_epoch(epoch_seconds: int) -> int:
    local = datetime.fromtimestamp(epoch_seconds, timezone.utc).astimezone(_ZONE)
    return int(datetime.combine(local.date(), time.min, tzinfo=_ZONE).timestamp())


def _test_day_starts(
    issue_times: np.ndarray,
    test_start_local_day: int,
) -> tuple[np.ndarray, np.ndarray]:
    day_starts = np.asarray(
        [_local_midnight_epoch(int(value)) for value in issue_times],
        dtype=np.int64,
    )
    local_days = np.asarray(
        [
            datetime.fromtimestamp(int(value), timezone.utc).astimezone(_ZONE).day
            for value in issue_times
        ],
        dtype=np.int16,
    )
    test_rows = np.flatnonzero(local_days >= test_start_local_day).astype(np.int64)
    if not len(test_rows):
        raise MechanismP1Error("ROLLING_SPLIT_INVALID")
    return day_starts, np.unique(day_starts[test_rows])


class _FoldPreprocessor:
    def __init__(self, indicator_columns: np.ndarray) -> None:
        self._indicator_columns = np.asarray(indicator_columns, dtype=np.int64)
        self._imputer = SimpleImputer(
            strategy="median",
            keep_empty_features=True,
        )
        self._scaler = StandardScaler()

    def fit(self, raw: np.ndarray) -> _FoldPreprocessor:
        encoded = self._encode_fit(raw)
        self._scaler.fit(encoded)
        return self

    def _indicators(self, raw: np.ndarray) -> np.ndarray:
        if not len(self._indicator_columns):
            return np.empty((len(raw), 0), dtype=np.float64)
        return np.isnan(raw[:, self._indicator_columns]).astype(np.float64)

    def _encode_fit(self, raw: np.ndarray) -> np.ndarray:
        if raw.ndim != 2 or not len(raw):
            raise MechanismP1Error("PREPROCESSING_INVALID")
        indicators = self._indicators(raw)
        imputed = np.asarray(self._imputer.fit_transform(raw), dtype=np.float64)
        if imputed.shape != raw.shape or not np.isfinite(imputed).all():
            raise MechanismP1Error("PREPROCESSING_INVALID")
        return np.column_stack([imputed, indicators])

    def transform(self, raw: np.ndarray) -> np.ndarray:
        if raw.ndim != 2:
            raise MechanismP1Error("PREPROCESSING_INVALID")
        indicators = self._indicators(raw)
        try:
            imputed = np.asarray(self._imputer.transform(raw), dtype=np.float64)
        except (ValueError, TypeError) as exc:
            raise MechanismP1Error("PREPROCESSING_INVALID") from exc
        encoded = np.column_stack([imputed, indicators])
        try:
            scaled = np.asarray(self._scaler.transform(encoded), dtype=np.float64)
        except (ValueError, TypeError) as exc:
            raise MechanismP1Error("PREPROCESSING_INVALID") from exc
        if scaled.shape[0] != len(raw) or not np.isfinite(scaled).all():
            raise MechanismP1Error("PREPROCESSING_INVALID")
        return scaled

    def fit_transform(self, raw: np.ndarray) -> np.ndarray:
        encoded = self._encode_fit(raw)
        scaled = np.asarray(self._scaler.fit_transform(encoded), dtype=np.float64)
        if not np.isfinite(scaled).all():
            raise MechanismP1Error("PREPROCESSING_INVALID")
        return scaled


def _e_indicator_columns() -> np.ndarray:
    return np.arange(_E_MISSING_INDICATORS, dtype=np.int64)


def _a_indicator_columns(nullable_mask: np.ndarray) -> np.ndarray:
    columns = np.flatnonzero(nullable_mask).astype(np.int64)
    if len(columns) != _A_MISSING_INDICATORS:
        raise MechanismP1Error("PREPROCESSING_INVALID")
    return columns


def _fit_continuation(
    x_train_raw: np.ndarray,
    y_train: np.ndarray,
    x_test_raw: np.ndarray,
) -> tuple[np.ndarray, int]:
    classes = np.unique(y_train)
    if len(classes) == 1:
        return np.full(len(x_test_raw), float(classes[0]), dtype=np.float64), 0
    if not np.array_equal(classes, np.asarray([0.0, 1.0])):
        raise MechanismP1Error("MODEL_TARGET_INVALID")
    preprocessor = _FoldPreprocessor(_e_indicator_columns())
    x_train = preprocessor.fit_transform(x_train_raw)
    x_test = preprocessor.transform(x_test_raw)
    estimator = LogisticRegression(
        penalty="l2",
        C=1.0,
        solver="lbfgs",
        max_iter=1000,
        class_weight=None,
    )
    try:
        with threadpool_limits(limits=_NATIVE_THREAD_LIMIT):
            estimator.fit(x_train, y_train.astype(np.int8))
            prediction = np.asarray(
                estimator.predict_proba(x_test)[:, 1],
                dtype=np.float64,
            )
    except Exception as exc:  # noqa: BLE001
        raise MechanismP1Error("MODEL_FIT_FAILED") from exc
    if (
        prediction.shape != (len(x_test_raw),)
        or not np.isfinite(prediction).all()
        or np.any(prediction < 0)
        or np.any(prediction > 1)
    ):
        raise MechanismP1Error("MODEL_OUTPUT_INVALID")
    return prediction, 1


def _fit_gamma_mark(
    x_train_raw: np.ndarray,
    y_train: np.ndarray,
    x_test_raw: np.ndarray,
    *,
    indicator_columns: np.ndarray,
) -> tuple[np.ndarray, int]:
    positive = y_train > 0
    count = int(np.sum(positive))
    if count == 0:
        return np.zeros(len(x_test_raw), dtype=np.float64), 0
    if count == 1:
        value = float(y_train[positive][0])
        return np.full(len(x_test_raw), value, dtype=np.float64), 0
    preprocessor = _FoldPreprocessor(indicator_columns)
    x_train = preprocessor.fit_transform(x_train_raw[positive])
    x_test = preprocessor.transform(x_test_raw)
    estimator = GammaRegressor(alpha=1.0, max_iter=1000)
    try:
        with threadpool_limits(limits=_NATIVE_THREAD_LIMIT):
            estimator.fit(x_train, y_train[positive])
            prediction = np.asarray(estimator.predict(x_test), dtype=np.float64)
    except Exception as exc:  # noqa: BLE001
        raise MechanismP1Error("MODEL_FIT_FAILED") from exc
    if (
        prediction.shape != (len(x_test_raw),)
        or not np.isfinite(prediction).all()
        or np.any(prediction <= 0)
    ):
        raise MechanismP1Error("MODEL_OUTPUT_INVALID")
    return prediction, 1


def _fit_poisson_count(
    x_train_raw: np.ndarray,
    y_train: np.ndarray,
    x_test_raw: np.ndarray,
    *,
    indicator_columns: np.ndarray,
) -> tuple[np.ndarray, int]:
    if np.any(y_train < 0) or not np.allclose(y_train, np.rint(y_train)):
        raise MechanismP1Error("MODEL_TARGET_INVALID")
    if not np.any(y_train > 0):
        return np.zeros(len(x_test_raw), dtype=np.float64), 0
    preprocessor = _FoldPreprocessor(indicator_columns)
    x_train = preprocessor.fit_transform(x_train_raw)
    x_test = preprocessor.transform(x_test_raw)
    estimator = PoissonRegressor(alpha=1.0, max_iter=1000)
    try:
        with threadpool_limits(limits=_NATIVE_THREAD_LIMIT):
            estimator.fit(x_train, y_train)
            prediction = np.asarray(estimator.predict(x_test), dtype=np.float64)
    except Exception as exc:  # noqa: BLE001
        raise MechanismP1Error("MODEL_FIT_FAILED") from exc
    if (
        prediction.shape != (len(x_test_raw),)
        or not np.isfinite(prediction).all()
        or np.any(prediction < 0)
    ):
        raise MechanismP1Error("MODEL_OUTPUT_INVALID")
    return prediction, 1


def _predict_task(
    *,
    data: MonthData,
    session_table: _SessionFeatureTable,
    targets: _MonthTargets,
    horizon_minutes: int,
    source: Mapping[str, np.ndarray],
    test_start_local_day: int,
) -> _TaskResult:
    column = HORIZONS_MINUTES.index(horizon_minutes)
    issue_times = data.issue_times
    day_starts_all, test_days = _test_day_starts(
        issue_times,
        test_start_local_day,
    )
    m2 = data.blocks["M2"]
    if (
        m2.values.shape != (len(issue_times), _A_RAW_DIMENSION)
        or not np.array_equal(m2.issue_times, issue_times)
    ):
        raise MechanismP1Error("FEATURE_INVALID")
    a_indicator_columns = _a_indicator_columns(m2.nullable_mask)

    predicted_issue_times: list[np.ndarray] = []
    predicted_day_starts: list[np.ndarray] = []
    predicted_existing: list[np.ndarray] = []
    predicted_arrival: list[np.ndarray] = []
    continuation_truth_parts: list[np.ndarray] = []
    continuation_probability_parts: list[np.ndarray] = []
    e_mark_truth_parts: list[np.ndarray] = []
    e_mark_prediction_parts: list[np.ndarray] = []
    count_truth_parts: list[np.ndarray] = []
    count_prediction_parts: list[np.ndarray] = []
    a_mark_truth_parts: list[np.ndarray] = []
    a_mark_prediction_parts: list[np.ndarray] = []
    fit_counts = {
        "e_logistic": 0,
        "e_gamma": 0,
        "a_poisson": 0,
        "a_gamma": 0,
    }

    session_issue_indices = session_table.issue_indices
    session_y = targets.session_contribution[:, column]
    continuation_y = (session_y > 0).astype(np.float64)
    count_y = targets.arrival_count[:, column]
    arrival_mark_y = targets.arrival_mark[:, column]

    for day_start in test_days:
        fit_issue_rows = np.flatnonzero(
            (issue_times < day_start)
            & (issue_times + horizon_minutes * 60 <= day_start)
        ).astype(np.int64)
        test_issue_rows = np.flatnonzero(day_starts_all == day_start).astype(np.int64)
        if (
            not len(fit_issue_rows)
            or not len(test_issue_rows)
            or np.intersect1d(fit_issue_rows, test_issue_rows).size
        ):
            raise MechanismP1Error("ROLLING_SPLIT_INVALID")
        if int(np.max(issue_times[fit_issue_rows] + horizon_minutes * 60)) > int(
            day_start
        ):
            raise MechanismP1Error("TEMPORAL_LEAKAGE")

        fit_session_mask = np.isin(session_issue_indices, fit_issue_rows)
        test_session_mask = np.isin(session_issue_indices, test_issue_rows)
        fit_session_rows = np.flatnonzero(fit_session_mask).astype(np.int64)
        test_session_rows = np.flatnonzero(test_session_mask).astype(np.int64)
        if not len(fit_session_rows):
            raise MechanismP1Error("ROLLING_SPLIT_INVALID")

        if len(test_session_rows):
            continuation_probability, fits = _fit_continuation(
                session_table.raw_features[fit_session_rows],
                continuation_y[fit_session_rows],
                session_table.raw_features[test_session_rows],
            )
            fit_counts["e_logistic"] += fits
            e_mark_prediction, fits = _fit_gamma_mark(
                session_table.raw_features[fit_session_rows],
                session_y[fit_session_rows],
                session_table.raw_features[test_session_rows],
                indicator_columns=_e_indicator_columns(),
            )
            fit_counts["e_gamma"] += fits
            session_expected = continuation_probability * e_mark_prediction
            existing_prediction = np.zeros(
                len(test_issue_rows),
                dtype=np.float64,
            )
            position = {
                int(issue_index): index
                for index, issue_index in enumerate(test_issue_rows)
            }
            destinations = np.asarray(
                [
                    position[int(session_issue_indices[row])]
                    for row in test_session_rows
                ],
                dtype=np.int64,
            )
            np.add.at(existing_prediction, destinations, session_expected)
            continuation_truth_parts.append(
                continuation_y[test_session_rows]
            )
            continuation_probability_parts.append(continuation_probability)
            positive_test = session_y[test_session_rows] > 0
            e_mark_truth_parts.append(session_y[test_session_rows][positive_test])
            e_mark_prediction_parts.append(e_mark_prediction[positive_test])
        else:
            existing_prediction = np.zeros(
                len(test_issue_rows),
                dtype=np.float64,
            )

        count_prediction, fits = _fit_poisson_count(
            m2.values[fit_issue_rows],
            count_y[fit_issue_rows],
            m2.values[test_issue_rows],
            indicator_columns=a_indicator_columns,
        )
        fit_counts["a_poisson"] += fits
        a_mark_prediction, fits = _fit_gamma_mark(
            m2.values[fit_issue_rows],
            arrival_mark_y[fit_issue_rows],
            m2.values[test_issue_rows],
            indicator_columns=a_indicator_columns,
        )
        fit_counts["a_gamma"] += fits
        arrival_prediction = count_prediction * a_mark_prediction

        predicted_issue_times.append(issue_times[test_issue_rows])
        predicted_day_starts.append(day_starts_all[test_issue_rows])
        predicted_existing.append(existing_prediction)
        predicted_arrival.append(arrival_prediction)
        count_truth_parts.append(count_y[test_issue_rows])
        count_prediction_parts.append(count_prediction)
        positive_arrival_test = count_y[test_issue_rows] > 0
        a_mark_truth_parts.append(arrival_mark_y[test_issue_rows][positive_arrival_test])
        a_mark_prediction_parts.append(a_mark_prediction[positive_arrival_test])

    task_times = np.concatenate(predicted_issue_times).astype(np.int64, copy=False)
    task_days = np.concatenate(predicted_day_starts).astype(np.int64, copy=False)
    p1_existing = np.concatenate(predicted_existing).astype(np.float64, copy=False)
    p1_arrival = np.concatenate(predicted_arrival).astype(np.float64, copy=False)
    if (
        not np.array_equal(task_times, source["issue_times"])
        or not np.array_equal(task_days, source["day_start_utc_s"])
    ):
        raise MechanismP1Error("COMMON_ROW_IDENTITY_INVALID")
    row_lookup = {int(value): index for index, value in enumerate(issue_times)}
    source_rows = np.asarray([row_lookup[int(value)] for value in task_times], dtype=np.int64)
    existing_truth = targets.existing_total[source_rows, column]
    arrival_truth = targets.arrival_total[source_rows, column]
    y_true = data.labels[source_rows, column]
    if (
        not np.allclose(
            existing_truth,
            source["existing_truth"],
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
        or not np.allclose(
            arrival_truth,
            source["arrival_truth"],
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
        or not np.allclose(
            y_true,
            source["y_true"],
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
    ):
        raise MechanismP1Error("COMPONENT_RECONSTRUCTION_INVALID")

    p1_eonly = p1_existing + source["arrival_predictions"]
    p1_aonly = source["existing_predictions"] + p1_arrival
    p1_ea = p1_existing + p1_arrival
    for prediction in (p1_existing, p1_arrival, p1_eonly, p1_aonly, p1_ea):
        if not np.isfinite(prediction).all() or np.any(prediction < 0):
            raise MechanismP1Error("MODEL_OUTPUT_INVALID")

    def _cat(parts: list[np.ndarray]) -> np.ndarray:
        return (
            np.concatenate(parts).astype(np.float64, copy=False)
            if parts and any(len(part) for part in parts)
            else np.asarray([], dtype=np.float64)
        )

    return _TaskResult(
        month=data.month,
        horizon_minutes=horizon_minutes,
        issue_times=task_times,
        day_starts=task_days,
        y_true=y_true,
        existing_truth=existing_truth,
        arrival_truth=arrival_truth,
        p1_existing=p1_existing,
        p1_arrival=p1_arrival,
        p1_eonly=p1_eonly,
        p1_aonly=p1_aonly,
        p1_ea=p1_ea,
        continuation_truth=_cat(continuation_truth_parts),
        continuation_probability=_cat(continuation_probability_parts),
        existing_positive_mark_truth=_cat(e_mark_truth_parts),
        existing_positive_mark_prediction=_cat(e_mark_prediction_parts),
        arrival_count_truth=_cat(count_truth_parts),
        arrival_count_prediction=_cat(count_prediction_parts),
        arrival_positive_mark_truth=_cat(a_mark_truth_parts),
        arrival_positive_mark_prediction=_cat(a_mark_prediction_parts),
        e_logistic_fits=fit_counts["e_logistic"],
        e_gamma_fits=fit_counts["e_gamma"],
        a_poisson_fits=fit_counts["a_poisson"],
        a_gamma_fits=fit_counts["a_gamma"],
    )


def _metrics(truth: np.ndarray, prediction: np.ndarray) -> dict[str, Any]:
    if truth.shape != prediction.shape or truth.ndim != 1 or not len(truth):
        raise MechanismP1Error("METRIC_INVALID")
    if not np.isfinite(truth).all() or not np.isfinite(prediction).all():
        raise MechanismP1Error("METRIC_INVALID")
    error = prediction - truth
    absolute = np.abs(error)
    denominator = float(np.sum(np.abs(truth)))
    return {
        "n": int(len(truth)),
        "mae_a": float(np.mean(absolute)),
        "rmse_a": float(np.sqrt(np.mean(np.square(error)))),
        "wape_ratio": None
        if denominator == 0
        else float(np.sum(absolute) / denominator),
        "negative_prediction_count": int(np.sum(prediction < 0)),
    }


def _classification_metrics(
    truth: np.ndarray,
    probability: np.ndarray,
) -> dict[str, Any]:
    if truth.shape != probability.shape:
        raise MechanismP1Error("METRIC_INVALID")
    if not len(truth):
        return {
            "n": 0,
            "brier": None,
            "log_loss": None,
            "positive_rate": None,
            "calibration_deciles": [],
        }
    if (
        not np.isfinite(truth).all()
        or not np.isfinite(probability).all()
        or np.any((truth != 0) & (truth != 1))
        or np.any(probability < 0)
        or np.any(probability > 1)
    ):
        raise MechanismP1Error("METRIC_INVALID")
    brier = float(np.mean(np.square(probability - truth)))
    eps = np.finfo(np.float64).eps
    stable = np.minimum(np.maximum(probability, eps), 1.0 - eps)
    log_loss = float(
        -np.mean(truth * np.log(stable) + (1.0 - truth) * np.log(1.0 - stable))
    )
    order = np.argsort(probability, kind="stable")
    bins = np.array_split(order, min(10, len(order)))
    calibration = [
        {
            "n": int(len(indexes)),
            "mean_probability": float(np.mean(probability[indexes])),
            "observed_rate": float(np.mean(truth[indexes])),
        }
        for indexes in bins
        if len(indexes)
    ]
    return {
        "n": int(len(truth)),
        "brier": brier,
        "log_loss": log_loss,
        "positive_rate": float(np.mean(truth)),
        "calibration_deciles": calibration,
    }


def _arrival_diagnostics(task: _TaskResult) -> dict[str, Any]:
    count_truth = task.arrival_count_truth
    count_prediction = task.arrival_count_prediction
    if count_truth.shape != count_prediction.shape or not len(count_truth):
        raise MechanismP1Error("METRIC_INVALID")
    if (
        np.any(count_truth < 0)
        or np.any(count_prediction < 0)
        or not np.isfinite(count_truth).all()
        or not np.isfinite(count_prediction).all()
    ):
        raise MechanismP1Error("METRIC_INVALID")
    if np.all(count_truth == 0) and np.all(count_prediction == 0):
        deviance = 0.0
    else:
        safe_prediction = np.maximum(count_prediction, 1e-12)
        try:
            deviance = float(mean_poisson_deviance(count_truth, safe_prediction))
        except ValueError as exc:
            raise MechanismP1Error("METRIC_INVALID") from exc
    mark_mae = (
        None
        if not len(task.arrival_positive_mark_truth)
        else float(
            np.mean(
                np.abs(
                    task.arrival_positive_mark_prediction
                    - task.arrival_positive_mark_truth
                )
            )
        )
    )
    return {
        "count_n": int(len(count_truth)),
        "count_mae": float(np.mean(np.abs(count_prediction - count_truth))),
        "mean_poisson_deviance": deviance,
        "positive_mark_n": int(len(task.arrival_positive_mark_truth)),
        "positive_mark_mae_a": mark_mae,
    }


def _existing_diagnostics(task: _TaskResult) -> dict[str, Any]:
    mark_mae = (
        None
        if not len(task.existing_positive_mark_truth)
        else float(
            np.mean(
                np.abs(
                    task.existing_positive_mark_prediction
                    - task.existing_positive_mark_truth
                )
            )
        )
    )
    return {
        "continuation": _classification_metrics(
            task.continuation_truth,
            task.continuation_probability,
        ),
        "positive_mark_n": int(len(task.existing_positive_mark_truth)),
        "positive_mark_mae_a": mark_mae,
    }


def _source_metrics(
    source: Mapping[str, np.ndarray],
    task: _TaskResult,
) -> dict[str, dict[str, Any]]:
    return {
        "M3": _metrics(task.y_true, source["m3_predictions"]),
        "equal": _metrics(task.y_true, source["equal_predictions"]),
        "S1": _metrics(task.y_true, source["structured_predictions"]),
        "S1_existing": _metrics(
            task.existing_truth,
            source["existing_predictions"],
        ),
        "S1_arrival": _metrics(
            task.arrival_truth,
            source["arrival_predictions"],
        ),
        "P1_existing": _metrics(task.existing_truth, task.p1_existing),
        "P1_arrival": _metrics(task.arrival_truth, task.p1_arrival),
        "P1-Eonly": _metrics(task.y_true, task.p1_eonly),
        "P1-Aonly": _metrics(task.y_true, task.p1_aonly),
        "P1-EA": _metrics(task.y_true, task.p1_ea),
    }


def _concat_metrics(
    records: Sequence[tuple[np.ndarray, np.ndarray]],
) -> dict[str, Any]:
    truth = np.concatenate([item[0] for item in records])
    prediction = np.concatenate([item[1] for item in records])
    return _metrics(truth, prediction)


def _aggregate_metric_bundle(
    records: Sequence[tuple[_TaskResult, Mapping[str, np.ndarray]]],
) -> dict[str, dict[str, Any]]:
    definitions = {
        "M3": lambda task, source: (task.y_true, source["m3_predictions"]),
        "equal": lambda task, source: (task.y_true, source["equal_predictions"]),
        "S1": lambda task, source: (task.y_true, source["structured_predictions"]),
        "S1_existing": lambda task, source: (
            task.existing_truth,
            source["existing_predictions"],
        ),
        "S1_arrival": lambda task, source: (
            task.arrival_truth,
            source["arrival_predictions"],
        ),
        "P1_existing": lambda task, source: (
            task.existing_truth,
            task.p1_existing,
        ),
        "P1_arrival": lambda task, source: (
            task.arrival_truth,
            task.p1_arrival,
        ),
        "P1-Eonly": lambda task, source: (task.y_true, task.p1_eonly),
        "P1-Aonly": lambda task, source: (task.y_true, task.p1_aonly),
        "P1-EA": lambda task, source: (task.y_true, task.p1_ea),
    }
    return {
        name: _concat_metrics([builder(task, source) for task, source in records])
        for name, builder in definitions.items()
    }


def _branch_decision(
    *,
    pooled: Mapping[str, Mapping[str, Any]],
    by_horizon: Sequence[Mapping[str, Any]],
    by_month: Sequence[Mapping[str, Any]],
    new_key: str,
    old_key: str,
    min_horizon_wins: int,
    min_month_wins: int,
) -> tuple[str, Mapping[str, Any]]:
    pooled_win = pooled[new_key]["mae_a"] < pooled[old_key]["mae_a"]
    horizon_wins = sum(
        item["metrics"][new_key]["mae_a"] < item["metrics"][old_key]["mae_a"]
        for item in by_horizon
    )
    month_wins = sum(
        item["metrics"][new_key]["mae_a"] < item["metrics"][old_key]["mae_a"]
        for item in by_month
    )
    if pooled_win and horizon_wins >= min_horizon_wins and month_wins >= min_month_wins:
        decision = "STABLE_COMPONENT_SIGNAL"
    elif pooled_win:
        decision = "MIXED_COMPONENT_SIGNAL"
    else:
        decision = "NO_COMPONENT_SIGNAL"
    return decision, MappingProxyType(
        {
            "pooled_component_win": bool(pooled_win),
            "horizon_wins": int(horizon_wins),
            "month_wins": int(month_wins),
        }
    )


def _primary_decision(
    *,
    protocol: MechanismP1Protocol,
    pooled: Mapping[str, Mapping[str, Any]],
    by_horizon: Sequence[Mapping[str, Any]],
    by_month: Sequence[Mapping[str, Any]],
    existing_branch_decision: str,
    arrival_branch_decision: str,
) -> tuple[str, Mapping[str, Any]]:
    ea_mae = pooled["P1-EA"]["mae_a"]
    pooled_better_equal = ea_mae < pooled["equal"]["mae_a"]
    pooled_better_s1 = ea_mae < pooled["S1"]["mae_a"]
    horizon_wins = sum(
        item["metrics"]["P1-EA"]["mae_a"] < item["metrics"]["equal"]["mae_a"]
        for item in by_horizon
    )
    month_wins = sum(
        item["metrics"]["P1-EA"]["mae_a"] < item["metrics"]["equal"]["mae_a"]
        for item in by_month
    )
    degradations = []
    for item in by_horizon:
        parent = item["metrics"]["equal"]["mae_a"]
        child = item["metrics"]["P1-EA"]["mae_a"]
        degradation = 0.0 if child <= parent else (child - parent) / parent
        degradations.append(float(degradation))
    max_degradation = max(degradations)
    sixty = next(
        item for item in by_horizon if item["horizon_minutes"] == 60
    )
    sixty_win = (
        sixty["metrics"]["P1-EA"]["mae_a"]
        < sixty["metrics"]["equal"]["mae_a"]
    )
    pass_all = (
        pooled_better_equal
        and pooled_better_s1
        and horizon_wins >= protocol.pass_min_horizon_wins
        and month_wins >= protocol.pass_min_month_wins
        and max_degradation <= protocol.pass_max_horizon_degradation_fraction
        and sixty_win
    )
    stable_count = sum(
        decision == "STABLE_COMPONENT_SIGNAL"
        for decision in (existing_branch_decision, arrival_branch_decision)
    )
    no_component_pooled_improvement = (
        pooled["P1_existing"]["mae_a"] >= pooled["S1_existing"]["mae_a"]
        and pooled["P1_arrival"]["mae_a"] >= pooled["S1_arrival"]["mae_a"]
    )
    if pass_all:
        decision = "PASS_MECHANISM_PROBE"
    elif (
        pooled_better_equal
        or pooled_better_s1
        or stable_count == 1
        or not no_component_pooled_improvement
    ):
        decision = "MIXED_MECHANISM_PROBE"
    else:
        decision = "STOP_MECHANISM_ROUTE"
    return decision, MappingProxyType(
        {
            "pooled_better_than_equal": bool(pooled_better_equal),
            "pooled_better_than_s1": bool(pooled_better_s1),
            "horizon_wins_vs_equal": int(horizon_wins),
            "month_wins_vs_equal": int(month_wins),
            "max_horizon_degradation_vs_equal_fraction": float(max_degradation),
            "sixty_min_better_than_equal": bool(sixty_win),
            "stable_component_count": int(stable_count),
        }
    )


def _daily_summary(
    task: _TaskResult,
    source: Mapping[str, np.ndarray],
) -> list[dict[str, Any]]:
    rows = []
    for day in np.unique(task.day_starts):
        mask = task.day_starts == day
        date = (
            datetime.fromtimestamp(int(day), timezone.utc)
            .astimezone(_ZONE)
            .date()
            .isoformat()
        )
        rows.append(
            {
                "local_date": date,
                "n": int(np.sum(mask)),
                "equal_mae_a": _metrics(
                    task.y_true[mask],
                    source["equal_predictions"][mask],
                )["mae_a"],
                "S1_mae_a": _metrics(
                    task.y_true[mask],
                    source["structured_predictions"][mask],
                )["mae_a"],
                "P1-EA_mae_a": _metrics(
                    task.y_true[mask],
                    task.p1_ea[mask],
                )["mae_a"],
            }
        )
    return rows


def _write_private_cache(
    stage: Path,
    *,
    task: _TaskResult,
    source: Mapping[str, np.ndarray],
) -> tuple[str, str]:
    name = f"{task.month}_h{task.horizon_minutes:03d}.npz"
    path = stage / name
    np.savez_compressed(
        path,
        issue_times=task.issue_times,
        day_start_utc_s=task.day_starts,
        y_true=task.y_true,
        existing_truth=task.existing_truth,
        arrival_truth=task.arrival_truth,
        m3_predictions=source["m3_predictions"],
        equal_predictions=source["equal_predictions"],
        s1_existing_predictions=source["existing_predictions"],
        s1_arrival_predictions=source["arrival_predictions"],
        s1_predictions=source["structured_predictions"],
        p1_existing_predictions=task.p1_existing,
        p1_arrival_predictions=task.p1_arrival,
        p1_eonly_predictions=task.p1_eonly,
        p1_aonly_predictions=task.p1_aonly,
        p1_ea_predictions=task.p1_ea,
    )
    return name, _sha256_file(path)


def run_mechanism_p1(
    *,
    authorized: bool,
    interim_root: str | Path,
    processed_root: str | Path,
    baseline_private_root: str | Path,
    s1_private_root: str | Path,
    private_output_root: str | Path,
    code_commit: str,
    repo_root: str | Path = ".",
    protocol_path: str | Path = DEFAULT_PROTOCOL_PATH,
    source_expert_protocol_path: str | Path = SOURCE_EXPERT_PROTOCOL_PATH,
) -> MechanismP1RunResult:
    if authorized is not True:
        raise MechanismP1Error("MECHANISM_P1_NOT_AUTHORIZED")
    root = Path(repo_root).resolve(strict=True)
    interim = Path(interim_root).resolve(strict=True)
    processed = Path(processed_root).resolve(strict=True)
    baseline_private = Path(baseline_private_root).resolve(strict=True)
    s1_private = Path(s1_private_root).resolve(strict=True)
    output = Path(private_output_root).resolve(strict=False)
    if any(
        path.is_symlink()
        for path in (interim, processed, baseline_private, s1_private)
    ) or output.exists():
        raise MechanismP1Error("OUTPUT_TOPOLOGY_INVALID")
    if any(
        (interim / month).exists() or (processed / month).exists()
        for month in FINAL_HOLDOUT_MONTHS
    ):
        raise MechanismP1Error("HOLDOUT_PATH_PRESENT")

    verify_mechanism_p1_implementation_commit(code_commit, repo_root=root)
    protocol = load_mechanism_p1_protocol(protocol_path)
    source_protocol: DevelopmentExpertProtocol = load_development_expert_protocol(
        source_expert_protocol_path
    )
    if (
        source_protocol.protocol_sha256
        != protocol.source_expert_protocol_sha256
        or source_protocol.source_model_selection_sha256
        != protocol.source_model_selection_sha256
    ):
        raise MechanismP1Error("SOURCE_IDENTITY_INVALID")

    baseline_manifest = _verify_private_cache(
        baseline_private,
        expected_manifest_sha256=protocol.baseline_private_manifest_sha256,
        schema_version="evcf-jpl-development-expert-private-cache/v1",
        entries_key="files",
    )
    s1_manifest = _verify_private_cache(
        s1_private,
        expected_manifest_sha256=protocol.s1_private_manifest_sha256,
        schema_version="evcf-jpl-structured-s1-private-cache/v1",
        entries_key="entries",
    )
    if (
        baseline_manifest.get("protocol_sha256")
        != protocol.source_expert_protocol_sha256
        or s1_manifest.get("protocol_sha256") != protocol.s1_protocol_sha256
        or s1_manifest.get("source_private_manifest_sha256")
        != protocol.baseline_private_manifest_sha256
    ):
        raise MechanismP1Error("SOURCE_IDENTITY_INVALID")

    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".evcf-mechanism-p1-", dir=output.parent))
    private_entries: list[dict[str, str]] = []
    month_summaries: list[Mapping[str, Any]] = []
    records: list[tuple[_TaskResult, Mapping[str, np.ndarray]]] = []
    total_fits = {
        "e_logistic": 0,
        "e_gamma": 0,
        "a_poisson": 0,
        "a_gamma": 0,
    }

    source_contracts = {item.month: item for item in source_protocol.months}
    try:
        for contract in protocol.months:
            source_contract = source_contracts.get(contract.month)
            if (
                source_contract is None
                or source_contract.formal_issue_times
                != contract.formal_issue_times
                or source_contract.processed_snapshot_sha256
                != contract.processed_snapshot_sha256
            ):
                raise MechanismP1Error("SOURCE_IDENTITY_INVALID")
            data = load_month_data(
                contract=source_contract,
                interim_root=interim,
                processed_root=processed,
            )
            sessions = _load_indexed_sessions(
                interim / contract.month / "cleaned_sessions.jsonl.gz",
                expected_count=contract.cleaned_session_count,
            )
            session_table = _load_m3_session_features(
                processed / contract.month / "m3.jsonl.gz",
                issue_times=data.issue_times,
                sessions=sessions,
            )
            contributions = _build_contribution_index(
                sessions=sessions,
                issue_times=data.issue_times,
            )
            targets = _build_month_targets(
                data=data,
                session_table=session_table,
                contributions=contributions,
            )
            horizon_summaries: list[dict[str, Any]] = []
            for horizon in HORIZONS_MINUTES:
                source_cache = _load_source_caches(
                    baseline_root=baseline_private,
                    s1_root=s1_private,
                    month=contract.month,
                    horizon=horizon,
                )
                task = _predict_task(
                    data=data,
                    session_table=session_table,
                    targets=targets,
                    horizon_minutes=horizon,
                    source=source_cache,
                    test_start_local_day=protocol.test_start_local_day,
                )
                for key in total_fits:
                    total_fits[key] += getattr(task, f"{key}_fits")
                name, digest = _write_private_cache(
                    stage,
                    task=task,
                    source=source_cache,
                )
                private_entries.append({"name": name, "sha256": digest})
                metric_bundle = _source_metrics(source_cache, task)
                horizon_summaries.append(
                    {
                        "horizon_minutes": horizon,
                        "test_rows": int(len(task.issue_times)),
                        "metrics": metric_bundle,
                        "existing_diagnostics": _existing_diagnostics(task),
                        "arrival_diagnostics": _arrival_diagnostics(task),
                        "fit_counts": {
                            "e_logistic": task.e_logistic_fits,
                            "e_gamma": task.e_gamma_fits,
                            "a_poisson": task.a_poisson_fits,
                            "a_gamma": task.a_gamma_fits,
                        },
                        "daily": _daily_summary(task, source_cache),
                    }
                )
                records.append((task, source_cache))
            month_summaries.append(
                MappingProxyType(
                    {
                        "month": contract.month,
                        "processed_snapshot_sha256": contract.processed_snapshot_sha256,
                        "horizons": horizon_summaries,
                    }
                )
            )

        pooled_by_horizon: list[Mapping[str, Any]] = []
        for horizon in HORIZONS_MINUTES:
            selected = [
                record
                for record in records
                if record[0].horizon_minutes == horizon
            ]
            pooled_by_horizon.append(
                MappingProxyType(
                    {
                        "horizon_minutes": horizon,
                        "metrics": _aggregate_metric_bundle(selected),
                    }
                )
            )

        pooled_by_month: list[Mapping[str, Any]] = []
        for month in DEVELOPMENT_MONTHS:
            selected = [
                record for record in records if record[0].month == month
            ]
            pooled_by_month.append(
                MappingProxyType(
                    {
                        "month": month,
                        "metrics": _aggregate_metric_bundle(selected),
                    }
                )
            )

        pooled_overall_metrics = _aggregate_metric_bundle(records)
        existing_decision, existing_evidence = _branch_decision(
            pooled=pooled_overall_metrics,
            by_horizon=pooled_by_horizon,
            by_month=pooled_by_month,
            new_key="P1_existing",
            old_key="S1_existing",
            min_horizon_wins=protocol.branch_min_horizon_wins,
            min_month_wins=protocol.branch_min_month_wins,
        )
        arrival_decision, arrival_evidence = _branch_decision(
            pooled=pooled_overall_metrics,
            by_horizon=pooled_by_horizon,
            by_month=pooled_by_month,
            new_key="P1_arrival",
            old_key="S1_arrival",
            min_horizon_wins=protocol.branch_min_horizon_wins,
            min_month_wins=protocol.branch_min_month_wins,
        )
        decision, decision_evidence = _primary_decision(
            protocol=protocol,
            pooled=pooled_overall_metrics,
            by_horizon=pooled_by_horizon,
            by_month=pooled_by_month,
            existing_branch_decision=existing_decision,
            arrival_branch_decision=arrival_decision,
        )
        pooled_overall = MappingProxyType(
            {
                "metrics": pooled_overall_metrics,
                "existing_branch_evidence": dict(existing_evidence),
                "arrival_branch_evidence": dict(arrival_evidence),
                "decision_evidence": dict(decision_evidence),
            }
        )

        private_manifest = {
            "schema_version": "evcf-jpl-structured-mechanism-p1-private-cache/v1",
            "protocol_sha256": protocol.protocol_sha256,
            "code_commit": code_commit,
            "baseline_private_manifest_sha256": protocol.baseline_private_manifest_sha256,
            "s1_private_manifest_sha256": protocol.s1_private_manifest_sha256,
            "entries": sorted(private_entries, key=lambda item: item["name"]),
        }
        manifest_bytes = _canonical_json_bytes(private_manifest)
        manifest_path = stage / "private_manifest.json"
        manifest_path.write_bytes(manifest_bytes)
        private_manifest_sha = _sha256_bytes(manifest_bytes)
        if output.exists():
            raise MechanismP1Error("OUTPUT_TOPOLOGY_INVALID")
        shutil.move(str(stage), str(output))
        stage = output
        return MechanismP1RunResult(
            status="COMPLETE",
            protocol_sha256=protocol.protocol_sha256,
            code_commit=code_commit,
            source_expert_protocol_sha256=protocol.source_expert_protocol_sha256,
            baseline_private_manifest_sha256=protocol.baseline_private_manifest_sha256,
            s1_private_manifest_sha256=protocol.s1_private_manifest_sha256,
            decision=decision,
            existing_branch_decision=existing_decision,
            arrival_branch_decision=arrival_decision,
            fit_counts=MappingProxyType(total_fits),
            private_cache_file_count=len(private_entries),
            private_manifest_sha256=private_manifest_sha,
            month_summaries=tuple(month_summaries),
            pooled_by_horizon=tuple(pooled_by_horizon),
            pooled_by_month=tuple(pooled_by_month),
            pooled_overall=pooled_overall,
            holdout_accessed=False,
        )
    except BaseException:
        if stage.exists() and stage != output:
            shutil.rmtree(stage, ignore_errors=True)
        raise


__all__ = [
    "DEFAULT_PROTOCOL_PATH",
    "DEVELOPMENT_MONTHS",
    "FINAL_HOLDOUT_MONTHS",
    "HORIZONS_MINUTES",
    "MechanismP1Error",
    "MechanismP1Protocol",
    "MechanismP1RunResult",
    "load_mechanism_p1_protocol",
    "run_mechanism_p1",
    "verify_mechanism_p1_implementation_commit",
]
