"""Frozen R2 higher-order origin-active session-set representation probe."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import math
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from evcf.forecasting.acn_jpl_development_experts_compat import (
    DevelopmentExpertError,
    load_development_expert_protocol,
    load_month_data,
)
from evcf.forecasting.acn_jpl_gate1_features import M3_SESSION_FIELDS
from evcf.forecasting.acn_jpl_structured_mechanism_probe import (
    EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256,
    _load_m3_groups,
    _verify_private_manifest,
)

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
EXPECTED_R1_PRIVATE_MANIFEST_SHA256 = (
    "56178b6eac582a7ed844d6f94324a6947580e0f9a42e95cb9307fd78adecfd0f"
)
EXPECTED_R1_CODE_COMMIT = "e01607078431141a1fccdd6a9db5f75ae561bfda"
PROTOCOL_MERGE_COMMIT = "ab0b8f6b7521f9e55d65a82fe7d44140a0973fef"
M2_RAW_WIDTH = 201
M2_CONTEXT_WIDTH = 204
SESSION_FIELD_COUNT = 11
SESSION_INPUT_WIDTH = 22
SESSION_HIDDEN = 32
CONTEXT_HIDDEN = 64
EPOCHS = 30
BATCH_SIZE = 256
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4
EXPECTED_FIT_COUNT = 550
GLOBAL_SEED_TEXT = "20260912"
_ZONE = ZoneInfo("America/Los_Angeles")
Progress = Callable[[str], None]

IMPLEMENTATION_PATHS = (
    "docs/JPL_R2_HIGHER_ORDER_SESSION_SET_PROTOCOL_20260912.md",
    "code/configs/acn_jpl_development_experts_2019.yaml",
    "code/src/evcf/forecasting/acn_jpl_development_experts.py",
    "code/src/evcf/forecasting/acn_jpl_development_experts_compat.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_data.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_features.py",
    "code/src/evcf/forecasting/acn_jpl_structured_mechanism_probe.py",
    "code/src/evcf/forecasting/acn_jpl_r2_session_set_probe.py",
    "scripts/run_jpl_r2_session_set_probe.py",
    "scripts/check_r2_cuda_environment.py",
)


class R2ProbeError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = (
            reason_code
            if isinstance(reason_code, str)
            and reason_code
            and reason_code.replace("_", "").isalnum()
            else "UNEXPECTED_ERROR"
        )
        super().__init__(self.reason_code)


@dataclass(frozen=True, slots=True)
class PairTask:
    issue_times: np.ndarray
    day_starts: np.ndarray
    y_true: np.ndarray
    joint_predictions: np.ndarray
    permuted_predictions: np.ndarray
    fit_count: int


@dataclass(frozen=True, slots=True)
class Result:
    code_commit: str
    fit_count: int
    private_manifest_sha256: str
    decision: str
    pooled: Mapping[str, Any]
    by_horizon: tuple[Mapping[str, Any], ...]
    by_month: tuple[Mapping[str, Any], ...]
    months: tuple[Mapping[str, Any], ...]
    device_info: Mapping[str, Any]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "evcf-jpl-r2-higher-order-session-set-summary/v1",
            "status": "COMPLETE",
            "code_commit": self.code_commit,
            "protocol_merge_commit": PROTOCOL_MERGE_COMMIT,
            "fit_count": self.fit_count,
            "private_cache_file_count": 20,
            "private_manifest_sha256": self.private_manifest_sha256,
            "decision": self.decision,
            "pooled_overall": dict(self.pooled),
            "pooled_by_horizon": [dict(x) for x in self.by_horizon],
            "pooled_by_month": [dict(x) for x in self.by_month],
            "months": [dict(x) for x in self.months],
            "device": dict(self.device_info),
            "holdout_accessed": False,
            "hyperparameter_search": False,
            "prediction_clipping": False,
            "prediction_calibration": False,
            "realized_composition_predictor": False,
            "future_session_generation": False,
            "set_transformer_trained": False,
            "moe_trained": False,
            "deep_sets_style_probe_trained": True,
        }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_git(code_commit: str, repo_root: Path) -> None:
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise R2ProbeError("IMPLEMENTATION_DRIFT")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="ascii",
        errors="ignore",
        check=False,
    )
    if head.returncode or head.stdout.strip() != code_commit:
        raise R2ProbeError("IMPLEMENTATION_DRIFT")
    for relative in IMPLEMENTATION_PATHS:
        path = repo_root / PurePosixPath(relative)
        if not path.is_file() or path.is_symlink():
            raise R2ProbeError("IMPLEMENTATION_DRIFT")
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{code_commit}:{relative}"],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if exists.returncode:
            raise R2ProbeError("IMPLEMENTATION_DRIFT")
    diff = subprocess.run(
        ["git", "diff", "--quiet", "--no-ext-diff", code_commit, "--", *IMPLEMENTATION_PATHS],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if diff.returncode:
        raise R2ProbeError("IMPLEMENTATION_DRIFT")


def _permutation_seed(issue_time_utc_s: int, field_index: int) -> int:
    payload = (
        f"R2_PERMUTED_V1|{GLOBAL_SEED_TEXT}|{int(issue_time_utc_s)}|{int(field_index)}"
    ).encode("ascii")
    return int.from_bytes(hashlib.sha256(payload).digest()[:16], "big", signed=False)


def _fold_seed(month: str, horizon: int, local_date: str) -> int:
    payload = f"R2_MODEL_V1|{GLOBAL_SEED_TEXT}|{month}|{horizon}|{local_date}".encode("ascii")
    value = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big", signed=False)
    return int(value % (2**31 - 1))


def _raw_session_group(rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
    ordered = sorted(rows, key=lambda row: int(row["anonymous_session_index"]))
    indexes = [int(row["anonymous_session_index"]) for row in ordered]
    if len(indexes) != len(set(indexes)):
        raise R2ProbeError("SESSION_IDENTITY_INVALID")
    matrix = np.full((len(ordered), SESSION_FIELD_COUNT), np.nan, dtype=np.float64)
    for r, row in enumerate(ordered):
        for c, field in enumerate(M3_SESSION_FIELDS):
            value = row[field]
            matrix[r, c] = np.nan if value is None else float(value)
    if matrix.shape[1] != SESSION_FIELD_COUNT or np.any(np.isinf(matrix)):
        raise R2ProbeError("SESSION_FEATURE_INVALID")
    return matrix


def build_joint_and_permuted(
    groups: Sequence[Sequence[Mapping[str, Any]]], issue_times: np.ndarray
) -> tuple[tuple[np.ndarray, ...], tuple[np.ndarray, ...]]:
    if len(groups) != len(issue_times):
        raise R2ProbeError("SESSION_GROUP_ALIGNMENT_INVALID")
    joint_groups: list[np.ndarray] = []
    permuted_groups: list[np.ndarray] = []
    for issue_raw, rows in zip(issue_times, groups, strict=True):
        joint = _raw_session_group(rows)
        permuted = joint.copy()
        n = len(joint)
        if n > 1:
            for field_index in range(SESSION_FIELD_COUNT):
                seed = _permutation_seed(int(issue_raw), field_index)
                rng = np.random.Generator(np.random.PCG64(seed))
                order = rng.permutation(n)
                permuted[:, field_index] = joint[order, field_index]
        for field_index in range(SESSION_FIELD_COUNT):
            a = joint[:, field_index]
            b = permuted[:, field_index]
            a_missing = np.isnan(a)
            b_missing = np.isnan(b)
            if int(np.sum(a_missing)) != int(np.sum(b_missing)):
                raise R2ProbeError("MARGINAL_CONTROL_INVALID")
            if not np.array_equal(np.sort(a[~a_missing]), np.sort(b[~b_missing])):
                raise R2ProbeError("MARGINAL_CONTROL_INVALID")
        joint_groups.append(joint)
        permuted_groups.append(permuted)
    return tuple(joint_groups), tuple(permuted_groups)


def _column_stats(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if values.ndim != 2:
        raise R2ProbeError("PREPROCESS_INVALID")
    means = np.zeros(values.shape[1], dtype=np.float64)
    scales = np.ones(values.shape[1], dtype=np.float64)
    for col in range(values.shape[1]):
        x = values[:, col]
        finite = x[np.isfinite(x)]
        if finite.size:
            means[col] = float(np.mean(finite))
            scale = float(np.std(finite, ddof=0))
            if math.isfinite(scale) and scale >= 1e-12:
                scales[col] = scale
    return means, scales


def _standardize(values: np.ndarray, means: np.ndarray, scales: np.ndarray) -> np.ndarray:
    if values.ndim != 2 or values.shape[1] != len(means) or means.shape != scales.shape:
        raise R2ProbeError("PREPROCESS_INVALID")
    out = np.zeros_like(values, dtype=np.float64)
    finite = np.isfinite(values)
    broadcast_mean = np.broadcast_to(means, values.shape)
    broadcast_scale = np.broadcast_to(scales, values.shape)
    out[finite] = (values[finite] - broadcast_mean[finite]) / broadcast_scale[finite]
    if not np.isfinite(out).all():
        raise R2ProbeError("PREPROCESS_INVALID")
    return out


def _m2_fold_transform(
    raw: np.ndarray,
    nullable: np.ndarray,
    train_rows: np.ndarray,
    test_rows: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    if raw.ndim != 2 or raw.shape[1] != M2_RAW_WIDTH:
        raise R2ProbeError("M2_CONTEXT_INVALID")
    nullable = np.asarray(nullable, dtype=np.bool_)
    if nullable.shape != (M2_RAW_WIDTH,) or int(np.sum(nullable)) != 3:
        raise R2ProbeError("M2_CONTEXT_INVALID")
    means, scales = _column_stats(raw[train_rows])

    def encode(rows: np.ndarray) -> np.ndarray:
        selected = np.asarray(raw[rows], dtype=np.float64)
        numeric = _standardize(selected, means, scales)
        indicators = np.isnan(selected[:, nullable]).astype(np.float64)
        output = np.concatenate((numeric, indicators), axis=1)
        if output.shape[1] != M2_CONTEXT_WIDTH or not np.isfinite(output).all():
            raise R2ProbeError("M2_CONTEXT_INVALID")
        return output.astype(np.float32)

    return encode(train_rows), encode(test_rows)


def _session_fold_stats(
    groups: Sequence[np.ndarray], train_rows: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    selected = [groups[int(row)] for row in train_rows if len(groups[int(row)])]
    if selected:
        values = np.concatenate(selected, axis=0)
    else:
        values = np.empty((0, SESSION_FIELD_COUNT), dtype=np.float64)
    return _column_stats(values)


def _encode_session_groups(
    groups: Sequence[np.ndarray], rows: np.ndarray, means: np.ndarray, scales: np.ndarray
) -> tuple[np.ndarray, ...]:
    output: list[np.ndarray] = []
    for row in rows:
        raw = np.asarray(groups[int(row)], dtype=np.float64)
        numeric = _standardize(raw, means, scales)
        observed = np.isfinite(raw).astype(np.float64)
        encoded = np.concatenate((numeric, observed), axis=1)
        if encoded.shape != (len(raw), SESSION_INPUT_WIDTH) or not np.isfinite(encoded).all():
            raise R2ProbeError("SESSION_PREPROCESS_INVALID")
        output.append(encoded.astype(np.float32))
    return tuple(output)


def _midnight(epoch: int) -> int:
    local = datetime.fromtimestamp(epoch, timezone.utc).astimezone(_ZONE)
    return int(datetime.combine(local.date(), time.min, tzinfo=_ZONE).timestamp())


def _local_date(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).astimezone(_ZONE).date().isoformat()


def _import_torch():
    try:
        return importlib.import_module("torch")
    except ImportError as exc:
        raise R2ProbeError("PYTORCH_NOT_AVAILABLE") from exc


def validate_formal_device() -> Mapping[str, Any]:
    try:
        version = importlib.metadata.version("torch")
    except importlib.metadata.PackageNotFoundError as exc:
        raise R2ProbeError("PYTORCH_NOT_AVAILABLE") from exc
    if version != "2.14.0":
        raise R2ProbeError("PYTORCH_VERSION_MISMATCH")
    torch = _import_torch()
    if not bool(torch.cuda.is_available()):
        raise R2ProbeError("CUDA_NOT_AVAILABLE")
    if int(torch.cuda.device_count()) < 1:
        raise R2ProbeError("CUDA_DEVICE_MISSING")
    name = str(torch.cuda.get_device_name(0))
    if "RTX 5080" not in name:
        raise R2ProbeError("GPU_IDENTITY_MISMATCH")
    cuda_version = str(torch.version.cuda)
    if not cuda_version.startswith("13.2"):
        raise R2ProbeError("CUDA_WHEEL_MISMATCH")
    device = torch.device("cuda:0")
    try:
        x = torch.tensor([[1.0, 2.0]], dtype=torch.float32, device=device, requires_grad=True)
        w = torch.tensor([[0.5], [-0.25]], dtype=torch.float32, device=device, requires_grad=True)
        loss = (x @ w).abs().sum()
        loss.backward()
        torch.cuda.synchronize(device)
    except Exception as exc:
        raise R2ProbeError("CUDA_SMOKE_TEST_FAILED") from exc
    return MappingProxyType(
        {
            "torch_version": version,
            "torch_cuda_version": cuda_version,
            "device": "cuda:0",
            "device_name": name,
            "float32_smoke_test": True,
        }
    )


def _make_model(torch):
    nn = torch.nn

    class R2Network(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.phi = nn.Sequential(
                nn.Linear(SESSION_INPUT_WIDTH, 32),
                nn.ReLU(),
                nn.Linear(32, 32),
                nn.ReLU(),
            )
            self.context = nn.Sequential(
                nn.Linear(M2_CONTEXT_WIDTH, 64),
                nn.ReLU(),
                nn.Linear(64, 32),
                nn.ReLU(),
            )
            self.head = nn.Sequential(nn.Linear(64, 32), nn.ReLU(), nn.Linear(32, 1))
            for module in self.modules():
                if isinstance(module, nn.Linear):
                    nn.init.xavier_uniform_(module.weight)
                    nn.init.zeros_(module.bias)

        def forward(self, context, sessions, valid):
            encoded = self.phi(sessions)
            encoded = encoded * valid.unsqueeze(-1).to(encoded.dtype)
            pooled = encoded.sum(dim=1)
            context_encoded = self.context(context)
            return self.head(torch.cat((context_encoded, pooled), dim=1)).squeeze(-1)

    return R2Network()


def _batch_tensors(
    torch, device, context: np.ndarray, sets: Sequence[np.ndarray],
    y: np.ndarray | None, rows: np.ndarray,
):
    if len(rows) == 0:
        raise R2ProbeError("BATCH_INVALID")
    max_sessions = max(1, max(len(sets[int(row)]) for row in rows))
    session_batch = np.zeros((len(rows), max_sessions, SESSION_INPUT_WIDTH), dtype=np.float32)
    valid_batch = np.zeros((len(rows), max_sessions), dtype=np.bool_)
    for out_row, source_row in enumerate(rows):
        values = sets[int(source_row)]
        if len(values):
            session_batch[out_row, : len(values)] = values
            valid_batch[out_row, : len(values)] = True
    context_tensor = torch.as_tensor(context[rows], dtype=torch.float32, device=device)
    session_tensor = torch.as_tensor(session_batch, dtype=torch.float32, device=device)
    valid_tensor = torch.as_tensor(valid_batch, dtype=torch.bool, device=device)
    y_tensor = None if y is None else torch.as_tensor(y[rows], dtype=torch.float32, device=device)
    return context_tensor, session_tensor, valid_tensor, y_tensor


def _train_predict_arm(
    *,
    context_train: np.ndarray,
    context_test: np.ndarray,
    sets_train: Sequence[np.ndarray],
    sets_test: Sequence[np.ndarray],
    y_train: np.ndarray,
    seed: int,
    arm: str,
    month: str,
    horizon: int,
    local_date: str,
    fit_number: int,
    total_fits: int,
    progress: Progress | None,
) -> np.ndarray:
    torch = _import_torch()
    if not torch.cuda.is_available():
        raise R2ProbeError("CUDA_NOT_AVAILABLE")
    device = torch.device("cuda:0")
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    if hasattr(torch.backends, "cuda") and hasattr(torch.backends.cuda, "matmul"):
        torch.backends.cuda.matmul.allow_tf32 = False
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.allow_tf32 = False
    if hasattr(torch, "set_float32_matmul_precision"):
        torch.set_float32_matmul_precision("highest")
    model = _make_model(torch).to(device=device, dtype=torch.float32)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    loss_fn = torch.nn.L1Loss(reduction="mean")
    rng = np.random.default_rng(seed)
    n = len(y_train)
    if n != len(context_train) or n != len(sets_train) or not n or not np.isfinite(y_train).all():
        raise R2ProbeError("TRAINING_DATA_INVALID")
    for epoch in range(1, EPOCHS + 1):
        order = rng.permutation(n).astype(np.int64)
        model.train()
        for start in range(0, n, BATCH_SIZE):
            rows = order[start : start + BATCH_SIZE]
            context_tensor, session_tensor, valid_tensor, y_tensor = _batch_tensors(
                torch, device, context_train, sets_train, y_train, rows
            )
            optimizer.zero_grad(set_to_none=True)
            pred = model(context_tensor, session_tensor, valid_tensor)
            loss = loss_fn(pred, y_tensor)
            if not bool(torch.isfinite(loss).item()):
                raise R2ProbeError("MODEL_FIT_INVALID")
            loss.backward()
            optimizer.step()
        if progress is not None and (epoch == 1 or epoch % 5 == 0 or epoch == EPOCHS):
            progress(
                "R2_PROGRESS=MODEL_FIT; "
                f"MONTH={month}; HORIZON={horizon}; DAY={local_date}; ARM={arm}; "
                f"FIT={fit_number}/{total_fits}; EPOCH={epoch}/{EPOCHS}"
            )
    model.eval()
    output = np.empty(len(context_test), dtype=np.float64)
    with torch.no_grad():
        for start in range(0, len(context_test), BATCH_SIZE):
            rows = np.arange(start, min(start + BATCH_SIZE, len(context_test)), dtype=np.int64)
            context_tensor, session_tensor, valid_tensor, _ = _batch_tensors(
                torch, device, context_test, sets_test, None, rows
            )
            pred = model(context_tensor, session_tensor, valid_tensor)
            output[rows] = pred.detach().cpu().numpy().astype(np.float64)
    if not np.isfinite(output).all():
        raise R2ProbeError("PREDICTION_INVALID")
    return output


def predict_horizon_pair(
    *,
    month: str,
    issue_times: np.ndarray,
    labels: np.ndarray,
    m2_raw: np.ndarray,
    m2_nullable: np.ndarray,
    joint_groups: Sequence[np.ndarray],
    permuted_groups: Sequence[np.ndarray],
    horizon: int,
    test_start_day: int,
    fit_offset: int,
    total_fits: int,
    progress: Progress | None,
) -> PairTask:
    position = HORIZONS_MINUTES.index(horizon)
    y = np.asarray(labels[:, position], dtype=np.float64)
    day_starts = np.asarray([_midnight(int(t)) for t in issue_times], dtype=np.int64)
    local_days = np.asarray(
        [datetime.fromtimestamp(int(t), timezone.utc).astimezone(_ZONE).day for t in issue_times]
    )
    days = np.unique(day_starts[local_days >= test_start_day])
    joint_pred = np.full(len(issue_times), np.nan)
    perm_pred = np.full(len(issue_times), np.nan)
    blocks: list[np.ndarray] = []
    fits = 0
    for day in days:
        fit = np.flatnonzero(issue_times + horizon * 60 <= int(day)).astype(np.int64)
        test = np.flatnonzero(day_starts == int(day)).astype(np.int64)
        if not len(fit) or not len(test) or np.intersect1d(fit, test).size:
            raise R2ProbeError("ROLLING_SPLIT_INVALID")
        if not np.isfinite(y[fit]).all() or not np.isfinite(y[test]).all():
            raise R2ProbeError("TARGET_INVALID")
        context_train, context_test = _m2_fold_transform(m2_raw, m2_nullable, fit, test)
        session_mean, session_scale = _session_fold_stats(joint_groups, fit)
        joint_train = _encode_session_groups(joint_groups, fit, session_mean, session_scale)
        joint_test = _encode_session_groups(joint_groups, test, session_mean, session_scale)
        perm_train = _encode_session_groups(permuted_groups, fit, session_mean, session_scale)
        perm_test = _encode_session_groups(permuted_groups, test, session_mean, session_scale)
        date_text = _local_date(int(day))
        seed = _fold_seed(month, horizon, date_text)
        joint_values = _train_predict_arm(
            context_train=context_train,
            context_test=context_test,
            sets_train=joint_train,
            sets_test=joint_test,
            y_train=y[fit],
            seed=seed,
            arm="JOINT",
            month=month,
            horizon=horizon,
            local_date=date_text,
            fit_number=fit_offset + fits + 1,
            total_fits=total_fits,
            progress=progress,
        )
        fits += 1
        perm_values = _train_predict_arm(
            context_train=context_train,
            context_test=context_test,
            sets_train=perm_train,
            sets_test=perm_test,
            y_train=y[fit],
            seed=seed,
            arm="PERMUTED",
            month=month,
            horizon=horizon,
            local_date=date_text,
            fit_number=fit_offset + fits + 1,
            total_fits=total_fits,
            progress=progress,
        )
        fits += 1
        joint_pred[test] = joint_values
        perm_pred[test] = perm_values
        blocks.append(test)
    rows = np.concatenate(blocks)
    return PairTask(
        issue_times=issue_times[rows],
        day_starts=day_starts[rows],
        y_true=y[rows],
        joint_predictions=joint_pred[rows],
        permuted_predictions=perm_pred[rows],
        fit_count=fits,
    )


def _metric(y: np.ndarray, pred: np.ndarray) -> dict[str, Any]:
    ae = np.abs(pred - y)
    denom = float(np.sum(np.abs(y)))
    return {
        "n": len(y),
        "mae_a": float(np.mean(ae)),
        "rmse_a": float(np.sqrt(np.mean(np.square(pred - y)))),
        "wape_ratio": None if denom <= 0 else float(np.sum(ae) / denom),
        "negative_prediction_count": int(np.sum(pred < 0)),
    }


_KEYS = {
    "M2": "m2_predictions",
    "M3": "m3_predictions",
    "Equal": "equal_predictions",
    "S1": "s1_predictions",
    "R1_Joint": "r1_joint_predictions",
    "R2_Permuted": "r2_permuted_predictions",
    "R2_Joint": "r2_joint_predictions",
}


def _summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    y = np.concatenate([r["y_true"] for r in records])
    return {
        name: _metric(y, np.concatenate([r[key] for r in records]))
        for name, key in _KEYS.items()
    }


def decide(
    pooled: Mapping[str, Any],
    by_horizon: Sequence[Mapping[str, Any]],
    by_month: Sequence[Mapping[str, Any]],
) -> tuple[str, dict[str, Any]]:
    jm = float(pooled["R2_Joint"]["mae_a"])
    pm = float(pooled["R2_Permuted"]["mae_a"])
    em = float(pooled["Equal"]["mae_a"])
    sm = float(pooled["S1"]["mae_a"])
    rm = float(pooled["R1_Joint"]["mae_a"])
    hwp = sum(x["R2_Joint"]["mae_a"] < x["R2_Permuted"]["mae_a"] for x in by_horizon)
    mwp = sum(x["R2_Joint"]["mae_a"] < x["R2_Permuted"]["mae_a"] for x in by_month)
    hwe = sum(x["R2_Joint"]["mae_a"] < x["Equal"]["mae_a"] for x in by_horizon)
    mwe = sum(x["R2_Joint"]["mae_a"] < x["Equal"]["mae_a"] for x in by_month)
    hws = sum(x["R2_Joint"]["mae_a"] < x["S1"]["mae_a"] for x in by_horizon)
    mws = sum(x["R2_Joint"]["mae_a"] < x["S1"]["mae_a"] for x in by_month)
    h60 = next(x for x in by_horizon if x["horizon_minutes"] == 60)
    sixty = h60["R2_Joint"]["mae_a"] < h60["Equal"]["mae_a"]
    degradation = []
    for x in by_horizon:
        better = min(float(x["Equal"]["mae_a"]), float(x["S1"]["mae_a"]))
        degradation.append((float(x["R2_Joint"]["mae_a"]) - better) / better)
    max_deg = max(degradation)
    support = {
        "joint_pooled_better_than_permuted": jm < pm,
        "joint_pooled_better_than_equal": jm < em,
        "joint_pooled_better_than_s1": jm < sm,
        "joint_pooled_better_than_r1_joint": jm < rm,
        "joint_horizon_wins_vs_permuted": int(hwp),
        "joint_month_wins_vs_permuted": int(mwp),
        "joint_horizon_wins_vs_equal": int(hwe),
        "joint_month_wins_vs_equal": int(mwe),
        "joint_horizon_wins_vs_s1": int(hws),
        "joint_month_wins_vs_s1": int(mws),
        "joint_60min_better_than_equal": bool(sixty),
        "joint_max_horizon_degradation_fraction_vs_better_equal_s1": float(max_deg),
    }
    if jm >= pm or hwp <= 1 or mwp <= 1:
        return "STOP_HIGHER_ORDER_SET_ROUTE", support
    passed = (
        jm < em
        and jm < sm
        and jm < rm
        and hwp >= 3
        and mwp >= 3
        and hwe >= 3
        and mwe >= 3
        and hws >= 3
        and mws >= 3
        and sixty
        and max_deg <= 0.05
    )
    if passed:
        return "PASS_HIGHER_ORDER_SET_SIGNAL", support
    return "MIXED_HIGHER_ORDER_SET_SIGNAL", support


def _load_r1_reference(root: Path, month: str, horizon: int) -> dict[str, np.ndarray]:
    required = {
        "issue_times",
        "day_start_utc_s",
        "y_true",
        "m2_predictions",
        "m3_predictions",
        "equal_predictions",
        "s1_predictions",
        "r1_control_predictions",
        "r1_joint_predictions",
    }
    path = root / f"{month}_h{horizon:03d}.npz"
    try:
        with np.load(path, allow_pickle=False) as archive:
            if set(archive.files) != required:
                raise R2ProbeError("R1_CACHE_SCHEMA_INVALID")
            data = {name: np.asarray(archive[name]) for name in required}
    except R2ProbeError:
        raise
    except (OSError, ValueError) as exc:
        raise R2ProbeError("R1_CACHE_SCHEMA_INVALID") from exc
    n = len(data["issue_times"])
    if n == 0 or any(array.shape != (n,) for array in data.values()):
        raise R2ProbeError("R1_CACHE_SCHEMA_INVALID")
    numeric = [v for k, v in data.items() if k not in {"issue_times", "day_start_utc_s"}]
    if not all(np.isfinite(v).all() for v in numeric):
        raise R2ProbeError("R1_CACHE_SCHEMA_INVALID")
    if not np.allclose(
        data["equal_predictions"],
        0.5 * data["m2_predictions"] + 0.5 * data["m3_predictions"],
        rtol=0,
        atol=1e-6,
    ):
        raise R2ProbeError("R1_CACHE_IDENTITY_INVALID")
    return data


def _write_cache(out: Path, code_commit: str, records: Sequence[Mapping[str, Any]]) -> str:
    out.mkdir(parents=True, exist_ok=False)
    entries: list[dict[str, str]] = []
    for record in records:
        name = f'{record["month"]}_h{int(record["horizon_minutes"]):03d}.npz'
        path = out / name
        np.savez_compressed(
            path,
            issue_times=record["issue_times"],
            day_start_utc_s=record["day_start_utc_s"],
            y_true=record["y_true"],
            m2_predictions=record["m2_predictions"],
            m3_predictions=record["m3_predictions"],
            equal_predictions=record["equal_predictions"],
            s1_predictions=record["s1_predictions"],
            r1_joint_predictions=record["r1_joint_predictions"],
            r2_permuted_predictions=record["r2_permuted_predictions"],
            r2_joint_predictions=record["r2_joint_predictions"],
        )
        entries.append({"name": name, "sha256": _sha256_file(path)})
    manifest = {
        "schema_version": "evcf-jpl-r2-higher-order-session-set-private-cache/v1",
        "code_commit": code_commit,
        "protocol_merge_commit": PROTOCOL_MERGE_COMMIT,
        "source_r1_private_manifest_sha256": EXPECTED_R1_PRIVATE_MANIFEST_SHA256,
        "holdout_accessed": False,
        "hyperparameter_search": False,
        "entries": sorted(entries, key=lambda item: item["name"]),
    }
    path = out / "private_manifest.json"
    path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii",
        newline="\n",
    )
    return _sha256_file(path)


def run_r2_probe(
    *,
    interim_root: str | Path,
    processed_root: str | Path,
    r1_private_run: str | Path,
    private_output_dir: str | Path,
    code_commit: str,
    repo_root: str | Path,
    progress: Progress | None = None,
) -> Result:
    repo = Path(repo_root).resolve(strict=True)
    _verify_git(code_commit, repo)
    device_info = validate_formal_device()
    interim = Path(interim_root).resolve(strict=True)
    processed = Path(processed_root).resolve(strict=True)
    r1_root = Path(r1_private_run).resolve(strict=True)
    try:
        r1_manifest = _verify_private_manifest(
            r1_root,
            expected_sha256=EXPECTED_R1_PRIVATE_MANIFEST_SHA256,
            schema_version="evcf-jpl-r1-joint-state-private-cache/v1",
            entries_key="entries",
        )
    except Exception as exc:
        raise R2ProbeError("R1_CACHE_IDENTITY_INVALID") from exc
    if (
        r1_manifest.get("code_commit") != EXPECTED_R1_CODE_COMMIT
        or r1_manifest.get("holdout_accessed") is not False
        or r1_manifest.get("hyperparameter_search") is not False
    ):
        raise R2ProbeError("R1_CACHE_IDENTITY_INVALID")

    protocol = load_development_expert_protocol(
        repo / "code/configs/acn_jpl_development_experts_2019.yaml"
    )
    if protocol.protocol_sha256 != EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256:
        raise R2ProbeError("PROTOCOL_INVALID")

    records: list[dict[str, Any]] = []
    month_rows: list[dict[str, Any]] = []
    fit_count = 0
    for contract in protocol.months:
        if contract.month not in DEVELOPMENT_MONTHS:
            raise R2ProbeError("HOLDOUT_ACCESS_ATTEMPT")
        if progress is not None:
            progress(f"R2_PROGRESS=LOAD_MONTH; MONTH={contract.month}")
        try:
            data = load_month_data(
                contract=contract, interim_root=interim, processed_root=processed
            )
        except DevelopmentExpertError as exc:
            raise R2ProbeError(exc.reason_code) from exc
        m2 = data.blocks["M2"]
        if m2.values.shape[1] != M2_RAW_WIDTH:
            raise R2ProbeError("M2_CONTEXT_INVALID")
        groups = _load_m3_groups(processed / contract.month, data.issue_times)
        joint_groups, permuted_groups = build_joint_and_permuted(groups, data.issue_times)
        horizons: list[dict[str, Any]] = []
        for horizon in HORIZONS_MINUTES:
            task = predict_horizon_pair(
                month=contract.month,
                issue_times=data.issue_times,
                labels=data.labels,
                m2_raw=m2.values,
                m2_nullable=m2.nullable_mask,
                joint_groups=joint_groups,
                permuted_groups=permuted_groups,
                horizon=horizon,
                test_start_day=protocol.test_start_local_day,
                fit_offset=fit_count,
                total_fits=EXPECTED_FIT_COUNT,
                progress=progress,
            )
            ref = _load_r1_reference(r1_root, contract.month, horizon)
            if not (
                np.array_equal(task.issue_times, ref["issue_times"])
                and np.array_equal(task.day_starts, ref["day_start_utc_s"])
                and np.allclose(task.y_true, ref["y_true"], rtol=0, atol=1e-6)
            ):
                raise R2ProbeError("COMMON_ROW_IDENTITY_INVALID")
            record = {
                "month": contract.month,
                "horizon_minutes": horizon,
                "issue_times": task.issue_times,
                "day_start_utc_s": task.day_starts,
                "y_true": task.y_true,
                "m2_predictions": ref["m2_predictions"],
                "m3_predictions": ref["m3_predictions"],
                "equal_predictions": ref["equal_predictions"],
                "s1_predictions": ref["s1_predictions"],
                "r1_joint_predictions": ref["r1_joint_predictions"],
                "r2_permuted_predictions": task.permuted_predictions,
                "r2_joint_predictions": task.joint_predictions,
            }
            records.append(record)
            horizons.append({"horizon_minutes": horizon, **_summary([record])})
            fit_count += task.fit_count
        month_rows.append(
            {
                "month": contract.month,
                "processed_snapshot_sha256": contract.processed_snapshot_sha256,
                "horizons": horizons,
            }
        )
    if fit_count != EXPECTED_FIT_COUNT:
        raise R2ProbeError("FIT_COUNT_INVALID")
    pooled = _summary(records)
    by_horizon = tuple(
        {"horizon_minutes": h, **_summary([r for r in records if r["horizon_minutes"] == h])}
        for h in HORIZONS_MINUTES
    )
    by_month = tuple(
        {"month": m, **_summary([r for r in records if r["month"] == m])}
        for m in DEVELOPMENT_MONTHS
    )
    decision, support = decide(pooled, by_horizon, by_month)
    pooled = {**pooled, "decision_support": support}
    manifest_sha = _write_cache(Path(private_output_dir), code_commit, records)
    return Result(
        code_commit=code_commit,
        fit_count=fit_count,
        private_manifest_sha256=manifest_sha,
        decision=decision,
        pooled=MappingProxyType(pooled),
        by_horizon=tuple(MappingProxyType(x) for x in by_horizon),
        by_month=tuple(MappingProxyType(x) for x in by_month),
        months=tuple(MappingProxyType(x) for x in month_rows),
        device_info=device_info,
    )
