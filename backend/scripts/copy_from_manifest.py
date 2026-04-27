"""
Copy selected files to a snapshot destination using a prepared manifest CSV.

The manifest must include:
- source_path
- snapshot_path

The script preserves the path below the configured raw root.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CopyResult:
    copied: int
    skipped: int
    failed: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Copy files from manifest")
    parser.add_argument("--manifest-csv", required=True, help="Manifest CSV path")
    parser.add_argument(
        "--dest-raw-root",
        required=True,
        help="Destination raw root, e.g. Y:\\weeslee-rag\\data\\raw",
    )
    parser.add_argument(
        "--expected-raw-prefix",
        default="data/raw/",
        help="Prefix used in snapshot_path that should be stripped before copying",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    manifest_csv = Path(args.manifest_csv).resolve()
    dest_raw_root = Path(args.dest_raw_root)
    expected_prefix = args.expected_raw_prefix.replace("\\", "/")

    copied = 0
    skipped = 0
    failed = 0
    failures: list[dict[str, str]] = []

    with manifest_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            source_path = Path(row["source_path"])
            snapshot_path = row["snapshot_path"].replace("\\", "/")

            if not source_path.exists():
                failed += 1
                failures.append(
                    {
                        "source_path": str(source_path),
                        "reason": "source_missing",
                    }
                )
                continue

            relative_snapshot = snapshot_path
            if relative_snapshot.startswith(expected_prefix):
                relative_snapshot = relative_snapshot[len(expected_prefix):]

            target_path = dest_raw_root / Path(relative_snapshot)
            target_path.parent.mkdir(parents=True, exist_ok=True)

            if target_path.exists():
                skipped += 1
                continue

            try:
                shutil.copy2(source_path, target_path)
                copied += 1
            except Exception as exc:  # pragma: no cover - operational path
                failed += 1
                failures.append(
                    {
                        "source_path": str(source_path),
                        "target_path": str(target_path),
                        "reason": str(exc),
                    }
                )

    summary = {
        "manifest_csv": str(manifest_csv),
        "dest_raw_root": str(dest_raw_root),
        "copied": copied,
        "skipped": skipped,
        "failed": failed,
        "failures": failures[:20],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
