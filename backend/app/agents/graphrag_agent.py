# GraphRAG Agent - 자동 수정 루프가 있는 Graph 기반 RAG 에이전트
# -*- coding: utf-8 -*-
"""
GraphRAG Agent - Graph 데이터를 활용한 RAG 에이전트.

Phase 6에서 구현된 핵심 Agent로 다음 단계를 수행한다.
1. 질문 유형 분석
2. Graph Schema 로드
3. Cypher 생성
4. Cypher 보안 검증
5. Graph DB 실행
6. 결과 평가
7. 결과 0건 또는 오류 시 쿼리 수정
8. 최대 2회 재시도
9. 실패 시 FAISS 검색 fallback
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from app.models.graph_schema import generate_schema_text, NodeType, RelationType
from app.services.cypher_guard import validate_cypher, ValidationResult
from app.services.graph_query_service import (
    GraphQueryService,
    GraphQueryResult,
    QueryResultQuality,
    get_graph_query_service,
)
from app.services.text2cypher_service import (
    Text2CypherService,
    Text2CypherResult,
    get_text2cypher_service,
)
from app.services.faiss_search_service import (
    FaissSearchService,
    FaissSearchResponse,
    get_faiss_search_service,
)


class QuestionType(str, Enum):
    """질문 유형."""
    ENTITY_SEARCH = "entity_search"       # 특정 엔티티 검색 (기관, 프로젝트 등)
    RELATION_SEARCH = "relation_search"   # 관계 기반 검색 (A와 연결된 B)
    AGGREGATE = "aggregate"               # 집계 쿼리 (개수, 통계)
    SEMANTIC = "semantic"                 # 의미 기반 검색 (FAISS 필요)
    UNKNOWN = "unknown"                   # 분류 불가


class AgentStatus(str, Enum):
    """Agent 실행 상태."""
    SUCCESS = "success"
    PARTIAL = "partial"      # 일부 결과만 있음
    FALLBACK = "fallback"    # FAISS fallback 사용
    FAILED = "failed"


@dataclass
class AgentStep:
    """Agent 실행 단계 기록."""
    step_name: str
    status: str
    details: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class GraphRAGResponse:
    """GraphRAG Agent 응답."""
    status: AgentStatus
    question: str
    question_type: QuestionType
    results: list[dict] = field(default_factory=list)
    result_count: int = 0
    cypher_queries: list[str] = field(default_factory=list)
    steps: list[AgentStep] = field(default_factory=list)
    fallback_used: bool = False
    fallback_results: list[dict] = field(default_factory=list)
    error: Optional[str] = None
    total_time_ms: int = 0


class GraphRAGAgent:
    """GraphRAG Agent - 자동 수정 루프가 있는 Graph 기반 RAG 에이전트."""

    MAX_RETRIES = 2  # 최대 재시도 횟수

    def __init__(
        self,
        source_id: Optional[str] = None,
        enable_fallback: bool = True,
    ):
        """
        Args:
            source_id: Graph 데이터 소스 ID
            enable_fallback: FAISS fallback 활성화 여부
        """
        self.source_id = source_id
        self.enable_fallback = enable_fallback
        self.text2cypher = get_text2cypher_service()
        self.graph_query = get_graph_query_service(source_id)
        self.faiss_search = get_faiss_search_service(source_id)
        self._steps: list[AgentStep] = []

    def _add_step(self, step_name: str, status: str, details: dict = None) -> None:
        """실행 단계 기록."""
        self._steps.append(AgentStep(
            step_name=step_name,
            status=status,
            details=details or {},
        ))

    def _analyze_question_type(self, question: str) -> QuestionType:
        """
        질문 유형 분석.

        간단한 규칙 기반 분류. 향후 LLM 기반으로 확장 가능.
        """
        question_lower = question.lower()

        # 집계 패턴
        aggregate_patterns = [
            r"몇\s*개", r"몇\s*건", r"개수", r"총\s*수", r"통계",
            r"얼마나", r"count", r"how many",
        ]
        for pattern in aggregate_patterns:
            if re.search(pattern, question_lower):
                return QuestionType.AGGREGATE

        # 관계 검색 패턴
        relation_patterns = [
            r"와\s*관련된", r"에서\s*진행한", r"의\s*문서",
            r"발주한", r"수행한", r"참여한", r"사용한",
            r"연결된", r"관계", r"related", r"connected",
        ]
        for pattern in relation_patterns:
            if re.search(pattern, question_lower):
                return QuestionType.RELATION_SEARCH

        # 엔티티 검색 패턴
        entity_patterns = [
            r"찾아", r"검색", r"조회", r"목록", r"리스트",
            r"어떤", r"무엇", r"어디", r"누구",
            r"search", r"find", r"list", r"show",
        ]
        for pattern in entity_patterns:
            if re.search(pattern, question_lower):
                return QuestionType.ENTITY_SEARCH

        # 의미 기반 패턴 (추상적 질문)
        semantic_patterns = [
            r"비슷한", r"유사한", r"추천", r"제안",
            r"어떻게", r"왜", r"설명", r"분석",
            r"similar", r"recommend", r"suggest",
        ]
        for pattern in semantic_patterns:
            if re.search(pattern, question_lower):
                return QuestionType.SEMANTIC

        # 기본적으로 엔티티 검색
        return QuestionType.ENTITY_SEARCH

    async def _generate_cypher(
        self,
        question: str,
        retry_context: Optional[str] = None,
    ) -> Text2CypherResult:
        """
        Cypher 쿼리 생성.

        Args:
            question: 원본 질문
            retry_context: 재시도 시 추가 컨텍스트 (이전 실패 정보)
        """
        if retry_context:
            enhanced_question = f"{question}\n\n[이전 시도 실패 정보: {retry_context}]"
        else:
            enhanced_question = question

        return await self.text2cypher.generate_cypher(
            question=enhanced_question,
            temperature=0.1,  # 낮은 온도로 결정적 생성
        )

    def _execute_cypher(self, cypher: str) -> GraphQueryResult:
        """Cypher 쿼리 실행."""
        return self.graph_query.execute_query(cypher)

    def _should_retry(self, result: GraphQueryResult) -> bool:
        """재시도 필요 여부 판단."""
        if not result.success:
            return True
        if result.evaluation and result.evaluation.should_retry:
            return True
        if result.evaluation and result.evaluation.quality == QueryResultQuality.EMPTY:
            return True
        return False

    def _generate_retry_context(self, result: GraphQueryResult) -> str:
        """재시도용 컨텍스트 생성."""
        context_parts = []

        if result.error:
            context_parts.append(f"오류: {result.error}")

        if result.evaluation:
            if result.evaluation.quality == QueryResultQuality.EMPTY:
                context_parts.append("결과 0건")
            if result.evaluation.suggestions:
                context_parts.append(f"제안: {', '.join(result.evaluation.suggestions)}")

        context_parts.append(f"이전 쿼리: {result.cypher}")

        return " | ".join(context_parts)

    async def _faiss_fallback(
        self,
        question: str,
        top_k: int = 10,
    ) -> list[dict]:
        """
        FAISS 검색 fallback.

        Graph 검색이 실패하거나 결과가 없을 때 벡터 검색으로 대체.

        Args:
            question: 검색 쿼리
            top_k: 최대 결과 수

        Returns:
            검색 결과 리스트
        """
        try:
            response = self.faiss_search.search(
                query=question,
                top_k=top_k,
                min_score=0.1,  # 최소 유사도
            )

            if not response.success:
                self._add_step("faiss_search", "failed", {
                    "error": response.error,
                })
                return []

            self._add_step("faiss_search", "success", {
                "result_count": response.result_count,
                "search_time_ms": response.search_time_ms,
            })

            # FaissSearchResult를 dict로 변환
            results = []
            for r in response.results:
                results.append({
                    "type": "chunk",
                    "rank": r.rank,
                    "score": r.score,
                    "chunk_id": r.chunk_id,
                    "document_id": r.document_id,
                    "category": r.category,
                    "organization": r.organization,
                    "file_name": r.file_name,
                    "text_preview": r.text_preview,
                    "source": "faiss_fallback",
                })

            return results

        except Exception as e:
            self._add_step("faiss_search", "error", {
                "error": str(e),
            })
            return []

    async def process(self, question: str) -> GraphRAGResponse:
        """
        질문 처리 - 메인 Agent 루프.

        Args:
            question: 사용자 질문

        Returns:
            GraphRAGResponse: Agent 응답
        """
        import time
        start_time = time.time()
        self._steps = []
        cypher_queries = []

        # Step 1: 질문 유형 분석
        question_type = self._analyze_question_type(question)
        self._add_step("analyze_question", "success", {
            "question_type": question_type.value,
        })

        # 의미 기반 질문은 바로 FAISS fallback
        if question_type == QuestionType.SEMANTIC:
            self._add_step("semantic_detected", "info", {
                "message": "의미 기반 질문 - FAISS fallback 사용",
            })
            if self.enable_fallback:
                fallback_results = await self._faiss_fallback(question)
                return GraphRAGResponse(
                    status=AgentStatus.FALLBACK if fallback_results else AgentStatus.FAILED,
                    question=question,
                    question_type=question_type,
                    fallback_used=True,
                    fallback_results=fallback_results,
                    steps=self._steps,
                    total_time_ms=int((time.time() - start_time) * 1000),
                )

        # Step 2: Cypher 생성 및 실행 루프
        retry_context = None
        final_result: Optional[GraphQueryResult] = None

        for attempt in range(self.MAX_RETRIES + 1):
            # Cypher 생성
            cypher_result = await self._generate_cypher(question, retry_context)
            self._add_step(f"generate_cypher_{attempt + 1}",
                          "success" if cypher_result.success else "failed", {
                "cypher": cypher_result.cypher,
                "error": cypher_result.error,
                "generation_time_ms": cypher_result.generation_time_ms,
            })

            if not cypher_result.success:
                retry_context = f"Cypher 생성 실패: {cypher_result.error}"
                continue

            cypher_queries.append(cypher_result.cypher)

            # Cypher 검증
            validation = validate_cypher(cypher_result.cypher)
            self._add_step(f"validate_cypher_{attempt + 1}",
                          "success" if validation.is_valid else "blocked", {
                "is_valid": validation.is_valid,
                "message": validation.message,
                "blocked_keyword": validation.blocked_keyword,
            })

            if not validation.is_valid:
                retry_context = f"보안 검증 실패: {validation.message}"
                continue

            # Cypher 실행
            query_result = self._execute_cypher(
                validation.sanitized_query or cypher_result.cypher
            )
            self._add_step(f"execute_cypher_{attempt + 1}",
                          "success" if query_result.success else "failed", {
                "result_count": len(query_result.results),
                "quality": query_result.evaluation.quality.value if query_result.evaluation else "unknown",
                "execution_time_ms": query_result.execution_time_ms,
            })

            final_result = query_result

            # 재시도 필요 여부 확인
            if not self._should_retry(query_result):
                break

            retry_context = self._generate_retry_context(query_result)

        # Step 3: 결과 평가 및 fallback 결정
        results = final_result.results if final_result else []
        fallback_used = False
        fallback_results = []

        if not results and self.enable_fallback:
            self._add_step("faiss_fallback", "triggered", {
                "reason": "Graph 검색 결과 없음",
            })
            fallback_results = await self._faiss_fallback(question)
            fallback_used = True

        # 최종 응답 생성
        if results:
            status = AgentStatus.SUCCESS
        elif fallback_results:
            status = AgentStatus.FALLBACK
        elif final_result and final_result.success:
            status = AgentStatus.PARTIAL
        else:
            status = AgentStatus.FAILED

        return GraphRAGResponse(
            status=status,
            question=question,
            question_type=question_type,
            results=results,
            result_count=len(results),
            cypher_queries=cypher_queries,
            steps=self._steps,
            fallback_used=fallback_used,
            fallback_results=fallback_results,
            error=final_result.error if final_result else None,
            total_time_ms=int((time.time() - start_time) * 1000),
        )

    def get_schema_summary(self) -> dict:
        """Graph Schema 요약 반환."""
        return {
            "node_types": [nt.value for nt in NodeType],
            "relation_types": [rt.value for rt in RelationType],
            "schema_text": generate_schema_text(),
        }


# 싱글톤 인스턴스 캐시
_agents: dict[str, GraphRAGAgent] = {}


def get_graphrag_agent(
    source_id: Optional[str] = None,
    enable_fallback: bool = True,
) -> GraphRAGAgent:
    """GraphRAG Agent 싱글톤 반환."""
    key = f"{source_id or '_default_'}_{enable_fallback}"
    if key not in _agents:
        _agents[key] = GraphRAGAgent(source_id, enable_fallback)
    return _agents[key]
