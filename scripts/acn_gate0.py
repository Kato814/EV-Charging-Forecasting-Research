"""ACN-Data Gate 0 command-line utility.

Install the repository first with ``python -m pip install -e .``. The command never
accepts a token on the command line; it reads ``ACN_API_TOKEN`` (or another explicitly
named environment variable) to avoid shell-history leakage.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evcf.data import (
    ACNClient,
    ACNQuery,
    audit_jsonl,
    download_sessions,
    parse_iso_datetime,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ACN-Data acquisition and semantic audit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser("download", help="Download a bounded ACN query to JSONL")
    download.add_argument("--site", choices=("caltech", "jpl", "office001"), required=True)
    download.add_argument("--start", required=True, help="ISO-8601 time with UTC offset")
    download.add_argument("--end", required=True, help="ISO-8601 time with UTC offset; exclusive")
    download.add_argument("--output", type=Path, required=True)
    download.add_argument("--timeseries", action="store_true", help="Use slow /ts endpoint")
    download.add_argument("--min-energy-kwh", type=float)
    download.add_argument("--max-sessions", type=int)
    download.add_argument("--token-env", default="ACN_API_TOKEN")
    download.add_argument("--overwrite", action="store_true")
    download.add_argument("--dry-run", action="store_true")

    audit = subparsers.add_parser("audit", help="Audit a downloaded JSONL file")
    audit.add_argument("--input", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "download":
        query = ACNQuery(
            site=args.site,
            start=parse_iso_datetime(args.start),
            end=parse_iso_datetime(args.end),
            timeseries=args.timeseries,
            min_energy_kwh=args.min_energy_kwh,
            max_sessions=args.max_sessions,
        )
        if args.dry_run:
            print(json.dumps(query.public_dict(), ensure_ascii=False, indent=2))
            return 0
        client = ACNClient.from_env(args.token_env)
        result = download_sessions(
            client,
            query,
            args.output,
            overwrite=args.overwrite,
            token_env=args.token_env,
        )
        print(
            json.dumps(
                {
                    "output": str(result.output_path),
                    "manifest": str(result.manifest_path),
                    "record_count": result.record_count,
                    "remote_total_reported": result.remote_total_reported,
                    "complete": result.complete,
                    "sha256": result.sha256,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    report = audit_jsonl(args.input, args.output)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
