# Query Router - 질문 분석 및 검색 소스 선택 (규칙 + LLM 하이브리드)
# -*- coding: utf-8 -*-
# 작업일: 2026-07-08 - DB 시스템 설정 연동 추가
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


def _get_ollama_host() -> str:
    """DB 설정 우선, 없으면 기본값 반환."""
    try:
        from app.services.system_settings_service import get_endpoint_setting
        return get_endpoint_setting("ollama_host", "http://127.0.0.1:11434")
    except Exception:
        return "http://127.0.0.1:11434"

SECTION_HINTS = (
    "전략및방법론",
    "기술및기능",
    "프로젝트관리",
    "프로젝트지원",
    "환경분석",
    "현황분석",
    "목표모델",
    "이행계획",
)


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
        "AI": [r"ai|인공지능|머신러닝|딥러닝|생성형\s*ai|llm"],
        "클라우드": [r"클라우드|aws|azure|gcp"],
        "데이터": [r"데이터|빅데이터|데이터베이스"],
        "선진사례": [r"선진사례|해외사례|벤치마크|선진\s*사례"],
        "유사사례": [r"유사사례|참고사례|유사\s*사례"],
    },
    "project_type": {
        "ISP": [r"ISP|정보화전략계획|정보화\s*전략"],
        "ISMP": [r"ISMP|정보시스템마스터플랜|마스터플랜"],
        "EA": [r"EA|전사아키텍처|아키텍처"],
        "BPR": [r"BPR|업무재설계|프로세스재설계"],
        "SI": [r"SI|시스템통합|시스템\s*구축"],
        "업무시스템개선": [r"업무\s*시스템\s*개선|업무시스템\s*개선|시스템\s*개선\s*사업"],
        "플랫폼개선": [r"플랫폼\s*개선|플랫폼\s*고도화|플랫폼\s*구축|플랫폼\s*확장"],
        "컨설팅": [r"컨설팅\s*사업|컨설팅|자문"],
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
            "관련", "관련된", "내용", "부분", "문서", "파일", "사업", "장표",
            "폴더", "안", "안에서", "중", "중에서", "대한", "기준", "원하는",
            "있는지", "찾기", "찾아", "조회", "검색", "알려", "보여",
        }

        # 토큰화
        tokens = re.findall(r"[가-힣A-Za-z0-9]+", query)
        keywords = [t for t in tokens if t not in stopwords and len(t) >= 2]

        return keywords[:10]

    def _extract_literal_filters(self, query: str, filters: Dict[str, Any]) -> Dict[str, Any]:
        """질문 원문에 명시된 섹션/문서그룹 힌트를 보강한다."""
        updated = dict(filters)
        normalized_query = re.sub(r"\s+", "", query)

        for section in SECTION_HINTS:
            if section in normalized_query:
                updated["document_section"] = section
                if section in {"전략및방법론", "기술및기능", "프로젝트관리", "프로젝트지원"}:
                    updated.setdefault("document_group", "제안서")
                elif section in {"환경분석", "현황분석", "목표모델", "이행계획"}:
                    updated.setdefault("document_group", "산출물")
                break

        if "제안서" in query and "document_group" not in updated:
            updated["document_group"] = "제안서"
        elif "산출물" in query and "document_group" not in updated:
            updated["document_group"] = "산출물"
        elif re.search(r"\bRFP\b|제안요청서", query, re.IGNORECASE) and "document_group" not in updated:
            updated["document_group"] = "RFP"

        return updated

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
        explicit_document_filters = any(
            key in filters
            for key in ("document_group", "document_section", "project_type", "organization_type", "topic")
        )
        section_or_group_filters = any(
            key in filters
            for key in ("document_group", "document_section")
        )

        # 단순 질문: FAISS만
        if complexity == QueryComplexity.SIMPLE and not filters:
            return [SearchSource.FAISS], "faiss_only"

        # 문서/섹션 찾기에서 명시적인 메타데이터 필터가 있으면
        # Graph 후보에 FAISS가 과도하게 종속되지 않도록 검색 순서를 낮춘다.
        if intent in [QueryIntent.FIND_DOCUMENT, QueryIntent.FIND_SECTION]:
            if section_or_group_filters:
                if complexity == QueryComplexity.COMPLEX:
                    return [SearchSource.FAISS, SearchSource.GRAPH, SearchSource.WIKI], "parallel"
                return [SearchSource.FAISS, SearchSource.GRAPH], "faiss_first"
            if explicit_document_filters:
                return [SearchSource.FAISS, SearchSource.GRAPH], "faiss_first"
            if complexity == QueryComplexity.COMPLEX:
                return [SearchSource.GRAPH, SearchSource.FAISS, SearchSource.WIKI], "graph_first"
            else:
                return [SearchSource.GRAPH, SearchSource.FAISS], "graph_first"

        # 예시/사례 찾기라도 문서그룹/섹션/주제 필터가 명확하면 병렬 검색이 더 안정적이다.
        if intent in [QueryIntent.FIND_EXAMPLE, QueryIntent.COMPARE]:
            if explicit_document_filters:
                if complexity == QueryComplexity.COMPLEX:
                    return [SearchSource.FAISS, SearchSource.GRAPH, SearchSource.WIKI], "parallel"
                return [SearchSource.FAISS, SearchSource.GRAPH, SearchSource.WIKI], "faiss_first"
            return [SearchSource.GRAPH, SearchSource.WIKI, SearchSource.FAISS], "graph_first"

        # 요구사항 찾기: FAISS 우선 (원문 검색)
        if intent == QueryIntent.FIND_REQUIREMENT:
            return [SearchSource.FAISS, SearchSource.GRAPH], "faiss_first"

        # 요약: Wiki 우선
        if intent == QueryIntent.SUMMARIZE:
            return [SearchSource.WIKI, SearchSource.FAISS], "wiki_first"

        # 복합 조건이 있더라도 명시적인 문서 필터가 있으면 FAISS를 먼저 사용한다.
        if explicit_document_filters:
            if complexity == QueryComplexity.COMPLEX:
                return [SearchSource.FAISS, SearchSource.GRAPH], "parallel"
            return [SearchSource.FAISS, SearchSource.GRAPH], "faiss_first"

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
        filters = self._extract_literal_filters(query, filters)

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


# LLM 기반 핵심 키워드 추출
import asyncio
import urllib.request
import urllib.error


_LLM_KEYWORD_PROMPT = """사용자 질문에서 문서 검색에 사용할 핵심 키워드만 추출하세요.

규칙:
1. 검색에 의미있는 명사, 고유명사, 전문용어만 추출
2. 조사(은/는/이/가/을/를/에/의/와/과), 동사(찾아/알려/보여/해줘), 부사(대한/위한/관한)는 제외
3. "폴더", "내용", "파일" 같은 일반적인 단어는 제외
4. 띄어쓰기가 있어도 하나의 개념이면 붙여서 추출 (예: "의사소통 관리" → "의사소통관리")
5. 최대 5개까지만 추출
6. JSON 배열 형식으로만 응답

예시:
질문: "프로젝트관리 폴더 안에서 의사소통 관리에 대한 내용을 찾아줘"
응답: ["프로젝트관리", "의사소통관리"]

질문: "공공기관을 고객으로 하여 AI를 접목한 시스템 도입을 원하는 사업 찾아줘"
응답: ["공공기관", "AI", "시스템도입"]

질문: {query}
응답:"""


async def extract_keywords_with_llm(
    query: str,
    ollama_url: str = None,
    model: str = "qwen2.5:14b",
    timeout: float = 10.0,
) -> List[str]:
    """
    LLM을 사용하여 질문에서 핵심 키워드를 추출한다.

    Args:
        query: 사용자 질문
        ollama_url: Ollama API URL
        model: 사용할 모델명
        timeout: 타임아웃 (초)

    Returns:
        핵심 키워드 리스트
    """
    # DB 설정 우선, 없으면 하드코딩 fallback
    if not ollama_url:
        ollama_url = f"{_get_ollama_host()}/api/generate"

    prompt = _LLM_KEYWORD_PROMPT.format(query=query)

    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 100,
        }
    }).encode("utf-8")

    request = urllib.request.Request(
        ollama_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    def _call_ollama():
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
                return data.get("response", "[]")
        except (urllib.error.URLError, TimeoutError):
            return "[]"

    try:
        loop = asyncio.get_event_loop()
        response_text = await loop.run_in_executor(None, _call_ollama)

        # JSON 파싱 시도
        response_text = response_text.strip()
        # JSON 배열만 추출
        start = response_text.find("[")
        end = response_text.rfind("]") + 1
        if start >= 0 and end > start:
            json_str = response_text[start:end]
            keywords = json.loads(json_str)
            if isinstance(keywords, list):
                return [str(k).strip() for k in keywords if k and len(str(k).strip()) >= 2][:5]
    except Exception:
        pass

    # LLM 실패 시 규칙 기반 폴백
    return get_query_router()._extract_keywords(query)[:5]


def extract_keywords_sync(query: str) -> List[str]:
    """동기 버전 키워드 추출 (규칙 기반)."""
    return get_query_router()._extract_keywords(query)[:5]
