"""Print a privacy-safe compute environment report for local experiment runs.

The script intentionally avoids environment variables, usernames, hostnames, absolute
paths, process lists, and serial numbers. PyTorch is optional so the script can also run
on CPU-only GitHub-hosted CI runners.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any


def _round_gib(value: float) -> float:
    return round(float(value) / (1024**3), 3)


def collect_compute_environment() -> dict[str, Any]:
    """Collect non-sensitive host and optional PyTorch/CUDA information."""

    disk = shutil.disk_usage(Path.cwd())
    report: dict[str, Any] = {
        "schema_version": "compute-environment/v1",
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable_basename": Path(sys.executable).name,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "logical_cpu_count": os.cpu_count(),
        },
        "working_disk": {
            "total_gib": _round_gib(disk.total),
            "free_gib": _round_gib(disk.free),
        },
        "pytorch": {
            "installed": False,
            "version": None,
            "cuda_runtime": None,
            "cuda_available": False,
            "cudnn_version": None,
        },
        "gpu": {
            "count": 0,
            "devices": [],
        },
        "privacy": {
            "environment_variables_included": False,
            "hostname_included": False,
            "username_included": False,
            "absolute_paths_included": False,
        },
    }

    try:
        import torch
    except ImportError:
        return report

    report["pytorch"]["installed"] = True
    report["pytorch"]["version"] = str(torch.__version__)
    report["pytorch"]["cuda_runtime"] = torch.version.cuda
    report["pytorch"]["cuda_available"] = bool(torch.cuda.is_available())
    try:
        report["pytorch"]["cudnn_version"] = torch.backends.cudnn.version()
    except (AttributeError, RuntimeError):
        report["pytorch"]["cudnn_version"] = None

    if not torch.cuda.is_available():
        return report

    device_count = int(torch.cuda.device_count())
    devices: list[dict[str, Any]] = []
    for index in range(device_count):
        properties = torch.cuda.get_device_properties(index)
        major, minor = torch.cuda.get_device_capability(index)
        devices.append(
            {
                "index": index,
                "name": str(properties.name),
                "compute_capability": f"{major}.{minor}",
                "total_memory_gib": _round_gib(properties.total_memory),
                "multiprocessor_count": int(properties.multi_processor_count),
            }
        )
    report["gpu"] = {"count": device_count, "devices": devices}
    return report


def evaluate_requirements(
    report: dict[str, Any],
    *,
    require_cuda: bool,
    min_vram_gb: float | None,
) -> list[str]:
    """Return human-readable requirement failures without mutating the report."""

    failures: list[str] = []
    cuda_available = bool(report.get("pytorch", {}).get("cuda_available"))
    if require_cuda and not cuda_available:
        failures.append("CUDA is required but PyTorch cannot access a CUDA device")

    if min_vram_gb is not None:
        devices = report.get("gpu", {}).get("devices", [])
        maximum = max(
            (float(device.get("total_memory_gib", 0.0)) for device in devices),
            default=0.0,
        )
        if maximum < min_vram_gb:
            failures.append(
                f"maximum GPU VRAM {maximum:.3f} GiB is below required {min_vram_gb:.3f} GiB"
            )
    return failures


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--require-cuda", action="store_true")
    parser.add_argument("--min-vram-gb", type=float, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.min_vram_gb is not None and args.min_vram_gb < 0:
        raise SystemExit("--min-vram-gb must be non-negative")

    report = collect_compute_environment()
    failures = evaluate_requirements(
        report,
        require_cuda=args.require_cuda,
        min_vram_gb=args.min_vram_gb,
    )
    report["requirements"] = {
        "require_cuda": bool(args.require_cuda),
        "min_vram_gb": args.min_vram_gb,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
    }

    if args.output is not None:
        _write_report(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
