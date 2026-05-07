# -*- coding: utf-8 -*-
"""
Query expansion for Korean public sector IT terminology.

Provides two expanders:
- expand_bid_query: 나라장터 bid project names → related terminology
- expand_rfp_query: RFP / 과업지시서 contents → proposal strategy terms
"""
from __future__ import annotations

import re

_TERM_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")

# token (lowercase) → list of expansion terms to append
_EXPANSIONS: dict[str, list[str]] = {
    "isp": ["정보화전략계획", "ISP", "information strategy plan"],
    "ismp": ["정보시스템마스터플랜", "ISMP"],
    "oda": ["공적개발원조", "ODA", "해외원조", "국제협력"],
    "gpt": ["GPT", "LLM", "대형언어모델", "생성형AI"],
    "llm": ["LLM", "GPT", "거대언어모델"],
    "ai": ["인공지능", "AI", "생성형AI", "AI플랫폼"],
    "ax": ["AX", "AI전환", "인공지능전환", "디지털AI전환"],
    "dx": ["디지털전환", "DX", "digital transformation"],
    "bpr": ["업무재설계", "BPR", "프로세스혁신"],
    "erp": ["전사자원관리", "ERP"],
    "정보화전략계획": ["ISP", "IT전략"],
    "정보시스템마스터플랜": ["ISMP", "ISP"],
    "고도화": ["성능고도화", "기능강화", "시스템개선"],
    "플랫폼": ["통합플랫폼", "서비스플랫폼", "platform"],
    "클라우드": ["클라우드전환", "cloud", "SaaS"],
    "보안": ["정보보안", "사이버보안", "보안체계"],
    "스마트": ["스마트시티", "스마트행정", "smart"],
    "빅데이터": ["빅데이터", "big data", "데이터분석"],
    "블록체인": ["블록체인", "blockchain"],
}


def _apply_expansions(query: str, table: dict[str, list[str]]) -> str:
    """Generic expansion helper — appends terms from table that aren't already in the query."""
    tokens = {t.lower() for t in _TERM_PATTERN.findall(query)}
    additions: list[str] = []
    added_lower: set[str] = set(tokens)

    for token in sorted(tokens):
        for expansion in table.get(token, []):
            if expansion.lower() not in added_lower:
                additions.append(expansion)
                added_lower.add(expansion.lower())

    if not additions:
        return query
    return query + " " + " ".join(additions)


def expand_bid_query(query: str) -> str:
    """Expand a 나라장터 bid project name with related IT terminology synonyms."""
    return _apply_expansions(query, _EXPANSIONS)


# RFP analysis mode: expand proposal/requirement terms
_RFP_EXPANSIONS: dict[str, list[str]] = {
    "rfp": ["제안요청서", "과업지시서", "입찰공고", "RFP"],
    "제안요청서": ["RFP", "과업지시서"],
    "과업지시서": ["RFP", "제안요청서", "요구사항"],
    "요구사항": ["기능요구사항", "비기능요구사항", "요구사항정의"],
    "제안서": ["proposal", "제안전략", "수행방법론"],
    "proposal": ["제안서", "제안전략", "수행계획"],
    "분석": ["현황분석", "문제점분석", "AS-IS분석"],
    "설계": ["아키텍처설계", "시스템설계", "TO-BE설계"],
    "isp": ["정보화전략계획", "ISP", "현황진단", "개선방안"],
    "ismp": ["정보시스템마스터플랜", "ISMP", "중장기계획"],
    "ai": ["인공지능", "AI적용방안", "AI활용"],
    "ax": ["AI전환전략", "AX", "디지털혁신"],
    "도입": ["도입방안", "도입전략", "구축방안"],
    "구축": ["구축방법론", "구축절차", "이행계획"],
    "일정": ["수행일정", "마일스톤", "추진일정"],
    "예산": ["사업비", "투입인력", "원가"],
}


def expand_rfp_query(query: str) -> str:
    """Expand an RFP / 과업지시서 query with proposal strategy terms for better recall."""
    return _apply_expansions(query, _RFP_EXPANSIONS)
