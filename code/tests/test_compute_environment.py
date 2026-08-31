from __future__ import annotations

from scripts.check_compute_environment import evaluate_requirements


def test_cuda_requirement_fails_when_cuda_is_unavailable() -> None:
    report = {
        "pytorch": {"cuda_available": False},
        "gpu": {"devices": []},
    }
    failures = evaluate_requirements(report, require_cuda=True, min_vram_gb=None)
    assert failures == ["CUDA is required but PyTorch cannot access a CUDA device"]


def test_vram_requirement_uses_largest_device() -> None:
    report = {
        "pytorch": {"cuda_available": True},
        "gpu": {
            "devices": [
                {"total_memory_gib": 8.0},
                {"total_memory_gib": 15.9},
            ]
        },
    }
    assert evaluate_requirements(report, require_cuda=True, min_vram_gb=14.0) == []
    failures = evaluate_requirements(report, require_cuda=True, min_vram_gb=16.0)
    assert failures == [
        "maximum GPU VRAM 15.900 GiB is below required 16.000 GiB"
    ]


def test_cpu_only_report_passes_without_gpu_requirement() -> None:
    report = {
        "pytorch": {"cuda_available": False},
        "gpu": {"devices": []},
    }
    assert evaluate_requirements(report, require_cuda=False, min_vram_gb=None) == []
