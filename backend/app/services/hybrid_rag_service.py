# Hybrid RAG 서비스 - FAISS + Graph + Wiki 결합 검색
# -*- coding: utf-8 -*-
"""
Hybrid RAG Service - 여러 검색 소스를 결합하는 통합 RAG 서비스.

Phase 7에서 구현된 핵심 서비스로 다음을 수행한다.
1. FAISS 벡터 검색
2. GraphRAG Agent 실행
3. LLM-Wiki 검색 (향후 연동)
4. 결과 병합 및 중복 제거
5. Re-ranking
6. 최종 답변 생성
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from app.agents.graphrag_agent import (
    GraphRAGAgent,
    GraphRAGResponse,
    AgentStatus,
    get_graphrag_agent,
)
from app.services.faiss_search_service import (
    FaissSearchService,
    FaissSearchResponse,
    FaissSearchResult,
    get_faiss_search_service,
)


class SearchSource(str, Enum):
    """검색 소스."""
    FAISS = "faiss"
    GRAPH = "graph"
    WIKI = "wiki"


class MergeStrategy(str, Enum):
    """결과 병합 전략."""
    INTERLEAVE = "interleave"  # 번갈아가며 병합
    FAISS_FIRST = "faiss_first"  # FAISS 결과 우선
    GRAPH_FIRST = "graph_first"  # Graph 결과 우선
    SCORE_BASED = "score_based"  # 점수 기반 정렬


@dataclass
class MergedDocument:
    """병합된 문서 결과."""
    document_id: str
    source: SearchSource
    rank: int
    score: float
    title: Optional[str] = None
    category: Optional[str] = None
    organization: Optional[str] = None
    file_name: Optional[str] = None
    text_preview: Optional[str] = None
    chunk_id: Optional[str] = None
    graph_relations: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class HybridRAGResponse:
    """Hybrid RAG 응답."""
    success: bool
    question: str
    answer: Optional[str] = None

    # 개별 검색 결과
    faiss_results: list[dict] = field(default_factory=list)
    graph_results: list[dict] = field(default_factory=list)
    wiki_results: list[dict] = field(default_factory=list)

    # 병합된 결과
    merged_documents: list[dict] = field(default_factory=list)

    # Graph 메타데이터
    graph_cypher: list[str] = field(default_factory=list)
    graph_retry_count: int = 0
    graph_question_type: Optional[str] = None

    # 근거
    evidence: list[dict] = field(default_factory=list)

    # 통계
    faiss_count: int = 0
    graph_count: int = 0
    wiki_count: int = 0
    merged_count: int = 0

    # 타이밍
    faiss_time_ms: int = 0
    graph_time_ms: int = 0
    wiki_time_ms: int = 0
    merge_time_ms: int = 0
    total_time_ms: int = 0

    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class HybridRAGService:
    """Hybrid RAG 서비스."""

    def __init__(
        self,
        source_id: Optional[str] = None,
        enable_graph: bool = True,
        enable_wiki: bool = False,  # 향후 구현
        merge_strategy: MergeStrategy = MergeStrategy.SCORE_BASED,
    ):
        """
        Args:
            source_id: 데이터 소스 ID
            enable_graph: GraphRAG 활성화
            enable_wiki: Wiki 검색 활성화 (향후)
            merge_strategy: 결과 병합 전략
        """
        self.source_id = source_id
        self.enable_graph = enable_graph
        self.enable_wiki = enable_wiki
        self.merge_strategy = merge_strategy

        self.faiss_service = get_faiss_search_service(source_id)
        self.graph_agent = get_graphrag_agent(source_id) if enable_graph else None

    async def _search_faiss(
        self,
        query: str,
        top_k: int = 10,
    ) -> tuple[list[dict], int]:
        """FAISS 검색."""
        start_time = time.time()

        response = self.faiss_service.search(
            query=query,
            top_k=top_k,
        )

        elapsed_ms = int((time.time() - start_time) * 1000)

        if not response.success:
            return [], elapsed_ms

        results = []
        for r in response.results:
            results.append({
                "document_id": r.document_id,
                "chunk_id": r.chunk_id,
                "score": r.score,
                "rank": r.rank,
                "category": r.category,
                "organization": r.organization,
                "file_name": r.file_name,
                "text_preview": r.text_preview,
                "source": SearchSource.FAISS.value,
            })

        return results, elapsed_ms

    async def _search_graph(
        self,
        query: str,
    ) -> tuple[list[dict], list[str], int, int, str]:
        """GraphRAG Agent 검색."""
        if not self.graph_agent:
            return [], [], 0, 0, ""

        start_time = time.time()

        response = await self.graph_agent.process(query)

        elapsed_ms = int((time.time() - start_time) * 1000)

        results = []
        for node in response.results:
            results.append({
                "document_id": node.get("document_id") or node.get("id", ""),
                "node_id": node.get("id", ""),
                "node_type": node.get("type", ""),
                "label": node.get("label", ""),
                "category": node.get("category", ""),
                "organization": node.get("organization", ""),
                "project_name": node.get("project_name", ""),
                "source_path": node.get("source_path", ""),
                "score": 1.0,  # Graph 결과는 기본 점수 1.0
                "source": SearchSource.GRAPH.value,
            })

        # Fallback 결과 추가
        for fb in response.fallback_results:
            results.append({
                "document_id": fb.get("document_id", ""),
                "chunk_id": fb.get("chunk_id", ""),
                "score": fb.get("score", 0.5),
                "category": fb.get("category", ""),
                "organization": fb.get("organization", ""),
                "file_name": fb.get("file_name", ""),
                "text_preview": fb.get("text_preview", ""),
                "source": f"{SearchSource.GRAPH.value}_fallback",
            })

        # 재시도 횟수 계산
        retry_count = len([s for s in response.steps if "retry" in s.step_name.lower() or "_2" in s.step_name or "_3" in s.step_name])

        return (
            results,
            response.cypher_queries,
            retry_count,
            elapsed_ms,
            response.question_type.value,
        )

    async def _search_wiki(
        self,
        query: str,
        top_k: int = 5,
    ) -> tuple[list[dict], int]:
        """LLM-Wiki 검색 (향후 구현)."""
        # TODO: Phase 10에서 구현
        return [], 0

    def _merge_results(
        self,
        faiss_results: list[dict],
        graph_results: list[dict],
        wiki_results: list[dict],
        max_results: int = 20,
    ) -> list[MergedDocument]:
        """결과 병합 및 중복 제거."""
        start_time = time.time()

        # 문서 ID 기준 병합
        doc_map: dict[str, MergedDocument] = {}

        # FAISS 결과 추가
        for i, r in enumerate(faiss_results):
            doc_id = r.get("document_id", "")
            if not doc_id:
                doc_id = r.get("chunk_id", f"faiss_{i}")

            if doc_id not in doc_map:
                doc_map[doc_id] = MergedDocument(
                    document_id=doc_id,
                    source=SearchSource.FAISS,
                    rank=i + 1,
                    score=r.get("score", 0.0),
                    category=r.get("category"),
                    organization=r.get("organization"),
                    file_name=r.get("file_name"),
                    text_preview=r.get("text_preview"),
                    chunk_id=r.get("chunk_id"),
                )
            else:
                # 이미 있으면 점수 업데이트
                existing = doc_map[doc_id]
                existing.score = max(existing.score, r.get("score", 0.0))

        # Graph 결과 추가
        for i, r in enumerate(graph_results):
            doc_id = r.get("document_id", "") or r.get("node_id", f"graph_{i}")

            if doc_id not in doc_map:
                doc_map[doc_id] = MergedDocument(
                    document_id=doc_id,
                    source=SearchSource.GRAPH,
                    rank=i + 1,
                    score=r.get("score", 1.0),
                    title=r.get("label"),
                    category=r.get("category"),
                    organization=r.get("organization"),
                    file_name=r.get("source_path"),
                    metadata={
                        "node_type": r.get("node_type"),
                        "project_name": r.get("project_name"),
                    },
                )
            else:
                # 이미 있으면 Graph 정보 추가
                existing = doc_map[doc_id]
                existing.graph_relations.append({
                    "node_id": r.get("node_id"),
                    "node_type": r.get("node_type"),
                    "label": r.get("label"),
                })
                # 점수 부스트 (FAISS + Graph 둘 다 있으면)
                existing.score *= 1.2

        # Wiki 결과 추가 (향후)
        for i, r in enumerate(wiki_results):
            doc_id = r.get("document_id", f"wiki_{i}")
            if doc_id not in doc_map:
                doc_map[doc_id] = MergedDocument(
                    document_id=doc_id,
                    source=SearchSource.WIKI,
                    rank=i + 1,
                    score=r.get("score", 0.5),
                    title=r.get("title"),
                    text_preview=r.get("content"),
                )

        # 병합 전략에 따라 정렬
        merged = list(doc_map.values())

        if self.merge_strategy == MergeStrategy.SCORE_BASED:
            merged.sort(key=lambda x: x.score, reverse=True)
        elif self.merge_strategy == MergeStrategy.FAISS_FIRST:
            merged.sort(key=lambda x: (x.source != SearchSource.FAISS, -x.score))
        elif self.merge_strategy == MergeStrategy.GRAPH_FIRST:
            merged.sort(key=lambda x: (x.source != SearchSource.GRAPH, -x.score))
        elif self.merge_strategy == MergeStrategy.INTERLEAVE:
            # FAISS와 Graph를 번갈아가며 배치
            faiss_docs = [d for d in merged if d.source == SearchSource.FAISS]
            graph_docs = [d for d in merged if d.source == SearchSource.GRAPH]
            other_docs = [d for d in merged if d.source not in (SearchSource.FAISS, SearchSource.GRAPH)]

            interleaved = []
            max_len = max(len(faiss_docs), len(graph_docs))
            for i in range(max_len):
                if i < len(faiss_docs):
                    interleaved.append(faiss_docs[i])
                if i < len(graph_docs):
                    interleaved.append(graph_docs[i])
            interleaved.extend(other_docs)
            merged = interleaved

        # 순위 재설정
        for i, doc in enumerate(merged[:max_results]):
            doc.rank = i + 1

        return merged[:max_results]

    def _build_evidence(
        self,
        merged_docs: list[MergedDocument],
        graph_cypher: list[str],
    ) -> list[dict]:
        """근거 정보 생성."""
        evidence = []

        for doc in merged_docs[:5]:  # 상위 5개만
            evidence.append({
                "document_id": doc.document_id,
                "source": doc.source.value,
                "title": doc.title or doc.file_name,
                "category": doc.category,
                "organization": doc.organization,
                "score": doc.score,
                "graph_relations": doc.graph_relations,
            })

        # Graph Cypher 추가
        if graph_cypher:
            evidence.append({
                "type": "cypher_queries",
                "queries": graph_cypher,
            })

        return evidence

    async def query(
        self,
        question: str,
        top_k: int = 10,
        max_results: int = 20,
        generate_answer: bool = False,
    ) -> HybridRAGResponse:
        """
        Hybrid RAG 쿼리 실행.

        Args:
            question: 사용자 질문
            top_k: 각 소스별 최대 결과 수
            max_results: 병합 후 최대 결과 수
            generate_answer: LLM 답변 생성 여부

        Returns:
            HybridRAGResponse: 통합 검색 결과
        """
        total_start = time.time()

        try:
            # 병렬 검색 실행
            tasks = [
                self._search_faiss(question, top_k),
            ]

            if self.enable_graph:
                tasks.append(self._search_graph(question))

            if self.enable_wiki:
                tasks.append(self._search_wiki(question, top_k))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 결과 파싱
            faiss_results, faiss_time = [], 0
            graph_results, graph_cypher, graph_retry, graph_time, graph_question_type = [], [], 0, 0, ""
            wiki_results, wiki_time = [], 0

            result_idx = 0

            # FAISS 결과
            if not isinstance(results[result_idx], Exception):
                faiss_results, faiss_time = results[result_idx]
            result_idx += 1

            # Graph 결과
            if self.enable_graph and result_idx < len(results):
                if not isinstance(results[result_idx], Exception):
                    graph_results, graph_cypher, graph_retry, graph_time, graph_question_type = results[result_idx]
                result_idx += 1

            # Wiki 결과
            if self.enable_wiki and result_idx < len(results):
                if not isinstance(results[result_idx], Exception):
                    wiki_results, wiki_time = results[result_idx]

            # 결과 병합
            merge_start = time.time()
            merged_docs = self._merge_results(
                faiss_results, graph_results, wiki_results, max_results
            )
            merge_time = int((time.time() - merge_start) * 1000)

            # 근거 생성
            evidence = self._build_evidence(merged_docs, graph_cypher)

            # 답변 생성 (옵션)
            answer = None
            if generate_answer and merged_docs:
                # TODO: LLM 답변 생성 구현
                answer = None

            total_time = int((time.time() - total_start) * 1000)

            return HybridRAGResponse(
                success=True,
                question=question,
                answer=answer,
                faiss_results=faiss_results,
                graph_results=graph_results,
                wiki_results=wiki_results,
                merged_documents=[
                    {
                        "document_id": d.document_id,
                        "source": d.source.value,
                        "rank": d.rank,
                        "score": d.score,
                        "title": d.title,
                        "category": d.category,
                        "organization": d.organization,
                        "file_name": d.file_name,
                        "text_preview": d.text_preview,
                        "chunk_id": d.chunk_id,
                        "graph_relations": d.graph_relations,
                        "metadata": d.metadata,
                    }
                    for d in merged_docs
                ],
                graph_cypher=graph_cypher,
                graph_retry_count=graph_retry,
                graph_question_type=graph_question_type,
                evidence=evidence,
                faiss_count=len(faiss_results),
                graph_count=len(graph_results),
                wiki_count=len(wiki_results),
                merged_count=len(merged_docs),
                faiss_time_ms=faiss_time,
                graph_time_ms=graph_time,
                wiki_time_ms=wiki_time,
                merge_time_ms=merge_time,
                total_time_ms=total_time,
            )

        except Exception as e:
            return HybridRAGResponse(
                success=False,
                question=question,
                error=str(e),
                total_time_ms=int((time.time() - total_start) * 1000),
            )


# 싱글톤 인스턴스 캐시
_services: dict[str, HybridRAGService] = {}


def get_hybrid_rag_service(
    source_id: Optional[str] = None,
    enable_graph: bool = True,
    enable_wiki: bool = False,
) -> HybridRAGService:
    """HybridRAGService 싱글톤 반환."""
    key = f"{source_id or '_default_'}_{enable_graph}_{enable_wiki}"
    if key not in _services:
        _services[key] = HybridRAGService(source_id, enable_graph, enable_wiki)
    return _services[key]
