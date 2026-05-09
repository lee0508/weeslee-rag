# -*- coding: utf-8 -*-
"""
Post-retrieval reranker for bid_project and rfp_analysis modes.

Applies a second-pass keyword-frequency score on top of the FAISS+aggregate
ranking_score returned by assemble_rag_response.py.  Only called for modes
that benefit from domain-keyword boosting; general mode is left untouched.
"""

from __future__ import annotations

import re
from typing import Literal

_TERM_PATTERN = re.compile(r"[0-9A-Za-z가-힣_]+")

# Domain keyword weights shared across modes
_DOMAIN_WEIGHTS: dict[str, float] = {
    "isp": 2.0,
    "ismp": 2.0,
    "정보화전략계획": 2.0,
    "정보시스템마스터플랜": 1.5,
    "ai": 1.5,
    "인공지능": 1.5,
    "gpt": 1.5,
    "llm": 1.5,
    "생성형ai": 1.5,
    "ax": 1.2,
    "디지털전환": 1.2,
    "dx": 1.2,
    "ai전환": 1.5,
    "oda": 1.2,
    "공적개발원조": 1.2,
    "고도화": 1.0,
    "플랫폼": 0.8,
    "클라우드": 0.8,
    "빅데이터": 0.8,
    "블록체인": 0.8,
    "스마트": 0.6,
    "erp": 1.0,
    "bpr": 1.0,
    "보안": 0.6,
}

_BID_CATEGORY_WEIGHTS: dict[str, float] = {
    "proposal": 3.0,
    "final_report": 2.0,
    "presentation": 1.5,
    "rfp": 1.0,
    "kickoff": 0.5,
}

_RFP_CATEGORY_WEIGHTS: dict[str, float] = {
    "rfp": 4.0,
    "kickoff": 3.0,
    "proposal": 1.5,
    "presentation": 0.8,
    "final_report": 0.4,
}

Mode = Literal["bid_project", "rfp_analysis"]


def _extract_terms(text: str) -> list[str]:
    return [t for t in _TERM_PATTERN.findall(text.lower()) if len(t) >= 2]


def _keyword_score(query_terms: list[str], texts: list[str]) -> float:
    corpus = " ".join(texts).lower()
    score = 0.0
    for term in query_terms:
        if term in corpus:
            score += _DOMAIN_WEIGHTS.get(term, 0.3)
    return min(score, 5.0)


def _category_weight(category: str, mode: Mode) -> float:
    table = _BID_CATEGORY_WEIGHTS if mode == "bid_project" else _RFP_CATEGORY_WEIGHTS
    return table.get(category, 0.0)


def _project_name_overlap(query_terms: list[str], project_name: str) -> float:
    project_terms = set(_extract_terms(project_name))
    overlap = len(project_terms & set(query_terms))
    return min(overlap * 0.5, 2.0)


def rerank(query: str, documents: list[dict], mode: Mode) -> list[dict]:
    """Re-sort documents with a keyword-frequency second pass.

    Documents already carry a ``ranking_score`` from aggregate_hits().
    This function computes a ``rerank_score`` by adding:
      - query-keyword frequency × domain weight  (from evidence_snippets + section_headings)
      - document-category weight for the given mode
      - project-name / query-term overlap bonus

    The final list is sorted by ``rerank_score`` descending and ranks are updated.
    """
    if not documents:
        return documents

    query_terms = _extract_terms(query)

    scored: list[tuple[float, dict]] = []
    for doc in documents:
        texts = (
            doc.get("evidence_snippets", [])
            + doc.get("section_headings", [])
            + [doc.get("source_path", "")]
        )
        kw = _keyword_score(query_terms, texts)
        cat = _category_weight(doc.get("category", ""), mode)
        proj = _project_name_overlap(query_terms, doc.get("project_name", ""))
        rerank_score = doc.get("ranking_score", 0.0) + kw + cat + proj
        enriched = {**doc, "rerank_score": round(rerank_score, 4)}
        scored.append((rerank_score, enriched))

    scored.sort(key=lambda t: t[0], reverse=True)
    result = []
    for new_rank, (_, doc) in enumerate(scored, start=1):
        result.append({**doc, "rank": new_rank})
    return result
