import json, urllib.request
BASE = "http://127.0.0.1:9284/api"
cases = [
    ("raw", {
        "question": "공공기관 + AI 시스템 도입 + 기술및기능 + 선진/유사사례 분석",
        "source_id": "src_20260702_163210_72c2d5",
        "top_k": 10,
        "max_results": 5,
        "enable_graph": True,
        "enable_wiki": False,
        "generate_answer": False
    }),
    ("clean", {
        "question": "공공기관 AI 시스템 도입 기술및기능 선진사례 유사사례 분석",
        "source_id": "src_20260702_163210_72c2d5",
        "top_k": 10,
        "max_results": 5,
        "enable_graph": True,
        "enable_wiki": False,
        "generate_answer": False
    }),
    ("expanded", {
        "question": "공공기관 + AI 시스템 도입 + 기술및기능 + 선진/유사사례 분석",
        "expanded_query": "공공기관 AI 시스템 도입 기술및기능 선진사례 유사사례 분석",
        "source_id": "src_20260702_163210_72c2d5",
        "top_k": 10,
        "max_results": 5,
        "enable_graph": True,
        "enable_wiki": False,
        "generate_answer": False
    }),
    ("simple", {
        "question": "AI 기술및기능 유사사례",
        "source_id": "src_20260702_163210_72c2d5",
        "top_k": 10,
        "max_results": 5,
        "enable_graph": True,
        "enable_wiki": False,
        "generate_answer": False
    }),
]
for name, payload in cases:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + "/rag/hybrid-query", data=data, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.loads(r.read().decode("utf-8"))
    docs = out.get("merged_documents") or []
    print("##", name)
    print("COUNT", len(docs), "ORDER", out.get("search_order"), "FAISS", len(out.get("faiss_results") or []), "GRAPH", len(out.get("graph_results") or []))
    for i, d in enumerate(docs[:3], 1):
        print(i, d.get("file_name"), d.get("score"), d.get("search_source") or d.get("source"))
    print()
