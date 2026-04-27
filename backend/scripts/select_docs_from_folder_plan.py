"""
Select representative files from a curated folder plan.

This script reads:
- phase1 representative folder plan CSV

And writes:
- representative document selection CSV

It searches only within the preferred subpath for each category to avoid
expensive full-tree scans on large network shares.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


ALLOWED_EXTENSIONS = {
    ".pdf",
    ".ppt",
    ".pptx",
    ".doc",
    ".docx",
    ".hwp",
    ".hwpx",
    ".xls",
    ".xlsx",
}

CATEGORY_KEYWORDS = {
    "rfp": ["제안요청", "과업", "입찰공고", "rfp", "과업지시"],
    "proposal": ["제안", "평가본", "발표본", "통합본"],
    "kickoff": ["착수"],
    "final_report": ["최종", "완료", "산출물", "보고서"],
    "presentation": ["발표", "보고회", "발표본"],
}

IGNORE_TOKENS = [
    "old",
    "backup",
    "백업",
    "tmp",
    "임시",
    "템플릿",
    "template",
    "개인작업",
    "참고자료",
    "참조자료",
    "기타",
    "작업폴더",
    ".ds_store",
    "thumbs.db",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select docs from folder plan")
    parser.add_argument("--source-root", required=True)
    parser.add_argument(
        "--plan-csv",
        default="data/staged/manifest/phase1_representative_folder_plan_top10.csv",
    )
    parser.add_argument(
        "--output-csv",
        default="data/staged/manifest/phase1_representative_docs_top10.csv",
    )
    return parser.parse_args()


def normalize(text: str) -> str:
    return text.lower().replace("_", "").replace(" ", "")


def should_ignore(path: Path) -> bool:
    normalized = normalize(str(path))
    return any(token in normalized for token in IGNORE_TOKENS)


def score_candidate(path: Path, category: str) -> int:
    score = 0
    name = normalize(path.name)
    for keyword in CATEGORY_KEYWORDS.get(category, []):
        if normalize(keyword) in name:
            score += 5

    if path.suffix.lower() in {".pdf", ".hwp", ".hwpx", ".doc", ".docx"}:
        score += 3
    if path.suffix.lower() in {".ppt", ".pptx"}:
        score += 2
    if path.suffix.lower() in {".xls", ".xlsx"}:
        score += 1

    if "최종" in path.name:
        score += 2
    if "발표본" in path.name:
        score += 2
    if "v0." in name or "ver0." in name:
        score -= 1

    return score


def pick_best(path: Path, category: str) -> tuple[str, str]:
    if not path.exists():
        return "", "missing_subpath"

    candidates = [path] if path.is_file() else list(path.rglob("*"))

    best: Path | None = None
    best_score = -10**9
    best_mtime = -1.0

    for candidate in candidates:
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        if should_ignore(candidate.relative_to(path if path.is_dir() else path.parent)):
            continue

        score = score_candidate(candidate, category)
        stat = candidate.stat()
        if score > best_score or (score == best_score and stat.st_mtime > best_mtime):
            best = candidate
            best_score = score
            best_mtime = stat.st_mtime

    if best is None:
        return "", "no_candidate"

    return str(best), "selected"


def main() -> int:
    args = parse_args()
    source_root = Path(args.source_root)
    plan_csv = Path(args.plan_csv)
    output_csv = Path(args.output_csv)

    output_csv.parent.mkdir(parents=True, exist_ok=True)

    with plan_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = list(csv.DictReader(handle))

    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "phase1_rank",
            "folder_name",
            "category",
            "preferred_subpath",
            "selection_status",
            "selected_path",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            target = source_root / row["folder_name"] / row["preferred_subpath"]
            selected_path, status = pick_best(target, row["category"])
            writer.writerow(
                {
                    "phase1_rank": row["phase1_rank"],
                    "folder_name": row["folder_name"],
                    "category": row["category"],
                    "preferred_subpath": row["preferred_subpath"],
                    "selection_status": status,
                    "selected_path": selected_path,
                }
            )

    print(f"Wrote {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
