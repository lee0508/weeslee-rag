import json, urllib.request
BASE = "http://127.0.0.1:9284/api"
q = "공공기관 + AI 시스템 도입 + 기술및기능 + 선진/유사사례 분석"

def post(path, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))

hybrid = post("/rag/hybrid-query", {
    "question": q,
    "source_id": "src_20260702_163210_72c2d5",
    "top_k": 10,
    "max_results": 5,
    "enable_graph": True,
    "enable_wiki": False,
    "generate_answer": False
})
print(json.dumps({
    "search_order": hybrid.get("search_order"),
    "faiss_count": len(hybrid.get("faiss_results") or []),
    "graph_count": len(hybrid.get("graph_results") or []),
    "merged_count": len(hybrid.get("merged_documents") or []),
    "faiss_top": [d.get("file_name") for d in (hybrid.get("faiss_results") or [])[:5]],
    "graph_top": [d.get("file_name") for d in (hybrid.get("graph_results") or [])[:5]],
    "merged_top": [d.get("file_name") for d in (hybrid.get("merged_documents") or [])[:5]],
}, ensure_ascii=False, indent=2))
