# Query Router - 질문 분석 및 검색 소스 선택 (규칙 + LLM 하이브리드)
# -*- coding: utf-8 -*-
"""
Query Router Service

사용자 질문을 분석하여 의도(intent)와 필터(filters)를 추출하고,
적절한 검색 소스(Graph, FAISS, Wiki)를 선택한다.

방식: 규칙 우선, 불확실하면 LLM
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pathlib import Path
import json


class SearchSource(str, Enum):
    """검색 소스 타입."""
    FAISS = "faiss"
    GRAPH = "graph"
    WIKI = "wiki"


class QueryIntent(str, Enum):
    """질문 의도 타입."""
    FIND_DOCUMENT = "find_document"        # 문서/장표 찾기
    FIND_EXAMPLE = "find_example"          # 예시/사례 찾기
    FIND_TEMPLATE = "find_template"        # 템플릿/양식 찾기
    FIND_REQUIREMENT = "find_requirement"  # 요구사항 찾기
    FIND_SECTION = "find_section"          # 특정 섹션 찾기
    COMPARE = "compare"                    # 비교/분석
    SUMMARIZE = "summarize"                # 요약 요청
    GENERAL = "general"                    # 일반 질문


class QueryComplexity(str, Enum):
    """질문 복잡도."""
    SIMPLE = "simple"      # 단순 키워드 검색
    MODERATE = "moderate"  # 복합 조건 (2-3개 필터)
    COMPLEX = "complex"    # 다중 조건 + 관계 추론 필요


@dataclass
class QueryAnalysis:
    """질문 분석 결과."""
    query: str
    intent: QueryIntent
    complexity: QueryComplexity
    filters: Dict[str, Any] = field(default_factory=dict)
    keywords: List[str] = field(default_factory=list)
    search_sources: List[SearchSource] = field(default_factory=list)
    search_order: str = "parallel"  # parallel | graph_first | faiss_first
    confidence: float = 0.0
    analysis_method: str = "rule"  # rule | llm | hybrid

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환."""
        return {
            "query": self.query,
            "intent": self.intent.value,
            "complexity": self.complexity.value,
            "filters": self.filters,
            "keywords": self.keywords,
            "search_sources": [s.value for s in self.search_sources],
            "search_order": self.search_order,
            "confidence": self.confidence,
            "analysis_method": self.analysis_method,
        }


# 의도 패턴 정의
INTENT_PATTERNS = {
    QueryIntent.FIND_DOCUMENT: [
        r"장표|슬라이드|페이지|문서|파일",
        r"어디에|어느\s*부분|위치",
        r"찾아|검색|조회",
    ],
    QueryIntent.FIND_EXAMPLE: [
        r"예시|사례|샘플|케이스",
        r"이전에|과거|기존",
        r"비슷한|유사한|관련",
    ],
    QueryIntent.FIND_TEMPLATE: [
        r"템플릿|양식|서식|폼",
        r"작성|만들|생성",
    ],
    QueryIntent.FIND_REQUIREMENT: [
        r"요구사항|요건|조건",
        r"RFP|제안요청",
        r"보안|성능|기능",
    ],
    QueryIntent.FIND_SECTION: [
        r"목차|섹션|챕터|장",
        r"기술및기능|프로젝트관리|프로젝트지원",
        r"현황분석|환경분석|목표모델",
    ],
    QueryIntent.COMPARE: [
        r"비교|대비|차이",
        r"분석|검토",
    ],
    QueryIntent.SUMMARIZE: [
        r"요약|정리|핵심",
        r"개요|소개",
    ],
}

# 필터 패턴 정의
FILTER_PATTERNS = {
    "organization_type": {
        "공공기관": [r"공공기관|공기업|정부기관|행정기관"],
        "연구기관": [r"연구기관|연구원|연구소"],
        "금융기관": [r"금융기관|은행|보험|증권"],
        "의료기관": [r"의료기관|병원|의료"],
        "교육기관": [r"교육기관|대학|학교"],
        "민간기업": [r"민간기업|기업|회사"],
    },
    "document_group": {
        "RFP": [r"RFP|제안요청서|입찰"],
        "제안서": [r"제안서|기술제안|사업제안"],
        "산출물": [r"산출물|보고서|결과물"],
    },
    "document_section": {
        "기술및기능": [r"기술및기능|기술\s*기능|기술제안"],
        "프로젝트관리": [r"프로젝트관리|사업관리|관리방안"],
        "프로젝트지원": [r"프로젝트지원|사업지원|지원방안"],
        "현황분석": [r"현황분석|현황\s*분석|As-Is"],
        "환경분석": [r"환경분석|환경\s*분석"],
        "목표모델": [r"목표모델|To-Be|목표\s*모델"],
    },
    "topic": {
        "보안": [r"보안|정보보호|개인정보|누출금지"],
        "AI": [r"AI|인공지능|머신러닝|딥러닝"],
        "클라우드": [r"클라우드|AWS|Azure|GCP"],
        "데이터": [r"데이터|빅데이터|데이터베이스"],
        "선진사례": [r"선진사례|해외사례|벤치마크"],
        "유사사례": [r"유사사례|참고사례"],
    },
    "project_type": {
        "ISP": [r"ISP|정보화전략계획|정보화\s*전략"],
        "ISMP": [r"ISMP|정보시스템마스터플랜|마스터플랜"],
        "EA": [r"EA|전사아키텍처|아키텍처"],
        "BPR": [r"BPR|업무재설계|프로세스재설계"],
        "SI": [r"SI|시스템통합|시스템\s*구축"],
    },
}

# 복잡도 판단 기준
COMPLEXITY_THRESHOLDS = {
    "simple": 1,      # 필터 1개 이하
    "moderate": 3,    # 필터 2-3개
    "complex": 4,     # 필터 4개 이상
}


class QueryRouter:
    """질문 분석 및 라우팅 서비스."""

    def __init__(self, entity_mappings_path: Optional[Path] = None):
        """
        Args:
            entity_mappings_path: entity_mappings.json 경로 (키워드 확장용)
        """
        self._entity_mappings: Optional[Dict] = None
        self._mappings_path = entity_mappings_path

    def _load_entity_mappings(self) -> Dict:
        """entity_mappings.json 로드."""
        if self._entity_mappings is not None:
            return self._entity_mappings

        if self._mappings_path and self._mappings_path.exists():
            try:
                self._entity_mappings = json.loads(
                    self._mappings_path.read_text(encoding="utf-8")
                )
            except Exception:
                self._entity_mappings = {}
        else:
            self._entity_mappings = {}

        return self._entity_mappings

    def _extract_intent(self, query: str) -> tuple[QueryIntent, float]:
        """규칙 기반 의도 추출."""
        query_lower = query.lower()
        scores: Dict[QueryIntent, int] = {}

        for intent, patterns in INTENT_PATTERNS.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    score += 1
            if score > 0:
                scores[intent] = score

        if not scores:
            return QueryIntent.GENERAL, 0.3

        best_intent = max(scores, key=lambda k: scores[k])
        confidence = min(0.5 + scores[best_intent] * 0.15, 0.9)
        return best_intent, confidence

    def _extract_filters(self, query: str) -> Dict[str, Any]:
        """규칙 기반 필터 추출."""
        query_lower = query.lower()
        filters: Dict[str, Any] = {}

        for filter_type, values in FILTER_PATTERNS.items():
            for value_name, patterns in values.items():
                for pattern in patterns:
                    if re.search(pattern, query_lower):
                        if filter_type not in filters:
                            filters[filter_type] = []
                        if value_name not in filters[filter_type]:
                            filters[filter_type].append(value_name)
                        break

        # 단일 값인 경우 리스트에서 문자열로 변환
        for key in filters:
            if isinstance(filters[key], list) and len(filters[key]) == 1:
                filters[key] = filters[key][0]

        return filters

    def _extract_keywords(self, query: str) -> List[str]:
        """키워드 추출."""
        # 불용어 제거
        stopwords = {
            "의", "를", "을", "이", "가", "에", "에서", "로", "으로",
            "와", "과", "또는", "및", "그리고", "하는", "있는", "된",
            "찾아줘", "검색해줘", "알려줘", "보여줘", "해줘",
        }

        # 토큰화
        tokens = re.findall(r"[가-힣A-Za-z0-9]+", query)
        keywords = [t for t in tokens if t not in stopwords and len(t) >= 2]

        return keywords[:10]

    def _determine_complexity(self, filters: Dict[str, Any]) -> QueryComplexity:
        """복잡도 판단."""
        filter_count = len(filters)

        if filter_count <= COMPLEXITY_THRESHOLDS["simple"]:
            return QueryComplexity.SIMPLE
        elif filter_count <= COMPLEXITY_THRESHOLDS["moderate"]:
            return QueryComplexity.MODERATE
        else:
            return QueryComplexity.COMPLEX

    def _select_search_sources(
        self,
        intent: QueryIntent,
        complexity: QueryComplexity,
        filters: Dict[str, Any]
    ) -> tuple[List[SearchSource], str]:
        """
        검색 소스 및 순서 결정.

        결정 기준 (Q5: C - 질문 유형별 분기):
        - 단순 키워드 검색: FAISS만
        - 복합 조건: Graph → FAISS 순차
        - 관계 추론 필요: Graph + FAISS + Wiki
        """
        # 단순 질문: FAISS만
        if complexity == QueryComplexity.SIMPLE and not filters:
            return [SearchSource.FAISS], "faiss_only"

        # 문서/섹션 찾기: Graph 우선
        if intent in [QueryIntent.FIND_DOCUMENT, QueryIntent.FIND_SECTION]:
            if complexity == QueryComplexity.COMPLEX:
                return [SearchSource.GRAPH, SearchSource.FAISS, SearchSource.WIKI], "graph_first"
            else:
                return [SearchSource.GRAPH, SearchSource.FAISS], "graph_first"

        # 예시/사례 찾기: Graph + Wiki
        if intent in [QueryIntent.FIND_EXAMPLE, QueryIntent.COMPARE]:
            return [SearchSource.GRAPH, SearchSource.WIKI, SearchSource.FAISS], "graph_first"

        # 요구사항 찾기: FAISS 우선 (원문 검색)
        if intent == QueryIntent.FIND_REQUIREMENT:
            return [SearchSource.FAISS, SearchSource.GRAPH], "faiss_first"

        # 요약: Wiki 우선
        if intent == QueryIntent.SUMMARIZE:
            return [SearchSource.WIKI, SearchSource.FAISS], "wiki_first"

        # 복합 조건이 있으면 Graph 우선
        if complexity in [QueryComplexity.MODERATE, QueryComplexity.COMPLEX]:
            return [SearchSource.GRAPH, SearchSource.FAISS], "graph_first"

        # 기본: FAISS 우선
        return [SearchSource.FAISS, SearchSource.GRAPH], "faiss_first"

    def analyze(self, query: str) -> QueryAnalysis:
        """
        질문 분석 수행.

        Args:
            query: 사용자 질문

        Returns:
            QueryAnalysis 객체
        """
        # 1. 의도 추출
        intent, intent_confidence = self._extract_intent(query)

        # 2. 필터 추출
        filters = self._extract_filters(query)

        # 3. 키워드 추출
        keywords = self._extract_keywords(query)

        # 4. 복잡도 판단
        complexity = self._determine_complexity(filters)

        # 5. 검색 소스 선택
        sources, order = self._select_search_sources(intent, complexity, filters)

        # 6. 최종 신뢰도 계산
        confidence = intent_confidence
        if filters:
            confidence = min(confidence + 0.1, 0.95)

        return QueryAnalysis(
            query=query,
            intent=intent,
            complexity=complexity,
            filters=filters,
            keywords=keywords,
            search_sources=sources,
            search_order=order,
            confidence=confidence,
            analysis_method="rule",
        )

    def needs_llm_analysis(self, analysis: QueryAnalysis) -> bool:
        """
        LLM 분석이 필요한지 판단.

        LLM 필요 조건:
        - 신뢰도가 0.5 미만
        - 의도가 GENERAL이고 복잡도가 MODERATE 이상
        - 필터가 없는데 질문이 긴 경우
        """
        if analysis.confidence < 0.5:
            return True

        if analysis.intent == QueryIntent.GENERAL and analysis.complexity != QueryComplexity.SIMPLE:
            return True

        if not analysis.filters and len(analysis.query) > 50:
            return True

        return False


# 싱글톤 인스턴스
_query_router: Optional[QueryRouter] = None


def get_query_router(entity_mappings_path: Optional[Path] = None) -> QueryRouter:
    """QueryRouter 싱글톤 반환."""
    global _query_router
    if _query_router is None:
        _query_router = QueryRouter(entity_mappings_path)
    return _query_router


# 편의 함수
def analyze_query(query: str) -> QueryAnalysis:
    """질문 분석 (단축 함수)."""
    return get_query_router().analyze(query)
