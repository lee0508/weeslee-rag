"""
Prepare a document snapshot manifest for the Weeslee RAG pipeline.

This script is intentionally safe by default:
- It scans a source tree.
- It filters files by extension.
- It computes hashes and writes a manifest.
- It does NOT copy files unless --copy is explicitly passed.

Typical usage:
    python backend/scripts/prepare_snapshot_manifest.py ^
      --source "W:\\01. 국내사업폴더" ^
      --snapshot-name "snapshot_2026-04-27" ^
      --output-dir "data/staged/manifest" ^
      --limit 300
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare snapshot manifest")
    parser.add_argument("--source", required=True, help="Source root path")
    parser.add_argument(
        "--snapshot-name",
        required=True,
        help="Snapshot label, for example snapshot_2026-04-27",
    )
    parser.add_argument(
        "--output-dir",
        default="data/staged/manifest",
        help="Directory where manifest files will be written",
    )
    parser.add_argument(
        "--raw-root",
        default="data/raw",
        help="Local raw root used to calculate snapshot_path values",
    )
    parser.add_argument(
        "--copy-dest",
        default="",
        help="Destination root for copied files. Copy is disabled unless --copy is passed.",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Actually copy files to --copy-dest/<snapshot-name>/...",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of files to process",
    )
    parser.add_argument(
        "--batch-id",
        default="batch-001",
        help="Copy batch identifier",
    )
    parser.add_argument(
        "--extensions",
        nargs="*",
        default=sorted(DEFAULT_EXTENSIONS),
        help="Allowed extensions, including the dot",
    )
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


def iter_candidate_files(source_root: Path, extensions: set[str]) -> Iterable[Path]:
    for path in source_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in extensions:
            yield path


def build_document_id(index: int) -> str:
    return f"DOC-{datetime.now().strftime('%Y%m%d')}-{index:06d}"


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


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

    source_root = Path(args.source).resolve()
    output_dir = Path(args.output_dir).resolve()
    raw_root = Path(args.raw_root)
    copy_dest = Path(args.copy_dest).resolve() if args.copy_dest else None
    extensions = {ext.lower() for ext in args.extensions}

    if not source_root.exists():
        raise SystemExit(f"Source root does not exist: {source_root}")

    ensure_directory(output_dir)

    rows: list[ManifestRecord] = []
    processed = 0

    for index, path in enumerate(iter_candidate_files(source_root, extensions), start=1):
        if args.limit and processed >= args.limit:
            break

        relative_path = path.relative_to(source_root)
        snapshot_relative = Path(args.snapshot_name) / "domestic_business" / relative_path
        snapshot_path = raw_root / snapshot_relative

        copied_at = utc_now_iso()
        status = "planned"

        if args.copy:
            if copy_dest is None:
                raise SystemExit("--copy requires --copy-dest")
            target_path = copy_dest / snapshot_relative
            ensure_directory(target_path.parent)
            shutil.copy2(path, target_path)
            status = "copied"

        stat = path.stat()
        row = ManifestRecord(
            document_id=build_document_id(index),
            source_root=str(source_root),
            source_path=str(path),
            relative_path=str(relative_path).replace("\\", "/"),
            snapshot_name=args.snapshot_name,
            snapshot_path=str(snapshot_path).replace("\\", "/"),
            sha256=sha256sum(path),
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(
                timespec="seconds"
            ),
            copied_at=copied_at,
            copy_batch=args.batch_id,
            copy_status=status,
            extension=path.suffix.lower(),
        )
        rows.append(row)
        processed += 1

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    jsonl_path = output_dir / f"{args.snapshot_name}_{args.batch_id}_{timestamp}.jsonl"
    csv_path = output_dir / f"{args.snapshot_name}_{args.batch_id}_{timestamp}.csv"

    write_jsonl(jsonl_path, rows)
    write_csv(csv_path, rows)

    summary = {
        "source_root": str(source_root),
        "snapshot_name": args.snapshot_name,
        "batch_id": args.batch_id,
        "processed_files": processed,
        "copy_enabled": args.copy,
        "jsonl_path": str(jsonl_path),
        "csv_path": str(csv_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
