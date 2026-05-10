"""
RAG quality evaluation for combined (batch-002 + batch-003) index.
Compares against batch-002 results from data/staged/rag_quality_eval_batch002.json
"""
import json
import urllib.request
import urllib.error
from pathlib import Path

SERVER = "http://192.168.0.207:8080"

TEST_QUERIES = [
    ("rfp",           "ISP 사업 제안요청서 요구사항 항목",       ["제안요청", "rfp", "요구사항", "과업"]),
    ("rfp",           "정보화전략계획 수립 과업 범위",            ["isp", "과업", "범위", "정보화"]),
    ("proposal",      "ISP 컨설팅 제안서 방법론 구성",           ["방법론", "제안서", "isp", "컨설팅"]),
    ("proposal",      "AX 전환 전략 제안 핵심 내용",             ["ax", "전환", "전략", "제안"]),
    ("kickoff",       "착수보고 추진 일정 주요 내용",             ["착수", "일정", "추진", "보고"]),
    ("kickoff",       "사업 착수 후 초기 단계 활동",              ["착수", "단계", "활동", "사업"]),
    ("final_report",  "ISP 최종 산출물 목차 구성",               ["최종", "산출물", "목차", "isp"]),
    ("final_report",  "정보화전략 이행계획서 주요 과제",           ["이행", "과제", "정보화", "계획"]),
    ("presentation",  "ISP 중간보고 발표 슬라이드 구성",          ["중간보고", "발표", "슬라이드"]),
    ("presentation",  "최종보고회 발표자료 핵심 메시지",           ["최종보고", "발표", "메시지"]),
]


def query_rag(query: str, top_k: int = 5) -> dict:
    payload = json.dumps({"query": query, "top_k": top_k, "stream": False}).encode("utf-8")
    req = urllib.request.Request(
        f"{SERVER}/api/rag/query",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e), "documents": [], "draft_answer": ""}


def score(result: dict, keywords: list[str]) -> dict:
    answer = (result.get("draft_answer") or "").lower()
    docs = result.get("documents", [])
    kw_hits = sum(1 for kw in keywords if kw.lower() in answer)
    return {
        "doc_count": len(docs),
        "unique_docs": len(set(d.get("document_id", "") for d in docs)),
        "categories": [d.get("category", "") for d in docs],
        "project_names": [d.get("project_name", "") for d in docs],
        "kw_score": kw_hits / len(keywords) if keywords else 0,
        "kw_hits": kw_hits,
        "answer_len": len(answer),
        "answer_preview": answer[:150].replace("\n", " "),
    }


print("=" * 80)
print("RAG Quality Evaluation: combined-v1 (61 docs, 6760 vectors)")
print("=" * 80)

results = []
total_kw = 0.0
total_docs = 0

for i, (cat, query, keywords) in enumerate(TEST_QUERIES, 1):
    print(f"[{i:2d}] [{cat}] {query}")
    res = query_rag(query)
    s = score(res, keywords)
    total_kw += s["kw_score"]
    total_docs += s["doc_count"]
    print(f"      docs={s['doc_count']} unique={s['unique_docs']} "
          f"kw={s['kw_hits']}/{len(keywords)} ({s['kw_score']:.0%}) "
          f"ans_len={s['answer_len']}")
    print(f"      projects: {s['project_names'][:3]}")
    print()
    results.append({"query_no": i, "category": cat, "query": query, **s})

avg_kw = total_kw / len(TEST_QUERIES)
avg_docs = total_docs / len(TEST_QUERIES)
print("=" * 80)
print(f"SUMMARY: avg keyword hit rate = {avg_kw:.1%}  |  avg retrieved docs = {avg_docs:.1f}")
print("=" * 80)

# Compare with batch-002
b002_path = Path("data/staged/rag_quality_eval_batch002.json")
if b002_path.exists():
    b002 = json.loads(b002_path.read_text(encoding="utf-8"))
    b002_kw = sum(r["kw_score"] for r in b002) / len(b002)
    b002_docs = sum(r["doc_count"] for r in b002) / len(b002)
    print()
    print("Comparison:")
    print(f"  batch-002 (27 docs): kw={b002_kw:.1%}  docs={b002_docs:.1f}")
    print(f"  combined  (61 docs): kw={avg_kw:.1%}  docs={avg_docs:.1f}")
    print(f"  kw change: {(avg_kw - b002_kw) * 100:+.1f}pp")
    print(f"  docs change: {avg_docs - b002_docs:+.1f}")

out = Path("data/staged/rag_quality_eval_combined.json")
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nResults saved → {out}")
