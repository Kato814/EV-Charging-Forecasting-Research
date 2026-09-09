from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pytest
from evcf.forecasting.acn_jpl_development_experts import DevelopmentExpertError
from evcf.forecasting.acn_jpl_development_experts_compat import (
    HORIZONS_MINUTES,
    _load_labels_order_insensitive,
)


def _write_labels(path: Path, labels: dict[str, float]) -> None:
    item = {
        "issue_index": 0,
        "issue_time_utc_s": 1546329600,
        "labels": labels,
    }
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        handle.write(
            json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        )


def test_canonical_sorted_label_json_is_read_in_frozen_horizon_order(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    processed.mkdir()
    labels = {str(horizon): float(horizon) for horizon in HORIZONS_MINUTES}
    _write_labels(processed / "labels.jsonl.gz", labels)

    with gzip.open(processed / "labels.jsonl.gz", "rt", encoding="utf-8") as handle:
        serialized = json.loads(handle.readline())
    assert tuple(serialized["labels"]) == ("120", "15", "240", "30", "60")

    times, values = _load_labels_order_insensitive(processed, 1)
    assert times.dtype == np.dtype(np.int64)
    assert values.dtype == np.dtype(np.float64)
    assert values.tolist() == [[15.0, 30.0, 60.0, 120.0, 240.0]]


def test_label_loader_requires_exact_horizon_key_set(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    processed.mkdir()
    labels = {str(horizon): float(horizon) for horizon in HORIZONS_MINUTES}
    labels.pop("240")
    labels["999"] = 999.0
    _write_labels(processed / "labels.jsonl.gz", labels)

    with pytest.raises(DevelopmentExpertError, match="LABEL_INVALID"):
        _load_labels_order_insensitive(processed, 1)
