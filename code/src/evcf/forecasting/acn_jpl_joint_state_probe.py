"""Frozen R1 joint-session-state representation probe."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timezone
from itertools import combinations
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from threadpoolctl import threadpool_limits

from evcf.forecasting.acn_jpl_development_experts import load_selected_hgb_parameters
from evcf.forecasting.acn_jpl_development_experts_compat import (
    DevelopmentExpertError,
    load_development_expert_protocol,
    load_month_data,
)
from evcf.forecasting.acn_jpl_gate1_features import M3_SESSION_FIELDS
from evcf.forecasting.acn_jpl_gate1_models import make_frozen_estimator
from evcf.forecasting.acn_jpl_structured_mechanism_probe import (
    EXPECTED_BASELINE_PRIVATE_MANIFEST_SHA256,
    EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256,
    EXPECTED_STRUCTURED_PRIVATE_MANIFEST_SHA256,
    _load_m3_groups,
    _load_reference_pair,
    _verify_private_manifest,
)

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
_ZONE = ZoneInfo("America/Los_Angeles")
PAIR_INDEX = tuple(combinations(range(len(M3_SESSION_FIELDS)), 2))
PAIR_NAMES = tuple(
    f"r1_corr_{M3_SESSION_FIELDS[i]}__{M3_SESSION_FIELDS[j]}"
    for i, j in PAIR_INDEX
)
M3_RAW_WIDTH = 311
M3_INPUT_WIDTH = 391
R1_RAW_WIDTH = M3_RAW_WIDTH + len(PAIR_INDEX)
R1_INPUT_WIDTH = R1_RAW_WIDTH + (M3_INPUT_WIDTH - M3_RAW_WIDTH) + len(PAIR_INDEX)
IMPLEMENTATION_PATHS = (
    "docs/JPL_JOINT_SESSION_STATE_PROBE_PROTOCOL_20260912.md",
    "code/configs/acn_jpl_development_experts_2019.yaml",
    "code/src/evcf/forecasting/acn_jpl_development_experts.py",
    "code/src/evcf/forecasting/acn_jpl_development_experts_compat.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_data.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_features.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_models.py",
    "code/src/evcf/forecasting/acn_jpl_structured_mechanism_probe.py",
    "code/src/evcf/forecasting/acn_jpl_joint_state_probe.py",
    "scripts/run_jpl_joint_state_probe.py",
)


class JointStateProbeError(RuntimeError):
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
class Task:
    issue_times: np.ndarray
    day_starts: np.ndarray
    y_true: np.ndarray
    predictions: np.ndarray
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

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "evcf-jpl-r1-joint-state-summary/v1",
            "status": "COMPLETE",
            "code_commit": self.code_commit,
            "fit_count": self.fit_count,
            "private_cache_file_count": 20,
            "private_manifest_sha256": self.private_manifest_sha256,
            "decision": self.decision,
            "pooled_overall": dict(self.pooled),
            "pooled_by_horizon": [dict(x) for x in self.by_horizon],
            "pooled_by_month": [dict(x) for x in self.by_month],
            "months": [dict(x) for x in self.months],
            "holdout_accessed": False,
            "hyperparameter_search": False,
            "prediction_clipping": False,
            "prediction_calibration": False,
            "realized_composition_predictor": False,
            "deep_sets_trained": False,
            "set_transformer_trained": False,
            "moe_trained": False,
        }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_git(code_commit: str, repo_root: Path) -> None:
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise JointStateProbeError("IMPLEMENTATION_DRIFT")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="ascii",
        check=False,
    )
    if head.returncode or head.stdout.strip() != code_commit:
        raise JointStateProbeError("IMPLEMENTATION_DRIFT")
    for rel in IMPLEMENTATION_PATHS:
        path = repo_root / PurePosixPath(rel)
        if not path.is_file() or path.is_symlink():
            raise JointStateProbeError("IMPLEMENTATION_DRIFT")
        chk = subprocess.run(
            ["git", "cat-file", "-e", f"{code_commit}:{rel}"],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if chk.returncode:
            raise JointStateProbeError("IMPLEMENTATION_DRIFT")
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
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if diff.returncode != 0:
        raise JointStateProbeError("IMPLEMENTATION_DRIFT")


def _session_matrix(rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
    x = np.empty((len(rows), len(M3_SESSION_FIELDS)), dtype=np.float64)
    for r, row in enumerate(rows):
        for c, field in enumerate(M3_SESSION_FIELDS):
            value = row[field]
            x[r, c] = np.nan if value is None else float(value)
    if np.any(np.isinf(x)):
        raise JointStateProbeError("PAIR_FEATURE_INVALID")
    return x


def pair_features(
    groups: Sequence[Sequence[Mapping[str, Any]]],
) -> tuple[np.ndarray, np.ndarray]:
    """Return matched control and joint pair-feature matrices."""
    control = np.full((len(groups), len(PAIR_INDEX)), np.nan)
    joint = np.full_like(control, np.nan)
    for g, rows in enumerate(groups):
        x = _session_matrix(rows)
        for p, (i, j) in enumerate(PAIR_INDEX):
            ok = np.isfinite(x[:, i]) & np.isfinite(x[:, j])
            if int(np.sum(ok)) < 2:
                continue
            a, b = x[ok, i], x[ok, j]
            if np.var(a, ddof=1) <= 0 or np.var(b, ddof=1) <= 0:
                continue
            ac = a - np.mean(a)
            bc = b - np.mean(b)
            denom = math.sqrt(float(np.dot(ac, ac)) * float(np.dot(bc, bc)))
            if not math.isfinite(denom) or denom <= 0:
                continue
            corr = float(np.dot(ac, bc) / denom)
            if not math.isfinite(corr):
                continue
            if corr < -1 - 1e-12 or corr > 1 + 1e-12:
                raise JointStateProbeError("PAIR_FEATURE_INVALID")
            control[g, p] = 0.0
            joint[g, p] = min(1.0, max(-1.0, corr))
    if not np.array_equal(np.isnan(control), np.isnan(joint)):
        raise JointStateProbeError("PAIR_AVAILABILITY_MISMATCH")
    return control, joint


def _raw_block(
    m3_values: np.ndarray, m3_nullable: np.ndarray, pairs: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    raw = np.concatenate((m3_values, pairs), axis=1)
    nullable = np.concatenate(
        (m3_nullable, np.ones(len(PAIR_INDEX), dtype=np.bool_))
    )
    if raw.shape[1] != R1_RAW_WIDTH or nullable.shape != (R1_RAW_WIDTH,):
        raise JointStateProbeError("FEATURE_INVALID")
    return raw, nullable


def _encode(raw: np.ndarray, nullable: np.ndarray, rows: np.ndarray) -> np.ndarray:
    selected = np.asarray(raw[rows], dtype=np.float64)
    if np.any(np.isinf(selected)):
        raise JointStateProbeError("FEATURE_INVALID")
    out = np.concatenate(
        (selected, np.isnan(selected[:, nullable]).astype(np.float64)), axis=1
    )
    if out.shape[1] != R1_INPUT_WIDTH:
        raise JointStateProbeError("FEATURE_INVALID")
    return out


def _midnight(epoch: int) -> int:
    local = datetime.fromtimestamp(epoch, timezone.utc).astimezone(_ZONE)
    return int(datetime.combine(local.date(), time.min, tzinfo=_ZONE).timestamp())


def predict(
    *,
    issue_times: np.ndarray,
    labels: np.ndarray,
    raw: np.ndarray,
    nullable: np.ndarray,
    horizon: int,
    params: Mapping[str, Any],
    test_start_day: int,
) -> Task:
    pos = HORIZONS_MINUTES.index(horizon)
    y = np.asarray(labels[:, pos], dtype=np.float64)
    day_starts = np.asarray([_midnight(int(t)) for t in issue_times], dtype=np.int64)
    local_days = np.asarray(
        [
            datetime.fromtimestamp(int(t), timezone.utc).astimezone(_ZONE).day
            for t in issue_times
        ]
    )
    days = np.unique(day_starts[local_days >= test_start_day])
    pred = np.full(len(issue_times), np.nan)
    test_blocks: list[np.ndarray] = []
    fits = 0
    for day in days:
        fit = np.flatnonzero(issue_times + horizon * 60 <= int(day)).astype(np.int64)
        test = np.flatnonzero(day_starts == int(day)).astype(np.int64)
        if not len(fit) or not len(test) or np.intersect1d(fit, test).size:
            raise JointStateProbeError("ROLLING_SPLIT_INVALID")
        model = make_frozen_estimator("hgb", params)
        try:
            with threadpool_limits(limits=1):
                model.fit(_encode(raw, nullable, fit), y[fit])
                values = np.asarray(model.predict(_encode(raw, nullable, test)))
        except (TypeError, ValueError, FloatingPointError) as exc:
            raise JointStateProbeError("MODEL_FIT_INVALID") from exc
        if values.shape != (len(test),) or not np.isfinite(values).all():
            raise JointStateProbeError("PREDICTION_INVALID")
        pred[test] = values
        test_blocks.append(test)
        fits += 1
    rows = np.concatenate(test_blocks)
    return Task(
        issue_times=issue_times[rows],
        day_starts=day_starts[rows],
        y_true=y[rows],
        predictions=pred[rows],
        fit_count=fits,
    )


def _metric(y: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    ae = np.abs(p - y)
    denom = float(np.sum(np.abs(y)))
    return {
        "n": int(len(y)),
        "mae_a": float(np.mean(ae)),
        "rmse_a": float(np.sqrt(np.mean(np.square(p - y)))),
        "wape_ratio": None if denom <= 0 else float(np.sum(ae) / denom),
        "negative_prediction_count": int(np.sum(p < 0)),
    }


_KEYS = {
    "M2": "m2_predictions",
    "M3": "m3_predictions",
    "Equal": "equal_predictions",
    "S1": "s1_predictions",
    "R1_Control": "control_predictions",
    "R1_Joint": "joint_predictions",
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
    jm = float(pooled["R1_Joint"]["mae_a"])
    cm = float(pooled["R1_Control"]["mae_a"])
    em = float(pooled["Equal"]["mae_a"])
    hwc = sum(
        x["R1_Joint"]["mae_a"] < x["R1_Control"]["mae_a"] for x in by_horizon
    )
    mwc = sum(
        x["R1_Joint"]["mae_a"] < x["R1_Control"]["mae_a"] for x in by_month
    )
    hwe = sum(x["R1_Joint"]["mae_a"] < x["Equal"]["mae_a"] for x in by_horizon)
    mwe = sum(x["R1_Joint"]["mae_a"] < x["Equal"]["mae_a"] for x in by_month)
    h60 = next(x for x in by_horizon if x["horizon_minutes"] == 60)
    sixty = h60["R1_Joint"]["mae_a"] < h60["Equal"]["mae_a"]
    max_deg = max(
        (x["R1_Joint"]["mae_a"] - x["Equal"]["mae_a"]) / x["Equal"]["mae_a"]
        for x in by_horizon
    )
    support = {
        "joint_pooled_better_than_control": jm < cm,
        "joint_pooled_better_than_equal": jm < em,
        "joint_horizon_wins_vs_control": int(hwc),
        "joint_month_wins_vs_control": int(mwc),
        "joint_horizon_wins_vs_equal": int(hwe),
        "joint_month_wins_vs_equal": int(mwe),
        "joint_60min_better_than_equal": bool(sixty),
        "joint_max_horizon_degradation_fraction_vs_equal": float(max_deg),
    }
    if jm >= cm or hwc <= 1 or mwc <= 1:
        return "STOP_JOINT_STATE_ROUTE", support
    if (
        jm < em
        and hwc >= 3
        and mwc >= 3
        and hwe >= 3
        and mwe >= 3
        and sixty
        and max_deg <= 0.05
    ):
        return "PASS_JOINT_STATE_SIGNAL", support
    return "MIXED_JOINT_STATE_SIGNAL", support


def _write_cache(
    out: Path, code_commit: str, records: Sequence[Mapping[str, Any]]
) -> str:
    out.mkdir(parents=True, exist_ok=False)
    entries: list[dict[str, str]] = []
    for r in records:
        name = f'{r["month"]}_h{int(r["horizon_minutes"]):03d}.npz'
        path = out / name
        np.savez_compressed(
            path,
            issue_times=r["issue_times"],
            day_start_utc_s=r["day_start_utc_s"],
            y_true=r["y_true"],
            m2_predictions=r["m2_predictions"],
            m3_predictions=r["m3_predictions"],
            equal_predictions=r["equal_predictions"],
            s1_predictions=r["s1_predictions"],
            r1_control_predictions=r["control_predictions"],
            r1_joint_predictions=r["joint_predictions"],
        )
        entries.append({"name": name, "sha256": _sha256_file(path)})
    manifest = {
        "schema_version": "evcf-jpl-r1-joint-state-private-cache/v1",
        "code_commit": code_commit,
        "source_baseline_private_manifest_sha256": EXPECTED_BASELINE_PRIVATE_MANIFEST_SHA256,
        "source_structured_private_manifest_sha256": EXPECTED_STRUCTURED_PRIVATE_MANIFEST_SHA256,
        "holdout_accessed": False,
        "hyperparameter_search": False,
        "entries": sorted(entries, key=lambda x: x["name"]),
    }
    path = out / "private_manifest.json"
    path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii",
        newline="\n",
    )
    return _sha256_file(path)


def run_joint_state_probe(
    *,
    interim_root: str | Path,
    processed_root: str | Path,
    baseline_private_run: str | Path,
    structured_private_run: str | Path,
    private_output_dir: str | Path,
    code_commit: str,
    repo_root: str | Path,
) -> Result:
    repo = Path(repo_root).resolve(strict=True)
    _verify_git(code_commit, repo)
    interim = Path(interim_root).resolve(strict=True)
    processed = Path(processed_root).resolve(strict=True)
    baseline = Path(baseline_private_run).resolve(strict=True)
    structured = Path(structured_private_run).resolve(strict=True)
    try:
        _verify_private_manifest(
            baseline,
            expected_sha256=EXPECTED_BASELINE_PRIVATE_MANIFEST_SHA256,
            schema_version="evcf-jpl-development-expert-private-cache/v1",
            entries_key="files",
        )
        _verify_private_manifest(
            structured,
            expected_sha256=EXPECTED_STRUCTURED_PRIVATE_MANIFEST_SHA256,
            schema_version="evcf-jpl-structured-s1-private-cache/v1",
            entries_key="entries",
        )
    except Exception as exc:
        raise JointStateProbeError("PRIVATE_CACHE_IDENTITY_INVALID") from exc

    protocol = load_development_expert_protocol(
        repo / "code/configs/acn_jpl_development_experts_2019.yaml"
    )
    if protocol.protocol_sha256 != EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256:
        raise JointStateProbeError("PROTOCOL_INVALID")
    params = load_selected_hgb_parameters(protocol=protocol, repo_root=repo)

    records: list[dict[str, Any]] = []
    month_rows: list[dict[str, Any]] = []
    fit_count = 0
    for contract in protocol.months:
        if contract.month not in DEVELOPMENT_MONTHS:
            raise JointStateProbeError("HOLDOUT_ACCESS_ATTEMPT")
        try:
            data = load_month_data(
                contract=contract, interim_root=interim, processed_root=processed
            )
        except DevelopmentExpertError as exc:
            raise JointStateProbeError(exc.reason_code) from exc
        groups = _load_m3_groups(processed / contract.month, data.issue_times)
        control_pairs, joint_pairs = pair_features(groups)
        m3 = data.blocks["M3"]
        control_raw, nullable = _raw_block(
            m3.values, m3.nullable_mask, control_pairs
        )
        joint_raw, joint_nullable = _raw_block(
            m3.values, m3.nullable_mask, joint_pairs
        )
        if not np.array_equal(nullable, joint_nullable):
            raise JointStateProbeError("PAIR_AVAILABILITY_MISMATCH")
        horizons: list[dict[str, Any]] = []
        for horizon in HORIZONS_MINUTES:
            p = params[("M3", horizon)]
            control = predict(
                issue_times=data.issue_times,
                labels=data.labels,
                raw=control_raw,
                nullable=nullable,
                horizon=horizon,
                params=p,
                test_start_day=protocol.test_start_local_day,
            )
            joint = predict(
                issue_times=data.issue_times,
                labels=data.labels,
                raw=joint_raw,
                nullable=nullable,
                horizon=horizon,
                params=p,
                test_start_day=protocol.test_start_local_day,
            )
            ref = _load_reference_pair(
                baseline_root=baseline,
                structured_root=structured,
                month=contract.month,
                horizon=horizon,
            )
            if not (
                np.array_equal(control.issue_times, joint.issue_times)
                and np.array_equal(control.issue_times, ref["issue_times"])
                and np.array_equal(control.day_starts, ref["day_start_utc_s"])
                and np.allclose(control.y_true, joint.y_true, rtol=0, atol=1e-6)
                and np.allclose(control.y_true, ref["y_true"], rtol=0, atol=1e-6)
            ):
                raise JointStateProbeError("COMMON_ROW_IDENTITY_INVALID")
            rec = {
                "month": contract.month,
                "horizon_minutes": horizon,
                "issue_times": control.issue_times,
                "day_start_utc_s": control.day_starts,
                "y_true": control.y_true,
                "m2_predictions": ref["m2_predictions"],
                "m3_predictions": ref["m3_predictions"],
                "equal_predictions": ref["equal_predictions"],
                "s1_predictions": ref["structured_predictions"],
                "control_predictions": control.predictions,
                "joint_predictions": joint.predictions,
            }
            records.append(rec)
            metrics = _summary([rec])
            horizons.append({"horizon_minutes": horizon, **metrics})
            fit_count += control.fit_count + joint.fit_count
        month_rows.append(
            {
                "month": contract.month,
                "processed_snapshot_sha256": contract.processed_snapshot_sha256,
                "horizons": horizons,
            }
        )

    pooled = _summary(records)
    by_horizon = tuple(
        {
            "horizon_minutes": h,
            **_summary([r for r in records if r["horizon_minutes"] == h]),
        }
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
    )
