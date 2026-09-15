from __future__ import annotations

import subprocess
from pathlib import Path

import evcf.forecasting.acn_jpl_r11_s0_backbone as controller
import pytest
from evcf.forecasting.acn_jpl_r11_s0_backbone import R11S0Error

from scripts import run_jpl_r11_s0_backbone as runner


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _init_repo(root: Path) -> str:
    assert _git(root, "init").returncode == 0
    assert _git(root, "config", "user.email", "r11-test@example.invalid").returncode == 0
    assert _git(root, "config", "user.name", "R11 Test").returncode == 0
    (root / ".gitattributes").write_text("* text eol=lf\n", encoding="utf-8", newline="\n")
    (root / "probe.txt").write_text("alpha\nbeta\n", encoding="utf-8", newline="\n")
    assert _git(root, "add", ".gitattributes", "probe.txt").returncode == 0
    assert _git(root, "commit", "-m", "probe").returncode == 0
    completed = _git(root, "rev-parse", "HEAD")
    assert completed.returncode == 0
    return completed.stdout.strip()


def test_portable_verifier_accepts_git_normalized_line_endings(tmp_path, monkeypatch):
    commit = _init_repo(tmp_path)
    monkeypatch.setattr(controller, "IMPLEMENTATION_PATHS", ("probe.txt",))

    # Simulate a checkout/text-filter byte representation that differs from the
    # Git blob but normalizes to the same tracked text.
    (tmp_path / "probe.txt").write_bytes(b"alpha\r\nbeta\r\n")
    assert _git(tmp_path, "diff", "--quiet", commit, "--", "probe.txt").returncode == 0

    runner._portable_verify_r11_s0_implementation_commit(commit, repo_root=tmp_path)


def test_portable_verifier_rejects_semantic_content_drift(tmp_path, monkeypatch):
    commit = _init_repo(tmp_path)
    monkeypatch.setattr(controller, "IMPLEMENTATION_PATHS", ("probe.txt",))
    (tmp_path / "probe.txt").write_text("alpha\nCHANGED\n", encoding="utf-8", newline="\n")

    with pytest.raises(R11S0Error, match="IMPLEMENTATION_DRIFT"):
        runner._portable_verify_r11_s0_implementation_commit(commit, repo_root=tmp_path)
