import csv
from pathlib import Path

TOP10 = [
    ("201703. 통계청 통계지리정보서비스 ISP",      1149, 7037),
    ("64. 재난정신건강서비스",                        915, 2816),
    ("202312. 법무부_디지털플랫폼 교육강화, 환경개선 로드맵 연구사업", 889, 2135),
    ("149. 국토지리정보원",                           863, 4580),
    ("202305. AI 기반 지능형 진로교육정보망",          787, 3520),
    ("215. K-water 데이터허브",                       765, 5712),
    ("90. 안양시청",                                  686, 4904),
    ("202407. 범죄예방정책_거대언어모델 도입활용방안 연구", 608, 1767),
    ("202407. 양형기준 운영점검시스템 및 양형정보시스템의 고도화를 위한 AI시스템 구축 ISP", 233, 168),
    ("202604. 과기정통부 AI-NEXT 고도화 ISP 수립",    139, 964),
]

out = Path("data/staged/manifest/phase1_project_candidates_batch003.csv")
fields = ["phase1_rank", "folder_name", "file_count", "total_size_mb",
          "phase1_status", "recommended_sample_docs", "priority", "selection_reason"]

with out.open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_ALL)
    w.writeheader()
    for rank, (folder, count, size) in enumerate(TOP10, 1):
        w.writerow({
            "phase1_rank": rank,
            "folder_name": folder,
            "file_count": count,
            "total_size_mb": size,
            "phase1_status": "partial_sample",
            "recommended_sample_docs": 8,
            "priority": "high",
            "selection_reason": "batch-003 신규 프로젝트 폴더",
        })

print(f"Written {len(TOP10)} candidates → {out}")
