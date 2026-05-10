"""
Fast representative doc selection for batch-003.
Scans max depth 3 in each project folder. Uses filename keywords for category.
Produces manifest-ready CSV compatible with build_manifest_from_selected_csv.py.
"""
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

SOURCE_ROOT = Path(r"W:\01. 국내사업폴더")
SNAPSHOT_NAME = "snapshot_2026-05-06_batch-003-top10-v1"
BATCH_ID = "batch-003-top10-v1"
OUT_JSONL = Path("data/staged/manifest/snapshot_2026-05-06_batch-003-top10-v1_manifest.jsonl")

PHASE1_EXTS = {".pdf", ".pptx", ".docx", ".xlsx"}
SKIP_EXTS = {".hwp", ".hwpx"}  # record but mark skip

CATEGORY_KEYWORDS = {
    "rfp":          ["rfp", "제안요청", "과업지시", "입찰공고", "과업내용"],
    "proposal":     ["제안서", "제안발표", "평가본", "최종제안"],
    "kickoff":      ["착수", "착수계", "착수보고", "kick"],
    "final_report": ["최종", "완료보고", "산출물", "최종보고", "최종산출"],
    "presentation": ["발표자료", "발표본", "발표", "ppt발표"],
}
IGNORE_TOKENS = {"old", "백업", "backup", "tmp", "임시", "참고자료", "참조", "기타", "작업폴더"}
MAX_FILE_MB = 100  # skip files larger than 100 MB

TOP10 = [
    "201703. 통계청 통계지리정보서비스 ISP",
    "64. 재난정신건강서비스",
    "202312. 법무부_디지털플랫폼 교육강화, 환경개선 로드맵 연구사업",
    "149. 국토지리정보원",
    "202305. AI 기반 지능형 진로교육정보망",
    "215. K-water 데이터허브",
    "90. 안양시청",
    "202407. 범죄예방정책_거대언어모델 도입활용방안 연구",
    "202407. 양형기준 운영점검시스템 및 양형정보시스템의 고도화를 위한 AI시스템 구축 ISP",
    "202604. 과기정통부 AI-NEXT 고도화 ISP 수립",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def guess_category(path: Path) -> str:
    text = (path.stem + " " + " ".join(path.parts)).lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return cat
    return "final_report"


def should_skip(path: Path) -> bool:
    name_lower = path.stem.lower()
    # Skip Office temp files (~$...)
    if path.name.startswith("~$"):
        return True
    # Skip by token
    if any(tok in name_lower for tok in IGNORE_TOKENS):
        return True
    # Skip oversized files
    try:
        if path.stat().st_size > MAX_FILE_MB * 1024 * 1024:
            return True
    except OSError:
        return True
    return False


def scan_folder_shallow(folder: Path, max_depth: int = 3) -> list[Path]:
    """Scan folder up to max_depth, return Phase1-supported files."""
    results = []

    def _walk(p: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            for child in sorted(p.iterdir()):
                if child.is_file() and child.suffix.lower() in PHASE1_EXTS:
                    if not should_skip(child):
                        results.append(child)
                elif child.is_dir():
                    _walk(child, depth + 1)
        except PermissionError:
            pass

    _walk(folder, 0)
    return results


def pick_best_per_category(files: list[Path]) -> dict[str, Path]:
    """Pick one file per category. Prefer larger files as more content-rich.
    Ensures no file is used in two categories (dedup by path).
    """
    by_cat: dict[str, list[Path]] = {}
    for f in files:
        cat = guess_category(f)
        by_cat.setdefault(cat, []).append(f)

    used: set[Path] = set()
    picked: dict[str, Path] = {}
    # Process in priority order so final_report/proposal get first pick
    for cat in ["final_report", "proposal", "rfp", "presentation", "kickoff"]:
        if cat not in by_cat:
            continue
        candidates = [p for p in by_cat[cat] if p not in used]
        if not candidates:
            continue
        best = max(candidates, key=lambda p: p.stat().st_size)
        picked[cat] = best
        used.add(best)
    return picked


now_iso = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
records = []
doc_counter = 1

for folder_name in TOP10:
    folder_path = SOURCE_ROOT / folder_name
    if not folder_path.exists():
        print(f"  MISSING: {folder_name}")
        continue

    print(f"Scanning: {folder_name} ...", end=" ", flush=True)
    files = scan_folder_shallow(folder_path, max_depth=3)
    print(f"{len(files)} Phase1 files found")

    picked = pick_best_per_category(files)

    for cat, file_path in sorted(picked.items()):
        rel = file_path.relative_to(SOURCE_ROOT)
        snap_path = f"data/raw/{SNAPSHOT_NAME}/domestic_business/{rel.as_posix()}"
        doc_id = f"DOC-20260506B3-{doc_counter:06d}"
        doc_counter += 1

        records.append({
            "document_id": doc_id,
            "source_root": str(SOURCE_ROOT),
            "source_path": str(file_path),
            "relative_path": rel.as_posix(),
            "snapshot_name": SNAPSHOT_NAME,
            "snapshot_path": snap_path,
            "sha256": "",  # skip hash for speed; fill later if needed
            "size_bytes": file_path.stat().st_size,
            "modified_at": datetime.fromtimestamp(
                file_path.stat().st_mtime, tz=timezone.utc
            ).astimezone().isoformat(timespec="seconds"),
            "copied_at": now_iso,
            "copy_batch": BATCH_ID,
            "copy_status": "planned",
            "extension": file_path.suffix.lower(),
            "phase1_rank": str(TOP10.index(folder_name) + 1),
            "folder_name": folder_name,
            "category": cat,
        })

OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
with OUT_JSONL.open("w", encoding="utf-8") as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

# Summary
from collections import Counter
cats = Counter(r["category"] for r in records)
exts = Counter(r["extension"] for r in records)
total_mb = sum(r["size_bytes"] for r in records) / 1024 / 1024
hwp_count = sum(1 for r in records if r["extension"] in {".hwp", ".hwpx"})
phase1_count = sum(1 for r in records if r["extension"] in PHASE1_EXTS)

print()
print(f"Total documents : {len(records)}")
print(f"Phase1 (non-HWP): {phase1_count}")
print(f"Total size      : {total_mb:.1f} MB")
print(f"Categories      : {dict(cats)}")
print(f"Extensions      : {dict(exts)}")
print(f"Output          : {OUT_JSONL}")
