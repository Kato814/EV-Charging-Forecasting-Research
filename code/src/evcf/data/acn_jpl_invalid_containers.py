"""Retain verified session structure when a current or pilot container is invalid.

Each unavailable branch has no observations and keeps the complete connected
duration as its coverage denominator.  Container-shape decisions are offline
cleaning decisions; no anomaly reason is added to prediction features.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from .acn_jpl_cleaning import (
    CleaningPolicy,
    CleanSeries,
    CleanSession,
    _audit_digest,
    clean_session,
    parse_timestamp_utc_s,
)

_VALUE_KEYS = {"chargingCurrent": "current", "pilotSignal": "pilot"}
_STRUCTURAL_FIELDS = ("siteID", "stationID", "spaceID", "clusterID", "timezone")


class StructuralMetadataError(ValueError):
    """A safe reason code for metadata that cannot authorize retained structure."""


def series_container_valid(record: Mapping[str, Any], field_name: str) -> bool:
    """Use the frozen mapping/list/equal-length container contract per branch."""

    if field_name not in _VALUE_KEYS:
        raise ValueError("INVALID_SERIES_FIELD")
    series = record.get(field_name)
    if not isinstance(series, Mapping):
        return False
    timestamps = series.get("timestamps")
    values = series.get(_VALUE_KEYS[field_name])
    return (
        isinstance(timestamps, list)
        and isinstance(values, list)
        and len(timestamps) == len(values)
    )


def verify_structural_metadata(
    record: Mapping[str, Any], expected_metadata: object
) -> None:
    """Fail with aggregate-safe codes unless official identity and bounds agree.

    Both sources must contain aware, parseable, positive-duration bounds at the
    cleaner's whole-second precision.  Optional structural fields must retain
    both their presence and values.  Retrospective energy and request revisions
    retain their existing cleaning semantics and do not authorize trajectories.
    """

    if not isinstance(record, Mapping) or not isinstance(expected_metadata, Mapping):
        raise StructuralMetadataError("STRUCTURAL_METADATA_MISSING")
    for field_name in ("_id", "sessionID"):
        actual = record.get(field_name)
        expected = expected_metadata.get(field_name)
        if (
            not isinstance(actual, str)
            or not actual.strip()
            or not isinstance(expected, str)
            or not expected.strip()
        ):
            raise StructuralMetadataError("STRUCTURAL_METADATA_IDENTITY_INVALID")
        if actual != expected:
            raise StructuralMetadataError("STRUCTURAL_METADATA_IDENTITY_MISMATCH")

    try:
        connection = parse_timestamp_utc_s(record.get("connectionTime"))
        disconnect = parse_timestamp_utc_s(record.get("disconnectTime"))
        expected_connection = parse_timestamp_utc_s(expected_metadata.get("connectionTime"))
        expected_disconnect = parse_timestamp_utc_s(expected_metadata.get("disconnectTime"))
    except (TypeError, ValueError, OverflowError, OSError):
        raise StructuralMetadataError("STRUCTURAL_METADATA_BOUNDS_INVALID") from None
    if disconnect <= connection or expected_disconnect <= expected_connection:
        raise StructuralMetadataError("STRUCTURAL_METADATA_BOUNDS_INVALID")
    if (connection, disconnect) != (expected_connection, expected_disconnect):
        raise StructuralMetadataError("STRUCTURAL_METADATA_BOUNDS_MISMATCH")

    for field_name in _STRUCTURAL_FIELDS:
        if (field_name in record) != (field_name in expected_metadata) or (
            record.get(field_name) != expected_metadata.get(field_name)
            or type(record.get(field_name)) is not type(expected_metadata.get(field_name))
        ):
            raise StructuralMetadataError("STRUCTURAL_METADATA_FIELDS_MISMATCH")


def valid_series_record_for_sampling(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a fresh record mapping that masks only invalid series containers.

    Valid branches retain their original arrays and raw order.  Callers still
    exclude independently classified trajectory-quarantine records before using
    this projection for mode derivation.
    """

    projected = dict(record)
    for field_name, value_name in _VALUE_KEYS.items():
        if not series_container_valid(record, field_name):
            projected[field_name] = {"timestamps": [], value_name: []}
    return projected


def _retain_invalid_container_audit(
    cleaned: CleanSeries, record: Mapping[str, Any], field_name: str
) -> CleanSeries:
    """Hash malformed raw evidence without asserting timestamp/value pairings.

    Available lists use the unchanged list digest convention.  Non-list members
    are hashed as tagged original values.  ``raw_pairs_sha256`` hashes a tagged
    original container for invalid branches: no zip, padding, or raw pairs are
    invented.  ``raw_samples`` counts available raw value-list entries only;
    point-level error counters remain zero because no pairs were evaluated.
    """

    container = record.get(field_name)
    values = container.get(_VALUE_KEYS[field_name]) if isinstance(container, Mapping) else None

    def component_digest(key: str) -> str:
        value = container.get(key) if isinstance(container, Mapping) else None
        if isinstance(value, list):
            return _audit_digest(value)
        return _audit_digest([
            {
                "invalid_component": value,
                "component_present": isinstance(container, Mapping) and key in container,
            }
        ])

    return replace(
        cleaned,
        audit=replace(
            cleaned.audit,
            raw_samples=len(values) if isinstance(values, list) else 0,
            raw_order_sha256=component_digest("timestamps"),
            raw_values_sha256=component_digest(_VALUE_KEYS[field_name]),
            raw_pairs_sha256=_audit_digest([
                {"invalid_container": container, "field_present": field_name in record}
            ]),
        ),
    )


def clean_branchwise_session(
    record: Mapping[str, Any],
    *,
    expected_metadata: object,
    session_index: int,
    policy: CleaningPolicy,
) -> CleanSession:
    """Clean valid branches unchanged and retain invalid ones as unobserved."""

    verify_structural_metadata(record, expected_metadata)
    projected = valid_series_record_for_sampling(record)
    cleaned = clean_session(projected, session_index=session_index, policy=policy)
    updates = {
        branch: _retain_invalid_container_audit(getattr(cleaned, branch), record, field_name)
        for field_name, branch in _VALUE_KEYS.items()
        if not series_container_valid(record, field_name)
    }
    return replace(cleaned, **updates) if updates else cleaned
