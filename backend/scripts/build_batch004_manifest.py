#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch-004 Full Scan: 신규 71개 프로젝트 폴더에서 대표 문서 선택 → manifest JSONL 생성.

Usage:
    python backend/scripts/build_batch004_manifest.py
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SOURCE_ROOT = Path(r"W:\01. 국내사업폴더")
SNAPSHOT_NAME = "snapshot_2026-05-07_batch-004-full-v1"
BATCH_ID = "batch-004-full-v1"
OUT_JSONL = Path("data/staged/manifest") / f"{SNAPSHOT_NAME}_manifest.jsonl"
OUT_SUMMARY = Path("data/staged/manifest") / f"{SNAPSHOT_NAME}_selection_summary.csv"

PHASE1_EXTS = {".pdf", ".pptx", ".docx", ".xlsx"}
MAX_FILE_MB = 60

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "rfp":          ["rfp", "제안요청", "과업지시", "입찰공고", "과업내용", "과업범위"],
    "proposal":     ["제안서", "제안발표", "평가본", "최종제안", "제안_", "_제안"],
    "kickoff":      ["착수", "kick", "착수계", "착수보고"],
    "final_report": ["최종", "완료보고", "산출물", "최종보고", "최종산출", "완료"],
    "presentation": ["발표자료", "발표본", "발표", "ppt발표", "중간보고"],
}
PRIORITY_EXTS = [".pdf", ".pptx", ".docx", ".xlsx"]

IGNORE_TOKENS = {
    "old", "백업", "backup", "tmp", "임시", "작업폴더",
    "~$", "이전버전", "참고자료", "자료요청", "기타",
}

# Folders already in existing snapshots — skip
ALREADY_PROCESSED = {
    "112. 차세대 국립병원 정보시스템 구축을 위한 BPRISP",
    "142. 차세대 보건의료빅데이터개방시스템 구축을 위한 ISP",
    "149. 국토지리정보원",
    "191. 제3차 보건의료기술 종합정보시스템 중기 isp 수립",
    "201703. 통계청 통계지리정보서비스 ISP",
    "202212. k-water 데이터허브플랫폼_ISP",
    "202305. AI 기반 지능형 진로교육정보망",
    "202312. 법무부_디지털플랫폼 교육강화, 환경개선 로드맵 연구사업",
    "202403. 기재부_전자수입인지 기관선정연구",
    "202407. 범죄예방정책_거대언어모델 도입활용방안 연구",
    "202407. 양형기준 운영점검시스템 및 양형정보시스템의 고도화를 위한 AI시스템 구축 ISP",
    "202503. AX 활용 정보화전략계획수립_서울주택도시개발공사",
    "202603. AX기반의 차세대 업무 시스템 구축을 위한 ISMP",
    "202604. 과기정통부 AI-NEXT 고도화 ISP 수립",
    "215. K-water 데이터허브",
    "56. 자율주행차_성과평가",
    "61. 농정원 AGRIX",
    "64. 재난정신건강서비스",
    "72. LH 스마트시티플랫폼",
    "90. 안양시청",
}

SKIP_NAME_PREFIXES = ("★", "■", "▶", "[")
SKIP_NAME_TOKENS = {
    "사업관리", "사업계획서", "협약서", "사업수행", "misc", "backup", "zoom",
    "제안검토", "제안실주", "제안일정", "제안준비", "사업개발", "사전규격", "입찰정보",
    "타컨설팅사", "타업체", "전문가", "자문위원", "감리분야", "방법론",
    "위즐리유니버시티", "위즐리앤로고", "자생한방병원", "제안서자료", "견적준비",
    "r&d사업", "ax전환", "설명회", "유니버시티", "로고", "2025년감리", "2025년정부",
    "2026년도ax",
}


def _is_project_folder(name: str) -> bool:
    if name in ALREADY_PROCESSED:
        return False
    if any(name.startswith(p) for p in SKIP_NAME_PREFIXES):
        return False
    n = name.lower().replace(" ", "").replace("_", "").replace(".", "").replace("-", "")
    for tok in SKIP_NAME_TOKENS:
        if tok.replace(" ", "") in n:
            return False
    return True


def _should_skip_file(path: Path) -> bool:
    if path.name.startswith("~$"):
        return True
    stem_lower = path.stem.lower()
    if any(tok in stem_lower for tok in IGNORE_TOKENS):
        return True
    try:
        if path.stat().st_size > MAX_FILE_MB * 1024 * 1024:
            return True
        if path.stat().st_size < 1024:  # skip tiny files
            return True
    except OSError:
        return True
    return False


def _guess_category(path: Path) -> str:
    text = (path.stem + " " + " ".join(p for p in path.parts[-4:])).lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return cat
    return "final_report"


def _ext_priority(path: Path) -> int:
    try:
        return PRIORITY_EXTS.index(path.suffix.lower())
    except ValueError:
        return len(PRIORITY_EXTS)


def _scan_folder(folder: Path, max_depth: int = 4) -> list[Path]:
    results: list[Path] = []

    def _walk(p: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            for child in sorted(p.iterdir()):
                if child.is_file() and child.suffix.lower() in PHASE1_EXTS:
                    if not _should_skip_file(child):
                        results.append(child)
                elif child.is_dir():
                    _walk(child, depth + 1)
        except (PermissionError, OSError):
            pass

    _walk(folder, 0)
    return results


def _pick_per_category(files: list[Path]) -> dict[str, Path]:
    """Pick best file per category — prefer ext priority, then larger size."""
    by_cat: dict[str, list[Path]] = {}
    for f in files:
        cat = _guess_category(f)
        by_cat.setdefault(cat, []).append(f)

    used: set[Path] = set()
    picked: dict[str, Path] = {}
    order = ["final_report", "proposal", "rfp", "presentation", "kickoff"]
    for cat in order:
        candidates = [p for p in by_cat.get(cat, []) if p not in used]
        if not candidates:
            continue
        best = min(candidates, key=lambda p: (_ext_priority(p), -p.stat().st_size))
        picked[cat] = best
        used.add(best)
    return picked


def main() -> None:
    OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)

    # Collect project folders
    project_folders: list[Path] = []
    for folder in sorted(SOURCE_ROOT.iterdir()):
        if folder.is_dir() and _is_project_folder(folder.name):
            project_folders.append(folder)

    print(f"Project folders to scan: {len(project_folders)}", flush=True)

    now_iso = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    records: list[dict] = []
    summary_rows: list[dict] = []
    doc_counter = 1

    for i, folder in enumerate(project_folders, 1):
        fname = folder.name
        print(f"[{i:2d}/{len(project_folders)}] {fname} ...", end=" ", flush=True)

        files = _scan_folder(folder)
        picked = _pick_per_category(files)

        print(f"{len(files)} files → {len(picked)} selected", flush=True)

        for cat, file_path in sorted(picked.items()):
            rel = file_path.relative_to(SOURCE_ROOT)
            snap_path = f"data/raw/{SNAPSHOT_NAME}/domestic_business/{rel.as_posix()}"
            doc_id = f"DOC-20260507B4-{doc_counter:06d}"
            doc_counter += 1

            records.append({
                "document_id": doc_id,
                "source_root": str(SOURCE_ROOT),
                "source_path": str(file_path),
                "relative_path": rel.as_posix(),
                "snapshot_name": SNAPSHOT_NAME,
                "snapshot_path": snap_path,
                "sha256": "",
                "size_bytes": file_path.stat().st_size,
                "modified_at": datetime.fromtimestamp(
                    file_path.stat().st_mtime, tz=timezone.utc
                ).astimezone().isoformat(timespec="seconds"),
                "copied_at": now_iso,
                "copy_batch": BATCH_ID,
                "copy_status": "planned",
                "extension": file_path.suffix.lower(),
                "phase1_rank": str(i),
                "folder_name": fname,
                "category": cat,
            })

        summary_rows.append({
            "rank": i,
            "folder_name": fname,
            "total_files_scanned": len(files),
            "docs_selected": len(picked),
            "categories": ",".join(sorted(picked.keys())),
        })

    # Write manifest JSONL
    with OUT_JSONL.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Write summary CSV
    with OUT_SUMMARY.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["rank", "folder_name", "total_files_scanned", "docs_selected", "categories"])
        writer.writeheader()
        writer.writerows(summary_rows)

    from collections import Counter
    cats = Counter(r["category"] for r in records)
    exts = Counter(r["extension"] for r in records)
    total_mb = sum(r["size_bytes"] for r in records) / 1024 / 1024

    print()
    print(f"=" * 60)
    print(f"Folders scanned  : {len(project_folders)}")
    print(f"Total docs       : {len(records)}")
    print(f"Total size       : {total_mb:.1f} MB")
    print(f"Categories       : {dict(cats)}")
    print(f"Extensions       : {dict(exts)}")
    print(f"Output JSONL     : {OUT_JSONL}")
    print(f"Output summary   : {OUT_SUMMARY}")


if __name__ == "__main__":
    main()
