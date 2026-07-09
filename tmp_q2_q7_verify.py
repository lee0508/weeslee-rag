import json, urllib.request
BASE = "http://127.0.0.1:9284/api"
SOURCE_ID = "src_20260702_163210_72c2d5"
SNAPSHOT_ID = "snapshot_20260702_src_20260702_163210_72c2d5_V1"
queries = {
    "Q2": "프로젝트관리 폴더 안의 의사소통 관리 내용 검색",
    "Q3": "업무시스템 개선 관련 사업의 기술및기능 제안서 검색",
    "Q4": "업무시스템 개선 관련 사업의 환경분석 산출물 검색",
    "Q5": "연구기관 고객의 컨설팅 사업 탐색",
    "Q6": "플랫폼 개선/고도화 관련 현황분석 산출물 검색",
    "Q7": "공공기관 + AI 시스템 도입 + 기술및기능 + 선진/유사사례 분석",
}

def post(path, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))

for key, q in queries.items():
    general = post("/rag/query", {
        "query": q,
        "top_k": 10,
        "top_docs": 5,
        "max_chunks_per_doc": 3,
        "mode": "general",
        "answer_provider": "none",
        "answer_model": "",
        "snapshot_ids": [SNAPSHOT_ID]
    })
    hybrid = post("/rag/hybrid-query", {
        "question": q,
        "source_id": SOURCE_ID,
        "top_k": 10,
        "max_results": 5,
        "enable_graph": True,
        "enable_wiki": False,
        "generate_answer": False
    })
    general_docs = general.get("documents") or general.get("results") or []
    hybrid_docs = hybrid.get("merged_documents") or hybrid.get("documents") or []
    print(f"## {key}")
    print(q)
    print("GENERAL_COUNT", len(general_docs))
    print("HYBRID_COUNT", len(hybrid_docs))
    print("HYBRID_SEARCH_ORDER", hybrid.get("search_order"))
    print("HYBRID_QUERY_ANALYSIS", json.dumps(hybrid.get("query_analysis") or {}, ensure_ascii=False))
    print("GENERAL_TOP")
    for idx, doc in enumerate(general_docs[:3], 1):
        print(idx, doc.get("file_name") or doc.get("filename") or doc.get("title") or "-", "|", doc.get("score"))
    print("HYBRID_TOP")
    for idx, doc in enumerate(hybrid_docs[:3], 1):
        print(idx, doc.get("file_name") or doc.get("filename") or doc.get("title") or "-", "|", doc.get("score"), "|", doc.get("search_source") or doc.get("source"))
    print()
