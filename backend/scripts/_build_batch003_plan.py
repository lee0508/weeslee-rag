"""
Build batch-003 folder plan CSV from top-10 new project folders
(not covered in batch-002) sorted by file count.
"""
import csv
from pathlib import Path

# Top-10 new project folders by file count (excluding admin/non-project folders)
TOP10_BATCH003 = [
    ("201703. 통계청 통계지리정보서비스 ISP",      1149),
    ("64. 재난정신건강서비스",                        915),
    ("202312. 법무부_디지털플랫폼 교육강화, 환경개선 로드맵 연구사업", 889),
    ("149. 국토지리정보원",                           863),
    ("202305. AI 기반 지능형 진로교육정보망",          787),
    ("215. K-water 데이터허브",                       765),
    ("90. 안양시청",                                  686),
    ("202407. 범죄예방정책_거대언어모델 도입활용방안 연구", 608),
    ("202407. 양형기준 운영점검시스템 및 양형정보시스템의 고도화를 위한 AI시스템 구축 ISP", 233),
    ("202604. 과기정통부 AI-NEXT 고도화 ISP 수립",    139),
]

# category → typical subpath patterns (batch-002 pattern generalized)
CATEGORY_SUBPATHS = {
    "rfp":          ("00. RFP", "RFP 원본 우선, 없으면 제안요청서/과업지시서"),
    "proposal":     ("★ 제안서", "최종 제안본 우선, 없으면 01. 제안서"),
    "kickoff":      ("사업수행", "착수보고 키워드 파일 우선"),
    "final_report": ("★ 산출물", "최종보고/완료보고서/산출물 우선"),
    "presentation": ("★ 발표자료", "발표 최종본 우선"),
}

out = Path("data/staged/manifest/phase1_representative_folder_plan_batch003.csv")
rows = []
for rank, (folder, file_count) in enumerate(TOP10_BATCH003, start=1):
    for category, (subpath, note) in CATEGORY_SUBPATHS.items():
        rows.append({
            "phase1_rank": rank,
            "folder_name": folder,
            "category": category,
            "preferred_subpath": subpath,
            "selection_note": f"[{file_count} files] {note}",
        })

with out.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["phase1_rank", "folder_name", "category", "preferred_subpath", "selection_note"])
    writer.writeheader()
    writer.writerows(rows)

print(f"Written {len(rows)} rows ({len(TOP10_BATCH003)} folders × 5 categories) → {out}")
for rank, (folder, cnt) in enumerate(TOP10_BATCH003, 1):
    print(f"  [{rank:2d}] {folder} ({cnt} files)")
