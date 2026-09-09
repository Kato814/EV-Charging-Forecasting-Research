from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from evcf.forecasting.acn_jpl_development_experts import DevelopmentExpertError
from evcf.forecasting.acn_jpl_development_experts_compat import _verify_git_semantic_checkout


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )


def _repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "core.autocrlf", "true")
    source = root / "sample.py"
    source.write_bytes(b"value = 1\nother = 2\n")
    _git(root, "add", "sample.py")
    _git(root, "commit", "-m", "baseline")
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    return root, head


def test_git_semantic_binding_accepts_crlf_materialization(tmp_path: Path) -> None:
    root, head = _repo(tmp_path)
    source = root / "sample.py"
    source.write_bytes(b"value = 1\r\nother = 2\r\n")

    diff = subprocess.run(
        ["git", "diff", "--quiet", "--no-ext-diff", head, "--", "sample.py"],
        cwd=root,
        check=False,
    )
    assert diff.returncode == 0
    _verify_git_semantic_checkout(head, repo_root=root, paths=("sample.py",))


def test_git_semantic_binding_rejects_real_content_change(tmp_path: Path) -> None:
    root, head = _repo(tmp_path)
    source = root / "sample.py"
    source.write_bytes(b"value = 9\r\nother = 2\r\n")

    with pytest.raises(DevelopmentExpertError, match="IMPLEMENTATION_DRIFT"):
        _verify_git_semantic_checkout(head, repo_root=root, paths=("sample.py",))


def test_git_semantic_binding_rejects_wrong_head(tmp_path: Path) -> None:
    root, head = _repo(tmp_path)
    source = root / "second.py"
    source.write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", "second.py")
    _git(root, "commit", "-m", "second")

    with pytest.raises(DevelopmentExpertError, match="IMPLEMENTATION_DRIFT"):
        _verify_git_semantic_checkout(head, repo_root=root, paths=("sample.py",))
