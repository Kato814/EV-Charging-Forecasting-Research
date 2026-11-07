"""Strict synthetic-only records and explicit power/energy conversions.

Timestamp checks validate supplied metadata, not its truthfulness. These helpers
neither establish real kW semantics nor authorize access to research data.
"""

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from numbers import Real


class ContractError(ValueError):
    """An input violates the synthetic dispatch contract."""


@dataclass(frozen=True)
class TimestampedPower:
    value: float
    unit: str
    available_at_utc: datetime


@dataclass(frozen=True)
class SyntheticForecast:
    kind: str
    generated_at_utc: datetime
    unit: str
    values: tuple[tuple[float, ...], ...]
    weights: tuple[float, ...]


@dataclass(frozen=True)
class SyntheticDispatchInput:
    schema_version: str
    issue_time_utc: datetime
    step_seconds: int
    station_power: TimestampedPower
    forecast: SyntheticForecast


def _keys(value, expected, name):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ContractError(f"{name} must contain exactly: {', '.join(expected)}")
    return value


def _number(value, name, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ContractError(f"{name} must be a finite number, not bool")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ContractError(f"{name} must be finite") from exc
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise ContractError(f"{name} must be finite" + (" and nonnegative" if nonnegative else ""))
    return result


def _kw(unit):
    if unit != "kW":
        raise ContractError("unit must be explicitly kW; A and Ah cannot be inferred as power")


def _utc(value, name):
    # This schema uses ISO calendar timestamps with explicit UTC and seconds.
    pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)"
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise ContractError(f"{name} must be an ISO timestamp with UTC Z or +00:00")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise ContractError(f"{name} is an invalid timestamp") from exc


def validate_synthetic_dispatch_input(payload, horizon_steps=16):
    """Return immutable records; weight sum tolerance is 1e-9 (absolute).

    Missing observations are rejected, while an explicit observed zero is valid.
    The fixed interval is 900 seconds; horizon_steps must be a positive integer.
    """
    if type(horizon_steps) is not int or horizon_steps < 1:
        raise ContractError("horizon_steps must be a positive integer")
    _keys(payload, ("schema_version", "issue_time_utc", "step_seconds", "observations",
                    "forecast"), "payload")
    if payload["schema_version"] != "synthetic-dispatch/v1":
        raise ContractError("schema_version must be synthetic-dispatch/v1")
    if type(payload["step_seconds"]) is not int or payload["step_seconds"] != 900:
        raise ContractError("step_seconds must be the integer 900")
    issue = _utc(payload["issue_time_utc"], "issue_time_utc")
    observations = _keys(payload["observations"], ("station_power",), "observations")
    power = _keys(observations["station_power"], ("value", "unit", "available_at_utc"),
                  "station_power")
    _kw(power["unit"])
    observed = _utc(power["available_at_utc"], "available_at_utc")
    if observed > issue:
        raise ContractError("station_power is unavailable at issue_time_utc")
    station_power = TimestampedPower(_number(power["value"], "station_power.value", True),
                                     "kW", observed)
    forecast = _keys(payload["forecast"], ("kind", "generated_at_utc", "unit", "values",
                                          "weights"), "forecast")
    if forecast["kind"] != "synthetic_forecast":
        raise ContractError("forecast.kind must be synthetic_forecast")
    _kw(forecast["unit"])
    generated = _utc(forecast["generated_at_utc"], "generated_at_utc")
    if generated > issue:
        raise ContractError("forecast was generated after issue_time_utc")
    values = forecast["values"]
    if not isinstance(values, list) or not values:
        raise ContractError("forecast.values must be a nonempty list of scenarios")
    normalized = []
    for index, scenario in enumerate(values):
        if not isinstance(scenario, list) or len(scenario) != horizon_steps:
            raise ContractError(f"scenario {index} must have {horizon_steps} interval values")
        normalized.append(tuple(_number(v, f"scenario {index}", True) for v in scenario))
    weights = forecast["weights"]
    if not isinstance(weights, list) or len(weights) != len(values):
        raise ContractError("forecast.weights must match the scenario count")
    weights = tuple(_number(v, "forecast.weights", True) for v in weights)
    if not math.isclose(sum(weights), 1.0, rel_tol=0, abs_tol=1e-9):
        raise ContractError("forecast.weights must sum to 1")
    return SyntheticDispatchInput(
        "synthetic-dispatch/v1", issue, 900, station_power,
        SyntheticForecast("synthetic_forecast", generated, "kW", tuple(normalized), weights),
    )


def kw_to_mw(value, unit="kW"):
    """Convert explicit finite kW to MW; do not infer power from current/charge."""
    _kw(unit)
    return _number(value, "power") / 1000.0


def interval_energy_kwh(values, step_seconds=900, unit="kW"):
    """Integrate a nonempty sequence of interval-average kW with explicit seconds.

    Signed power is supported by this arithmetic helper; the dispatch validator
    separately requires nonnegative charging demand.
    """
    _kw(unit)
    seconds = _number(step_seconds, "step_seconds")
    if seconds <= 0:
        raise ContractError("step_seconds must be positive")
    if not isinstance(values, (list, tuple)) or not values:
        raise ContractError("values must be a nonempty list or tuple of interval-average power")
    try:
        energy = math.fsum(_number(value, "power") * (seconds / 3600.0) for value in values)
    except (ValueError, OverflowError) as exc:
        raise ContractError("integrated energy must be finite") from exc
    return _number(energy, "integrated energy")
