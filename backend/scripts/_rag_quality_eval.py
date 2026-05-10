"""
RAG quality evaluation: compare batch-001 (5 docs) vs batch-002 (27 docs).
Tests 10 representative queries across 5 categories.
Sends queries to the live server and compares result quality.
"""
import json
import urllib.request
import urllib.error
from pathlib import Path

SERVER = "http://192.168.0.207:8080"

TEST_QUERIES = [
    # (category, query, expected_keywords)
    ("rfp",           "ISP 사업 제안요청서 요구사항 항목", ["제안요청", "rfp", "요구사항", "과업"]),
    ("rfp",           "정보화전략계획 수립 과업 범위", ["isp", "과업", "범위", "정보화"]),
    ("proposal",      "ISP 컨설팅 제안서 방법론 구성", ["방법론", "제안서", "isp", "컨설팅"]),
    ("proposal",      "AX 전환 전략 제안 핵심 내용", ["ax", "전환", "전략", "제안"]),
    ("kickoff",       "착수보고 추진 일정 주요 내용", ["착수", "일정", "추진", "보고"]),
    ("kickoff",       "사업 착수 후 초기 단계 활동", ["착수", "단계", "활동", "사업"]),
    ("final_report",  "ISP 최종 산출물 목차 구성", ["최종", "산출물", "목차", "isp"]),
    ("final_report",  "정보화전략 이행계획서 주요 과제", ["이행", "과제", "정보화", "계획"]),
    ("presentation",  "ISP 중간보고 발표 슬라이드 구성", ["중간보고", "발표", "슬라이드"]),
    ("presentation",  "최종보고회 발표자료 핵심 메시지", ["최종보고", "발표", "메시지"]),
]


def query_rag(query: str, top_k: int = 5) -> dict:
    payload = json.dumps({
        "query": query,
        "top_k": top_k,
        "stream": False,
    }).encode("utf-8")
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


def score_response(result: dict, expected_keywords: list[str]) -> dict:
    answer = (result.get("draft_answer") or "").lower()
    docs = result.get("documents", [])

    kw_hits = sum(1 for kw in expected_keywords if kw.lower() in answer)
    kw_score = kw_hits / len(expected_keywords) if expected_keywords else 0

    categories = [d.get("category", "") for d in docs]
    unique_docs = len(set(d.get("document_id", "") for d in docs))
    answer_len = len(answer)

    return {
        "doc_count": len(docs),
        "unique_docs": unique_docs,
        "categories": categories,
        "kw_score": kw_score,
        "kw_hits": kw_hits,
        "answer_len": answer_len,
        "answer_preview": answer[:150].replace("\n", " "),
    }


print("=" * 80)
print("RAG Quality Evaluation: batch-002 (27 docs) active index")
print("=" * 80)
print()

results = []
total_kw_score = 0.0
total_doc_count = 0

for i, (cat, query, keywords) in enumerate(TEST_QUERIES, 1):
    print(f"[{i:2d}] [{cat}] {query}")
    result = query_rag(query, top_k=5)
    score = score_response(result, keywords)

    total_kw_score += score["kw_score"]
    total_doc_count += score["doc_count"]

    print(f"      docs={score['doc_count']} unique={score['unique_docs']} "
          f"kw={score['kw_hits']}/{len(keywords)} ({score['kw_score']:.0%}) "
          f"ans_len={score['answer_len']}")
    print(f"      answer: {score['answer_preview']}")
    print()

    results.append({
        "query_no": i,
        "category": cat,
        "query": query,
        **score,
    })

avg_kw = total_kw_score / len(TEST_QUERIES)
avg_docs = total_doc_count / len(TEST_QUERIES)
print("=" * 80)
print(f"SUMMARY: avg keyword hit rate = {avg_kw:.1%}  |  avg retrieved docs = {avg_docs:.1f}")
print("=" * 80)

out = Path("data/staged/rag_quality_eval_batch002.json")
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Results saved → {out}")
