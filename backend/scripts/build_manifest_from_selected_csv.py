"""
Build a manifest from an explicit selected-document CSV.

Input CSV example columns:
- phase1_rank
- folder_name
- category
- selection_status
- selected_path
- selection_note

This script ignores rows where selection_status is not "selected".
It is intended for small curated batches such as phase1_representative_docs_top5.csv.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ManifestRecord:
    document_id: str
    source_root: str
    source_path: str
    relative_path: str
    snapshot_name: str
    snapshot_path: str
    sha256: str
    size_bytes: int
    modified_at: str
    copied_at: str
    copy_batch: str
    copy_status: str
    extension: str
    phase1_rank: str
    folder_name: str
    category: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build manifest from selected CSV")
    parser.add_argument("--selected-csv", required=True, help="Path to selected document CSV")
    parser.add_argument("--source-root", required=True, help="Root path of source repository")
    parser.add_argument("--snapshot-name", required=True, help="Snapshot label")
    parser.add_argument("--output-dir", default="data/staged/manifest", help="Output directory")
    parser.add_argument("--raw-root", default="data/raw", help="Raw root for snapshot_path")
    parser.add_argument("--batch-id", default="batch-001-top5", help="Batch identifier")
    return parser.parse_args()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256sum(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_document_id(index: int) -> str:
    return f"DOC-{datetime.now().strftime('%Y%m%d')}-{index:06d}"


def write_jsonl(path: Path, rows: list[ManifestRecord]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[ManifestRecord]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def main() -> int:
    args = parse_args()

    selected_csv = Path(args.selected_csv).resolve()
    source_root = Path(args.source_root)
    output_dir = Path(args.output_dir).resolve()
    raw_root = Path(args.raw_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[ManifestRecord] = []
    copied_at = utc_now_iso()

    with selected_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            if row.get("selection_status") != "selected":
                continue

            source_path = Path(row["selected_path"])
            if not source_path.exists():
                continue

            relative_path = Path(os.path.relpath(str(source_path), str(source_root)))
            snapshot_relative = Path(args.snapshot_name) / "domestic_business" / relative_path
            snapshot_path = raw_root / snapshot_relative
            stat = source_path.stat()

            rows.append(
                ManifestRecord(
                    document_id=build_document_id(index),
                    source_root=str(source_root),
                    source_path=str(source_path),
                    relative_path=str(relative_path).replace("\\", "/"),
                    snapshot_name=args.snapshot_name,
                    snapshot_path=str(snapshot_path).replace("\\", "/"),
                    sha256=sha256sum(source_path),
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(
                        timespec="seconds"
                    ),
                    copied_at=copied_at,
                    copy_batch=args.batch_id,
                    copy_status="planned",
                    extension=source_path.suffix.lower(),
                    phase1_rank=row.get("phase1_rank", ""),
                    folder_name=row.get("folder_name", ""),
                    category=row.get("category", ""),
                )
            )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    jsonl_path = output_dir / f"{args.snapshot_name}_{args.batch_id}_{timestamp}.jsonl"
    csv_path = output_dir / f"{args.snapshot_name}_{args.batch_id}_{timestamp}.csv"

    write_jsonl(jsonl_path, rows)
    write_csv(csv_path, rows)

    summary = {
        "selected_csv": str(selected_csv),
        "snapshot_name": args.snapshot_name,
        "batch_id": args.batch_id,
        "selected_rows": len(rows),
        "jsonl_path": str(jsonl_path),
        "csv_path": str(csv_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
