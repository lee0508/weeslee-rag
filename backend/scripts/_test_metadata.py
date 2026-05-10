import sys
sys.path.insert(0, "backend/scripts")
from extract_manifest_batch import enrich_project_metadata

cases = [
    "202212. k-water 데이터허브플랫폼_ISP",
    "202503. AX 활용 정보화전략계획수립",
    "20250506. K-water형 고유플랫폼 구축을 위한 전략계획 수립",
    "202005. 안양시ISP_발표자료",
    "202506. 법무부LLM 구축",
    "2024. 법무부_성범죄백서",
    "",
]
for c in cases:
    r = enrich_project_metadata(c)
    print("IN :", repr(c))
    print("OUT: project_name=%r  year=%r" % (r["project_name"], r["folder_year"]))
    print()
