"""
RAG retrieval benchmark runner.

Reads tests/queries/*.json, queries the live RAG API, and scores keyword hits
against expected_keywords from each query definition.

Output: JSONL progress lines + final {"benchmark_complete": true, ...} line.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUERIES_DIR = PROJECT_ROOT / "tests" / "queries"
RESULTS_DIR = PROJECT_ROOT / "data" / "staged"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RAG benchmark runner")
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--top-docs", type=int, default=5)
    parser.add_argument("--answer-provider", default="search_only")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def query_rag(server: str, query: str, category: str | None, top_k: int, top_docs: int, answer_provider: str) -> dict:
    payload: dict = {
        "query": query,
        "top_k": top_k,
        "top_docs": top_docs,
        "answer_provider": answer_provider,
    }
    if category:
        payload["category"] = category
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{server}/api/rag/query",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"error": str(exc), "documents": [], "draft_answer": ""}


def score_result(result: dict, expected_keywords: list[str], min_kw_score: float, min_docs: int) -> dict:
    docs = result.get("documents", [])

    # Build searchable corpus: draft_answer + all evidence snippets + project names
    corpus_parts: list[str] = [
        (result.get("draft_answer") or "").lower(),
    ]
    for doc in docs:
        for snippet in doc.get("evidence_snippets", []):
            corpus_parts.append(snippet.lower())
        corpus_parts.append((doc.get("project_name") or "").lower())
    corpus = " ".join(corpus_parts)

    kw_hits = sum(1 for kw in expected_keywords if kw.lower() in corpus)
    kw_score = kw_hits / len(expected_keywords) if expected_keywords else 0.0
    passed = kw_score >= min_kw_score and len(docs) >= min_docs

    return {
        "doc_count":  len(docs),
        "kw_hits":    kw_hits,
        "kw_total":   len(expected_keywords),
        "kw_score":   round(kw_score, 3),
        "pass_kw":    kw_score >= min_kw_score,
        "pass_docs":  len(docs) >= min_docs,
        "pass":       passed,
        "error":      result.get("error"),
    }


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def main() -> int:
    args = parse_args()

    query_files = sorted(QUERIES_DIR.glob("*_queries.json"))
    if not query_files:
        emit({"error": f"No query files found in {QUERIES_DIR}"})
        return 1

    all_results: list[dict] = []
    total_run = 0

    for qf in query_files:
        cat_name = qf.stem.replace("_queries", "")
        try:
            queries = json.loads(qf.read_text(encoding="utf-8"))
        except Exception as exc:
            emit({"warning": f"Could not read {qf.name}: {exc}"})
            continue

        for q in queries:
            query_text = q.get("query", "")
            expected_keywords = q.get("expected_keywords", [])
            expected_category = q.get("expected_category", cat_name)
            min_kw_score = float(q.get("min_kw_score", 0.5))
            min_docs = int(q.get("min_docs", 1))

            total_run += 1
            emit({"running": query_text, "category": cat_name, "n": total_run})

            rag_result = query_rag(
                args.server, query_text, expected_category,
                args.top_k, args.top_docs, args.answer_provider,
            )
            scores = score_result(rag_result, expected_keywords, min_kw_score, min_docs)

            row = {
                "category": cat_name,
                "query": query_text,
                "expected_keywords": expected_keywords,
                "min_kw_score": min_kw_score,
                **scores,
            }
            all_results.append(row)
            emit({"result": row})

    total = len(all_results)
    passed = sum(1 for r in all_results if r["pass"])
    avg_kw = sum(r["kw_score"] for r in all_results) / total if total else 0.0

    summary = {
        "total":        total,
        "passed":       passed,
        "failed":       total - passed,
        "pass_rate":    round(passed / total, 3) if total else 0.0,
        "avg_kw_score": round(avg_kw, 3),
        "run_at":       datetime.now().isoformat(timespec="seconds"),
    }

    # Save to file
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.output) if args.output else RESULTS_DIR / f"benchmark_{ts}.json"
    out_path.write_text(
        json.dumps({"summary": summary, "results": all_results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    emit({"benchmark_complete": True, "summary": summary, "output": str(out_path)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
