"""Explicit unit and identity guards for hand-authored controller simulations.

Evidence labels validate declarations, not their truth. No helper admits measured
power, calibrates meters, infers a missing device mapping, or changes a forecast.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from .controller_common import AdmissionError, exact_keys, identifier, number, utc


@dataclass(frozen=True)
class DeviceMapping:
    site_id: str
    cluster_id: str
    station_id: str
    space_id: str
    topology_label: str
    node_id: str
    valid_from_utc: datetime
    valid_to_utc: datetime | None
    available_at_utc: datetime
    evidence_id: str
    mapping_basis: str


@dataclass(frozen=True)
class PowerProxy:
    value: float
    evidence_id: str
    unit: str = "kW"
    power_basis: str = "assumed_proxy"


@dataclass(frozen=True)
class IntervalCurrentMeans:
    fixed_window_mean_a: float
    covered_time_mean_a: float | None
    coverage: float
    complete: bool


_DEVICE_KEY = ("site_id", "cluster_id", "station_id", "space_id")
_MAPPING_KEYS = (
    *_DEVICE_KEY,
    "topology_label",
    "node_id",
    "valid_from_utc",
    "valid_to_utc",
    "available_at_utc",
    "evidence_id",
    "mapping_basis",
)


def resolve_device_mapping(mappings, *, site_id, cluster_id, station_id, space_id, issue_time_utc):
    """Select one declared synthetic mapping effective and available at issue."""
    issue = utc(issue_time_utc, "issue_time_utc")
    key = tuple(
        identifier(value, label)
        for value, label in zip((site_id, cluster_id, station_id, space_id), _DEVICE_KEY)
    )
    if not isinstance(mappings, (list, tuple)):
        raise AdmissionError("INVALID_DEVICE_MAPPING", "mappings must be a list or tuple")
    eligible = []
    for value in mappings:
        # Determine eligibility from explicit clocks before reading identity content.
        clocks = ("valid_from_utc", "valid_to_utc", "available_at_utc")
        if not isinstance(value, dict) or any(clock not in value for clock in clocks):
            raise AdmissionError(
                "INVALID_SCHEMA", "mapping requires all validity/availability clocks"
            )
        start = utc(value["valid_from_utc"], "valid_from_utc")
        end = None if value["valid_to_utc"] is None else utc(value["valid_to_utc"], "valid_to_utc")
        available = utc(value["available_at_utc"], "available_at_utc")
        if end is not None and end <= start:
            raise AdmissionError(
                "INVALID_DEVICE_MAPPING", "mapping validity interval must be positive"
            )
        if available > issue or start > issue or (end is not None and issue >= end):
            continue
        exact_keys(value, _MAPPING_KEYS, "mapping")
        fields = {
            field: identifier(value[field], field)
            for field in (*_DEVICE_KEY, "topology_label", "node_id", "evidence_id")
        }
        if value["mapping_basis"] != "synthetic_assumption":
            raise AdmissionError(
                "INVALID_DEVICE_MAPPING", "mapping basis must be synthetic_assumption"
            )
        if tuple(fields[field] for field in _DEVICE_KEY) == key:
            eligible.append(
                DeviceMapping(
                    **fields,
                    valid_from_utc=start,
                    valid_to_utc=end,
                    available_at_utc=available,
                    mapping_basis="synthetic_assumption",
                )
            )
    if not eligible:
        raise AdmissionError(
            "UNKNOWN_DEVICE_MAPPING", "no effective mapping available for exact key"
        )
    if len(eligible) != 1:
        raise AdmissionError(
            "AMBIGUOUS_DEVICE_MAPPING", "multiple effective mappings for exact key"
        )
    return eligible[0]


def current_to_power_proxy(current_a, *, profile, requested_basis, assumptions):
    """Return I * V * PF / 1000 only as a single-phase assumed simulation proxy."""
    if profile != "assumed_power_simulation" or requested_basis != "assumed_proxy":
        raise AdmissionError(
            "POWER_BASIS_MISMATCH", "only explicit assumed power simulation is admitted"
        )
    current = number(current_a, "current_a")
    try:
        exact_keys(
            assumptions,
            ("voltage_v", "power_factor", "pf_basis", "connection", "evidence_id"),
            "power assumptions",
        )
        voltage = number(assumptions["voltage_v"], "voltage_v")
        factor = number(assumptions["power_factor"], "power_factor")
        evidence = identifier(assumptions["evidence_id"], "evidence_id")
        if (
            voltage <= 0
            or factor > 1
            or assumptions["pf_basis"] != "explicit_assumption"
            or assumptions["connection"] != "single_phase_line_to_line"
        ):
            raise AdmissionError(
                "INVALID_POWER_ASSUMPTION", "invalid voltage, PF basis or connection"
            )
        value = number(current * voltage * factor / 1000, "assumed power proxy")
    except AdmissionError as exc:
        raise AdmissionError("INVALID_POWER_ASSUMPTION", str(exc)) from exc
    return PowerProxy(value, evidence)


def interval_current_means(ampere_seconds, covered_seconds, interval_seconds=900):
    """Keep the fixed-window statistic distinct from the covered-time statistic."""
    try:
        area = number(ampere_seconds, "ampere_seconds")
        covered = number(covered_seconds, "covered_seconds")
        interval = number(interval_seconds, "interval_seconds")
        if interval <= 0 or covered > interval or (covered == 0 and area != 0):
            raise AdmissionError("INVALID_INTERVAL", "inconsistent interval area or coverage")
        fixed = number(area / interval, "fixed_window_mean_a")
        observed = None if covered == 0 else number(area / covered, "covered_time_mean_a")
        return IntervalCurrentMeans(fixed, observed, covered / interval, covered == interval)
    except AdmissionError as exc:
        raise AdmissionError("INVALID_INTERVAL", str(exc)) from exc


def _require_kwh(unit):
    if unit != "kWh":
        raise AdmissionError("UNIT_MISMATCH", "energy must be explicitly kWh")


def energy_increment(previous, current, *, previous_epoch, current_epoch, unit="kWh"):
    """Difference of one monotone energy counter; resets cannot imply V2G."""
    _require_kwh(unit)
    before = number(previous, "previous")
    after = number(current, "current")
    try:
        identifier(previous_epoch, "previous_epoch")
        identifier(current_epoch, "current_epoch")
    except AdmissionError as exc:
        raise AdmissionError("ENERGY_COUNTER_BOUNDARY", str(exc)) from exc
    if previous_epoch != current_epoch:
        raise AdmissionError("ENERGY_COUNTER_BOUNDARY", "energy counter epoch changed")
    if after < before:
        raise AdmissionError("ENERGY_COUNTER_RESET", "cumulative energy decreased within an epoch")
    return after - before


def remaining_energy_kwh(
    requested, delivered_so_far, *, request_basis, unit="kWh", delivered_at_revision=None
):
    """Resolve total or additional declarations; no basis is inferred."""
    _require_kwh(unit)
    request = number(requested, "requested")
    delivered = number(delivered_so_far, "delivered_so_far")
    if request_basis == "total":
        return max(request - delivered, 0.0)
    if request_basis != "additional" or delivered_at_revision is None:
        raise AdmissionError(
            "UNKNOWN_REQUEST_BASIS", "an explicit basis and revision baseline are required"
        )
    baseline = number(delivered_at_revision, "delivered_at_revision")
    if baseline > delivered:
        raise AdmissionError("INVALID_NUMBER", "revision baseline exceeds delivered energy")
    # Subtraction first avoids overflowing baseline + request for valid inputs.
    return max(request - (delivered - baseline), 0.0)


def validate_interval_support(intervals, issue_time_utc, *, horizon_steps=16, step_seconds=900):
    """Validate temporal support only, not forecast probabilities or correctness."""
    try:
        if (
            type(horizon_steps) is not int
            or horizon_steps <= 0
            or type(step_seconds) is not int
            or step_seconds <= 0
        ):
            raise AdmissionError(
                "INSUFFICIENT_FORECAST_SUPPORT", "positive integer horizon/step required"
            )
        issue = utc(issue_time_utc, "issue_time_utc")
        if not isinstance(intervals, list) or len(intervals) != horizon_steps:
            raise AdmissionError(
                "INSUFFICIENT_FORECAST_SUPPORT", "one interval per horizon step required"
            )
        step = timedelta(seconds=step_seconds)
        result = []
        for index, value in enumerate(intervals):
            exact_keys(value, ("start_utc", "end_utc"), "interval")
            start = utc(value["start_utc"], "start_utc")
            end = utc(value["end_utc"], "end_utc")
            if start != issue + index * step or end != issue + (index + 1) * step:
                raise AdmissionError(
                    "INSUFFICIENT_FORECAST_SUPPORT", "intervals must be contiguous from issue"
                )
            result.append((start, end))
        return tuple(result)
    except (AdmissionError, OverflowError) as exc:
        raise AdmissionError("INSUFFICIENT_FORECAST_SUPPORT", str(exc)) from exc


def require_same_power_boundary(left, right):
    """Compare declared measurement scope; this does not establish calibration."""
    try:
        normalized = []
        for value in (left, right):
            exact_keys(value, ("boundary_id", "components"), "power boundary")
            boundary = identifier(value["boundary_id"], "boundary_id")
            components = value["components"]
            if not isinstance(components, list) or not components:
                raise AdmissionError(
                    "MEASUREMENT_BOUNDARY_MISMATCH", "components must be a nonempty list"
                )
            names = [identifier(component, "component") for component in components]
            if len(set(names)) != len(names):
                raise AdmissionError("MEASUREMENT_BOUNDARY_MISMATCH", "components must be unique")
            normalized.append((boundary, frozenset(names)))
        if normalized[0] != normalized[1]:
            raise AdmissionError(
                "MEASUREMENT_BOUNDARY_MISMATCH", "power boundaries or components differ"
            )
    except AdmissionError as exc:
        raise AdmissionError("MEASUREMENT_BOUNDARY_MISMATCH", str(exc)) from exc
