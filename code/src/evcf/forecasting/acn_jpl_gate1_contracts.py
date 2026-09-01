"""Fail-closed contracts for the frozen JPL May 2019 Gate 1 pilot."""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

_TIMEZONE_NAME = "America/Los_Angeles"
_PDT_OFFSET = timedelta(hours=-7)
_TIME_INTERVAL_NAMES = ("initial_train", "validation", "rolling_test")

_FROZEN_CONFIG: dict[str, Any] = {
    "schema_version": "acn-jpl-gate1-pilot/v1",
    "data_snapshot_sha256": ("7066ffc8ba42a98f73246acfbc62352fe55a1433a43cba80957c6034e3aeaa5d"),
    "target": "station_current_mean_a",
    "seeds": {"model": 20260901, "bootstrap": 20260902},
    "bootstrap_repetitions": 10_000,
    "horizons_minutes": [15, 30, 60, 120, 240],
    "time_split": {
        "timezone": _TIMEZONE_NAME,
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
    },
    "ridge": {"alpha": [0.1, 1, 10, 100]},
    "hgb": {
        "learning_rate": [0.03, 0.08],
        "max_leaf_nodes": [15, 31],
        "min_samples_leaf": [20, 50],
        "l2_regularization": [0, 1],
        "max_iter": 300,
        "early_stopping": False,
        "loss": "squared_error",
        "random_state": 20260901,
        "categorical_features": None,
    },
    "windows_minutes": [5, 15, 30, 60],
    "bounded_hold_seconds": 12,
}


class FrozenConfigError(ValueError):
    """Raised when a Gate 1 config is not exactly the frozen protocol."""


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _parse_yaml(raw: bytes) -> dict[str, Any]:
    try:
        payload = yaml.load(raw, Loader=_UniqueKeySafeLoader)
    except yaml.YAMLError as exc:
        raise FrozenConfigError(f"invalid frozen Gate 1 YAML: {exc}") from exc
    if type(payload) is not dict:
        raise FrozenConfigError("frozen Gate 1 config root must be a mapping")
    return payload


def _validate_frozen(actual: Any, expected: Any, *, path: str = "config") -> None:
    if type(actual) is not type(expected):
        raise FrozenConfigError(
            f"{path} changed frozen type: expected {type(expected).__name__}, "
            f"found {type(actual).__name__}"
        )

    if isinstance(expected, dict):
        actual_keys = tuple(actual)
        expected_keys = tuple(expected)
        if actual_keys != expected_keys:
            raise FrozenConfigError(
                f"{path} changed frozen keys or declaration order: "
                f"expected {expected_keys!r}, found {actual_keys!r}"
            )
        for key, expected_value in expected.items():
            _validate_frozen(actual[key], expected_value, path=f"{path}.{key}")
        return

    if isinstance(expected, list):
        if len(actual) != len(expected):
            raise FrozenConfigError(
                f"{path} changed frozen length: expected {len(expected)}, found {len(actual)}"
            )
        for index, (actual_value, expected_value) in enumerate(zip(actual, expected, strict=True)):
            _validate_frozen(actual_value, expected_value, path=f"{path}[{index}]")
        return

    if actual != expected:
        raise FrozenConfigError(
            f"{path} changed frozen value: expected {expected!r}, found {actual!r}"
        )


def _parse_local_boundary(value: Any, *, path: str, zone: ZoneInfo) -> datetime:
    if not isinstance(value, str):
        raise FrozenConfigError(f"{path} must be a frozen timezone-aware ISO datetime string")
    try:
        boundary = datetime.fromisoformat(value)
    except ValueError as exc:
        raise FrozenConfigError(f"{path} must be a frozen timezone-aware ISO datetime") from exc
    if boundary.tzinfo is None or boundary.utcoffset() is None:
        raise FrozenConfigError(f"{path} must be timezone-aware")
    if boundary.utcoffset() != _PDT_OFFSET:
        raise FrozenConfigError(f"{path} must use the frozen PDT offset -07:00")

    localized = boundary.astimezone(zone)
    if localized.utcoffset() != _PDT_OFFSET or localized.replace(tzinfo=None) != boundary.replace(
        tzinfo=None
    ):
        raise FrozenConfigError(f"{path} must correspond to ZoneInfo {_TIMEZONE_NAME}")
    return localized


def parse_time_split_boundaries(time_split: Any) -> dict[str, Any]:
    """Validate frozen split semantics and return runtime-only aware boundaries."""

    if type(time_split) is not dict:
        raise FrozenConfigError("frozen config.time_split must be a mapping")
    if time_split.get("timezone") != _TIMEZONE_NAME:
        raise FrozenConfigError(f"frozen config.time_split timezone must be {_TIMEZONE_NAME}")

    zone = ZoneInfo(_TIMEZONE_NAME)
    parsed: dict[str, Any] = {"timezone": zone}
    previous_end: datetime | None = None
    for name in _TIME_INTERVAL_NAMES:
        interval = time_split.get(name)
        if type(interval) is not dict:
            raise FrozenConfigError(f"frozen config.time_split.{name} must be a mapping")
        start = _parse_local_boundary(
            interval.get("start_local"),
            path=f"config.time_split.{name}.start_local",
            zone=zone,
        )
        end = _parse_local_boundary(
            interval.get("end_local_exclusive"),
            path=f"config.time_split.{name}.end_local_exclusive",
            zone=zone,
        )
        if start >= end:
            raise FrozenConfigError(f"config.time_split.{name} must place start before end")
        if previous_end is not None and previous_end != start:
            raise FrozenConfigError("frozen config.time_split intervals must be contiguous")
        parsed[name] = {"start_local": start, "end_local_exclusive": end}
        previous_end = end
    return parsed


def expand_hgb_grid(hgb_config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expand the frozen HGB Cartesian grid in YAML declaration order."""

    declared = dict(hgb_config)
    _validate_frozen(declared, _FROZEN_CONFIG["hgb"], path="config.hgb")
    varying_keys = [key for key, value in declared.items() if isinstance(value, list)]
    axes = [declared[key] for key in varying_keys]
    candidates: list[dict[str, Any]] = []
    for values in itertools.product(*axes):
        selected = dict(zip(varying_keys, values, strict=True))
        candidates.append({key: selected.get(key, value) for key, value in declared.items()})
    if len(candidates) != 16:
        raise FrozenConfigError("config.hgb frozen Cartesian grid must contain 16 candidates")
    return candidates


def _copy_in_frozen_order(actual: Any, expected: Any, *, path: str) -> Any:
    """Return a plain copy ordered like the frozen schema after exact validation."""

    if type(actual) is not type(expected):
        raise FrozenConfigError(
            f"{path} changed frozen type: expected {type(expected).__name__}, "
            f"found {type(actual).__name__}"
        )
    if isinstance(expected, dict):
        if set(actual) != set(expected) or len(actual) != len(expected):
            raise FrozenConfigError(
                f"{path} changed frozen keys: expected {tuple(expected)!r}, found {tuple(actual)!r}"
            )
        return {
            key: _copy_in_frozen_order(actual[key], value, path=f"{path}.{key}")
            for key, value in expected.items()
        }
    if isinstance(expected, list):
        if len(actual) != len(expected):
            raise FrozenConfigError(
                f"{path} changed frozen length: expected {len(expected)}, found {len(actual)}"
            )
        return [
            _copy_in_frozen_order(value, expected_value, path=f"{path}[{index}]")
            for index, (value, expected_value) in enumerate(zip(actual, expected, strict=True))
        ]
    if actual != expected:
        raise FrozenConfigError(
            f"{path} changed frozen value: expected {expected!r}, found {actual!r}"
        )
    return actual


def validate_gate1_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate every frozen field and return one canonical, path-free copy.

    File loading retains the stricter YAML declaration-order check.  Runtime
    consumers may receive a JSON-decoded mapping whose insertion order changed,
    so this function checks the exact recursive key set, types, and values before
    restoring the one authoritative declaration order.
    """

    if type(config) is not dict:
        raise FrozenConfigError("config must be a plain mapping with exact frozen keys")
    allowed_keys = (tuple(_FROZEN_CONFIG), tuple(_FROZEN_CONFIG) + ("hgb_grid",))
    if tuple(config) not in allowed_keys and set(config) not in (
        set(_FROZEN_CONFIG),
        set(_FROZEN_CONFIG) | {"hgb_grid"},
    ):
        raise FrozenConfigError(
            f"config changed frozen keys: expected {tuple(_FROZEN_CONFIG)!r} "
            "with optional derived hgb_grid"
        )
    base_input = {key: config[key] for key in _FROZEN_CONFIG if key in config}
    canonical = _copy_in_frozen_order(base_input, _FROZEN_CONFIG, path="config")
    _validate_frozen(canonical, _FROZEN_CONFIG)
    parse_time_split_boundaries(canonical["time_split"])
    expanded = expand_hgb_grid(canonical["hgb"])
    if "hgb_grid" in config:
        declared_grid = _copy_in_frozen_order(config["hgb_grid"], expanded, path="config.hgb_grid")
        _validate_frozen(declared_grid, expanded, path="config.hgb_grid")
    canonical["hgb_grid"] = expanded
    return canonical


def config_sha256(path: str | Path) -> str:
    """Return SHA-256 over the config's exact bytes, including whitespace."""

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_gate1_config(path: str | Path) -> dict[str, Any]:
    """Load, strictly validate, and expand the frozen Gate 1 pilot config."""

    payload = _parse_yaml(Path(path).read_bytes())
    parse_time_split_boundaries(payload.get("time_split"))
    _validate_frozen(payload, _FROZEN_CONFIG)
    return validate_gate1_config(payload)
