"""
Select representative document candidates for phase 1 projects.

This script applies simple folder/file heuristics to pick one candidate per
document category for each project:
- rfp
- proposal
- kickoff
- final_report
- presentation
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
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

IGNORE_TOKENS = [
    "old",
    "백업",
    "backup",
    "tmp",
    "임시",
    "템플릿",
    "template",
    "개인작업",
    "참고자료",
    "참조자료",
    "기타",
    "작업폴더",
    "pool",
]


@dataclass
class CategoryRule:
    category: str
    folder_tokens: list[str]
    file_tokens: list[str]
    preferred_roots: list[str]


CATEGORY_RULES = [
    CategoryRule(
        "rfp",
        ["rfp", "제안요청", "과업", "사전규격"],
        ["제안요청", "과업", "입찰공고", "rfp"],
        ["rfp", "사업준비", "사전규격"],
    ),
    CategoryRule(
        "proposal",
        ["제안서", "★ 제안서"],
        ["제안", "평가본", "발표본"],
        ["제안서", "★ 제안서"],
    ),
    CategoryRule(
        "kickoff",
        ["착수", "착수계"],
        ["착수"],
        ["착수", "착수계", "사업수행"],
    ),
    CategoryRule(
        "final_report",
        ["최종", "완료보고서", "산출물", "★ 산출물"],
        ["최종", "완료", "산출물"],
        ["완료보고서", "산출물", "★ 산출물", "사업수행", "보고회"],
    ),
    CategoryRule(
        "presentation",
        ["발표", "보고회", "★ 발표자료", "★발표자료"],
        ["발표", "보고회"],
        ["발표", "★ 발표자료", "★발표자료", "보고회", "제안서"],
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select representative docs")
    parser.add_argument(
        "--source-root",
        required=True,
        help="Project source root, e.g. W:\\01. 국내사업폴더",
    )
    parser.add_argument(
        "--candidates-csv",
        default="data/staged/manifest/phase1_project_candidates.csv",
        help="CSV with phase 1 candidate projects",
    )
    parser.add_argument(
        "--output-csv",
        default="data/staged/manifest/phase1_representative_docs_top10.csv",
        help="Output CSV path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of candidate projects to process from the top of the CSV",
    )
    return parser.parse_args()


def normalize(text: str) -> str:
    return text.lower().replace("_", "").replace(" ", "")


def should_ignore(path: Path) -> bool:
    parts = [normalize(part) for part in path.parts]
    return any(token in part for part in parts for token in IGNORE_TOKENS)


def score_path(path: Path, rule: CategoryRule) -> int:
    score = 0
    normalized_parts = [normalize(part) for part in path.parts]
    filename = normalize(path.name)

    for token in rule.folder_tokens:
        token_norm = normalize(token)
        if any(token_norm in part for part in normalized_parts):
            score += 5

    for token in rule.file_tokens:
        token_norm = normalize(token)
        if token_norm in filename:
            score += 4

    if path.suffix.lower() in {".pdf", ".hwp", ".hwpx", ".doc", ".docx"}:
        score += 2
    if path.suffix.lower() in {".ppt", ".pptx"}:
        score += 1

    if "최종" in path.name:
        score += 2
    if "발표본" in path.name:
        score += 2

    return score


def iter_search_roots(project_dir: Path, rule: CategoryRule) -> list[Path]:
    roots: list[Path] = []
    for child in project_dir.iterdir():
        if not child.exists():
            continue
        name_norm = normalize(child.name)
        if any(normalize(token) in name_norm for token in rule.preferred_roots):
            roots.append(child)

    if roots:
        return roots
    return [project_dir]


def pick_candidate(project_dir: Path, rule: CategoryRule) -> tuple[str, str]:
    best_path: Path | None = None
    best_score = -1
    best_mtime = -1.0

    for root in iter_search_roots(project_dir, rule):
        if root.is_file():
            candidate_paths = [root]
        else:
            candidate_paths = root.rglob("*")

        for path in candidate_paths:
            if not path.is_file():
                continue
            if path.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            if should_ignore(path.relative_to(project_dir)):
                continue

            score = score_path(path.relative_to(project_dir), rule)
            if score <= 0:
                continue

            stat = path.stat()
            if score > best_score or (score == best_score and stat.st_mtime > best_mtime):
                best_path = path
                best_score = score
                best_mtime = stat.st_mtime

    if best_path is None:
        return "", "missing"

    return str(best_path), "selected"


def main() -> int:
    args = parse_args()
    source_root = Path(args.source_root)
    candidates_csv = Path(args.candidates_csv)
    output_csv = Path(args.output_csv)

    rows = []
    with candidates_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            if index >= args.limit:
                break
            rows.append(row)

    output_csv.parent.mkdir(parents=True, exist_ok=True)

    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "phase1_rank",
            "folder_name",
            "category",
            "selection_status",
            "selected_path",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            project_dir = source_root / row["folder_name"]
            for rule in CATEGORY_RULES:
                selected_path, status = pick_candidate(project_dir, rule)
                writer.writerow(
                    {
                        "phase1_rank": row["phase1_rank"],
                        "folder_name": row["folder_name"],
                        "category": rule.category,
                        "selection_status": status,
                        "selected_path": selected_path,
                    }
                )

    print(f"Wrote representative document candidates to {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
