"""Leak-aware ACN-Data API access and reproducible raw-data downloads.

The module intentionally uses the public REST API directly instead of hiding query
semantics behind a third-party wrapper. Every download produces a JSONL file and a
sidecar manifest without storing the API token.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any, Iterator, Mapping
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_API_BASE_URL = "https://ev.caltech.edu/api/v1/"
DEFAULT_TOKEN_ENV = "ACN_API_TOKEN"
VALID_SITES = frozenset({"caltech", "jpl", "office001"})


class ACNDataError(RuntimeError):
    """Base error for ACN-Data acquisition."""


class ACNAuthenticationError(ACNDataError):
    """Raised when the API rejects or cannot find the access token."""


class ACNSchemaError(ACNDataError):
    """Raised when an API response does not follow the documented envelope."""


def _aware_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware; received {value!r}")
    return value.astimezone(timezone.utc)


def format_http_date(value: datetime) -> str:
    """Format an aware datetime as the RFC 1123 value expected by ACN-Data."""

    return format_datetime(_aware_utc(value, "datetime"), usegmt=True)


def parse_iso_datetime(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and require an explicit UTC offset."""

    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    return _aware_utc(parsed, "timestamp")


@dataclass(frozen=True)
class ACNQuery:
    """Reproducible description of one ACN-Data session query.

    The end time is exclusive so adjacent windows can be concatenated without
    duplicate boundary sessions.
    """

    site: str
    start: datetime
    end: datetime
    timeseries: bool = False
    min_energy_kwh: float | None = None
    max_sessions: int | None = None
    sort: str = "-connectionTime"

    def __post_init__(self) -> None:
        if self.site not in VALID_SITES:
            raise ValueError(f"site must be one of {sorted(VALID_SITES)}")
        start = _aware_utc(self.start, "start")
        end = _aware_utc(self.end, "end")
        if start >= end:
            raise ValueError("start must be earlier than end")
        if self.min_energy_kwh is not None and self.min_energy_kwh < 0:
            raise ValueError("min_energy_kwh must be non-negative")
        if self.max_sessions is not None and self.max_sessions <= 0:
            raise ValueError("max_sessions must be positive when provided")

    @property
    def start_utc(self) -> datetime:
        return _aware_utc(self.start, "start")

    @property
    def end_utc(self) -> datetime:
        return _aware_utc(self.end, "end")

    @property
    def condition(self) -> str:
        clauses = [
            f'connectionTime >= "{format_http_date(self.start_utc)}"',
            f'connectionTime < "{format_http_date(self.end_utc)}"',
        ]
        if self.min_energy_kwh is not None:
            clauses.append(f"kWhDelivered >= {self.min_energy_kwh:g}")
        return " and ".join(clauses)

    @property
    def endpoint(self) -> str:
        suffix = "/ts" if self.timeseries else ""
        return f"sessions/{self.site}{suffix}"

    def public_dict(self) -> dict[str, Any]:
        """Return a JSON-safe, secret-free representation of the query."""

        return {
            "site": self.site,
            "start_utc": self.start_utc.isoformat(),
            "end_utc": self.end_utc.isoformat(),
            "timeseries": self.timeseries,
            "min_energy_kwh": self.min_energy_kwh,
            "max_sessions": self.max_sessions,
            "sort": self.sort,
            "where": self.condition,
            "endpoint": self.endpoint,
        }


@dataclass(frozen=True)
class DownloadResult:
    output_path: Path
    manifest_path: Path
    record_count: int
    remote_total_reported: int | None
    complete: bool
    sha256: str


class ACNClient:
    """Small, retrying client for the documented ACN-Data sessions API."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = DEFAULT_API_BASE_URL,
        timeout: tuple[float, float] = (10.0, 120.0),
        session: requests.Session | None = None,
    ) -> None:
        clean_token = token.strip()
        if not clean_token:
            raise ACNAuthenticationError("ACN API token is empty")
        self._token = clean_token
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.session = session or self._build_session()
        # ACN documentation specifies HTTP Basic authentication with the token as
        # username and a blank password. The token is never written to manifests.
        self.session.auth = (self._token, "")
        self.session.headers.setdefault(
            "User-Agent", "EV-Charging-Forecasting-Research/ACN-Gate0"
        )
        self.session.headers.setdefault("Accept", "application/json")

    @classmethod
    def from_env(
        cls,
        token_env: str = DEFAULT_TOKEN_ENV,
        **kwargs: Any,
    ) -> "ACNClient":
        token = os.environ.get(token_env)
        if token is None or not token.strip():
            raise ACNAuthenticationError(
                f"Missing {token_env}. Store the ACN token in a local environment "
                "variable; never commit it to Git."
            )
        return cls(token, **kwargs)

    @staticmethod
    def _build_session() -> requests.Session:
        retry = Retry(
            total=5,
            connect=5,
            read=5,
            status=5,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session = requests.Session()
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        response = self.session.get(url, params=params, timeout=self.timeout)
        if response.status_code in {401, 403}:
            raise ACNAuthenticationError(
                "ACN-Data authentication failed. Verify the token and repository-local "
                "environment configuration."
            )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise ACNDataError(
                f"ACN-Data request failed with HTTP {response.status_code}"
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ACNSchemaError("ACN-Data returned a non-JSON response") from exc
        if not isinstance(payload, Mapping):
            raise ACNSchemaError("ACN-Data response root must be an object")
        return payload

    def iter_pages(self, query: ACNQuery) -> Iterator[Mapping[str, Any]]:
        """Yield validated API pages while following documented HATEOAS links."""

        url = urljoin(self.base_url, query.endpoint)
        params: Mapping[str, Any] | None = {
            "where": query.condition,
            "sort": query.sort,
            # The official API documents 25 metadata sessions and one time-series
            # session per page. Explicit limits avoid unnecessarily large responses.
            "max_results": 1 if query.timeseries else 25,
        }
        seen_urls: set[str] = set()
        while True:
            payload = self._get_json(url, params=params)
            items = payload.get("_items")
            links = payload.get("_links")
            if not isinstance(items, list):
                raise ACNSchemaError("ACN-Data page is missing list field '_items'")
            if not isinstance(links, Mapping):
                raise ACNSchemaError("ACN-Data page is missing object field '_links'")
            yield payload

            next_link = links.get("next")
            if not isinstance(next_link, Mapping) or not next_link.get("href"):
                break
            next_url = urljoin(self.base_url, str(next_link["href"]))
            if next_url in seen_urls:
                raise ACNSchemaError("ACN-Data pagination loop detected")
            seen_urls.add(next_url)
            url = next_url
            params = None

    def iter_sessions(self, query: ACNQuery) -> Iterator[dict[str, Any]]:
        yielded = 0
        for page in self.iter_pages(query):
            for item in page["_items"]:
                if not isinstance(item, dict):
                    raise ACNSchemaError("ACN-Data session record must be an object")
                yield item
                yielded += 1
                if query.max_sessions is not None and yielded >= query.max_sessions:
                    return


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def download_sessions(
    client: ACNClient,
    query: ACNQuery,
    output_path: str | Path,
    *,
    overwrite: bool = False,
    token_env: str = DEFAULT_TOKEN_ENV,
) -> DownloadResult:
    """Download sessions to deterministic JSONL plus a secret-free manifest."""

    output = Path(output_path)
    manifest = output.with_suffix(output.suffix + ".manifest.json")
    if not output.suffix:
        raise ValueError("output_path must include a file extension, preferably .jsonl")
    if not overwrite and (output.exists() or manifest.exists()):
        raise FileExistsError(
            f"Refusing to overwrite {output} or its manifest; pass overwrite=True explicitly"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".partial")
    digest = hashlib.sha256()
    record_count = 0
    remote_total: int | None = None

    try:
        with temporary.open("wb") as handle:
            for page in client.iter_pages(query):
                if remote_total is None:
                    meta = page.get("_meta")
                    if isinstance(meta, Mapping) and isinstance(meta.get("total"), int):
                        remote_total = int(meta["total"])
                for item in page["_items"]:
                    if query.max_sessions is not None and record_count >= query.max_sessions:
                        break
                    if not isinstance(item, dict):
                        raise ACNSchemaError("ACN-Data session record must be an object")
                    encoded = (
                        json.dumps(
                            item,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\n"
                    ).encode("utf-8")
                    handle.write(encoded)
                    digest.update(encoded)
                    record_count += 1
                if query.max_sessions is not None and record_count >= query.max_sessions:
                    break
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    if query.max_sessions is not None and remote_total is None:
        complete = False
    else:
        complete = remote_total is None or record_count >= remote_total
    manifest_payload = {
        "schema_version": "acn-download-manifest/v1",
        "dataset_id": "D0001",
        "source": "ACN-Data public REST API",
        "source_documentation": "https://ev.caltech.edu/dataset",
        "api_base_url": client.base_url,
        "query": query.public_dict(),
        "authentication": {
            "method": "HTTP Basic; token as username, blank password",
            "token_environment_variable": token_env,
            "token_stored": False,
        },
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_file": output.name,
        "record_count": record_count,
        "remote_total_reported": remote_total,
        "complete_for_query": complete,
        "sha256": digest.hexdigest(),
        "notes": [
            "Raw timestamp strings are preserved exactly as returned by the API.",
            "chargingCurrent is measured current, not a direct kW time series.",
            "The /ts endpoint is intentionally opt-in because the provider "
            "documents it as expensive.",
        ],
    }
    _atomic_write_json(manifest, manifest_payload)
    return DownloadResult(
        output_path=output,
        manifest_path=manifest,
        record_count=record_count,
        remote_total_reported=remote_total,
        complete=complete,
        sha256=digest.hexdigest(),
    )


def iter_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield JSON objects from a UTF-8 JSONL file with line-aware errors."""

    source = Path(path)
    with source.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ACNSchemaError(
                    f"Invalid JSON in {source} at line {line_number}: {exc.msg}"
                ) from exc
            if not isinstance(item, dict):
                raise ACNSchemaError(
                    f"Expected an object in {source} at line {line_number}"
                )
            yield item
