"""Release template: substitute only reviewed-head, PR and module-digest tokens.

The delivered launcher is otherwise byte-identical to this CI-tested template.
It does not launch the R1 training module or read development raw/processed data.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

EXPECTED_CODE_COMMIT = "__REVIEWED_HEAD__"
PR_NUMBER = "__PR_NUMBER__"
CORE_SHA256 = "__CORE_SHA256__"
CORE_PATH = "code/src/evcf/forecasting/acn_jpl_r1_mixed_diagnostic.py"
REFERENCE_PATH = "code/configs/acn_jpl_r1_diagnostic_reference.json"
REFERENCE_SHA256 = "0c8075eb05c2405769862db72012076fc2f5a019c85a260d5b0315809520c703"
R1_MANIFEST_SHA256 = "56178b6eac582a7ed844d6f94324a6947580e0f9a42e95cb9307fd78adecfd0f"
CACHE_SUFFIX = "-jpl-r1-joint-state-runs-v1"
CODE_SUFFIX = "-jpl-r1-mixed-diagnostic-code-v1"
DECISION = "MIXED_JOINT_STATE_SIGNAL"


class LauncherError(RuntimeError):
    """Sanitized static failure, never a raw subprocess message."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class Progress:
    def __init__(self) -> None:
        self.start = perf_counter()
        self.stage = "START"
        self.stage_start = self.start
        self.stages: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.worker = threading.Thread(target=self._heartbeat, daemon=True)

    def emit(self, stage: str, done: int = 0, total: int = 0, cell: str = "") -> None:
        with self.lock:
            now = perf_counter()
            if stage != self.stage:
                self.stages.append({"stage": self.stage, "elapsed_seconds": now - self.stage_start})
                self.stage, self.stage_start = stage, now
            print(f"R1_DIAG_PROGRESS={stage}; DONE={done}/{total}; CELL={cell}; "
                  f"ELAPSED_S={now-self.start:.1f}", file=sys.stderr, flush=True)

    def _heartbeat(self) -> None:
        while not self.stop_event.wait(30):
            with self.lock:
                print(f"R1_DIAG_HEARTBEAT=RUNNING; STAGE={self.stage}; "
                      f"ELAPSED_S={perf_counter()-self.start:.1f}",
                      file=sys.stderr, flush=True)

    def finish(self) -> None:
        self.stop_event.set()
        if self.worker.is_alive():
            self.worker.join(timeout=1)
        self.stages.append({"stage": self.stage,
                            "elapsed_seconds": perf_counter() - self.stage_start})


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # Only short Git control output is captured; diagnostic progress is direct.
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        ["git", "-c", "maintenance.auto=false", "-c", "gc.auto=0", *args],
        cwd=repo, env=env, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", timeout=180,
    )


def _safe_path(path: Path) -> Path:
    for part in (path, *path.parents):
        if part.is_symlink():
            raise LauncherError("LINKED_PATH_NOT_ALLOWED")
        if part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 0x400:
            raise LauncherError("LINKED_PATH_NOT_ALLOWED")
    return path.resolve(strict=True)


def _worktrees(repo: Path) -> dict[str, tuple[str, str]]:
    result = _git(repo, "worktree", "list", "--porcelain")
    if result.returncode:
        raise LauncherError("WORKTREE_LIST_FAILED")
    out = {}
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            path = _safe_path(Path(line[9:]))
            head = _git(path, "rev-parse", "HEAD")
            status = _git(path, "status", "--porcelain=v1", "--untracked-files=no")
            if head.returncode or status.returncode:
                raise LauncherError("WORKTREE_STATE_READ_FAILED")
            out[str(path)] = (head.stdout.strip(), status.stdout)
    if not out:
        raise LauncherError("WORKTREE_LIST_EMPTY")
    return out


def _code_worktree(repo: Path, before: dict[str, tuple[str, str]]) -> tuple[Path, bool]:
    found = _git(repo, "rev-parse", f"{EXPECTED_CODE_COMMIT}^{{commit}}")
    if found.returncode:
        # Fetch exactly the reviewed commit, without pruning or forced ref updates.
        fetched = _git(repo, "fetch", "--no-tags", "--no-recurse-submodules",
                       "origin", EXPECTED_CODE_COMMIT)
        if fetched.returncode:
            raise LauncherError("REVIEWED_HEAD_FETCH_FAILED")
        found = _git(repo, "rev-parse", f"{EXPECTED_CODE_COMMIT}^{{commit}}")
    if found.returncode or found.stdout.strip() != EXPECTED_CODE_COMMIT:
        raise LauncherError("REVIEWED_HEAD_IDENTITY_INVALID")
    target = repo.parent / f"{repo.name}{CODE_SUFFIX}"
    created = False
    if target.exists():
        target = _safe_path(target)
        if before.get(str(target)) != (EXPECTED_CODE_COMMIT, ""):
            raise LauncherError("CODE_WORKTREE_MISMATCH")
    else:
        result = _git(repo, "worktree", "add", "--detach", str(target), EXPECTED_CODE_COMMIT)
        if result.returncode:
            raise LauncherError("CODE_WORKTREE_CREATE_FAILED")
        created = True
    return _safe_path(target), created


def _verify_code(root: Path) -> None:
    head = _git(root, "rev-parse", "HEAD")
    if head.returncode or head.stdout.strip() != EXPECTED_CODE_COMMIT:
        raise LauncherError("IMPLEMENTATION_DRIFT")
    for relative, expected_sha in ((CORE_PATH, CORE_SHA256), (REFERENCE_PATH, REFERENCE_SHA256)):
        path = _safe_path(root / relative)
        local = path.read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(local).hexdigest() != expected_sha:
            raise LauncherError("IMPLEMENTATION_DRIFT")
        git = _git(root, "show", f"{EXPECTED_CODE_COMMIT}:{relative}")
        if git.returncode or hashlib.sha256(git.stdout.encode("utf-8")).hexdigest() != expected_sha:
            raise LauncherError("IMPLEMENTATION_DRIFT")


def _locate_cache(repo: Path, progress: Progress) -> Path:
    parent = _safe_path(repo.parent / f"{repo.name}{CACHE_SUFFIX}")
    # The accepted R1 cache parent is the only data location examined.
    candidates = sorted(p for p in parent.iterdir() if p.name.startswith("run_"))
    matches = []
    for index, candidate in enumerate(candidates, start=1):
        _safe_path(candidate)
        if not candidate.is_dir():
            continue
        manifest = candidate / "private_manifest.json"
        if manifest.is_file():
            _safe_path(manifest)
            if hashlib.sha256(manifest.read_bytes()).hexdigest() == R1_MANIFEST_SHA256:
                matches.append(candidate)
        progress.emit("LOCATE_R1_CACHE", index, len(candidates))
    if len(matches) != 1:
        raise LauncherError("R1_PRIVATE_RUN_NOT_UNIQUE")
    return matches[0]


def _check_public(value: Any) -> None:
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LauncherError("PUBLIC_NONFINITE_VALUE")
        return
    if isinstance(value, str):
        if re.search(r"[A-Za-z]:[\\/]|^/(?:mnt|home|Users|tmp)/|^\\\\", value):
            raise LauncherError("PUBLIC_PATH_REJECTED")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if (not isinstance(key, str)
                    or key in {"session_id", "user_id", "issue_times", "y_true"}):
                raise LauncherError("PUBLIC_FIELD_REJECTED")
            _check_public(item)
        return
    if isinstance(value, list):
        for item in value:
            _check_public(item)
        return
    raise LauncherError("PUBLIC_TYPE_REJECTED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--authorize-r1-diagnostic", action="store_true")
    args = parser.parse_args()
    if not args.authorize_r1_diagnostic:
        print("R1_DIAGNOSTIC=NOT_AUTHORIZED", flush=True)
        return 2
    if not re.fullmatch(r"[0-9a-f]{40}", EXPECTED_CODE_COMMIT):
        print("R1_DIAGNOSTIC=UNRELEASED_TEMPLATE; DO_NOT_RUN", flush=True)
        return 2
    started = datetime.now(timezone.utc).isoformat()
    progress = Progress()
    progress.worker.start()
    status: dict[str, Any] = {
        "schema_version": "evcf-r1-mixed-diagnostic-launcher/v1",
        "status": "INCOMPLETE", "reason_code": None,
        "started_at_utc": started, "expected_code_commit": EXPECTED_CODE_COMMIT,
        "pr_number": int(PR_NUMBER), "source_r1_decision": DECISION,
        "analysis_only": True, "model_fit_attempted": False, "fit_count": 0,
        "raw_interim_processed_accessed": False, "holdout_accessed": False,
        "network_requests": "GIT_FETCH_ONLY_NO_DATA_DOWNLOAD",
        "r1_private_cache_unchanged": None,
        "existing_worktrees_preserved": None,
        "existing_worktree_heads_and_tracked_status_unchanged": None,
        "automatic_cleanup": False, "code_worktree_created_this_run": False,
        "device": "CPU", "gpu_used": False, "device_reason": "ARRAY_STATISTICS_NO_MODEL_FIT",
    }
    print("R1_DIAGNOSTIC=STARTED; DEVICE=CPU; MODEL_FIT=false; FINAL_HOLDOUT_ACCESS=false",
          flush=True)
    try:
        progress.emit("VERIFY_ENVIRONMENT")
        actual_numpy = importlib.metadata.version("numpy")
        status["environment"] = {"python": ".".join(map(str, sys.version_info[:3])),
                                 "numpy": actual_numpy}
        if sys.version_info[:3] != (3, 11, 16) or actual_numpy != "2.4.6":
            raise LauncherError("FROZEN_ENVIRONMENT_MISMATCH")
        progress.emit("VERIFY_WORKTREES")
        top = _git(_safe_path(args.repo), "rev-parse", "--show-toplevel")
        if top.returncode:
            raise LauncherError("REPOSITORY_NOT_FOUND")
        repo = _safe_path(Path(top.stdout.strip()))
        before = _worktrees(repo)
        output_parent = Path(__file__).resolve().parent
        if any(output_parent.is_relative_to(Path(p)) for p in before):
            raise LauncherError("LAUNCHER_MUST_BE_OUTSIDE_WORKTREES")
        progress.emit("RESOLVE_REVIEWED_CODE")
        root, created = _code_worktree(repo, before)
        status["code_worktree_created_this_run"] = created
        _verify_code(root)
        status["resolved_code_commit"] = EXPECTED_CODE_COMMIT
        progress.emit("LOCATE_R1_CACHE")
        cache = _locate_cache(repo, progress)
        if output_parent.is_relative_to(cache.parent):
            raise LauncherError("STATUS_OUTPUT_MUST_BE_OUTSIDE_PRIVATE_CACHE")
        # Import only this reviewed NumPy-only module; no model imports or child output buffering.
        spec = importlib.util.spec_from_file_location(
            "evcf_r1_readonly_diagnostic", root / CORE_PATH
        )
        if spec is None or spec.loader is None:
            raise LauncherError("DIAGNOSTIC_MODULE_NOT_FOUND")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        public = module.run_diagnostic(
            r1_private_run=cache, reference_path=root / REFERENCE_PATH, progress=progress.emit,
        )
        _check_public(public)
        status["diagnostic_public_result"] = public
        status["r1_private_cache_unchanged"] = public["r1_private_cache_unchanged"]
        progress.emit("FINAL_WORKTREE_CHECK")
        _verify_code(root)
        after = _worktrees(repo)
        if any(after.get(path) != value for path, value in before.items()):
            raise LauncherError("EXISTING_WORKTREE_STATE_CHANGED")
        if after.get(str(root)) != (EXPECTED_CODE_COMMIT, ""):
            raise LauncherError("IMPLEMENTATION_DRIFT")
        status["existing_worktrees_preserved"] = True
        status["existing_worktree_heads_and_tracked_status_unchanged"] = True
        status["status"] = "COMPLETE"
        progress.emit("COMPLETE", 20, 20)
    except (OSError, ValueError, RuntimeError, ImportError, KeyError, TypeError,
            subprocess.SubprocessError) as exc:
        reason = getattr(exc, "reason_code", "UNEXPECTED_ERROR")
        status["reason_code"] = reason if isinstance(reason, str) and re.fullmatch(
            r"[A-Z][A-Z0-9_]+", reason) else "UNEXPECTED_ERROR"
        progress.emit("INCOMPLETE")
    except KeyboardInterrupt:
        status["reason_code"] = "USER_INTERRUPTED"
        progress.emit("INTERRUPTED")
    finally:
        progress.finish()
    status["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    status["elapsed_seconds"] = perf_counter() - progress.start
    status["stage_timings"] = progress.stages
    status["launcher_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    _check_public(status)
    path = Path(__file__).resolve().parent / (
        "evcf_r1_mixed_diagnostic_status_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        + ".json"
    )
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(status, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    print(f'R1_DIAGNOSTIC={status["status"]}; '
          f'ELAPSED_S={status["elapsed_seconds"]:.1f}', flush=True)
    print(f"UPLOAD_ONLY={path.name}", flush=True)
    return 0 if status["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
