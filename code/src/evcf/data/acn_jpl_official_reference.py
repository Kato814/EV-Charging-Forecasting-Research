"""One-request official count reference for an approved JPL local month."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .acn_api import ACNClient, ACNQuery
from .acn_jpl_month_config import MAY_2019, JPLMonthConfig

_REFERENCE_KEYS = frozenset(
    {
        "schema_version",
        "source",
        "endpoint",
        "site",
        "timezone",
        "interval_semantics",
        "local_start_inclusive",
        "local_end_exclusive",
        "utc_start_inclusive",
        "utc_end_exclusive",
        "query_condition",
        "official_meta_total",
        "request_count",
        "response_fields_consumed",
        "token_stored",
    }
)
_VERIFIED_RESULT_SEAL = object()


class OfficialLocalMonthReferenceError(ValueError):
    """Raised when a saved aggregate reference is absent or not exact."""


@dataclass(frozen=True)
class OfficialLocalMonthTotalResult:
    """Validated aggregate total and its secret-free local evidence path."""

    total: int
    reference_path: Path = field(repr=False)
    month: str
    local_start_inclusive: str
    local_end_exclusive: str
    utc_start_inclusive: str
    utc_end_exclusive: str
    request_count: Literal[1]
    _verification_seal: object | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )
    _verified_result_binding: str | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )
    _verified_reference_sha256: str | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def is_verified_for(self, month: JPLMonthConfig) -> bool:
        """Return whether this sealed result and saved file exactly match ``month``."""

        if not (
            self._verification_seal is _VERIFIED_RESULT_SEAL
            and isinstance(self.reference_path, Path)
            and _result_matches_month(self, month)
        ):
            return False
        try:
            if self._verified_result_binding != _result_binding(self):
                return False
            partial = self.reference_path.with_suffix(self.reference_path.suffix + ".partial")
            if partial.exists() or not self.reference_path.is_file():
                return False
            current_sha256 = hashlib.sha256(self.reference_path.read_bytes()).hexdigest()
        except (OSError, TypeError, ValueError):
            return False
        return current_sha256 == self._verified_reference_sha256


def _reference_payload(month: JPLMonthConfig, total: int) -> dict[str, object]:
    query = ACNQuery(
        site="jpl",
        start=month.local_start,
        end=month.local_end,
        timeseries=False,
    )
    return {
        "schema_version": "acn-jpl-official-local-month-total/v1",
        "source": "ACN-Data official REST API",
        "endpoint": query.endpoint,
        "site": "jpl",
        "timezone": month.timezone_name,
        "interval_semantics": "[start,end)",
        "local_start_inclusive": month.local_start.isoformat(),
        "local_end_exclusive": month.local_end.isoformat(),
        "utc_start_inclusive": month.utc_start.isoformat(),
        "utc_end_exclusive": month.utc_end.isoformat(),
        "query_condition": query.condition,
        "official_meta_total": total,
        "request_count": 1,
        "response_fields_consumed": ["_meta.total"],
        "token_stored": False,
    }


def _result_matches_month(
    result: OfficialLocalMonthTotalResult,
    month: JPLMonthConfig,
) -> bool:
    return (
        isinstance(month, JPLMonthConfig)
        and isinstance(result.total, int)
        and not isinstance(result.total, bool)
        and result.total >= 0
        and result.month == month.month
        and result.local_start_inclusive == month.local_start.isoformat()
        and result.local_end_exclusive == month.local_end.isoformat()
        and result.utc_start_inclusive == month.utc_start.isoformat()
        and result.utc_end_exclusive == month.utc_end.isoformat()
        and isinstance(result.request_count, int)
        and not isinstance(result.request_count, bool)
        and result.request_count == 1
    )


def _result_binding(result: OfficialLocalMonthTotalResult) -> str:
    payload = {
        "total": result.total,
        "reference_path": str(result.reference_path),
        "month": result.month,
        "local_start_inclusive": result.local_start_inclusive,
        "local_end_exclusive": result.local_end_exclusive,
        "utc_start_inclusive": result.utc_start_inclusive,
        "utc_end_exclusive": result.utc_end_exclusive,
        "request_count": result.request_count,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _seal_result(
    result: OfficialLocalMonthTotalResult,
    *,
    reference_sha256: str,
) -> OfficialLocalMonthTotalResult:
    object.__setattr__(result, "_verified_reference_sha256", reference_sha256)
    object.__setattr__(result, "_verified_result_binding", _result_binding(result))
    object.__setattr__(result, "_verification_seal", _VERIFIED_RESULT_SEAL)
    return result


def _closed_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise OfficialLocalMonthReferenceError(
                "official local-month reference contains duplicate keys"
            )
        result[key] = value
    return result


def _validated_reference_total(
    payload: object,
    month: JPLMonthConfig,
) -> int:
    if not isinstance(payload, Mapping) or set(payload) != _REFERENCE_KEYS:
        raise OfficialLocalMonthReferenceError(
            "official local-month reference fields are not closed"
        )
    total = payload.get("official_meta_total")
    request_count = payload.get("request_count")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise OfficialLocalMonthReferenceError("official local-month reference total is invalid")
    if not isinstance(request_count, int) or isinstance(request_count, bool) or request_count != 1:
        raise OfficialLocalMonthReferenceError(
            "official local-month reference request count is invalid"
        )
    if payload.get("token_stored") is not False:
        raise OfficialLocalMonthReferenceError(
            "official local-month reference token declaration is unsafe"
        )
    if dict(payload) != _reference_payload(month, total):
        raise OfficialLocalMonthReferenceError(
            "official local-month reference contract does not match the requested month"
        )
    return total


def load_verified_official_local_month_total(
    path: str | Path,
    *,
    month: JPLMonthConfig = MAY_2019,
) -> OfficialLocalMonthTotalResult:
    """Strictly validate an existing v1 aggregate reference without networking."""

    reference_path = Path(path)
    partial = reference_path.with_suffix(reference_path.suffix + ".partial")
    if partial.exists() or not reference_path.is_file():
        raise OfficialLocalMonthReferenceError(
            "official local-month reference is missing or partial"
        )
    try:
        raw = reference_path.read_bytes()
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_closed_json_object,
        )
    except OfficialLocalMonthReferenceError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfficialLocalMonthReferenceError(
            "official local-month reference is not valid UTF-8 JSON"
        ) from exc
    total = _validated_reference_total(payload, month)
    result = OfficialLocalMonthTotalResult(
        total=total,
        reference_path=reference_path,
        month=month.month,
        local_start_inclusive=month.local_start.isoformat(),
        local_end_exclusive=month.local_end.isoformat(),
        utc_start_inclusive=month.utc_start.isoformat(),
        utc_end_exclusive=month.utc_end.isoformat(),
        request_count=1,
    )
    _seal_result(result, reference_sha256=hashlib.sha256(raw).hexdigest())
    if not result.is_verified_for(month):
        raise OfficialLocalMonthReferenceError(
            "official local-month reference changed during validation"
        )
    return result


def _atomic_write_reference(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def probe_official_local_month_total(
    client: ACNClient,
    destination: str | Path,
    *,
    month: JPLMonthConfig = MAY_2019,
) -> OfficialLocalMonthTotalResult:
    """Query one complete LA-local month exactly once and persist only total."""

    reference_path = Path(destination)
    if (
        reference_path.exists()
        or reference_path.with_suffix(reference_path.suffix + ".partial").exists()
    ):
        raise FileExistsError(
            f"Refusing to overwrite existing official count reference: {reference_path}"
        )

    query = ACNQuery(
        site="jpl",
        start=month.local_start,
        end=month.local_end,
        timeseries=False,
    )
    total = client.fetch_total_once(query)
    payload = _reference_payload(month, total)
    _atomic_write_reference(reference_path, payload)
    return load_verified_official_local_month_total(
        reference_path,
        month=month,
    )
