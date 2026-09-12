"""Read-only identity evidence for R1 diagnostic v1; never opens a data cache.

Release by replacing only __PREFLIGHT_REVIEWED_HEAD__ after review and CI.
This collects evidence; it neither bypasses verification nor resumes analysis.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

PREFLIGHT_REVIEWED_HEAD = "__PREFLIGHT_REVIEWED_HEAD__"
SOURCE_COMMIT = "dd05258bf44d0a71773b6522ef6fb039831c77f1"
CODE_SUFFIX = "-jpl-r1-mixed-diagnostic-code-v1"
ARTIFACTS = (
    (
        "DIAGNOSTIC_MODULE",
        "code/src/evcf/forecasting/acn_jpl_r1_mixed_diagnostic.py",
        "f552ce48f5a831064cff77e88ddccc26f76466697a0697860d5692bc1a1bbfc9",
    ),
    (
        "AGGREGATE_REFERENCE",
        "code/configs/acn_jpl_r1_diagnostic_reference.json",
        "0c8075eb05c2405769862db72012076fc2f5a019c85a260d5b0315809520c703",
    ),
)


class IdentityCheckError(RuntimeError):
    """Only static, path-free reasons may appear in the status."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _safe(path: Path) -> Path:
    for part in (path, *path.parents):
        if part.is_symlink():
            raise IdentityCheckError("LINKED_PATH_REJECTED")
        if part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 0x400:
            raise IdentityCheckError("LINKED_PATH_REJECTED")
    return path.resolve(strict=True)


def _git(root: Path, *args: str, legacy_text: bool = False):
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    kwargs = {"text": True, "encoding": "utf-8", "errors": "replace"} if legacy_text else {}
    # These are read commands only. stdout/stderr contents are never published.
    return subprocess.run(
        ["git", "-c", "maintenance.auto=false", "-c", "gc.auto=0", *args],
        cwd=root, env=env, check=False, capture_output=True, timeout=60, **kwargs,
    )


def _state(root: Path) -> tuple[str, str]:
    head = _git(root, "rev-parse", "HEAD", legacy_text=True)
    tracked = _git(root, "status", "--porcelain=v1", "--untracked-files=no")
    if head.returncode or tracked.returncode:
        raise IdentityCheckError("CODE_STATE_READ_FAILED")
    value = head.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise IdentityCheckError("CODE_HEAD_OUTPUT_INVALID")
    return value, _sha(tracked.stdout)


def _fingerprint(root: Path, label: str, relative: str, expected: str) -> dict[str, Any]:
    path = _safe(root / relative)
    if not path.is_file():
        raise IdentityCheckError("CODE_FILE_MISSING")
    raw = path.read_bytes()
    normalized = raw.replace(b"\r\n", b"\n")
    blob = _git(root, "cat-file", "blob", f"{SOURCE_COMMIT}:{relative}")
    show_bytes = _git(root, "show", f"{SOURCE_COMMIT}:{relative}")
    show_text = _git(root, "show", f"{SOURCE_COMMIT}:{relative}", legacy_text=True)
    diff = _git(root, "diff", "--quiet", "--no-ext-diff", SOURCE_COMMIT, "--", relative)
    text_bytes = show_text.stdout.encode("utf-8")
    return {
        "artifact": label, "expected_sha256": expected,
        "working_tree_bytes": len(raw), "working_tree_sha256": _sha(raw),
        "working_tree_lf_sha256": _sha(normalized),
        "crlf_count": raw.count(b"\r\n"), "lf_count": raw.count(b"\n"),
        "utf8_bom_present": raw.startswith(b"\xef\xbb\xbf"),
        "working_tree_lf_matches_pin": _sha(normalized) == expected,
        "git_blob_returncode": blob.returncode,
        "git_blob_bytes": len(blob.stdout), "git_blob_sha256": _sha(blob.stdout),
        "git_blob_matches_pin": blob.returncode == 0 and _sha(blob.stdout) == expected,
        "git_show_binary_returncode": show_bytes.returncode,
        "git_show_binary_bytes": len(show_bytes.stdout),
        "git_show_binary_sha256": _sha(show_bytes.stdout),
        "legacy_git_show_text_returncode": show_text.returncode,
        "legacy_git_show_text_bytes": len(text_bytes),
        "legacy_git_show_text_sha256": _sha(text_bytes),
        "legacy_git_show_text_matches_pin": show_text.returncode == 0 and _sha(text_bytes) == expected,
        "git_normalized_diff_returncode": diff.returncode,
    }


def _collect(root: Path, result: dict[str, Any]) -> None:
    before = _state(root)
    result["observed_code_commit"] = before[0]
    result["head_matches_expected"] = before[0] == SOURCE_COMMIT
    result["code_checks"] = []
    if before[0] != SOURCE_COMMIT:
        raise IdentityCheckError("CODE_HEAD_MISMATCH")
    for number, (label, relative, expected) in enumerate(ARTIFACTS, start=1):
        print(f"R1_IDENTITY_PROGRESS=CHECK_CODE; DONE={number-1}/2; ARTIFACT={label}",
              file=sys.stderr, flush=True)
        result["code_checks"].append(_fingerprint(root, label, relative, expected))
    after = _state(root)
    result["checked_code_worktree_state_unchanged"] = before == after
    if before != after:
        raise IdentityCheckError("CODE_STATE_CHANGED_DURING_CHECK")
    checks = result["code_checks"]
    local_ok = all(c["working_tree_lf_matches_pin"] for c in checks)
    blob_ok = all(c["git_blob_matches_pin"] for c in checks)
    text_ok = all(c["legacy_git_show_text_matches_pin"] for c in checks)
    result["legacy_verifier_passes_now"] = local_ok and text_ok
    result["raw_blob_and_working_tree_match"] = local_ok and blob_ok
    if not blob_ok:
        classification = "PINNED_GIT_BLOB_MISMATCH"
    elif not local_ok:
        classification = "WORKING_TREE_CONTENT_MISMATCH"
    elif not text_ok:
        classification = "LEGACY_GIT_SHOW_TEXT_MISMATCH"
    else:
        classification = "IDENTITY_MATCHES_NOW_PRIOR_CAUSE_UNRESOLVED"
    result["identity_classification"] = classification


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--authorize-r1-identity-check", action="store_true")
    args = parser.parse_args()
    if not args.authorize_r1_identity_check:
        print("R1_IDENTITY=NOT_AUTHORIZED", flush=True)
        return 2
    if not re.fullmatch(r"[0-9a-f]{40}", PREFLIGHT_REVIEWED_HEAD):
        print("R1_IDENTITY=UNRELEASED_TEMPLATE", flush=True)
        return 2
    started = perf_counter()
    status: dict[str, Any] = {
        "schema_version": "evcf-r1-identity-preflight/v1", "status": "INCOMPLETE",
        "reason_code": None, "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "preflight_reviewed_head": PREFLIGHT_REVIEWED_HEAD,
        "expected_code_commit": SOURCE_COMMIT,
        "source_r1_decision": "MIXED_JOINT_STATE_SIGNAL",
        "identity_evidence_only": True, "diagnostic_analysis_attempted": False,
        "model_fit_attempted": False, "fit_count": 0,
        "r1_private_cache_accessed": False, "raw_interim_processed_accessed": False,
        "holdout_accessed": False, "network_requests": False,
        "worktree_created": False, "automatic_cleanup": False,
        "checked_code_worktree_state_unchanged": None,
    }
    output_parent = _safe(Path(__file__).parent)
    print("R1_IDENTITY=STARTED; MODEL_FIT=false; CACHE_ACCESS=false", flush=True)
    try:
        repo = _safe(args.repo)
        top = _git(repo, "rev-parse", "--show-toplevel", legacy_text=True)
        if top.returncode:
            raise IdentityCheckError("REPOSITORY_NOT_FOUND")
        repo = _safe(Path(top.stdout.strip()))
        registry = _git(repo, "worktree", "list", "--porcelain", legacy_text=True)
        if registry.returncode:
            raise IdentityCheckError("WORKTREE_LIST_FAILED")
        paths = [_safe(Path(line[9:])) for line in registry.stdout.splitlines()
                 if line.startswith("worktree ")]
        if any(output_parent.is_relative_to(p) for p in paths):
            raise IdentityCheckError("PREFLIGHT_MUST_BE_OUTSIDE_WORKTREES")
        target = _safe(repo.parent / f"{repo.name}{CODE_SUFFIX}")
        if target not in paths:
            raise IdentityCheckError("EXPECTED_CODE_WORKTREE_NOT_REGISTERED")
        _collect(target, status)
        status["status"] = "COMPLETE"
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        status["reason_code"] = str(exc) if isinstance(exc, IdentityCheckError) else "CHECK_FAILED"
    except KeyboardInterrupt:
        status["reason_code"] = "USER_INTERRUPTED"
    status["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    status["elapsed_seconds"] = perf_counter() - started
    status["launcher_sha256"] = _sha(Path(__file__).read_bytes())
    name = "evcf_r1_identity_preflight_status_" + datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ") + ".json"
    with (output_parent / name).open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(status, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    print(f'R1_IDENTITY={status["status"]}; ELAPSED_S={status["elapsed_seconds"]:.2f}', flush=True)
    print(f"UPLOAD_ONLY={name}", flush=True)
    return 0 if status["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
