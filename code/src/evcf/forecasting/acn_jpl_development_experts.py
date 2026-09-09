"""Fail-closed OOS HGB expert predictions for the four JPL development months.

This controller consumes the already prepared local snapshots for 2019-01/04/07/10.
It never downloads data, never touches the final holdout months, and never retunes
M2/M3 expert hyperparameters. Full row predictions are written only to a caller-
supplied private local directory; returned summaries are aggregate-only.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import numpy as np
import yaml
from threadpoolctl import threadpool_limits

from evcf.forecasting.acn_jpl_gate1_features import FeatureBlock, canonical_feature_schema
from evcf.forecasting.acn_jpl_gate1_models import HGBPreprocessor, make_frozen_estimator

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
TIERS = ("M2", "M3")
TIMEZONE_NAME = "America/Los_Angeles"
_ZONE = ZoneInfo(TIMEZONE_NAME)
DEFAULT_PROTOCOL_PATH = Path("code/configs/acn_jpl_development_experts_2019.yaml")
IMPLEMENTATION_PATHS = (
    "code/configs/acn_jpl_development_experts_2019.yaml",
    "code/src/evcf/forecasting/acn_jpl_development_experts.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_features.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_models.py",
    "scripts/run_jpl_development_experts.py",
)
_EXPECTED_RAW_DIMENSIONS = {"M2": 201, "M3": 311}
_EXPECTED_INPUT_DIMENSIONS = {"M2": 204, "M3": 391}


class DevelopmentExpertError(RuntimeError):
    """Static identifier-free failure safe for aggregate status output."""

    def __init__(self, reason_code: str) -> None:
        if not isinstance(reason_code, str) or not reason_code.replace("_", "").isalnum():
            reason_code = "UNEXPECTED_ERROR"
        self.reason_code = reason_code
        super().__init__(reason_code)


class _Estimator(Protocol):
    def fit(self, x: np.ndarray, y: np.ndarray) -> _Estimator: ...

    def predict(self, x: np.ndarray) -> np.ndarray: ...


EstimatorFactory = Callable[[Mapping[str, Any]], _Estimator]


@dataclass(frozen=True, slots=True)
class MonthContract:
    month: str
    formal_issue_times: int
    processed_snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class DevelopmentExpertProtocol:
    protocol_id: str
    protocol_sha256: str
    months: tuple[MonthContract, ...]
    source_model_selection_manifest: str
    source_model_selection_sha256: str
    selected_parameter_sha256: Mapping[str, Mapping[int, str]]
    test_start_local_day: int
    native_thread_limit: int


@dataclass(frozen=True, slots=True)
class MonthData:
    month: str
    issue_times: np.ndarray
    labels: np.ndarray
    blocks: Mapping[str, FeatureBlock]
    processed_snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class TaskPrediction:
    month: str
    tier: str
    horizon_minutes: int
    issue_times: np.ndarray
    day_starts: np.ndarray
    y_true: np.ndarray
    predictions: np.ndarray
    fit_count: int
    first_fit_rows: int
    last_fit_rows: int
    selected_parameter_sha256: str


@dataclass(frozen=True, slots=True)
class DevelopmentExpertRunResult:
    status: str
    protocol_sha256: str
    code_commit: str
    source_model_selection_sha256: str
    month_summaries: tuple[Mapping[str, Any], ...]
    fit_count: int
    private_cache_file_count: int
    private_manifest_sha256: str
    holdout_accessed: bool = False
    gate_trained: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "evcf-jpl-development-expert-oos-summary/v1",
            "status": self.status,
            "protocol_sha256": self.protocol_sha256,
            "code_commit": self.code_commit,
            "source_model_selection_sha256": self.source_model_selection_sha256,
            "months": [dict(item) for item in self.month_summaries],
            "fit_count": self.fit_count,
            "private_cache_file_count": self.private_cache_file_count,
            "private_manifest_sha256": self.private_manifest_sha256,
            "holdout_accessed": self.holdout_accessed,
            "gate_trained": self.gate_trained,
            "expert_retuning": False,
            "prediction_clipping": False,
            "prediction_calibration": False,
        }


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def _validate_sha256(value: object, context: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise DevelopmentExpertError("PROTOCOL_INVALID")
    return value


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise DevelopmentExpertError("MODEL_SELECTION_INVALID") from exc


def _exact_mapping(value: object, keys: Sequence[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or tuple(value) != tuple(keys):
        raise DevelopmentExpertError("PROTOCOL_INVALID")
    return value


def load_development_expert_protocol(
    path: str | Path = DEFAULT_PROTOCOL_PATH,
) -> DevelopmentExpertProtocol:
    source = Path(path)
    try:
        raw = source.read_bytes()
        document = yaml.safe_load(raw.decode("utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise DevelopmentExpertError("PROTOCOL_INVALID") from exc
    root = _exact_mapping(
        document,
        (
            "schema_version",
            "protocol_id",
            "target",
            "development_months",
            "final_holdout",
            "experts",
            "rolling_origin",
            "preprocessing",
            "prediction",
            "baselines",
            "evaluation",
            "publication",
        ),
    )
    if root["schema_version"] != "acn-jpl-development-expert-protocol/v1":
        raise DevelopmentExpertError("PROTOCOL_INVALID")
    target = _exact_mapping(root["target"], ("name", "unit"))
    if target != {"name": "station_current_mean_a", "unit": "A"}:
        raise DevelopmentExpertError("PROTOCOL_INVALID")
    month_mapping = root["development_months"]
    if not isinstance(month_mapping, Mapping) or tuple(month_mapping) != DEVELOPMENT_MONTHS:
        raise DevelopmentExpertError("PROTOCOL_INVALID")
    months: list[MonthContract] = []
    for month in DEVELOPMENT_MONTHS:
        item = _exact_mapping(month_mapping[month], ("formal_issue_times", "processed_snapshot_sha256"))
        count = item["formal_issue_times"]
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise DevelopmentExpertError("PROTOCOL_INVALID")
        months.append(
            MonthContract(
                month=month,
                formal_issue_times=count,
                processed_snapshot_sha256=_validate_sha256(
                    item["processed_snapshot_sha256"], "processed snapshot"
                ),
            )
        )
    holdout = _exact_mapping(root["final_holdout"], ("months", "access_allowed"))
    if holdout != {"months": list(FINAL_HOLDOUT_MONTHS), "access_allowed": False}:
        raise DevelopmentExpertError("PROTOCOL_INVALID")
    experts = _exact_mapping(
        root["experts"],
        (
            "learner",
            "tiers",
            "horizons_minutes",
            "source_model_selection_manifest",
            "source_model_selection_sha256",
            "selected_parameter_sha256",
        ),
    )
    if (
        experts["learner"] != "hgb"
        or experts["tiers"] != list(TIERS)
        or experts["horizons_minutes"] != list(HORIZONS_MINUTES)
    ):
        raise DevelopmentExpertError("PROTOCOL_INVALID")
    hashes = experts["selected_parameter_sha256"]
    if not isinstance(hashes, Mapping) or tuple(hashes) != TIERS:
        raise DevelopmentExpertError("PROTOCOL_INVALID")
    selected: dict[str, Mapping[int, str]] = {}
    for tier in TIERS:
        tier_hashes = hashes[tier]
        expected_keys = tuple(str(value) for value in HORIZONS_MINUTES)
        if not isinstance(tier_hashes, Mapping) or tuple(tier_hashes) != expected_keys:
            raise DevelopmentExpertError("PROTOCOL_INVALID")
        selected[tier] = MappingProxyType(
            {
                horizon: _validate_sha256(tier_hashes[str(horizon)], "selected parameter")
                for horizon in HORIZONS_MINUTES
            }
        )
    rolling = _exact_mapping(
        root["rolling_origin"],
        (
            "timezone",
            "test_start_local_day",
            "refit_frequency",
            "use_same_month_history_only",
            "fit_issue_rule",
            "fit_label_rule",
            "test_rule",
        ),
    )
    if rolling != {
        "timezone": TIMEZONE_NAME,
        "test_start_local_day": 18,
        "refit_frequency": "local_midnight_daily",
        "use_same_month_history_only": True,
        "fit_issue_rule": "issue_time_utc_s < refit_cutoff_utc_s",
        "fit_label_rule": "issue_time_utc_s + horizon_minutes * 60 <= refit_cutoff_utc_s",
        "test_rule": "all_formal_rows_on_local_test_day",
    }:
        raise DevelopmentExpertError("PROTOCOL_INVALID")
    preprocessing = _exact_mapping(
        root["preprocessing"],
        ("raw_nan_preserved", "append_nullable_missing_indicators", "imputation", "scaling"),
    )
    if preprocessing != {
        "raw_nan_preserved": True,
        "append_nullable_missing_indicators": True,
        "imputation": False,
        "scaling": False,
    }:
        raise DevelopmentExpertError("PROTOCOL_INVALID")
    prediction = _exact_mapping(
        root["prediction"],
        (
            "clipping",
            "calibration",
            "retuning",
            "nonnegative_projection_primary",
            "native_thread_limit",
        ),
    )
    if prediction != {
        "clipping": False,
        "calibration": False,
        "retuning": False,
        "nonnegative_projection_primary": False,
        "native_thread_limit": 1,
    }:
        raise DevelopmentExpertError("PROTOCOL_INVALID")
    baselines = _exact_mapping(root["baselines"], ("equal_weight_m2_m3",))
    if baselines != {"equal_weight_m2_m3": 0.5}:
        raise DevelopmentExpertError("PROTOCOL_INVALID")
    evaluation = _exact_mapping(
        root["evaluation"],
        (
            "primary_metric",
            "secondary_metrics",
            "common_rows_required",
            "local_day_aggregates",
            "development_only",
        ),
    )
    if evaluation != {
        "primary_metric": "MAE",
        "secondary_metrics": ["RMSE", "WAPE"],
        "common_rows_required": True,
        "local_day_aggregates": True,
        "development_only": True,
    }:
        raise DevelopmentExpertError("PROTOCOL_INVALID")
    publication = _exact_mapping(
        root["publication"],
        (
            "public_aggregate_only",
            "private_row_predictions_local_only",
            "model_objects_public",
            "absolute_paths_public",
        ),
    )
    if publication != {
        "public_aggregate_only": True,
        "private_row_predictions_local_only": True,
        "model_objects_public": False,
        "absolute_paths_public": False,
    }:
        raise DevelopmentExpertError("PROTOCOL_INVALID")
    protocol_id = root["protocol_id"]
    source_manifest = experts["source_model_selection_manifest"]
    if not isinstance(protocol_id, str) or not protocol_id or not isinstance(source_manifest, str):
        raise DevelopmentExpertError("PROTOCOL_INVALID")
    return DevelopmentExpertProtocol(
        protocol_id=protocol_id,
        protocol_sha256=_sha256_bytes(raw),
        months=tuple(months),
        source_model_selection_manifest=source_manifest,
        source_model_selection_sha256=_validate_sha256(
            experts["source_model_selection_sha256"], "source model selection"
        ),
        selected_parameter_sha256=MappingProxyType(selected),
        test_start_local_day=18,
        native_thread_limit=1,
    )


def _verify_file_at_commit(root: Path, commit: str, relative: str) -> None:
    current = root / PurePosixPath(relative)
    if not current.is_file() or current.is_symlink():
        raise DevelopmentExpertError("IMPLEMENTATION_DRIFT")
    completed = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0 or completed.stdout != current.read_bytes():
        raise DevelopmentExpertError("IMPLEMENTATION_DRIFT")


def verify_development_expert_implementation_commit(
    code_commit: str,
    *,
    repo_root: str | Path,
) -> None:
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise DevelopmentExpertError("IMPLEMENTATION_DRIFT")
    root = Path(repo_root).resolve(strict=True)
    for relative in IMPLEMENTATION_PATHS:
        _verify_file_at_commit(root, code_commit, relative)


def _safe_relative(name: object) -> PurePosixPath:
    if not isinstance(name, str):
        raise DevelopmentExpertError("PROCESSED_SNAPSHOT_INVALID")
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 2:
        raise DevelopmentExpertError("PROCESSED_SNAPSHOT_INVALID")
    if relative.parts[0] not in ("interim", "processed"):
        raise DevelopmentExpertError("PROCESSED_SNAPSHOT_INVALID")
    return relative


def _verify_month_artifacts(
    *,
    month: MonthContract,
    interim_root: Path,
    processed_root: Path,
) -> tuple[Path, Path]:
    interim = interim_root / month.month
    processed = processed_root / month.month
    if any(not path.is_dir() or path.is_symlink() for path in (interim, processed)):
        raise DevelopmentExpertError("PROCESSED_SNAPSHOT_INVALID")
    manifest_path = processed / "data_snapshot_manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise DevelopmentExpertError("PROCESSED_SNAPSHOT_INVALID")
    raw = manifest_path.read_bytes()
    if _sha256_bytes(raw) != month.processed_snapshot_sha256:
        raise DevelopmentExpertError("PROCESSED_SNAPSHOT_INVALID")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DevelopmentExpertError("PROCESSED_SNAPSHOT_INVALID") from exc
    if (
        not isinstance(document, dict)
        or set(document) != {"schema_version", "month", "source_inventory_sha256", "data_snapshot_sha256", "artifacts", "tiers"}
        or document["schema_version"] != "acn-jpl-seasonal-local-snapshot/v1"
        or document["month"] != month.month
        or document["tiers"] != ["M1", "M2", "M3"]
    ):
        raise DevelopmentExpertError("PROCESSED_SNAPSHOT_INVALID")
    _validate_sha256(document["source_inventory_sha256"], "source inventory")
    _validate_sha256(document["data_snapshot_sha256"], "data snapshot")
    artifacts = document["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise DevelopmentExpertError("PROCESSED_SNAPSHOT_INVALID")
    seen: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != {"name", "sha256", "size"}:
            raise DevelopmentExpertError("PROCESSED_SNAPSHOT_INVALID")
        relative = _safe_relative(item["name"])
        name = relative.as_posix()
        if name in seen:
            raise DevelopmentExpertError("PROCESSED_SNAPSHOT_INVALID")
        seen.add(name)
        digest = _validate_sha256(item["sha256"], "artifact")
        size = item["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise DevelopmentExpertError("PROCESSED_SNAPSHOT_INVALID")
        base = interim if relative.parts[0] == "interim" else processed
        path = base / relative.parts[1]
        if (
            not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != size
            or _sha256_file(path) != digest
        ):
            raise DevelopmentExpertError("PROCESSED_SNAPSHOT_INVALID")
    required = {
        "processed/labels.jsonl.gz",
        "processed/M2.values.npy",
        "processed/M2.issue_times.npy",
        "processed/M2.nullable_mask.npy",
        "processed/M3.values.npy",
        "processed/M3.issue_times.npy",
        "processed/M3.nullable_mask.npy",
    }
    if not required.issubset(seen):
        raise DevelopmentExpertError("PROCESSED_SNAPSHOT_INVALID")
    return interim, processed


def _load_array(path: Path) -> np.ndarray:
    try:
        value = np.load(path, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise DevelopmentExpertError("FEATURE_INVALID") from exc
    if not isinstance(value, np.ndarray):
        raise DevelopmentExpertError("FEATURE_INVALID")
    return value


def _load_feature_block(processed: Path, tier: str, row_count: int) -> FeatureBlock:
    names, canonical_nullable = canonical_feature_schema(tier)
    values = _load_array(processed / f"{tier}.values.npy")
    issue_times = _load_array(processed / f"{tier}.issue_times.npy")
    nullable = _load_array(processed / f"{tier}.nullable_mask.npy")
    if (
        values.dtype != np.dtype(np.float64)
        or values.shape != (row_count, _EXPECTED_RAW_DIMENSIONS[tier])
        or issue_times.dtype != np.dtype(np.int64)
        or issue_times.shape != (row_count,)
        or nullable.dtype != np.dtype(np.bool_)
        or nullable.shape != (_EXPECTED_RAW_DIMENSIONS[tier],)
        or not np.array_equal(nullable, canonical_nullable)
    ):
        raise DevelopmentExpertError("FEATURE_INVALID")
    try:
        return FeatureBlock(issue_times, values, names, nullable)
    except (TypeError, ValueError) as exc:
        raise DevelopmentExpertError("FEATURE_INVALID") from exc


def _load_labels(processed: Path, row_count: int) -> tuple[np.ndarray, np.ndarray]:
    issue_times: list[int] = []
    rows: list[list[float]] = []
    path = processed / "labels.jsonl.gz"
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for ordinal, line in enumerate(handle):
                if not line.strip():
                    raise DevelopmentExpertError("LABEL_INVALID")
                item = json.loads(line)
                if not isinstance(item, dict) or set(item) != {"issue_index", "issue_time_utc_s", "labels"}:
                    raise DevelopmentExpertError("LABEL_INVALID")
                issue_index = item["issue_index"]
                issue = item["issue_time_utc_s"]
                labels = item["labels"]
                if (
                    isinstance(issue_index, bool)
                    or not isinstance(issue_index, int)
                    or issue_index < 0
                    or isinstance(issue, bool)
                    or not isinstance(issue, int)
                    or not isinstance(labels, dict)
                    or tuple(labels) != tuple(str(value) for value in HORIZONS_MINUTES)
                ):
                    raise DevelopmentExpertError("LABEL_INVALID")
                values: list[float] = []
                for horizon in HORIZONS_MINUTES:
                    value = labels[str(horizon)]
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        raise DevelopmentExpertError("LABEL_INVALID")
                    parsed = float(value)
                    if not math.isfinite(parsed) or parsed < 0:
                        raise DevelopmentExpertError("LABEL_INVALID")
                    values.append(parsed)
                if ordinal and issue <= issue_times[-1]:
                    raise DevelopmentExpertError("LABEL_INVALID")
                issue_times.append(issue)
                rows.append(values)
    except DevelopmentExpertError:
        raise
    except (OSError, UnicodeError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
        raise DevelopmentExpertError("LABEL_INVALID") from exc
    times = np.asarray(issue_times, dtype=np.int64)
    labels_array = np.asarray(rows, dtype=np.float64)
    if times.shape != (row_count,) or labels_array.shape != (row_count, len(HORIZONS_MINUTES)):
        raise DevelopmentExpertError("LABEL_INVALID")
    return times, labels_array


def load_month_data(
    *,
    contract: MonthContract,
    interim_root: Path,
    processed_root: Path,
) -> MonthData:
    _, processed = _verify_month_artifacts(
        month=contract,
        interim_root=interim_root,
        processed_root=processed_root,
    )
    labels_times, labels = _load_labels(processed, contract.formal_issue_times)
    blocks = {
        tier: _load_feature_block(processed, tier, contract.formal_issue_times) for tier in TIERS
    }
    if any(not np.array_equal(block.issue_times, labels_times) for block in blocks.values()):
        raise DevelopmentExpertError("FEATURE_LABEL_ALIGNMENT_INVALID")
    local_months = {
        datetime.fromtimestamp(int(value), timezone.utc).astimezone(_ZONE).strftime("%Y-%m")
        for value in labels_times
    }
    if local_months != {contract.month}:
        raise DevelopmentExpertError("FEATURE_LABEL_ALIGNMENT_INVALID")
    return MonthData(
        month=contract.month,
        issue_times=labels_times,
        labels=labels,
        blocks=MappingProxyType(blocks),
        processed_snapshot_sha256=contract.processed_snapshot_sha256,
    )


def _hgb_candidates() -> tuple[Mapping[str, Any], ...]:
    candidates: list[Mapping[str, Any]] = []
    for learning_rate in (0.03, 0.08):
        for max_leaf_nodes in (15, 31):
            for min_samples_leaf in (20, 50):
                for l2_regularization in (0, 1):
                    candidate = {
                        "categorical_features": None,
                        "early_stopping": False,
                        "interaction_cst": None,
                        "l2_regularization": l2_regularization,
                        "learning_rate": learning_rate,
                        "loss": "squared_error",
                        "max_bins": 255,
                        "max_depth": None,
                        "max_features": 1.0,
                        "max_iter": 300,
                        "max_leaf_nodes": max_leaf_nodes,
                        "min_samples_leaf": min_samples_leaf,
                        "monotonic_cst": None,
                        "n_iter_no_change": 10,
                        "quantile": None,
                        "random_state": 20260901,
                        "scoring": "loss",
                        "tol": 1e-7,
                        "validation_fraction": 0.1,
                        "verbose": 0,
                        "warm_start": False,
                    }
                    candidates.append(MappingProxyType(candidate))
    return tuple(candidates)


def _walk(value: object) -> Sequence[Mapping[str, Any]]:
    found: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        if {"learner", "tier", "horizon_minutes", "selected_candidate_index", "selected_parameter_sha256", "selected_parameters"}.issubset(value):
            found.append(value)
        for nested in value.values():
            found.extend(_walk(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_walk(nested))
    return found


def load_selected_hgb_parameters(
    *,
    protocol: DevelopmentExpertProtocol,
    repo_root: Path,
) -> Mapping[tuple[str, int], Mapping[str, Any]]:
    path = repo_root / PurePosixPath(protocol.source_model_selection_manifest)
    if not path.is_file() or path.is_symlink() or _sha256_file(path) != protocol.source_model_selection_sha256:
        raise DevelopmentExpertError("MODEL_SELECTION_INVALID")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DevelopmentExpertError("MODEL_SELECTION_INVALID") from exc
    candidates = _hgb_candidates()
    selections = _walk(document)
    output: dict[tuple[str, int], Mapping[str, Any]] = {}
    for tier in TIERS:
        for horizon in HORIZONS_MINUTES:
            matches = [
                item
                for item in selections
                if item.get("learner") == "hgb"
                and item.get("tier") == tier
                and item.get("horizon_minutes") == horizon
            ]
            if len(matches) != 1:
                raise DevelopmentExpertError("MODEL_SELECTION_INVALID")
            item = matches[0]
            index = item["selected_candidate_index"]
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(candidates):
                raise DevelopmentExpertError("MODEL_SELECTION_INVALID")
            params = candidates[index]
            parameter_sha = _sha256_bytes(_canonical_json_bytes(dict(params)))
            expected_sha = protocol.selected_parameter_sha256[tier][horizon]
            if (
                parameter_sha != expected_sha
                or item.get("selected_parameter_sha256") != expected_sha
                or item.get("selected_parameters") != dict(params)
            ):
                raise DevelopmentExpertError("MODEL_SELECTION_INVALID")
            try:
                make_frozen_estimator("hgb", params)
            except (TypeError, ValueError) as exc:
                raise DevelopmentExpertError("MODEL_SELECTION_INVALID") from exc
            output[(tier, horizon)] = params
    return MappingProxyType(output)


def _local_midnight_epoch(epoch_seconds: int) -> int:
    local = datetime.fromtimestamp(epoch_seconds, timezone.utc).astimezone(_ZONE)
    return int(datetime.combine(local.date(), time.min, tzinfo=_ZONE).timestamp())


def _test_day_starts(issue_times: np.ndarray, test_start_day: int) -> tuple[np.ndarray, np.ndarray]:
    day_starts = np.asarray([_local_midnight_epoch(int(value)) for value in issue_times], dtype=np.int64)
    local_days = np.asarray(
        [datetime.fromtimestamp(int(value), timezone.utc).astimezone(_ZONE).day for value in issue_times],
        dtype=np.int16,
    )
    test_rows = np.flatnonzero(local_days >= test_start_day).astype(np.int64)
    if not len(test_rows):
        raise DevelopmentExpertError("ROLLING_SPLIT_INVALID")
    test_days = np.unique(day_starts[test_rows])
    return day_starts, test_days


def _default_estimator_factory(params: Mapping[str, Any]) -> _Estimator:
    return make_frozen_estimator("hgb", params)


def predict_task(
    *,
    data: MonthData,
    tier: str,
    horizon_minutes: int,
    params: Mapping[str, Any],
    selected_parameter_sha256: str,
    test_start_local_day: int,
    native_thread_limit: int,
    estimator_factory: EstimatorFactory = _default_estimator_factory,
) -> TaskPrediction:
    if tier not in TIERS or horizon_minutes not in HORIZONS_MINUTES:
        raise DevelopmentExpertError("ROLLING_SPLIT_INVALID")
    block = data.blocks[tier]
    horizon_position = HORIZONS_MINUTES.index(horizon_minutes)
    labels = data.labels[:, horizon_position]
    issue_times = data.issue_times
    all_day_starts, test_days = _test_day_starts(issue_times, test_start_local_day)
    predicted_times: list[np.ndarray] = []
    predicted_days: list[np.ndarray] = []
    predicted_truth: list[np.ndarray] = []
    predicted_values: list[np.ndarray] = []
    fit_counts: list[int] = []
    for day_start in test_days:
        fit_rows = np.flatnonzero(
            (issue_times < day_start) & (issue_times + horizon_minutes * 60 <= day_start)
        ).astype(np.int64)
        test_rows = np.flatnonzero(all_day_starts == day_start).astype(np.int64)
        if not len(fit_rows) or not len(test_rows) or np.intersect1d(fit_rows, test_rows).size:
            raise DevelopmentExpertError("ROLLING_SPLIT_INVALID")
        if int(np.max(issue_times[fit_rows] + horizon_minutes * 60)) > int(day_start):
            raise DevelopmentExpertError("TEMPORAL_LEAKAGE")
        preprocessor = HGBPreprocessor().fit(block, fit_rows)
        x_train = preprocessor.transform(block, fit_rows)
        x_test = preprocessor.transform(block, test_rows)
        if x_train.shape[1] != _EXPECTED_INPUT_DIMENSIONS[tier] or x_test.shape[1] != _EXPECTED_INPUT_DIMENSIONS[tier]:
            raise DevelopmentExpertError("FEATURE_INVALID")
        try:
            estimator = estimator_factory(params)
            with threadpool_limits(limits=native_thread_limit):
                estimator.fit(x_train, labels[fit_rows])
                predictions = np.asarray(estimator.predict(x_test), dtype=np.float64)
        except DevelopmentExpertError:
            raise
        except Exception as exc:  # noqa: BLE001 - private exception text is never published
            raise DevelopmentExpertError("MODEL_FIT_FAILED") from exc
        if predictions.shape != (len(test_rows),) or not np.isfinite(predictions).all():
            raise DevelopmentExpertError("MODEL_OUTPUT_INVALID")
        predicted_times.append(issue_times[test_rows])
        predicted_days.append(all_day_starts[test_rows])
        predicted_truth.append(labels[test_rows])
        predicted_values.append(predictions)
        fit_counts.append(len(fit_rows))
    times = np.concatenate(predicted_times).astype(np.int64, copy=False)
    days = np.concatenate(predicted_days).astype(np.int64, copy=False)
    truth = np.concatenate(predicted_truth).astype(np.float64, copy=False)
    predictions = np.concatenate(predicted_values).astype(np.float64, copy=False)
    if np.any(np.diff(times) <= 0) or not np.array_equal(days, np.asarray([_local_midnight_epoch(int(value)) for value in times], dtype=np.int64)):
        raise DevelopmentExpertError("ROLLING_SPLIT_INVALID")
    return TaskPrediction(
        month=data.month,
        tier=tier,
        horizon_minutes=horizon_minutes,
        issue_times=times,
        day_starts=days,
        y_true=truth,
        predictions=predictions,
        fit_count=len(test_days),
        first_fit_rows=fit_counts[0],
        last_fit_rows=fit_counts[-1],
        selected_parameter_sha256=selected_parameter_sha256,
    )


def _metrics(y_true: np.ndarray, predictions: np.ndarray) -> dict[str, Any]:
    if y_true.shape != predictions.shape or y_true.ndim != 1 or not len(y_true):
        raise DevelopmentExpertError("METRIC_INVALID")
    if not np.isfinite(y_true).all() or not np.isfinite(predictions).all():
        raise DevelopmentExpertError("METRIC_INVALID")
    error = predictions - y_true
    absolute = np.abs(error)
    denominator = float(np.sum(np.abs(y_true)))
    return {
        "n": len(y_true),
        "mae_a": float(np.mean(absolute)),
        "rmse_a": float(np.sqrt(np.mean(np.square(error)))),
        "wape_ratio": None if denominator == 0 else float(np.sum(absolute) / denominator),
        "negative_prediction_count": int(np.sum(predictions < 0)),
    }


def _improvement(parent_mae: float, child_mae: float) -> float | None:
    return None if parent_mae == 0 else float((parent_mae - child_mae) / parent_mae * 100.0)


def _daily_summary(
    *,
    issue_times: np.ndarray,
    day_starts: np.ndarray,
    truth: np.ndarray,
    m2: np.ndarray,
    m3: np.ndarray,
    equal: np.ndarray,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for day in np.unique(day_starts):
        mask = day_starts == day
        date = datetime.fromtimestamp(int(day), timezone.utc).astimezone(_ZONE).date().isoformat()
        rows.append(
            {
                "local_date": date,
                "n": int(np.sum(mask)),
                "M2_mae_a": _metrics(truth[mask], m2[mask])["mae_a"],
                "M3_mae_a": _metrics(truth[mask], m3[mask])["mae_a"],
                "equal_mae_a": _metrics(truth[mask], equal[mask])["mae_a"],
            }
        )
    if sum(item["n"] for item in rows) != len(issue_times):
        raise DevelopmentExpertError("METRIC_INVALID")
    return rows


def _write_private_cache(
    *,
    stage: Path,
    month: str,
    horizon: int,
    m2: TaskPrediction,
    m3: TaskPrediction,
) -> tuple[str, str]:
    if not (
        np.array_equal(m2.issue_times, m3.issue_times)
        and np.array_equal(m2.day_starts, m3.day_starts)
        and np.array_equal(m2.y_true, m3.y_true)
    ):
        raise DevelopmentExpertError("COMMON_ROW_IDENTITY_INVALID")
    equal = (m2.predictions + m3.predictions) / 2.0
    name = f"{month}_h{horizon:03d}.npz"
    path = stage / name
    np.savez_compressed(
        path,
        issue_times=m2.issue_times,
        day_start_utc_s=m2.day_starts,
        y_true=m2.y_true,
        m2_predictions=m2.predictions,
        m3_predictions=m3.predictions,
        equal_predictions=equal,
    )
    return name, _sha256_file(path)


def run_development_experts(
    *,
    authorized: bool,
    interim_root: str | Path,
    processed_root: str | Path,
    private_output_root: str | Path,
    code_commit: str,
    repo_root: str | Path = ".",
    protocol_path: str | Path = DEFAULT_PROTOCOL_PATH,
    implementation_verifier: Callable[..., None] | None = None,
    estimator_factory: EstimatorFactory = _default_estimator_factory,
) -> DevelopmentExpertRunResult:
    if authorized is not True:
        raise DevelopmentExpertError("EXPERT_RUN_NOT_AUTHORIZED")
    root = Path(repo_root).resolve(strict=True)
    interim = Path(interim_root).resolve(strict=True)
    processed = Path(processed_root).resolve(strict=True)
    output = Path(private_output_root).resolve(strict=False)
    if any(path.is_symlink() for path in (interim, processed)) or output.exists():
        raise DevelopmentExpertError("OUTPUT_TOPOLOGY_INVALID")
    verifier = verify_development_expert_implementation_commit if implementation_verifier is None else implementation_verifier
    verifier(code_commit, repo_root=root)
    protocol = load_development_expert_protocol(protocol_path)
    selected_params = load_selected_hgb_parameters(protocol=protocol, repo_root=root)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".evcf-dev-experts-", dir=output.parent))
    cache_entries: list[dict[str, Any]] = []
    summaries: list[Mapping[str, Any]] = []
    total_fits = 0
    try:
        for contract in protocol.months:
            data = load_month_data(contract=contract, interim_root=interim, processed_root=processed)
            month_horizons: list[dict[str, Any]] = []
            for horizon in HORIZONS_MINUTES:
                tasks: dict[str, TaskPrediction] = {}
                for tier in TIERS:
                    task = predict_task(
                        data=data,
                        tier=tier,
                        horizon_minutes=horizon,
                        params=selected_params[(tier, horizon)],
                        selected_parameter_sha256=protocol.selected_parameter_sha256[tier][horizon],
                        test_start_local_day=protocol.test_start_local_day,
                        native_thread_limit=protocol.native_thread_limit,
                        estimator_factory=estimator_factory,
                    )
                    tasks[tier] = task
                    total_fits += task.fit_count
                m2 = tasks["M2"]
                m3 = tasks["M3"]
                name, digest = _write_private_cache(
                    stage=stage,
                    month=contract.month,
                    horizon=horizon,
                    m2=m2,
                    m3=m3,
                )
                cache_entries.append({"name": name, "sha256": digest})
                equal = (m2.predictions + m3.predictions) / 2.0
                m2_metrics = _metrics(m2.y_true, m2.predictions)
                m3_metrics = _metrics(m3.y_true, m3.predictions)
                equal_metrics = _metrics(m2.y_true, equal)
                month_horizons.append(
                    {
                        "horizon_minutes": horizon,
                        "test_rows": len(m2.issue_times),
                        "test_days": m2.fit_count,
                        "first_fit_rows": {"M2": m2.first_fit_rows, "M3": m3.first_fit_rows},
                        "last_fit_rows": {"M2": m2.last_fit_rows, "M3": m3.last_fit_rows},
                        "selected_parameter_sha256": {
                            "M2": m2.selected_parameter_sha256,
                            "M3": m3.selected_parameter_sha256,
                        },
                        "metrics": {"M2": m2_metrics, "M3": m3_metrics, "equal": equal_metrics},
                        "mae_improvement_percent": {
                            "M3_vs_M2": _improvement(m2_metrics["mae_a"], m3_metrics["mae_a"]),
                            "equal_vs_M2": _improvement(m2_metrics["mae_a"], equal_metrics["mae_a"]),
                            "equal_vs_M3": _improvement(m3_metrics["mae_a"], equal_metrics["mae_a"]),
                        },
                        "daily": _daily_summary(
                            issue_times=m2.issue_times,
                            day_starts=m2.day_starts,
                            truth=m2.y_true,
                            m2=m2.predictions,
                            m3=m3.predictions,
                            equal=equal,
                        ),
                    }
                )
            summaries.append(
                MappingProxyType(
                    {
                        "month": contract.month,
                        "processed_snapshot_sha256": contract.processed_snapshot_sha256,
                        "horizons": month_horizons,
                    }
                )
            )
        private_manifest = {
            "schema_version": "evcf-jpl-development-expert-private-cache/v1",
            "protocol_sha256": protocol.protocol_sha256,
            "code_commit": code_commit,
            "source_model_selection_sha256": protocol.source_model_selection_sha256,
            "holdout_accessed": False,
            "gate_trained": False,
            "files": sorted(cache_entries, key=lambda item: item["name"]),
        }
        manifest_bytes = _canonical_json_bytes(private_manifest)
        (stage / "private_manifest.json").write_bytes(manifest_bytes)
        os.replace(stage, output)
        stage = output
        manifest_sha = _sha256_bytes(manifest_bytes)
        return DevelopmentExpertRunResult(
            status="COMPLETE",
            protocol_sha256=protocol.protocol_sha256,
            code_commit=code_commit,
            source_model_selection_sha256=protocol.source_model_selection_sha256,
            month_summaries=tuple(summaries),
            fit_count=total_fits,
            private_cache_file_count=len(cache_entries),
            private_manifest_sha256=manifest_sha,
            holdout_accessed=False,
            gate_trained=False,
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
    "TIERS",
    "DevelopmentExpertError",
    "DevelopmentExpertProtocol",
    "DevelopmentExpertRunResult",
    "MonthContract",
    "MonthData",
    "TaskPrediction",
    "load_development_expert_protocol",
    "load_month_data",
    "load_selected_hgb_parameters",
    "predict_task",
    "run_development_experts",
    "verify_development_expert_implementation_commit",
]
