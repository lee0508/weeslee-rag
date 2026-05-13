# Phase 1 RAG 품질 평가 스크립트 — 검색 정확도, 응답 시간, 할루시네이션 감지
"""
사용법:
  python run_quality_eval.py                          # 기본(localhost:8080)
  python run_quality_eval.py --server http://서버:8080
  python run_quality_eval.py --top-k 10 --answer-mode ollama
  python run_quality_eval.py --output eval_result.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
from pathlib import Path

# ── 테스트 쿼리 (TC-01 기준, 5개 카테고리 × 2) ─────────────────────────────
TEST_CASES = [
    ("rfp",          "ISP 사업 제안요청서 요구사항 항목",         ["제안요청", "rfp", "요구사항", "과업"]),
    ("rfp",          "정보화전략계획 수립 과업 범위",             ["isp", "과업", "범위", "정보화"]),
    ("proposal",     "ISP 컨설팅 제안서 방법론 구성",            ["방법론", "제안서", "isp", "컨설팅"]),
    ("proposal",     "AX 전환 전략 제안 핵심 내용",              ["ax", "전환", "전략", "제안"]),
    ("kickoff",      "착수보고 추진 일정 주요 내용",              ["착수", "일정", "추진", "보고"]),
    ("kickoff",      "사업 착수 후 초기 단계 활동",               ["착수", "단계", "활동", "사업"]),
    ("final_report", "ISP 최종 산출물 목차 구성",                ["최종", "산출물", "목차", "isp"]),
    ("final_report", "정보화전략 이행계획서 주요 과제",            ["이행", "과제", "정보화", "계획"]),
    ("presentation", "ISP 중간보고 발표 슬라이드 구성",           ["중간보고", "발표", "슬라이드"]),
    ("presentation", "최종보고회 발표자료 핵심 메시지",            ["최종보고", "발표", "메시지"]),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RAG 품질 평가 스크립트")
    p.add_argument("--server",      default=os.getenv("RAG_API_BASE", "http://localhost:8080"))
    p.add_argument("--top-k",       type=int, default=10)
    p.add_argument("--top-docs",    type=int, default=5)
    p.add_argument("--answer-mode", choices=["ollama", "none"], default="ollama")
    p.add_argument("--answer-model", default="gemma4:latest")
    p.add_argument("--output",      default="")
    return p.parse_args()


def query_rag(server: str, query: str, top_k: int, top_docs: int,
              answer_mode: str, answer_model: str) -> tuple[dict, float]:
    payload = json.dumps({
        "query": query,
        "top_k": top_k,
        "top_docs": top_docs,
        "answer_provider": answer_mode,
        "answer_model": answer_model if answer_mode != "none" else "",
        "max_chunks_per_doc": 3,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{server}/api/rag/query",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        data = {"error": str(e), "documents": [], "draft_answer": "", "answer": ""}
    elapsed = time.perf_counter() - t0
    return data, round(elapsed, 2)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r'[.。\n]+', text) if len(s.strip()) > 8]


def score(result: dict, keywords: list[str], elapsed: float) -> dict:
    answer = (result.get("answer") or result.get("draft_answer") or "").lower()
    docs = result.get("documents") or result.get("results") or []

    # 1. 키워드 히트율
    kw_hits = sum(1 for kw in keywords if kw.lower() in answer)
    kw_score = kw_hits / len(keywords) if keywords else 0.0

    # 2. 할루시네이션 감지 — 답변 문장이 검색 근거에 기반하는지 확인
    all_snippets = " ".join(
        s for doc in docs
        for s in (doc.get("evidence_snippets") or doc.get("snippet") and [doc["snippet"]] or [])
    ).lower()
    all_project_names = " ".join(
        (doc.get("project_name") or "").lower() for doc in docs
    )
    evidence_base = all_snippets + " " + all_project_names

    sentences = _sentences(answer)
    grounded, orphan = 0, 0
    orphan_list: list[str] = []
    for sent in sentences:
        # 근거 텍스트에서 단어 3개 이상 겹치면 grounded
        words = [w for w in re.findall(r'[가-힣a-z]{2,}', sent) if len(w) >= 2]
        hits = sum(1 for w in words if w in evidence_base)
        if hits >= 2 or not words:
            grounded += 1
        else:
            orphan += 1
            orphan_list.append(sent[:60])

    total_s = grounded + orphan
    grounding_score = grounded / total_s if total_s else 1.0

    # 3. 응답 지표
    doc_count = len(docs)
    unique_docs = len(set(
        (d.get("document_id") or d.get("rank", i)) for i, d in enumerate(docs)
    ))
    top_project = docs[0].get("project_name", "-") if docs else "-"

    return {
        "doc_count":       doc_count,
        "unique_docs":     unique_docs,
        "top_project":     top_project,
        "kw_hits":         kw_hits,
        "kw_total":        len(keywords),
        "kw_score":        round(kw_score, 3),
        "answer_len":      len(answer),
        "response_sec":    elapsed,
        "grounding_score": round(grounding_score, 3),
        "orphan_count":    orphan,
        "orphan_samples":  orphan_list[:3],
        "answer_preview":  answer[:120].replace("\n", " "),
        "error":           result.get("error", ""),
    }


def main() -> None:
    args = parse_args()
    server = args.server.rstrip("/")

    print("=" * 72)
    print(f"RAG 품질 평가  |  서버: {server}  |  top_k={args.top_k}  |  mode={args.answer_mode}")
    print("=" * 72)

    records: list[dict] = []
    total_kw = 0.0
    total_sec = 0.0
    total_ground = 0.0
    errors = 0

    for i, (cat, query, keywords) in enumerate(TEST_CASES, 1):
        result, elapsed = query_rag(server, query, args.top_k, args.top_docs,
                                    args.answer_mode, args.answer_model)
        s = score(result, keywords, elapsed)
        total_kw    += s["kw_score"]
        total_sec   += s["response_sec"]
        total_ground += s["grounding_score"]
        if s["error"]:
            errors += 1

        status = "✓" if s["kw_score"] >= 0.5 else "✗"
        hall   = "⚠ HALL" if s["grounding_score"] < 0.6 else ""
        print(f"[{i:2d}] {status} [{cat}] {query}")
        print(f"      docs={s['doc_count']}  kw={s['kw_hits']}/{s['kw_total']} ({s['kw_score']:.0%})"
              f"  grounding={s['grounding_score']:.0%}  {s['response_sec']:.1f}s  {hall}")
        if s["orphan_samples"]:
            for o in s["orphan_samples"]:
                print(f"      ⚠ 미근거 문장: {o}")
        print(f"      상위 프로젝트: {s['top_project']}")
        print()

        records.append({"no": i, "category": cat, "query": query, "keywords": keywords, **s})

    n = len(TEST_CASES)
    avg_kw    = total_kw    / n
    avg_sec   = total_sec   / n
    avg_grnd  = total_ground / n

    print("=" * 72)
    print(f"결과 요약")
    print(f"  키워드 히트율 (목표 ≥80%)  : {avg_kw:.1%}"
          + ("  ✓" if avg_kw >= 0.8 else "  ✗ 개선 필요"))
    print(f"  평균 응답 시간 (목표 ≤30s) : {avg_sec:.1f}s"
          + ("  ✓" if avg_sec <= 30 else "  ✗ 개선 필요"))
    print(f"  근거 기반 비율 (목표 ≥80%) : {avg_grnd:.1%}"
          + ("  ✓" if avg_grnd >= 0.8 else "  ✗ 할루시네이션 의심"))
    print(f"  오류 건수                  : {errors}/{n}")
    print("=" * 72)

    # KPI 기준 최종 판정
    passed = avg_kw >= 0.8 and avg_sec <= 30 and avg_grnd >= 0.8
    print(f"\n최종 판정: {'PASS ✓' if passed else 'FAIL ✗ — 위 항목을 개선한 후 재평가 하세요.'}\n")

    output = args.output or f"data/staged/rag_quality_eval_{int(time.time())}.json"
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "server": server,
        "top_k": args.top_k,
        "answer_mode": args.answer_mode,
        "avg_kw_score": round(avg_kw, 3),
        "avg_response_sec": round(avg_sec, 2),
        "avg_grounding_score": round(avg_grnd, 3),
        "error_count": errors,
        "passed": passed,
        "cases": records,
    }
    Path(output).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"결과 저장: {output}")


if __name__ == "__main__":
    main()
