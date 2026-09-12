from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def launcher():
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts/evcf_r1_identity_preflight_template.py"
    spec = importlib.util.spec_from_file_location("r1_identity_preflight_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def identity_repo(tmp_path, launcher, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    raw = b"# Synthetic code: never executed by the checker.\n"
    artifacts = []
    for label, relative, _ in launcher.ARTIFACTS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        artifacts.append((label, relative, hashlib.sha256(raw).hexdigest()))
    (root / ".gitattributes").write_text("* text eol=lf\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run([
        "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "synthetic identity fixture",
    ], cwd=root, check=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()
    monkeypatch.setattr(launcher, "SOURCE_COMMIT", sha)
    monkeypatch.setattr(launcher, "ARTIFACTS", tuple(artifacts))
    return root, raw


def test_pins_equal_accepted_repository_bytes(launcher):
    root = Path(__file__).resolve().parents[2]
    for _, relative, expected in launcher.ARTIFACTS:
        assert hashlib.sha256((root / relative).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == expected


@pytest.mark.parametrize("crlf", [False, True])
def test_real_git_read_only_identity_passes(launcher, identity_repo, crlf, capsys):
    root, raw = identity_repo
    if crlf:
        for _, relative, _ in launcher.ARTIFACTS:
            (root / relative).write_bytes(raw.replace(b"\n", b"\r\n"))
    before = {r: (root / r).read_bytes() for _, r, _ in launcher.ARTIFACTS}
    result = {}
    launcher._collect(root, result)
    assert result["legacy_verifier_passes_now"] is True
    assert result["raw_blob_and_working_tree_match"] is True
    assert result["identity_classification"] == "IDENTITY_MATCHES_NOW_PRIOR_CAUSE_UNRESOLVED"
    assert result["checked_code_worktree_state_unchanged"] is True
    assert before == {r: (root / r).read_bytes() for r in before}
    assert str(root) not in json.dumps(result)
    assert "R1_IDENTITY_PROGRESS=CHECK_CODE" in capsys.readouterr().err


def test_local_content_difference_is_evidence_not_a_bypass(launcher, identity_repo):
    root, _ = identity_repo
    (root / launcher.ARTIFACTS[0][1]).write_bytes(b"# Changed\n")
    result = {}
    launcher._collect(root, result)
    assert result["identity_classification"] == "WORKING_TREE_CONTENT_MISMATCH"
    assert result["legacy_verifier_passes_now"] is False
    assert result["raw_blob_and_working_tree_match"] is False


def test_legacy_transport_difference_is_distinguished(launcher, identity_repo, monkeypatch):
    root, _ = identity_repo
    original = launcher._git

    def changed(path, *args, legacy_text=False):
        if args[0] == "show" and legacy_text:
            return SimpleNamespace(returncode=0, stdout="transport differs")
        return original(path, *args, legacy_text=legacy_text)

    monkeypatch.setattr(launcher, "_git", changed)
    result = {}
    launcher._collect(root, result)
    assert result["identity_classification"] == "LEGACY_GIT_SHOW_TEXT_MISMATCH"
    assert result["raw_blob_and_working_tree_match"] is True
    assert result["legacy_verifier_passes_now"] is False


def test_blob_difference_is_distinguished(launcher, identity_repo, monkeypatch):
    root, _ = identity_repo
    original = launcher._git

    def changed(path, *args, legacy_text=False):
        if args[0] == "cat-file":
            return SimpleNamespace(returncode=0, stdout=b"not the pinned blob")
        return original(path, *args, legacy_text=legacy_text)

    monkeypatch.setattr(launcher, "_git", changed)
    result = {}
    launcher._collect(root, result)
    assert result["identity_classification"] == "PINNED_GIT_BLOB_MISMATCH"


def test_wrong_head_blocks_file_reads(launcher, identity_repo, monkeypatch):
    root, _ = identity_repo
    monkeypatch.setattr(launcher, "SOURCE_COMMIT", "0" * 40)
    monkeypatch.setattr(Path, "read_bytes", lambda p: pytest.fail("Unexpected file read"))
    with pytest.raises(launcher.IdentityCheckError, match="CODE_HEAD_MISMATCH"):
        launcher._collect(root, {})


def test_state_change_detected(launcher, identity_repo, monkeypatch):
    root, _ = identity_repo
    values = iter([(launcher.SOURCE_COMMIT, "before"), (launcher.SOURCE_COMMIT, "after")])
    monkeypatch.setattr(launcher, "_state", lambda p: next(values))
    with pytest.raises(launcher.IdentityCheckError, match="CHANGED_DURING_CHECK"):
        launcher._collect(root, {})


def test_unreleased_template_refuses_execution(launcher, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["preflight", "--repo", ".", "--authorize-r1-identity-check"])
    assert launcher.main() == 2
    assert "UNRELEASED_TEMPLATE" in capsys.readouterr().out


def test_authorization_required(launcher, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["preflight", "--repo", "."])
    assert launcher.main() == 2
    assert "NOT_AUTHORIZED" in capsys.readouterr().out
