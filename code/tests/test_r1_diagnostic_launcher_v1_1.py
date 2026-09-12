from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def launcher():
    path = (Path(__file__).resolve().parents[2]
            / "scripts/evcf_r1_mixed_diagnostic_launcher_v1_1_template.py")
    spec = importlib.util.spec_from_file_location("r1_launcher_v1_1_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def identity_repo(tmp_path, launcher, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    artifacts = ((launcher.CORE_PATH, b"# Synthetic module, not imported.\n"),
                 (launcher.REFERENCE_PATH, b'{"synthetic":true}\n'))
    for relative, raw in artifacts:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    (root / ".gitattributes").write_text("* text eol=lf\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "-qm", "synthetic identity fixture"], cwd=root, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()
    monkeypatch.setattr(launcher, "EXPECTED_CODE_COMMIT", head)
    monkeypatch.setattr(launcher, "CORE_SHA256", hashlib.sha256(artifacts[0][1]).hexdigest())
    monkeypatch.setattr(launcher, "REFERENCE_SHA256", hashlib.sha256(artifacts[1][1]).hexdigest())
    return root, artifacts


def test_original_source_and_scientific_pins_are_unchanged(launcher):
    assert launcher.EXPECTED_CODE_COMMIT == "dd05258bf44d0a71773b6522ef6fb039831c77f1"
    assert launcher.PR_NUMBER == "65"
    assert launcher.CORE_SHA256 == "f552ce48f5a831064cff77e88ddccc26f76466697a0697860d5692bc1a1bbfc9"
    assert launcher.REFERENCE_SHA256 == "0c8075eb05c2405769862db72012076fc2f5a019c85a260d5b0315809520c703"
    assert launcher.R1_MANIFEST_SHA256 == "56178b6eac582a7ed844d6f94324a6947580e0f9a42e95cb9307fd78adecfd0f"
    assert launcher.DECISION == "MIXED_JOINT_STATE_SIGNAL"
    assert launcher.CODE_SUFFIX == "-jpl-r1-mixed-diagnostic-code-v1"


@pytest.mark.parametrize("crlf", [False, True])
def test_binary_verifier_preserves_lf_or_crlf_files(launcher, identity_repo, crlf):
    root, artifacts = identity_repo
    if crlf:
        for relative, raw in artifacts:
            (root / relative).write_bytes(raw.replace(b"\n", b"\r\n"))
    before = {r: (root / r).read_bytes() for r, _ in artifacts}
    checks = []
    launcher._verify_code(root, checks)
    assert len(checks) == 2
    assert all(c["git_blob_returncode"] == 0 and c["git_blob_matches_pin"] for c in checks)
    assert all(c["working_tree_lf_matches_pin"] for c in checks)
    assert before == {r: (root / r).read_bytes() for r in before}


def test_observed_show_failure_signature_no_longer_blocks_valid_blob(
    launcher, identity_repo, monkeypatch,
):
    root, _ = identity_repo
    original = launcher._git
    calls = []

    def git(path, *args):
        calls.append(args)
        if args[0] == "show":
            return SimpleNamespace(returncode=128, stdout="")
        return original(path, *args)

    monkeypatch.setattr(launcher, "_git", git)
    assert git(root, "show", f"{launcher.EXPECTED_CODE_COMMIT}:{launcher.CORE_PATH}").returncode == 128
    calls.clear()
    checks = []
    launcher._verify_code(root, checks)
    assert all(c["git_blob_matches_pin"] for c in checks)
    assert all(args[0] == "rev-parse" for args in calls)


@pytest.mark.parametrize("returncode,raw,reason", [
    (128, b"", "CORE_BLOB_READ_FAILED"),
    (0, b"changed object", "CORE_BLOB_SHA256_MISMATCH"),
    (0, b"", "CORE_BLOB_SHA256_MISMATCH"),
])
def test_blob_error_or_changed_bytes_fail_closed(
    launcher, identity_repo, monkeypatch, returncode, raw, reason,
):
    root, _ = identity_repo
    monkeypatch.setattr(launcher, "_git_blob", lambda *a: SimpleNamespace(
        returncode=returncode, stdout=raw))
    checks = []
    with pytest.raises(launcher.LauncherError, match=reason):
        launcher._verify_code(root, checks)
    assert checks[0]["git_blob_returncode"] == returncode
    assert checks[0]["git_blob_matches_pin"] is False


@pytest.mark.parametrize("artifact,label", [(0, "CORE"), (1, "REFERENCE")])
def test_local_drift_is_never_accepted(launcher, identity_repo, artifact, label):
    root, artifacts = identity_repo
    (root / artifacts[artifact][0]).write_bytes(b"changed file\n")
    with pytest.raises(launcher.LauncherError, match=f"{label}_LOCAL_SHA256_MISMATCH"):
        launcher._verify_code(root, [])


def test_wrong_head_fails_before_file_read(launcher, identity_repo, monkeypatch):
    root, _ = identity_repo
    monkeypatch.setattr(launcher, "EXPECTED_CODE_COMMIT", "0" * 40)
    monkeypatch.setattr(Path, "read_bytes", lambda p: pytest.fail("File read before HEAD check"))
    with pytest.raises(launcher.LauncherError, match="CODE_HEAD_MISMATCH"):
        launcher._verify_code(root)


def test_existing_code_worktree_is_reused_without_fetch_or_creation(
    launcher, identity_repo, monkeypatch,
):
    root, _ = identity_repo
    target = root.parent / f"{root.name}{launcher.CODE_SUFFIX}"
    subprocess.run(["git", "worktree", "add", "--detach", str(target),
                    launcher.EXPECTED_CODE_COMMIT], cwd=root, check=True, capture_output=True)
    before = launcher._worktrees(root)
    monkeypatch.setattr(launcher, "_git", lambda *a: pytest.fail("Unexpected Git write/fetch"))
    actual, created = launcher._code_worktree(root, before)
    assert actual == target and created is False


def test_absent_existing_worktree_is_not_recreated(launcher, identity_repo, monkeypatch):
    root, _ = identity_repo
    monkeypatch.setattr(launcher, "_git", lambda *a: pytest.fail("Unexpected Git fetch/add"))
    with pytest.raises(launcher.LauncherError, match="EXISTING_DIAGNOSTIC_WORKTREE_MISSING"):
        launcher._code_worktree(root, {})


def test_dirty_existing_worktree_is_not_reset(launcher, identity_repo):
    root, _ = identity_repo
    target = root.parent / f"{root.name}{launcher.CODE_SUFFIX}"
    target.mkdir()
    before = {str(target): (launcher.EXPECTED_CODE_COMMIT, " M file")}
    with pytest.raises(launcher.LauncherError, match="CODE_WORKTREE_MISMATCH"):
        launcher._code_worktree(root, before)


def test_unreleased_or_unauthorized_launcher_cannot_run(launcher, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["launcher", "--repo", "."])
    assert launcher.main() == 2
    assert "NOT_AUTHORIZED" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["launcher", "--repo", ".", "--authorize-r1-diagnostic"])
    assert launcher.main() == 2
    assert "UNRELEASED_TEMPLATE" in capsys.readouterr().out


def test_progress_stays_live_and_separate(launcher, capsys):
    progress = launcher.Progress()
    progress.emit("READ_VERIFY", 1, 20, "2019-01_h015")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "DONE=1/20" in captured.err and "READ_VERIFY" in captured.err
    progress.finish()
