from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from scripts.acn_jpl_2019_05 import MISSING_TOKEN_MESSAGE, run_metadata


def test_missing_token_stops_before_client_or_network(tmp_path: Path) -> None:
    output = io.StringIO()

    def forbidden_client_factory() -> Any:
        raise AssertionError("client must not be constructed")

    def forbidden_runner(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("runner must not be called")

    status = run_metadata(
        raw_root=tmp_path,
        environ={},
        client_factory=forbidden_client_factory,
        chunk_runner=forbidden_runner,
        stdout=output,
    )

    assert status == 2
    assert output.getvalue() == MISSING_TOKEN_MESSAGE + "\n"


def test_success_uses_fixed_metadata_scope_and_emits_only_aggregate_progress(
    tmp_path: Path,
) -> None:
    output = io.StringIO()
    sentinel = "sentinel-secret-token"
    fake_client = object()
    observed: dict[str, Any] = {}

    def fake_runner(
        client: Any,
        root: Path,
        windows: Any,
        *,
        endpoint: str,
    ) -> dict[str, Any]:
        observed.update(
            client=client,
            root=Path(root),
            windows=list(windows),
            endpoint=endpoint,
        )
        return {
            "completed_days": [window.day_key for window in observed["windows"]],
            "pending_days": [],
            "failed_days": [],
            "last_success": "2019-05-31",
            "retry_count": 0,
        }

    status = run_metadata(
        raw_root=tmp_path,
        environ={"ACN_API_TOKEN": sentinel},
        client_factory=lambda: fake_client,
        chunk_runner=fake_runner,
        stdout=output,
    )

    payload = json.loads(output.getvalue())
    assert status == 0
    assert observed["client"] is fake_client
    assert observed["root"] == tmp_path
    assert observed["endpoint"] == "metadata"
    assert len(observed["windows"]) == 38
    assert payload == {
        "raw_root": str(tmp_path),
        "completed_days": 38,
        "pending_days": 0,
        "failed_days": 0,
        "last_success": "2019-05-31",
        "retry_count": 0,
        "status": "COMPLETE",
    }
    assert sentinel not in output.getvalue()


def test_failed_or_pending_chunk_returns_nonzero(tmp_path: Path) -> None:
    output = io.StringIO()

    def fake_runner(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "completed_days": ["2019-04-24"],
            "pending_days": ["2019-04-25"],
            "failed_days": ["2019-04-26"],
            "last_success": "2019-04-24",
            "retry_count": 2,
        }

    status = run_metadata(
        raw_root=tmp_path,
        environ={"ACN_API_TOKEN": "sentinel-secret-token"},
        client_factory=object,
        chunk_runner=fake_runner,
        stdout=output,
    )

    payload = json.loads(output.getvalue())
    assert status == 1
    assert payload["status"] == "INCOMPLETE"
    assert payload["pending_days"] == 1
    assert payload["failed_days"] == 1
    assert "2019-04-25" not in output.getvalue()
    assert "2019-04-26" not in output.getvalue()
    assert "sentinel-secret-token" not in output.getvalue()
