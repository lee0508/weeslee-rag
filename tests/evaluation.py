"""
Automated RAG benchmark evaluation.

Usage:
    python tests/evaluation.py [--server http://192.168.0.207:8080] [--category rfp]
    python tests/evaluation.py --all          # run all categories
    python tests/evaluation.py --html         # write HTML report to tests/report.html
"""

from __future__ import annotations

import argparse
import json
import ssl
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

QUERIES_DIR = Path(__file__).parent / "queries"

# Allow self-signed certs on internal server
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE
CATEGORIES = ["rfp", "proposal", "kickoff", "final_report", "presentation", "bid_project"]
DEFAULT_SERVER = "http://192.168.0.207:8080"

# Search mode per category (bid_project uses bid_project mode, rfp uses rfp_analysis)
CATEGORY_MODE = {
    "rfp": "rfp_analysis",
    "proposal": "bid_project",
    "kickoff": "general",
    "final_report": "general",
    "presentation": "general",
    "bid_project": "bid_project",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RAG benchmark evaluation")
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--category", choices=CATEGORIES, help="Run single category")
    parser.add_argument("--all", action="store_true", help="Run all categories")
    parser.add_argument("--html", action="store_true", help="Write HTML report")
    parser.add_argument("--no-category-filter", action="store_true",
                        help="Run without category pre-filter (tests combined index)")
    parser.add_argument("--retrieval-only", action="store_true", default=True,
                        help="Score on retrieved docs only, skip Ollama answer generation (default: True)")
    parser.add_argument("--sleep", type=float, default=0.0,
                        help="Seconds to sleep between queries (default 0; use 2.0 for Ollama full-gen mode)")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Per-query timeout in seconds (default 300)")
    return parser.parse_args()


def get_active_snapshot(server: str) -> str:
    """Fetch active snapshot name from admin/stats."""
    req = urllib.request.Request(f"{server}/api/admin/stats", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as r:
            return json.loads(r.read()).get("snapshot", "unknown")
    except Exception:
        return "unknown"


def query_rag(server: str, query: str, category: str | None, top_k: int = 5,
              retrieval_only: bool = True, timeout: int = 300,
              mode: str = "general") -> dict:
    payload: dict = {
        "query": query,
        "top_k": top_k,
        "top_docs": 5,
        "mode": mode,
        "max_chunks_per_doc": 3,
    }
    # bid_project category is a cross-category search — no category filter
    if category and category != "bid_project":
        payload["category"] = category
    if retrieval_only:
        payload["answer_provider"] = "none"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{server}/api/rag/query",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e), "documents": [], "draft_answer": ""}


def score_result(result: dict, case: dict, retrieval_only: bool = False) -> dict:
    answer = (result.get("draft_answer") or "").lower()
    docs = result.get("documents", [])
    keywords = case.get("expected_keywords", [])
    expected_cat = case.get("expected_category", "")

    if retrieval_only:
        returned_cats = [d.get("category", "") for d in docs]
        if expected_cat:
            # Category-filtered search: score by fraction of docs matching expected category
            cat_hits = sum(1 for c in returned_cats if c == expected_cat)
            kw_hits = cat_hits
            kw_score = cat_hits / len(returned_cats) if returned_cats else 0.0
        else:
            # Cross-category search (bid_project): score by whether min_docs is reached
            min_docs = case.get("min_docs", 1)
            unique_doc_count = len({d.get("document_id", "") for d in docs})
            kw_hits = unique_doc_count
            kw_score = min(1.0, unique_doc_count / max(min_docs, 1))
    else:
        kw_hits = sum(1 for kw in keywords if kw.lower() in answer)
        kw_score = kw_hits / len(keywords) if keywords else 0.0

    returned_cats = [d.get("category", "") for d in docs]
    cat_match = sum(1 for c in returned_cats if c == expected_cat) / len(returned_cats) if returned_cats else 0.0

    projects = list({d.get("project_name", "") for d in docs if d.get("project_name")})
    unique_docs = len({d.get("document_id", "") for d in docs})

    return {
        "query": case["query"],
        "kw_score": round(kw_score, 3),
        "kw_hits": kw_hits,
        "kw_total": len(keywords),
        "cat_match_rate": round(cat_match, 3),
        "doc_count": len(docs),
        "unique_docs": unique_docs,
        "answer_len": len(answer),
        "projects": projects[:3],
        "categories_returned": returned_cats[:5],
        "pass_kw": kw_score >= case.get("min_kw_score", 0.5),
        "pass_docs": unique_docs >= case.get("min_docs", 1),
        "answer_preview": answer[:120].replace("\n", " "),
    }


def run_category(server: str, category: str, use_filter: bool, retrieval_only: bool = True,
                 query_sleep: float = 0.0) -> dict:
    query_file = QUERIES_DIR / f"{category}_queries.json"
    if not query_file.exists():
        print(f"  [SKIP] No query file: {query_file}")
        return {"category": category, "results": [], "avg_kw": 0.0, "pass_rate": 0.0,
                "query_count": 0}

    cases = json.loads(query_file.read_text(encoding="utf-8"))
    results = []
    search_mode = CATEGORY_MODE.get(category, "general")
    for case in cases:
        cat_filter = category if (use_filter and category != "bid_project") else None
        # Allow per-case mode override
        effective_mode = case.get("mode", search_mode)
        raw = query_rag(server, case["query"], cat_filter, retrieval_only=retrieval_only,
                        mode=effective_mode)
        s = score_result(raw, case, retrieval_only=retrieval_only)
        results.append(s)
        if query_sleep > 0:
            import time
            time.sleep(query_sleep)
        status = "PASS" if (s["pass_kw"] and s["pass_docs"]) else "FAIL"
        print(
            f"  [{status}] kw={s['kw_hits']}/{s['kw_total']} "
            f"cats={s['categories_returned'][:2]} "
            f"docs={s['unique_docs']} | {case['query'][:50]}"
        )

    avg_kw = sum(r["kw_score"] for r in results) / len(results) if results else 0.0
    pass_rate = sum(1 for r in results if r["pass_kw"] and r["pass_docs"]) / len(results) if results else 0.0
    return {
        "category": category,
        "results": results,
        "avg_kw": round(avg_kw, 3),
        "pass_rate": round(pass_rate, 3),
        "query_count": len(results),
    }


def write_html(report: list[dict], out_path: Path) -> None:
    rows = ""
    for cat_data in report:
        cat = cat_data["category"]
        for r in cat_data["results"]:
            status = "pass" if (r["pass_kw"] and r["pass_docs"]) else "fail"
            rows += (
                f'<tr class="{status}">'
                f'<td>{cat}</td>'
                f'<td>{r["query"]}</td>'
                f'<td>{r["kw_hits"]}/{r["kw_total"]} ({r["kw_score"]:.0%})</td>'
                f'<td>{r["unique_docs"]}</td>'
                f'<td>{", ".join(r["categories_returned"][:3])}</td>'
                f'<td>{r["answer_len"]}</td>'
                f'</tr>\n'
            )

    summary_rows = ""
    for cat_data in report:
        summary_rows += (
            f'<tr><td>{cat_data["category"]}</td>'
            f'<td>{cat_data["query_count"]}</td>'
            f'<td>{cat_data["avg_kw"]:.1%}</td>'
            f'<td>{cat_data["pass_rate"]:.1%}</td></tr>\n'
        )

    snapshot_label = ""
    if report:
        snapshot_label = report[0].get("snapshot", "")

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>RAG Evaluation Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}</title>
<style>
body {{font-family: 'Malgun Gothic', sans-serif; margin: 2rem; background:#f5f7fa;}}
h1 {{color:#1B3A6B; border-bottom:3px solid #E8971F; padding-bottom:8px;}}
.meta {{background:#fff;padding:10px 16px;border-radius:8px;margin-bottom:16px;font-size:.9em;color:#555;}}
table {{border-collapse: collapse; width: 100%; background:#fff; border-radius:8px; overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,.1);}}
th, td {{border: 1px solid #eee; padding: 7px 10px; text-align: left; font-size:.88em;}}
th {{background: #1B3A6B; color: white; border-color:#1B3A6B;}}
tr.pass td:first-child {{border-left: 4px solid #22c55e;}}
tr.fail td:first-child {{border-left: 4px solid #ef4444;}}
</style></head><body>
<h1>RAG Evaluation Report</h1>
<div class="meta">
  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} &nbsp;|&nbsp;
  Snapshot: <strong>{snapshot_label}</strong> &nbsp;|&nbsp;
  Mode: search_only (retrieval only)
</div>
<h2>Summary</h2>
<table><tr><th>Category</th><th>Queries</th><th>Avg KW Score</th><th>Pass Rate</th></tr>
{summary_rows}</table>
<h2>Detail</h2>
<table><tr><th>Category</th><th>Query</th><th>KW Score</th><th>Unique Docs</th><th>Categories</th><th>Ans Len</th></tr>
{rows}</table>
</body></html>"""
    out_path.write_text(html, encoding="utf-8")
    print(f"\nHTML report → {out_path}")


def main() -> None:
    args = parse_args()
    use_filter = not args.no_category_filter

    if not args.all and not args.category:
        args.all = True

    categories = [args.category] if args.category else CATEGORIES
    report = []

    snapshot = get_active_snapshot(args.server)
    print(f"Server: {args.server}  |  snapshot: {snapshot}")
    print(f"category_filter={'ON' if use_filter else 'OFF'}  |  retrieval_only={args.retrieval_only}")
    print("=" * 70)

    retrieval_only = getattr(args, 'retrieval_only', True)
    query_sleep = getattr(args, 'sleep', 0.0)
    for cat in categories:
        print(f"\n[{cat.upper()}]")
        cat_data = run_category(args.server, cat, use_filter, retrieval_only=retrieval_only,
                                query_sleep=query_sleep)
        cat_data["snapshot"] = snapshot
        report.append(cat_data)
        print(f"  → avg_kw={cat_data['avg_kw']:.1%}  pass_rate={cat_data['pass_rate']:.0%}")

    print("\n" + "=" * 70)
    print("OVERALL SUMMARY")
    total_q = sum(c["query_count"] for c in report)
    overall_kw = sum(c["avg_kw"] * c["query_count"] for c in report) / total_q if total_q else 0
    overall_pass = sum(c["pass_rate"] * c["query_count"] for c in report) / total_q if total_q else 0
    print(f"  Total queries : {total_q}")
    print(f"  Avg KW score  : {overall_kw:.1%}")
    print(f"  Pass rate     : {overall_pass:.0%}")

    out = Path(__file__).parent / f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults saved → {out}")

    if args.html:
        write_html(report, Path(__file__).parent / "report.html")


if __name__ == "__main__":
    main()
