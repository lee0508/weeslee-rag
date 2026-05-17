# 확장 Knowledge Graph 스키마 및 동의어 매핑 정의
# -*- coding: utf-8 -*-
"""
Knowledge Graph schema definitions and synonym mappings.

확장 노드 타입:
- organization: 발주기관 (동의어 지원)
- technology: 기술 키워드 (계층 구조)
- methodology: 방법론 (ISP, ISMP 등)
- domain: 도메인/분야

확장 엣지 타입:
- 발주: organization → project
- 적용기술: project → technology
- 사용방법론: project → methodology
- 관련도메인: project → domain
- 동의어: entity ↔ entity
- 유사기술: technology ↔ technology
"""
from __future__ import annotations

import re
from typing import Optional

# ── 기관 동의어 매핑 ─────────────────────────────────────────────────────────

ORGANIZATION_SYNONYMS: dict[str, list[str]] = {
    "한국수자원공사": ["K-water", "수자원공사", "수공", "K-Water", "k-water"],
    "한국토지주택공사": ["LH", "LH공사", "토지주택공사", "엘에이치"],
    "농림수산식품교육문화정보원": ["농정원", "EPIS"],
    "건강보험심사평가원": ["심평원", "HIRA", "심사평가원"],
    "국민건강보험공단": ["건보공단", "NHIS", "건강보험공단"],
    "행정안전부": ["행안부", "MOIS"],
    "과학기술정보통신부": ["과기정통부", "과기부", "MSIT"],
    "국토교통부": ["국토부", "MOLIT"],
    "환경부": ["MOE"],
    "보건복지부": ["복지부", "MOHW"],
    "기상청": ["KMA"],
    "기상산업진흥원": ["KMI"],
    "한국정보화진흥원": ["NIA", "정보화진흥원"],
    "한국지능정보사회진흥원": ["NIA", "지능정보사회진흥원"],
    "경기주택도시공사": ["GH", "경기도시공사"],
    "인천국제공항공사": ["인천공항", "IIAC"],
    "한국전력공사": ["한전", "KEPCO"],
    "한국도로공사": ["도로공사", "고속도로공사", "EX"],
    "한국철도공사": ["코레일", "KORAIL", "철도공사"],
    "서울교통공사": ["서울메트로", "지하철공사"],
    "한국가스공사": ["가스공사", "KOGAS"],
    "한국석유공사": ["석유공사", "KNOC"],
}

# 역방향 매핑 생성 (동의어 → 정규 이름)
_SYNONYM_TO_CANONICAL: dict[str, str] = {}
for canonical, synonyms in ORGANIZATION_SYNONYMS.items():
    _SYNONYM_TO_CANONICAL[canonical.lower()] = canonical
    for syn in synonyms:
        _SYNONYM_TO_CANONICAL[syn.lower()] = canonical


def normalize_organization(name: str) -> str:
    """기관명을 정규화된 이름으로 변환."""
    if not name:
        return ""
    return _SYNONYM_TO_CANONICAL.get(name.lower().strip(), name)


def get_organization_synonyms(name: str) -> list[str]:
    """기관명의 모든 동의어 반환 (정규 이름 포함)."""
    canonical = normalize_organization(name)
    if canonical in ORGANIZATION_SYNONYMS:
        return [canonical] + ORGANIZATION_SYNONYMS[canonical]
    return [name]


# ── 기술 키워드 매핑 ─────────────────────────────────────────────────────────

TECHNOLOGY_HIERARCHY: dict[str, dict] = {
    "AI": {
        "synonyms": ["인공지능", "Artificial Intelligence", "AI/ML"],
        "children": ["머신러닝", "딥러닝", "자연어처리", "컴퓨터비전", "생성AI"],
    },
    "머신러닝": {
        "synonyms": ["ML", "Machine Learning", "기계학습"],
        "parent": "AI",
    },
    "딥러닝": {
        "synonyms": ["DL", "Deep Learning"],
        "parent": "AI",
    },
    "자연어처리": {
        "synonyms": ["NLP", "Natural Language Processing"],
        "parent": "AI",
    },
    "생성AI": {
        "synonyms": ["GenAI", "Generative AI", "생성형AI", "LLM"],
        "parent": "AI",
    },
    "RAG": {
        "synonyms": ["Retrieval Augmented Generation", "검색증강생성"],
        "parent": "생성AI",
    },
    "OCR": {
        "synonyms": ["광학문자인식", "Optical Character Recognition", "문자인식"],
    },
    "빅데이터": {
        "synonyms": ["Big Data", "대용량데이터"],
        "children": ["데이터레이크", "데이터웨어하우스", "ETL"],
    },
    "클라우드": {
        "synonyms": ["Cloud", "클라우드컴퓨팅"],
        "children": ["AWS", "Azure", "GCP", "NCP"],
    },
    "IoT": {
        "synonyms": ["사물인터넷", "Internet of Things"],
    },
    "디지털트윈": {
        "synonyms": ["Digital Twin", "DT"],
    },
    "블록체인": {
        "synonyms": ["Blockchain", "분산원장"],
    },
    "RPA": {
        "synonyms": ["로봇프로세스자동화", "Robotic Process Automation"],
    },
    "스마트시티": {
        "synonyms": ["Smart City", "지능형도시"],
    },
}

# 기술 동의어 역방향 매핑
_TECH_SYNONYM_TO_CANONICAL: dict[str, str] = {}
for canonical, info in TECHNOLOGY_HIERARCHY.items():
    _TECH_SYNONYM_TO_CANONICAL[canonical.lower()] = canonical
    for syn in info.get("synonyms", []):
        _TECH_SYNONYM_TO_CANONICAL[syn.lower()] = canonical


def normalize_technology(name: str) -> str:
    """기술명을 정규화된 이름으로 변환."""
    if not name:
        return ""
    return _TECH_SYNONYM_TO_CANONICAL.get(name.lower().strip(), name)


def get_related_technologies(name: str) -> list[str]:
    """기술명과 관련된 기술 목록 (부모, 자식, 동의어)."""
    canonical = normalize_technology(name)
    info = TECHNOLOGY_HIERARCHY.get(canonical, {})

    related = [canonical]
    related.extend(info.get("synonyms", []))
    related.extend(info.get("children", []))
    if info.get("parent"):
        related.append(info["parent"])

    return list(set(related))


# ── 방법론 매핑 ─────────────────────────────────────────────────────────────

METHODOLOGY_SYNONYMS: dict[str, list[str]] = {
    "ISP": ["정보화전략계획", "정보전략계획", "Information Strategy Planning"],
    "ISMP": ["정보시스템마스터플랜", "IS마스터플랜", "Information System Master Plan"],
    "EA": ["전사아키텍처", "Enterprise Architecture"],
    "BPR": ["업무재설계", "Business Process Reengineering"],
    "PI": ["프로세스혁신", "Process Innovation"],
    "DX": ["디지털전환", "Digital Transformation", "디지털트랜스포메이션"],
    "AX": ["AI전환", "AI Transformation", "AI트랜스포메이션"],
    "애자일": ["Agile", "스크럼", "Scrum"],
    "워터폴": ["Waterfall", "폭포수"],
}

_METHOD_SYNONYM_TO_CANONICAL: dict[str, str] = {}
for canonical, synonyms in METHODOLOGY_SYNONYMS.items():
    _METHOD_SYNONYM_TO_CANONICAL[canonical.lower()] = canonical
    for syn in synonyms:
        _METHOD_SYNONYM_TO_CANONICAL[syn.lower()] = canonical


def normalize_methodology(name: str) -> str:
    """방법론명을 정규화된 이름으로 변환."""
    if not name:
        return ""
    return _METHOD_SYNONYM_TO_CANONICAL.get(name.lower().strip(), name)


# ── 도메인 매핑 ─────────────────────────────────────────────────────────────

DOMAIN_SYNONYMS: dict[str, list[str]] = {
    "수자원": ["물관리", "수자원관리", "하천", "댐"],
    "스마트시티": ["도시", "스마트도시", "지능형도시"],
    "교통": ["도로", "철도", "항공", "물류"],
    "보건의료": ["헬스케어", "의료", "건강", "병원"],
    "농업": ["농촌", "농산물", "스마트팜"],
    "환경": ["기후", "기상", "탄소"],
    "에너지": ["전력", "가스", "신재생"],
    "행정": ["공공행정", "전자정부", "민원"],
    "금융": ["은행", "보험", "핀테크"],
    "제조": ["스마트팩토리", "공장", "생산"],
}

_DOMAIN_SYNONYM_TO_CANONICAL: dict[str, str] = {}
for canonical, synonyms in DOMAIN_SYNONYMS.items():
    _DOMAIN_SYNONYM_TO_CANONICAL[canonical.lower()] = canonical
    for syn in synonyms:
        _DOMAIN_SYNONYM_TO_CANONICAL[syn.lower()] = canonical


def normalize_domain(name: str) -> str:
    """도메인명을 정규화된 이름으로 변환."""
    if not name:
        return ""
    return _DOMAIN_SYNONYM_TO_CANONICAL.get(name.lower().strip(), name)


# ── 텍스트에서 엔티티 추출 ─────────────────────────────────────────────────────

def extract_organizations(text: str) -> list[str]:
    """텍스트에서 기관명 추출."""
    found = []
    text_lower = text.lower()
    for canonical, synonyms in ORGANIZATION_SYNONYMS.items():
        if canonical.lower() in text_lower:
            found.append(canonical)
            continue
        for syn in synonyms:
            if syn.lower() in text_lower:
                found.append(canonical)
                break
    return list(set(found))


def extract_technologies(text: str) -> list[str]:
    """텍스트에서 기술 키워드 추출."""
    found = []
    text_lower = text.lower()
    for canonical, info in TECHNOLOGY_HIERARCHY.items():
        if canonical.lower() in text_lower:
            found.append(canonical)
            continue
        for syn in info.get("synonyms", []):
            if syn.lower() in text_lower:
                found.append(canonical)
                break
    return list(set(found))


def extract_methodologies(text: str) -> list[str]:
    """텍스트에서 방법론 추출."""
    found = []
    text_lower = text.lower()
    for canonical, synonyms in METHODOLOGY_SYNONYMS.items():
        if canonical.lower() in text_lower:
            found.append(canonical)
            continue
        for syn in synonyms:
            if syn.lower() in text_lower:
                found.append(canonical)
                break
    return list(set(found))


def extract_domains(text: str) -> list[str]:
    """텍스트에서 도메인 추출."""
    found = []
    text_lower = text.lower()
    for canonical, synonyms in DOMAIN_SYNONYMS.items():
        if canonical.lower() in text_lower:
            found.append(canonical)
            continue
        for syn in synonyms:
            if syn.lower() in text_lower:
                found.append(canonical)
                break
    return list(set(found))


def extract_all_entities(text: str) -> dict[str, list[str]]:
    """텍스트에서 모든 유형의 엔티티 추출."""
    return {
        "organizations": extract_organizations(text),
        "technologies": extract_technologies(text),
        "methodologies": extract_methodologies(text),
        "domains": extract_domains(text),
    }
