from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main() -> None:
    core = read(ROOT / "literature/core_library.csv")
    frontier = read(ROOT / "literature/frontier_watchlist.csv")
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in core:
        groups[row["priority"]].append(row)

    lines = [
        "# Reading Queue",
        "",
        "由 `scripts/build_reading_queue.py` 自动生成。正式全文阅读优先于继续扩大检索数量。",
        "",
    ]
    for priority in ("P0", "P1", "P2"):
        rows = sorted(groups.get(priority, []), key=lambda r: (int(r["year"]), r["paper_id"]), reverse=True)
        lines.extend([f"## {priority} — 正式文献（{len(rows)}）", ""])
        for row in rows:
            lines.append(f"- [ ] **{row['paper_id']}** ({row['year']}) {row['title']} — `{row['theme']}` — {row['status']}")
        lines.append("")

    p0_watch = [r for r in frontier if r["priority"] == "P0"]
    lines.extend([f"## P0 前沿观察（{len(p0_watch)}；不可替代同行评议证据）", ""])
    for row in sorted(p0_watch, key=lambda r: (int(r["year"]), r["paper_id"]), reverse=True):
        lines.append(f"- [ ] **{row['paper_id']}** ({row['year']}) {row['title']} — {row['identifier']}")
    lines.append("")
    (ROOT / "literature/reading_queue.md").write_text("\n".join(lines), encoding="utf-8")
    print("updated literature/reading_queue.md")


if __name__ == "__main__":
    main()
