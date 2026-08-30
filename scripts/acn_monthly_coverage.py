"""Query ACN-Data monthly metadata coverage without downloading raw sessions."""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from evcf.data import ACNClient
from evcf.data.acn_coverage import collect_monthly_coverage, summarize_monthly_coverage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit monthly ACN-Data session coverage using API-reported totals"
    )
    parser.add_argument("--site", choices=("caltech", "jpl", "office001"), required=True)
    parser.add_argument("--start-month", required=True, help="Inclusive YYYY-MM")
    parser.add_argument("--end-month", required=True, help="Inclusive YYYY-MM")
    parser.add_argument("--timezone", default="America/Los_Angeles")
    parser.add_argument("--output", type=Path, required=True, help="Output CSV path")
    parser.add_argument("--token-env", default="ACN_API_TOKEN")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    summary_path = args.output.with_suffix(args.output.suffix + ".summary.json")
    if not args.overwrite and (args.output.exists() or summary_path.exists()):
        raise FileExistsError(
            f"Refusing to overwrite {args.output} or {summary_path}; pass --overwrite explicitly"
        )

    client = ACNClient.from_env(args.token_env)
    records = collect_monthly_coverage(
        client,
        site=args.site,
        start_month=args.start_month,
        end_month=args.end_month,
        timezone_name=args.timezone,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary_csv = args.output.with_suffix(args.output.suffix + ".partial")
    with temporary_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0].to_dict()) if records else [])
        if records:
            writer.writeheader()
            writer.writerows(record.to_dict() for record in records)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary_csv, args.output)

    summary = {
        "schema_version": "acn-monthly-coverage/v1",
        "site": args.site,
        "timezone": args.timezone,
        "start_month": args.start_month,
        "end_month": args.end_month,
        "queried_at_utc": datetime.now(timezone.utc).isoformat(),
        "authentication": {
            "token_environment_variable": args.token_env,
            "token_stored": False,
        },
        "summary": summarize_monthly_coverage(records),
        "selection_rule": (
            "Formal modelling windows must be chosen after reviewing continuity, monthly density, "
            "field stability and time-series availability; recency alone is insufficient."
        ),
    }
    temporary_json = summary_path.with_suffix(summary_path.suffix + ".partial")
    temporary_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_json, summary_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
