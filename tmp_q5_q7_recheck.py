import json, urllib.request
BASE = "http://127.0.0.1:9284/api"
SOURCE_ID = "src_20260702_163210_72c2d5"
queries = {
    "Q5": "연구기관 고객의 컨설팅 사업 탐색",
    "Q7": "공공기관 + AI 시스템 도입 + 기술및기능 + 선진/유사사례 분석",
}

def post(path, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))

for key, q in queries.items():
    hybrid = post("/rag/hybrid-query", {
        "question": q,
        "source_id": SOURCE_ID,
        "top_k": 10,
        "max_results": 5,
        "enable_graph": True,
        "enable_wiki": False,
        "generate_answer": False
    })
    docs = hybrid.get("merged_documents") or []
    print(f"## {key}")
    print("COUNT", len(docs))
    print("SEARCH_ORDER", hybrid.get("search_order"))
    print("FAISS", len(hybrid.get("faiss_results") or []), "GRAPH", len(hybrid.get("graph_results") or []))
    for idx, doc in enumerate(docs[:5], 1):
        print(idx, doc.get("file_name"), "|", doc.get("score"), "|", doc.get("search_source") or doc.get("source"))
    print()
