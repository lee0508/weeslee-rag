import json, urllib.request
BASE = "http://127.0.0.1:9284/api"
q = "공공기관 + AI 시스템 도입 + 기술및기능 + 선진/유사사례 분석"
data = json.dumps({
    "question": q,
    "source_id": "src_20260702_163210_72c2d5",
    "top_k": 10,
    "max_results": 5,
    "enable_graph": True,
    "enable_wiki": False,
    "generate_answer": False
}, ensure_ascii=False).encode("utf-8")
req = urllib.request.Request(BASE + "/rag/hybrid-query", data=data, headers={"Content-Type":"application/json"})
with urllib.request.urlopen(req, timeout=120) as r:
    payload = json.loads(r.read().decode("utf-8"))
docs = payload.get("merged_documents") or []
print("COUNT", len(docs))
print("SEARCH_ORDER", payload.get("search_order"))
print("FAISS", len(payload.get("faiss_results") or []), "GRAPH", len(payload.get("graph_results") or []))
for idx, doc in enumerate(docs[:5], 1):
    print(idx, doc.get("file_name"), "|", doc.get("score"), "|", doc.get("search_source") or doc.get("source"))
