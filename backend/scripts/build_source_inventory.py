"""
Build an inventory report for the Weeslee source document repository.

The script groups files by the first-level directory under the source root
and counts supported document extensions. This is meant to support sample
selection before snapshot copying.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


DEFAULT_EXTENSIONS = {
    ".pdf",
    ".ppt",
    ".pptx",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".txt",
}


@dataclass
class FolderInventory:
    folder_name: str
    total_files: int
    total_size_bytes: int
    latest_modified_at: str
    extension_counts: dict[str, int]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build source inventory")
    parser.add_argument("--source", required=True, help="Source root path")
    parser.add_argument(
        "--output-dir",
        default="data/staged/manifest",
        help="Output directory for CSV and JSON files",
    )
    parser.add_argument(
        "--extensions",
        nargs="*",
        default=sorted(DEFAULT_EXTENSIONS),
        help="Allowed extensions, including the dot",
    )
    return parser.parse_args()


def iso_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="seconds")


def main() -> int:
    args = parse_args()
    source_root = Path(args.source).resolve()
    output_dir = Path(args.output_dir).resolve()
    extensions = {ext.lower() for ext in args.extensions}

    if not source_root.exists():
        raise SystemExit(f"Source root does not exist: {source_root}")

    output_dir.mkdir(parents=True, exist_ok=True)

    folder_counters: dict[str, Counter] = defaultdict(Counter)
    folder_sizes: Counter = Counter()
    folder_latest: dict[str, float] = {}

    for path in source_root.rglob("*"):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in extensions:
            continue

        try:
            relative = path.relative_to(source_root)
        except ValueError:
            continue

        top_folder = relative.parts[0] if relative.parts else "_ROOT_"
        stat = path.stat()

        folder_counters[top_folder][ext] += 1
        folder_counters[top_folder]["_total_files"] += 1
        folder_sizes[top_folder] += stat.st_size
        folder_latest[top_folder] = max(folder_latest.get(top_folder, 0.0), stat.st_mtime)

    rows: list[FolderInventory] = []
    for folder_name, counter in folder_counters.items():
        rows.append(
            FolderInventory(
                folder_name=folder_name,
                total_files=counter["_total_files"],
                total_size_bytes=folder_sizes[folder_name],
                latest_modified_at=iso_from_timestamp(folder_latest[folder_name]),
                extension_counts={
                    key: value for key, value in sorted(counter.items()) if key != "_total_files"
                },
            )
        )

    rows.sort(key=lambda item: (-item.total_files, item.folder_name))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"source_inventory_{timestamp}.json"
    csv_path = output_dir / f"source_inventory_{timestamp}.csv"

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(
            [
                {
                    "folder_name": row.folder_name,
                    "total_files": row.total_files,
                    "total_size_bytes": row.total_size_bytes,
                    "latest_modified_at": row.latest_modified_at,
                    "extension_counts": row.extension_counts,
                }
                for row in rows
            ],
            handle,
            ensure_ascii=False,
            indent=2,
        )

    extension_headers = sorted({ext for row in rows for ext in row.extension_counts})
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["folder_name", "total_files", "total_size_bytes", "latest_modified_at", *extension_headers]
        )
        for row in rows:
            writer.writerow(
                [
                    row.folder_name,
                    row.total_files,
                    row.total_size_bytes,
                    row.latest_modified_at,
                    *[row.extension_counts.get(header, 0) for header in extension_headers],
                ]
            )

    summary = {
        "source_root": str(source_root),
        "folder_count": len(rows),
        "json_path": str(json_path),
        "csv_path": str(csv_path),
        "top_10": [
            {
                "folder_name": row.folder_name,
                "total_files": row.total_files,
                "latest_modified_at": row.latest_modified_at,
            }
            for row in rows[:10]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
