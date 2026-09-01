from __future__ import annotations

import copy
import hashlib
import importlib
import re
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from zoneinfo import ZoneInfo

import pytest
import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "code/configs/acn_jpl_gate1_pilot_2019-05.yaml"
ENVIRONMENT_PATH = ROOT / "environment-gate1-pilot.yml"
EXPECTED_CONFIG_SHA256 = "852949542474f931159284365e5f54cbe1e2ca2437b4bc8f7ca40599cbeeeab5"
EXPECTED_TIME_SPLIT = {
    "timezone": "America/Los_Angeles",
    "initial_train": {
        "start_local": "2019-05-02T00:00:00-07:00",
        "end_local_exclusive": "2019-05-15T00:00:00-07:00",
    },
    "validation": {
        "start_local": "2019-05-15T00:00:00-07:00",
        "end_local_exclusive": "2019-05-18T00:00:00-07:00",
    },
    "rolling_test": {
        "start_local": "2019-05-18T00:00:00-07:00",
        "end_local_exclusive": "2019-06-01T00:00:00-07:00",
    },
}


def _contracts_module() -> ModuleType:
    try:
        return importlib.import_module("evcf.forecasting.acn_jpl_gate1_contracts")
    except ModuleNotFoundError:
        pytest.fail("Gate 1 contract loader is not implemented", pytrace=False)


def test_frozen_gate1_grid_and_seeds() -> None:
    contracts_module = _contracts_module()
    config = contracts_module.load_gate1_config()

    assert config["seeds"] == {"model": 20260901, "bootstrap": 20260902}
    assert config["bootstrap_repetitions"] == 10_000
    assert config["ridge"]["alpha"] == [0.1, 1, 10, 100]
    assert len(config["ridge"]["alpha"]) == 4

    grid = config["hgb_grid"]
    assert len(grid) == 16
    assert tuple(grid[0]) == (
        "learning_rate",
        "max_leaf_nodes",
        "min_samples_leaf",
        "l2_regularization",
        "max_iter",
        "early_stopping",
        "loss",
        "random_state",
    )
    assert grid == [
        {
            "learning_rate": learning_rate,
            "max_leaf_nodes": max_leaf_nodes,
            "min_samples_leaf": min_samples_leaf,
            "l2_regularization": l2_regularization,
            "max_iter": 300,
            "early_stopping": False,
            "loss": "squared_error",
            "random_state": 20260901,
        }
        for learning_rate in (0.03, 0.08)
        for max_leaf_nodes in (15, 31)
        for min_samples_leaf in (20, 50)
        for l2_regularization in (0, 1)
    ]
    assert {candidate["random_state"] for candidate in grid} == {config["seeds"]["model"]}


def test_frozen_dates_horizons_windows_target_and_snapshot() -> None:
    contracts_module = _contracts_module()
    config = contracts_module.load_gate1_config(CONFIG_PATH)

    assert config["horizons_minutes"] == [15, 30, 60, 120, 240]
    assert config["windows_minutes"] == [5, 15, 30, 60]
    assert config["bounded_hold_seconds"] == 12
    assert config["target"] == "station_current_mean_a"
    assert config["data_snapshot_sha256"] == (
        "7066ffc8ba42a98f73246acfbc62352fe55a1433a43cba80957c6034e3aeaa5d"
    )
    assert config["time_split"] == EXPECTED_TIME_SPLIT

    zone = ZoneInfo("America/Los_Angeles")
    boundaries = config["time_split_boundaries"]
    assert boundaries == {
        "timezone": zone,
        "initial_train": {
            "start_local": datetime(2019, 5, 2, tzinfo=zone),
            "end_local_exclusive": datetime(2019, 5, 15, tzinfo=zone),
        },
        "validation": {
            "start_local": datetime(2019, 5, 15, tzinfo=zone),
            "end_local_exclusive": datetime(2019, 5, 18, tzinfo=zone),
        },
        "rolling_test": {
            "start_local": datetime(2019, 5, 18, tzinfo=zone),
            "end_local_exclusive": datetime(2019, 6, 1, tzinfo=zone),
        },
    }
    intervals = ("initial_train", "validation", "rolling_test")
    for name in intervals:
        assert boundaries[name]["start_local"].tzinfo == zone
        assert boundaries[name]["end_local_exclusive"].tzinfo == zone
        assert boundaries[name]["start_local"].utcoffset() == timedelta(hours=-7)
        assert boundaries[name]["start_local"] < boundaries[name]["end_local_exclusive"]
    assert (
        boundaries["initial_train"]["end_local_exclusive"]
        == boundaries["validation"]["start_local"]
    )
    assert (
        boundaries["validation"]["end_local_exclusive"]
        == boundaries["rolling_test"]["start_local"]
    )


def test_config_sha256_covers_exact_file_bytes() -> None:
    contracts_module = _contracts_module()
    raw = CONFIG_PATH.read_bytes()

    assert hashlib.sha256(raw).hexdigest() == EXPECTED_CONFIG_SHA256
    assert contracts_module.config_sha256(CONFIG_PATH) == EXPECTED_CONFIG_SHA256


@pytest.mark.parametrize("mutation", ["missing", "extra", "changed"])
def test_loader_rejects_frozen_config_mutations(
    tmp_path: Path,
    mutation: str,
) -> None:
    contracts_module = _contracts_module()
    payload = copy.deepcopy(yaml.safe_load(CONFIG_PATH.read_bytes()))
    if mutation == "missing":
        del payload["horizons_minutes"]
    elif mutation == "extra":
        payload["unfrozen_override"] = True
    else:
        payload["seeds"]["model"] += 1
    mutated = tmp_path / f"{mutation}.yaml"
    mutated.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(contracts_module.FrozenConfigError, match="frozen"):
        contracts_module.load_gate1_config(mutated)


def test_loader_rejects_duplicate_yaml_keys(
    tmp_path: Path,
) -> None:
    contracts_module = _contracts_module()
    duplicated = tmp_path / "duplicated.yaml"
    duplicated.write_bytes(CONFIG_PATH.read_bytes() + b"target: station_current_mean_a\n")

    with pytest.raises(contracts_module.FrozenConfigError, match="duplicate"):
        contracts_module.load_gate1_config(duplicated)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("naive", "timezone-aware"),
        ("wrong_offset", "-07:00"),
        ("reversed", "start before end"),
        ("non_contiguous", "contiguous"),
    ],
)
def test_loader_rejects_invalid_time_split_semantics(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    contracts_module = _contracts_module()
    payload = copy.deepcopy(yaml.safe_load(CONFIG_PATH.read_bytes()))
    payload["time_split"] = copy.deepcopy(EXPECTED_TIME_SPLIT)
    payload["hgb"]["random_state"] = 20260901
    if mutation == "naive":
        payload["time_split"]["initial_train"]["start_local"] = "2019-05-02T00:00:00"
    elif mutation == "wrong_offset":
        payload["time_split"]["initial_train"]["start_local"] = (
            "2019-05-02T00:00:00-08:00"
        )
    elif mutation == "reversed":
        payload["time_split"]["initial_train"]["end_local_exclusive"] = (
            "2019-05-01T00:00:00-07:00"
        )
    else:
        payload["time_split"]["validation"]["start_local"] = (
            "2019-05-15T00:15:00-07:00"
        )
    mutated = tmp_path / f"time-split-{mutation}.yaml"
    mutated.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(contracts_module.FrozenConfigError, match=message):
        contracts_module.load_gate1_config(mutated)


def test_gate1_environment_is_exact_path_free_and_cpu_only() -> None:
    raw = ENVIRONMENT_PATH.read_text(encoding="utf-8")
    environment = yaml.safe_load(raw)

    assert set(environment) == {"name", "channels", "dependencies"}
    assert environment["name"] == "evcf-gate1-pilot"
    assert environment["channels"] == ["conda-forge"]
    assert environment["dependencies"] == [
        "python=3.11.16",
        "numpy=2.4.6",
        "pandas=3.0.5",
        "scipy=1.17.1",
        "scikit-learn=1.9.0",
        "joblib=1.6.0",
        "pyarrow=25.0.1",
        "pyyaml=6.0.3",
        "pytest=9.1.1",
        "ruff=0.16.5",
        "requests=2.34.2",
    ]
    assert "prefix" not in environment
    assert re.search(r"[A-Za-z]:[\\/]", raw) is None
    assert not any(token in raw.casefold() for token in ("pytorch", "torch", "cuda", "gpu"))


def test_gate1_optional_dependencies_are_separate_and_base_is_unchanged() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["dependencies"] == [
        "numpy>=1.26",
        "pandas>=2.2",
        "pyyaml>=6.0",
        "requests>=2.32",
    ]
    optional = project["project"]["optional-dependencies"]
    assert optional["dev"] == ["pytest>=8.0", "ruff>=0.12"]
    assert optional["gate1"] == [
        "scipy==1.17.1",
        "scikit-learn==1.9.0",
        "joblib==1.6.0",
        "pyarrow==25.0.1",
    ]
    assert "torch" not in " ".join(optional["gate1"]).casefold()


def test_library_ci_installs_gate1_group_under_python_311() -> None:
    workflow = (ROOT / ".github/workflows/library-check.yml").read_text(encoding="utf-8")

    assert "python-version: '3.11'" in workflow
    assert "python -m pip install -e .[dev,gate1]" in workflow
    assert "python -m pip install -e .[dev]" not in workflow
