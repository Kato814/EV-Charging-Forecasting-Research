"""Offline, aggregate-only power-semantics audit for JPL May 2019."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

DEFAULT_EVSE_VOLTAGE_V = 208.0
KW_RECONSTRUCTION_CANDIDATE = "KW_RECONSTRUCTION_CANDIDATE"
CURRENT_PROXY_ONLY = "CURRENT_PROXY_ONLY"
POWER_SEMANTICS_FAIL = "POWER_SEMANTICS_FAIL"


@dataclass(frozen=True)
class PinnedPowerEvidence:
    """Public provenance for the exact ACN-Sim network definition used by the audit."""

    repository: str
    commit: str
    source_path: str
    source_url: str
    source_sha256: str
    source_retrieved_utc: str
    license: str
    license_path: str
    license_url: str
    license_sha256: str
    license_retrieved_utc: str
    license_copyright: str
    default_evse_voltage_v: float
    line_to_line_network: bool
    line_to_line_definition: str
    pinned_evse_name_count: int
    evse_naming_summary: str
    topology_caveat: str
    static_mirror: str

    def public_dict(self) -> dict[str, Any]:
        """Return aggregate, identifier-free evidence suitable for publication."""

        return asdict(self)


PINNED_POWER_EVIDENCE = PinnedPowerEvidence(
    repository="https://github.com/zach401/acnportal",
    commit="14e723b11339e56ca3afd2bf4969f9e4bc8c2623",
    source_path="acnportal/acnsim/network/sites/jpl_acn.py",
    source_url=(
        "https://raw.githubusercontent.com/zach401/acnportal/"
        "14e723b11339e56ca3afd2bf4969f9e4bc8c2623/"
        "acnportal/acnsim/network/sites/jpl_acn.py"
    ),
    source_sha256="0a8c9de3c972995dd323e3c2a976bff8511b795553f3926b60251b5418d6140d",
    source_retrieved_utc="2026-09-01T06:31:52.7278373Z",
    license="BSD-3-Clause",
    license_path="LICENSE.txt",
    license_url=(
        "https://raw.githubusercontent.com/zach401/acnportal/"
        "14e723b11339e56ca3afd2bf4969f9e4bc8c2623/LICENSE.txt"
    ),
    license_sha256="34256c87b252573d30203b02ee12407bfbf2169684adfef3a3ea4f9bb9e0db5f",
    license_retrieved_utc="2026-09-01T06:31:55.3086889Z",
    license_copyright="Copyright 2019 California Institute of Technology",
    default_evse_voltage_v=DEFAULT_EVSE_VOLTAGE_V,
    line_to_line_network=True,
    line_to_line_definition=(
        "EVSEs are assigned to AB/BC/CA branches at 30/-90/150 degrees; "
        "phase currents are Ia=Iab-Ica, Ib=Ibc-Iab, Ic=Ica-Ibc."
    ),
    pinned_evse_name_count=52,
    evse_naming_summary=(
        "52 AG-prefixed, floor-coded, two-digit EVSE/space names: "
        "14 first-floor, 19 third-floor, 19 fourth-floor."
    ),
    topology_caveat=(
        "ACN-Sim network-model defaults are audit evidence, not proof of per-session "
        "measured voltage or active power."
    ),
    static_mirror="NOT_USED",
)


@dataclass(frozen=True)
class PowerDecisionInputs:
    """Aggregate-only inputs to the closed power-semantics decision rule."""

    mapping_rate: float
    primary_audit_coverage: float
    eligible_session_count: int
    retained_session_count: int
    median_absolute_percentage_error: float
    p90_absolute_percentage_error: float
    monthly_relative_energy_error: float
    statistics_finite: bool

    @property
    def retained_rate(self) -> float | None:
        if self.eligible_session_count <= 0:
            return None
        return self.retained_session_count / self.eligible_session_count


def classify_power_semantics(inputs: PowerDecisionInputs) -> str:
    """Apply the frozen candidate, current-only, and severe-failure rules."""

    numeric_statistics = (
        inputs.mapping_rate,
        inputs.primary_audit_coverage,
        inputs.median_absolute_percentage_error,
        inputs.p90_absolute_percentage_error,
        inputs.monthly_relative_energy_error,
    )
    retained_rate = inputs.retained_rate
    statistics_finite = (
        inputs.statistics_finite
        and retained_rate is not None
        and all(math.isfinite(value) for value in numeric_statistics)
        and math.isfinite(retained_rate)
    )
    if (
        inputs.mapping_rate < 0.95
        or not statistics_finite
        or abs(inputs.monthly_relative_energy_error) > 0.50
    ):
        return POWER_SEMANTICS_FAIL
    if (
        inputs.mapping_rate == 1.0
        and inputs.primary_audit_coverage >= 0.90
        and retained_rate >= 0.90
        and inputs.median_absolute_percentage_error <= 0.20
        and inputs.p90_absolute_percentage_error <= 0.40
        and abs(inputs.monthly_relative_energy_error) <= 0.10
    ):
        return KW_RECONSTRUCTION_CANDIDATE
    return CURRENT_PROXY_ONLY


_OFFLINE_ONLY_KEY_TOKENS = (
    "kwhdelivered",
    "effectivevoltage",
    "veff",
    "e208",
)


def _normalized_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def assert_online_feature_payload_safe(payload: object) -> None:
    """Reject final-energy and power-audit values from an online feature payload."""

    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if not isinstance(key, str):
                raise TypeError("online feature keys must be strings")
            normalized = _normalized_key(key)
            if any(token in normalized for token in _OFFLINE_ONLY_KEY_TOKENS):
                raise ValueError(f"offline-only power audit field is not an online feature: {key}")
            assert_online_feature_payload_safe(value)
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        for value in payload:
            assert_online_feature_payload_safe(value)


def ampere_hours_from_ampere_seconds(ampere_seconds: float) -> float:
    """Convert a time integral of current from ampere-seconds to ampere-hours."""

    return float(ampere_seconds) / 3600.0


def energy_at_208v_kwh(ampere_hours: float) -> float:
    """Return the offline 208 V energy candidate in kWh."""

    return float(ampere_hours) * DEFAULT_EVSE_VOLTAGE_V / 1000.0


def effective_voltage_v(ampere_hours: float, kwh_delivered: float) -> float | None:
    """Return audit-only effective voltage, or ``None`` when Ah is non-positive."""

    if ampere_hours <= 0:
        return None
    return float(kwh_delivered) * 1000.0 / float(ampere_hours)


@dataclass(frozen=True, repr=False)
class PowerAuditSession:
    """Private per-session inputs consumed only by the offline audit."""

    space_id: str | None
    ampere_hours: float | None
    kwh_delivered: float | None
    current_coverage: float | None
    is_weekend: bool
    retained: bool = True


@dataclass(frozen=True)
class _CohortThreshold:
    minimum_kwh_delivered: float
    minimum_current_coverage: float


@dataclass(frozen=True, repr=False)
class _AuditRow:
    space_id: str | None
    is_weekend: bool
    actual_kwh: float
    e208_kwh: float
    effective_voltage_v: float
    absolute_error_kwh: float
    absolute_percentage_error: float


_PINNED_JPL_SPACE_IDS = frozenset(
    [*(f"AG-1F{number:02d}" for number in range(1, 15))]
    + [*(f"AG-3F{number:02d}" for number in range(15, 34))]
    + [*(f"AG-4F{number:02d}" for number in range(34, 53))]
)
_PRIMARY_COHORT = _CohortThreshold(0.5, 0.90)
_SENSITIVITY_COHORTS = tuple(
    threshold
    for threshold in (
        _CohortThreshold(energy, coverage)
        for energy in (0.1, 0.5, 1.0)
        for coverage in (0.80, 0.90, 0.95)
    )
    if threshold != _PRIMARY_COHORT
)


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _safe_rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return float(ordered[lower_index])
    weight = position - lower_index
    return float(ordered[lower_index] * (1.0 - weight) + ordered[upper_index] * weight)


def _distribution(values: Sequence[float]) -> dict[str, int | float | None]:
    p25 = _quantile(values, 0.25)
    p75 = _quantile(values, 0.75)
    return {
        "count": len(values),
        "median": _quantile(values, 0.50),
        "iqr": None if p25 is None or p75 is None else p75 - p25,
        "p05": _quantile(values, 0.05),
        "p95": _quantile(values, 0.95),
    }


def _aggregate_energy(rows: Sequence[_AuditRow]) -> dict[str, int | float | None]:
    actual_kwh = sum(row.actual_kwh for row in rows)
    e208_kwh = sum(row.e208_kwh for row in rows)
    error_kwh = e208_kwh - actual_kwh
    relative_error = error_kwh / actual_kwh if actual_kwh > 0 else None
    return {
        "session_count": len(rows),
        "observed_kwh": actual_kwh,
        "e208_kwh": e208_kwh,
        "error_kwh": error_kwh,
        "relative_error": relative_error,
        "absolute_relative_error": (abs(relative_error) if relative_error is not None else None),
    }


def _aggregate_by_evse(rows: Sequence[_AuditRow]) -> dict[str, Any]:
    grouped: dict[str, list[_AuditRow]] = {}
    for row in rows:
        if row.space_id in _PINNED_JPL_SPACE_IDS:
            grouped.setdefault(str(row.space_id), []).append(row)
    relative_errors: list[float] = []
    absolute_relative_errors: list[float] = []
    session_counts: list[float] = []
    groups: list[dict[str, Any]] = []
    ordered_pinned_ids = sorted(_PINNED_JPL_SPACE_IDS)
    pinned_indexes = {space_id: index + 1 for index, space_id in enumerate(ordered_pinned_ids)}
    for space_id in sorted(grouped):
        group = grouped[space_id]
        aggregate = _aggregate_energy(group)
        relative_error = aggregate["relative_error"]
        if isinstance(relative_error, float) and math.isfinite(relative_error):
            relative_errors.append(relative_error)
            absolute_relative_errors.append(abs(relative_error))
        session_counts.append(float(len(group)))
        groups.append(
            {
                "anonymous_evse_index": pinned_indexes[space_id],
                "session_count": len(group),
                "observed_kwh": aggregate["observed_kwh"],
                "e208_kwh": aggregate["e208_kwh"],
                "relative_error": aggregate["relative_error"],
                "median_absolute_percentage_error": _quantile(
                    [row.absolute_percentage_error for row in group], 0.50
                ),
            }
        )
    return {
        "evse_count": len(grouped),
        "groups": groups,
        "session_count": _distribution(session_counts),
        "relative_error": _distribution(relative_errors),
        "absolute_relative_error": _distribution(absolute_relative_errors),
    }


def _energy_eligible(session: PowerAuditSession, threshold: _CohortThreshold) -> bool:
    return (
        _finite_number(session.kwh_delivered)
        and float(session.kwh_delivered) >= threshold.minimum_kwh_delivered
    )


def _coverage_qualified(session: PowerAuditSession, threshold: _CohortThreshold) -> bool:
    return (
        _energy_eligible(session, threshold)
        and _finite_number(session.current_coverage)
        and 0.0 <= float(session.current_coverage) <= 1.0
        and float(session.current_coverage) >= threshold.minimum_current_coverage
    )


def _audit_row(session: PowerAuditSession) -> _AuditRow | None:
    if (
        not session.retained
        or not _finite_number(session.ampere_hours)
        or float(session.ampere_hours) <= 0
        or not _finite_number(session.kwh_delivered)
        or float(session.kwh_delivered) <= 0
    ):
        return None
    ampere_hours = float(session.ampere_hours)
    actual_kwh = float(session.kwh_delivered)
    e208_kwh = energy_at_208v_kwh(ampere_hours)
    voltage = effective_voltage_v(ampere_hours, actual_kwh)
    if voltage is None or not math.isfinite(voltage):
        return None
    absolute_error = abs(e208_kwh - actual_kwh)
    return _AuditRow(
        space_id=session.space_id,
        is_weekend=session.is_weekend,
        actual_kwh=actual_kwh,
        e208_kwh=e208_kwh,
        effective_voltage_v=voltage,
        absolute_error_kwh=absolute_error,
        absolute_percentage_error=absolute_error / actual_kwh,
    )


def _cohort_report(
    sessions: Sequence[PowerAuditSession], threshold: _CohortThreshold
) -> dict[str, Any]:
    eligible = [session for session in sessions if _energy_eligible(session, threshold)]
    coverage_qualified = [
        session for session in eligible if _coverage_qualified(session, threshold)
    ]
    rows = [row for session in coverage_qualified if (row := _audit_row(session)) is not None]
    voltages = [row.effective_voltage_v for row in rows]
    absolute_errors = [row.absolute_error_kwh for row in rows]
    absolute_percentage_errors = [row.absolute_percentage_error for row in rows]
    weekday = [row for row in rows if not row.is_weekend]
    weekend = [row for row in rows if row.is_weekend]
    return {
        "thresholds": {
            "minimum_kwh_delivered": threshold.minimum_kwh_delivered,
            "minimum_current_coverage": threshold.minimum_current_coverage,
        },
        "input_session_count": len(sessions),
        "eligible_session_count": len(eligible),
        "coverage_qualified_session_count": len(coverage_qualified),
        "retained_session_count": len(rows),
        "audit_coverage": _safe_rate(len(coverage_qualified), len(eligible)),
        "retained_rate": _safe_rate(len(rows), len(eligible)),
        "effective_voltage_v": _distribution(voltages),
        "e208_error": {
            "count": len(rows),
            "mae_kwh": sum(absolute_errors) / len(absolute_errors) if absolute_errors else None,
            "median_absolute_percentage_error": _quantile(absolute_percentage_errors, 0.50),
            "p90_absolute_percentage_error": _quantile(absolute_percentage_errors, 0.90),
        },
        "aggregate_energy": _aggregate_energy(rows),
        "weekday_aggregate_energy": _aggregate_energy(weekday),
        "weekend_aggregate_energy": _aggregate_energy(weekend),
        "aggregate_by_evse_distribution": _aggregate_by_evse(rows),
    }


def _mapping_report(sessions: Sequence[PowerAuditSession]) -> dict[str, Any]:
    observed = {
        session.space_id
        for session in sessions
        if isinstance(session.space_id, str) and session.space_id
    }
    mapped = {value for value in observed if value in _PINNED_JPL_SPACE_IDS}
    unmapped = observed - mapped
    records_with_space = sum(
        isinstance(session.space_id, str) and bool(session.space_id) for session in sessions
    )
    mapped_record_count = sum(session.space_id in _PINNED_JPL_SPACE_IDS for session in sessions)
    mapping_rate = _safe_rate(mapped_record_count, len(sessions))
    return {
        "raw_record_count": len(sessions),
        "records_with_space": records_with_space,
        "mapped_record_count": mapped_record_count,
        "unmapped_record_count": len(sessions) - mapped_record_count,
        "mapping_rate": 0.0 if mapping_rate is None else mapping_rate,
        "observed_unique_space_count": len(observed),
        "mapped_unique_space_count": len(mapped),
        "unmapped_unique_space_count": len(unmapped),
        "pinned_source_space_count": len(_PINNED_JPL_SPACE_IDS),
        "complete_for_candidate": bool(sessions) and mapped_record_count == len(sessions),
    }


def _required_statistics_finite(primary: Mapping[str, Any]) -> bool:
    voltage = primary["effective_voltage_v"]
    error = primary["e208_error"]
    aggregate = primary["aggregate_energy"]
    required = (
        voltage["median"],
        voltage["iqr"],
        voltage["p05"],
        voltage["p95"],
        error["mae_kwh"],
        error["median_absolute_percentage_error"],
        error["p90_absolute_percentage_error"],
        aggregate["relative_error"],
    )
    return all(_finite_number(value) for value in required)


def _decision_report(status: str, inputs: PowerDecisionInputs) -> dict[str, Any]:
    retained_rate = inputs.retained_rate
    return {
        "status": status,
        "threshold_interpretation": ("predeclared_data_preparation_gate_not_scientific_validation"),
        "thresholds": {
            "mapping_rate_candidate": 1.0,
            "mapping_rate_fail_below": 0.95,
            "primary_audit_coverage_minimum": 0.90,
            "retained_rate_minimum": 0.90,
            "median_absolute_percentage_error_maximum": 0.20,
            "p90_absolute_percentage_error_maximum": 0.40,
            "absolute_monthly_relative_energy_error_candidate_maximum": 0.10,
            "absolute_monthly_relative_energy_error_fail_above": 0.50,
        },
        "conditions": {
            "mapping_complete": inputs.mapping_rate == 1.0,
            "mapping_not_severe": inputs.mapping_rate >= 0.95,
            "primary_audit_coverage_pass": inputs.primary_audit_coverage >= 0.90,
            "retained_rate_pass": retained_rate is not None and retained_rate >= 0.90,
            "median_absolute_percentage_error_pass": (
                inputs.median_absolute_percentage_error <= 0.20
            ),
            "p90_absolute_percentage_error_pass": (inputs.p90_absolute_percentage_error <= 0.40),
            "monthly_relative_energy_error_candidate_pass": (
                abs(inputs.monthly_relative_energy_error) <= 0.10
            ),
            "monthly_relative_energy_error_not_severe": (
                abs(inputs.monthly_relative_energy_error) <= 0.50
            ),
            "statistics_finite": inputs.statistics_finite,
        },
        "reconstructed_kw_column_authorized": False,
        "main_control_approval_required": True,
        "direct_measured_kw_available": False,
        "current_proxy_available": True,
    }


def audit_power_semantics(
    sessions: Iterable[PowerAuditSession],
) -> dict[str, Any]:
    """Return an aggregate-only offline audit without exposing spaces or sessions."""

    ordered_sessions = list(sessions)
    mapping = _mapping_report(ordered_sessions)
    primary = _cohort_report(ordered_sessions, _PRIMARY_COHORT)
    sensitivity = [
        _cohort_report(ordered_sessions, threshold) for threshold in _SENSITIVITY_COHORTS
    ]
    error = primary["e208_error"]
    monthly = primary["aggregate_energy"]
    statistics_finite = _required_statistics_finite(primary)

    def finite_or_nan(value: object) -> float:
        return float(value) if _finite_number(value) else math.nan

    inputs = PowerDecisionInputs(
        mapping_rate=float(mapping["mapping_rate"]),
        primary_audit_coverage=finite_or_nan(primary["audit_coverage"]),
        eligible_session_count=int(primary["eligible_session_count"]),
        retained_session_count=int(primary["retained_session_count"]),
        median_absolute_percentage_error=finite_or_nan(error["median_absolute_percentage_error"]),
        p90_absolute_percentage_error=finite_or_nan(error["p90_absolute_percentage_error"]),
        monthly_relative_energy_error=finite_or_nan(monthly["relative_error"]),
        statistics_finite=statistics_finite,
    )
    status = classify_power_semantics(inputs)
    return {
        "schema_version": "acn-jpl-power-semantics-audit/v1",
        "status": status,
        "evidence": PINNED_POWER_EVIDENCE.public_dict(),
        "static_mirror": "NOT_USED",
        "mapping": mapping,
        "cohorts": {"primary": primary, "sensitivity": sensitivity},
        "decision": _decision_report(status, inputs),
        "online_feature_policy": {
            "status": "ENFORCED",
            "final_kwh_delivered_allowed": False,
            "effective_voltage_allowed": False,
            "e208_allowed": False,
            "reconstructed_kw_column_authorized": False,
        },
        "privacy": {
            "aggregate_only": True,
            "identifiers_emitted": False,
            "space_names_emitted": False,
            "token_emitted": False,
        },
    }
