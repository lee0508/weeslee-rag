"""Quick validation of category filter and max_chunks_per_doc features."""
import json
import urllib.request

SERVER = "http://192.168.0.207:8080"


def query_rag(q, category=None, max_chunks=3):
    payload = {"query": q, "top_k": 20, "top_docs": 5, "max_chunks_per_doc": max_chunks}
    if category:
        payload["category"] = category
    req = urllib.request.Request(
        f"{SERVER}/api/rag/query",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


print("=== Test 1: category=rfp filter ===")
res = query_rag("ISP 사업 제안요청서 요구사항 항목", category="rfp")
cats = [d["category"] for d in res["documents"]]
print(f"  docs={len(res['documents'])}, categories={cats}")
print(f"  category_filter={res.get('category_filter')}")
assert all(c == "rfp" for c in cats), f"Non-rfp category found: {cats}"
print("  PASS: all returned docs are rfp")

print()
print("=== Test 2: max_chunks_per_doc=3 (default) ===")
res2 = query_rag("ISP 최종 산출물 목차 구성", max_chunks=3)
hits = [(d["document_id"], d["hit_count"]) for d in res2["documents"]]
print(f"  docs={len(res2['documents'])}: {hits}")
max_hit = max(d["hit_count"] for d in res2["documents"]) if res2["documents"] else 0
print(f"  max hit_count per doc = {max_hit}")
assert max_hit <= 3, f"hit_count {max_hit} exceeds max_chunks_per_doc=3"
print("  PASS: no doc has more than 3 chunks")

print()
print("=== Test 3: max_chunks_per_doc=1 (max diversity) ===")
res3 = query_rag("ISP 최종 산출물 목차 구성", max_chunks=1)
hits3 = [(d["document_id"], d["hit_count"]) for d in res3["documents"]]
print(f"  docs={len(res3['documents'])}: {hits3}")
max_hit3 = max(d["hit_count"] for d in res3["documents"]) if res3["documents"] else 0
assert max_hit3 <= 1, f"hit_count {max_hit3} exceeds max_chunks_per_doc=1"
print("  PASS: all docs have hit_count=1")

print()
print("All feature tests PASSED.")
