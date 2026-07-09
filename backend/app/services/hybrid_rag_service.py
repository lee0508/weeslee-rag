# Hybrid RAG 서비스 - FAISS + Graph + Wiki 결합 검색 (Query Router 통합)
# -*- coding: utf-8 -*-
"""
Hybrid RAG Service - 여러 검색 소스를 결합하는 통합 RAG 서비스.

Phase 7에서 구현된 핵심 서비스로 다음을 수행한다.
1. Query Router로 질문 분석 (의도, 필터, 복잡도)
2. 질문 유형별 검색 소스 및 순서 결정
3. FAISS 벡터 검색
4. GraphRAG Agent 실행
5. LLM-Wiki 검색
6. 결과 병합 및 중복 제거
7. Re-ranking
8. 최종 답변 생성
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from app.agents.graphrag_agent import (
    get_graphrag_agent,
)
from app.services.faiss_search_service import (
    get_faiss_search_service,
)
from app.services.query_router import (
    QueryAnalysis,
    QueryIntent,
    SearchSource as RouterSearchSource,
    get_query_router,
    extract_keywords_with_llm,
)
from app.services.wiki_search_service import (
    get_wiki_search_service,
)
from app.services.rag_runtime import run_rag_query


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
    ranking_score: float = 0.0
    faiss_score: float = 0.0
    graph_score: float = 0.0


@dataclass
class HybridRAGResponse:
    """Hybrid RAG 응답."""
    success: bool
    question: str
    answer: Optional[str] = None

    # Query Router 분석 결과
    query_analysis: Optional[dict] = None

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
    query_analysis_time_ms: int = 0
    faiss_time_ms: int = 0
    graph_time_ms: int = 0
    wiki_time_ms: int = 0
    merge_time_ms: int = 0
    total_time_ms: int = 0

    # 검색 전략 정보
    search_order: Optional[str] = None
    sources_used: list[str] = field(default_factory=list)

    # LLM 추출 핵심 키워드 (하이라이트용)
    extracted_keywords: list[str] = field(default_factory=list)

    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class HybridRAGService:
    """Hybrid RAG 서비스."""

    _GENERIC_QUERY_TERMS = {
        "관련", "관련된", "내용", "문서", "파일", "사업", "자료", "장표", "슬라이드",
        "찾아줘", "검색", "조회", "알려줘", "보여줘", "안에서", "중에서", "원하는",
        "대한", "부분", "있는", "있는지",
    }

    @staticmethod
    def _normalize_project_type_value(value: Optional[str]) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""

        normalized = raw.replace(" ", "")
        alias_map = {
            "업무시스템개선": "시스템개선",
            "시스템개선사업": "시스템개선",
            "플랫폼개선": "플랫폼고도화",
            "플랫폼고도화": "플랫폼고도화",
            "플랫폼구축": "플랫폼고도화",
            "isp": "isp수립",
            "정보화전략계획": "isp수립",
            "bpr": "bprisp",
            "bpr/isp": "bprisp",
            "bprisp": "bprisp",
        }
        return alias_map.get(normalized, normalized)

    @staticmethod
    def _normalize_document_group_value(value: Optional[str]) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""

        alias_map = {
            "proposal": "제안서",
            "deliverable": "산출물",
            "rfp": "rfp",
        }
        return alias_map.get(raw, raw)

    @staticmethod
    def _normalize_section_value(value: Optional[str]) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""
        return raw.replace(" ", "")

    @staticmethod
    def _normalize_soft_hints(
        hints: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        if not hints:
            return normalized

        for key in (
            "organization",
            "organization_type",
            "project_type",
            "document_group",
            "document_category",
            "section_type",
            "topic",
        ):
            value = hints.get(key)
            if isinstance(value, str):
                value = value.strip()
                if value:
                    if key == "project_type":
                        normalized[key] = HybridRAGService._normalize_project_type_value(value)
                    elif key == "document_group":
                        normalized[key] = HybridRAGService._normalize_document_group_value(value)
                    elif key in ("document_category", "section_type"):
                        normalized[key] = HybridRAGService._normalize_section_value(value)
                    else:
                        normalized[key] = value.lower()

        inferred_terms = hints.get("inferred_terms")
        if isinstance(inferred_terms, list):
            terms = [
                str(term).strip().lower()
                for term in inferred_terms
                if str(term).strip()
            ]
            if terms:
                normalized["inferred_terms"] = terms

        return normalized

    @classmethod
    def _sanitize_inferred_terms(cls, terms: Optional[list[str]]) -> list[str]:
        cleaned: list[str] = []
        for term in terms or []:
            token = str(term or "").strip().lower()
            if not token:
                continue
            compact = token.replace(" ", "")
            if compact in cls._GENERIC_QUERY_TERMS:
                continue
            if len(compact) < 2:
                continue
            if compact not in cleaned:
                cleaned.append(compact)
        return cleaned[:8]

    @staticmethod
    def _normalize_search_query_text(value: Optional[str]) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        suffix_candidates = ("사례", "분석", "비교", "도입", "구축", "관리", "계획", "전략", "모델")
        normalized = re.sub(r"[+|]+", " ", raw)
        normalized = re.sub(r"\s+", " ", normalized).strip()

        expanded_tokens: list[str] = []
        for token in normalized.split():
            if "/" not in token:
                expanded_tokens.append(token)
                continue

            parts = [part.strip() for part in token.split("/") if part.strip()]
            if len(parts) < 2:
                expanded_tokens.append(token.replace("/", " "))
                continue

            left, right = parts[0], parts[1]
            variant_tokens = []
            for suffix in suffix_candidates:
                if right.endswith(suffix) and not left.endswith(suffix):
                    variant_tokens.append(f"{left}{suffix}")
                    break
            variant_tokens.extend(parts)

            for variant in variant_tokens:
                if variant and variant not in expanded_tokens:
                    expanded_tokens.append(variant)

        return " ".join(expanded_tokens)

    @staticmethod
    def _extract_literal_section_hint(question: str) -> Optional[str]:
        normalized = str(question or "").replace(" ", "")
        for value in (
            "전략및방법론",
            "기술및기능",
            "프로젝트관리",
            "프로젝트지원",
            "환경분석",
            "현황분석",
            "목표모델",
            "이행계획",
        ):
            if value in normalized:
                return value
        return None

    @classmethod
    def _infer_question_hints(cls, question: str) -> dict[str, Any]:
        """질문문에서 문서 필터와 랭킹 힌트를 직접 추론한다."""
        raw = str(question or "").strip()
        normalized = raw.replace(" ", "")
        hints: dict[str, Any] = {}
        inferred_terms: list[str] = []

        if "제안서" in raw:
            hints["document_group"] = "제안서"
        elif "산출물" in raw:
            hints["document_group"] = "산출물"
        elif re.search(r"\bRFP\b|제안요청서", raw, re.IGNORECASE):
            hints["document_group"] = "RFP"

        literal_section = cls._extract_literal_section_hint(raw)
        if literal_section:
            hints["document_category"] = literal_section
            hints["section_type"] = literal_section
            inferred_terms.append(literal_section)

        if "공공기관" in raw:
            hints["organization_type"] = "공공기관"
            inferred_terms.append("공공기관")
        elif "연구기관" in raw:
            hints["organization_type"] = "연구기관"
            inferred_terms.extend(["연구기관", "연구원", "연구소"])

        if "업무시스템개선" in normalized or ("업무시스템" in raw and "개선" in raw):
            hints["project_type"] = "시스템개선"
            inferred_terms.extend(["업무시스템", "개선"])
        elif "플랫폼고도화" in normalized or "플랫폼개선" in normalized or ("플랫폼" in raw and ("고도화" in raw or "개선" in raw)):
            hints["project_type"] = "플랫폼고도화"
            inferred_terms.extend(["플랫폼", "고도화"])
        elif "컨설팅사업" in normalized or "컨설팅" in raw:
            hints["project_type"] = "컨설팅"
            inferred_terms.append("컨설팅")
        elif "시스템도입" in normalized or ("시스템" in raw and "도입" in raw):
            hints["project_type"] = "시스템구축"
            inferred_terms.extend(["시스템", "도입"])

        if "AI" in raw or "인공지능" in raw:
            hints["topic"] = "ai"
            inferred_terms.extend(["ai", "인공지능"])

        for token in (
            "의사소통관리",
            "의사소통",
            "선진사례",
            "유사사례",
            "사례분석",
            "현황분석",
            "환경분석",
            "기술및기능",
            "프로젝트관리",
            "업무시스템",
            "플랫폼",
            "고도화",
            "개선",
        ):
            if token in normalized and token.lower() not in inferred_terms:
                inferred_terms.append(token.lower())

        if inferred_terms:
            hints["inferred_terms"] = cls._sanitize_inferred_terms(inferred_terms)

        return hints

    def __init__(
        self,
        source_id: Optional[str] = None,
        enable_graph: bool = True,
        enable_wiki: bool = True,
        merge_strategy: MergeStrategy = MergeStrategy.SCORE_BASED,
        use_query_router: bool = True,
    ):
        """
        Args:
            source_id: 데이터 소스 ID
            enable_graph: GraphRAG 활성화
            enable_wiki: Wiki 검색 활성화
            merge_strategy: 결과 병합 전략
            use_query_router: Query Router 사용 여부
        """
        self.source_id = source_id
        self.enable_graph = enable_graph
        self.enable_wiki = enable_wiki
        self.merge_strategy = merge_strategy
        self.use_query_router = use_query_router

        self.faiss_service = get_faiss_search_service(source_id)
        self.graph_agent = get_graphrag_agent(source_id) if enable_graph else None
        self.wiki_service = get_wiki_search_service(source_id) if enable_wiki else None
        self.query_router = get_query_router() if use_query_router else None

    async def _search_faiss(
        self,
        query: str,
        top_k: int = 10,
        *,
        category_filter: Optional[str] = None,
        organization_filter: Optional[str] = None,
        allowed_document_ids: Optional[set[str]] = None,
        metadata_filters: Optional[dict[str, Any]] = None,
    ) -> tuple[list[dict], int]:
        """FAISS 검색."""
        start_time = time.time()

        response = self.faiss_service.search(
            query=query,
            top_k=max(top_k * 10, top_k) if metadata_filters else top_k,
            category_filter=category_filter,
            organization_filter=organization_filter,
        )

        elapsed_ms = int((time.time() - start_time) * 1000)

        if not response.success:
            return [], elapsed_ms

        results = []
        for r in response.results:
            metadata = dict(r.metadata or {})
            metadata.setdefault("source_id", metadata.get("source_id") or self.source_id)
            metadata.setdefault("dataset_id", metadata.get("dataset_id"))
            metadata.setdefault("snapshot_id", metadata.get("snapshot_id") or metadata.get("faiss_snapshot"))
            metadata.setdefault("document_uid", metadata.get("document_uid"))
            metadata.setdefault("relative_path", metadata.get("relative_path"))
            metadata.setdefault("source_path", metadata.get("source_path") or r.source_path)
            metadata.setdefault("page_no", metadata.get("page_no") or r.page_no)
            metadata.setdefault("slide_no", metadata.get("slide_no") or r.slide_no)
            metadata.setdefault("section_title", metadata.get("section_title") or r.section_title)
            metadata.setdefault("section_id", metadata.get("section_id") or r.section_id)
            metadata.setdefault("organization", metadata.get("organization") or r.organization or "")
            metadata.setdefault("organization_type", metadata.get("organization_type") or r.organization_type or "")
            metadata.setdefault("client_type", metadata.get("client_type") or r.client_type or "")
            metadata.setdefault("project_type", metadata.get("project_type") or r.project_type or "")
            metadata.setdefault("section_type", metadata.get("section_type") or "")
            metadata.setdefault("search_keywords", metadata.get("search_keywords") or [])
            metadata.setdefault("file_name", metadata.get("file_name") or r.file_name or "")
            project_name = (
                metadata.get("project_name")
                or metadata.get("final_project_name")
                or metadata.get("ocr_project_name")
                or metadata.get("scan_project_name")
                or ""
            )
            metadata.setdefault("project_name", project_name)
            metadata.setdefault(
                "project_id",
                metadata.get("project_id") or (f"project:{project_name}" if project_name else ""),
            )
            document_id = str(r.document_id or "")
            if allowed_document_ids and document_id and document_id not in allowed_document_ids:
                continue

            candidate = {
                "document_id": r.document_id,
                "chunk_id": r.chunk_id,
                "score": r.score,
                "rank": r.rank,
                "category": r.category,
                "organization": r.organization,
                "organization_type": r.organization_type,
                "client_type": r.client_type,
                "project_type": r.project_type,
                "file_name": r.file_name,
                "text_preview": r.text_preview,
                "section_title": r.section_title,
                "section_id": r.section_id,
                "page_no": r.page_no,
                "slide_no": r.slide_no,
                "source_path": r.source_path,
                "source_id": metadata.get("source_id") or self.source_id,
                "dataset_id": metadata.get("dataset_id"),
                "snapshot_id": metadata.get("snapshot_id"),
                "document_uid": metadata.get("document_uid"),
                "relative_path": metadata.get("relative_path"),
                "project_name": metadata.get("project_name"),
                "project_id": metadata.get("project_id"),
                "metadata": metadata,
                "source": SearchSource.FAISS.value,
            }

            if not self._matches_metadata_filters(candidate, metadata_filters or {}):
                continue

            results.append({
                **candidate,
            })

        return results, elapsed_ms

    @staticmethod
    def _matches_metadata_filters(candidate: dict[str, Any], filters: dict[str, Any]) -> bool:
        if not filters:
            return True

        metadata = candidate.get("metadata") or {}
        category = str(candidate.get("category") or metadata.get("category") or "").strip().lower()
        project_type = HybridRAGService._normalize_project_type_value(
            candidate.get("project_type") or metadata.get("project_type") or ""
        )
        organization = str(candidate.get("organization") or metadata.get("organization") or "").strip().lower()
        organization_type = str(candidate.get("organization_type") or candidate.get("client_type") or metadata.get("organization_type") or metadata.get("client_type") or "").strip().lower()
        year = str(metadata.get("folder_year") or metadata.get("year") or "").strip().lower()
        document_group = HybridRAGService._normalize_document_group_value(metadata.get("document_group") or "")
        document_category = HybridRAGService._normalize_section_value(metadata.get("document_category") or "")
        section_type = HybridRAGService._normalize_section_value(
            metadata.get("section_type")
            or candidate.get("section_title")
            or metadata.get("section_title")
            or metadata.get("section_heading")
            or metadata.get("section_label")
            or ""
        )
        section_search_text = HybridRAGService._normalize_section_value(" ".join(
            str(value or "")
            for value in (
                metadata.get("document_category"),
                metadata.get("section_type"),
                candidate.get("section_title"),
                metadata.get("section_title"),
                metadata.get("section_heading"),
                metadata.get("section_label"),
                candidate.get("file_name"),
                metadata.get("file_name"),
            )
        ))

        def contains(actual: str, expected: str) -> bool:
            return not expected or expected in actual

        if filters.get("category") and not contains(category, str(filters["category"]).strip().lower()):
            return False
        if filters.get("organization") and not contains(organization, str(filters["organization"]).strip().lower()):
            return False
        if filters.get("organization_type") and not contains(organization_type, str(filters["organization_type"]).strip().lower()):
            return False
        if filters.get("project_type") and not contains(project_type, HybridRAGService._normalize_project_type_value(filters["project_type"])):
            return False
        if filters.get("year") and not contains(year, str(filters["year"]).strip().lower()):
            return False
        if filters.get("document_group") and not contains(document_group, HybridRAGService._normalize_document_group_value(filters["document_group"])):
            return False
        if filters.get("document_category") and not contains(section_search_text or document_category, HybridRAGService._normalize_section_value(filters["document_category"])):
            return False
        if filters.get("section_type") and not contains(section_search_text or section_type, HybridRAGService._normalize_section_value(filters["section_type"])):
            return False
        return True

    @staticmethod
    def _relax_project_type_filter(filters: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not filters:
            return filters
        relaxed = dict(filters)
        relaxed["project_type"] = None
        return relaxed

    @staticmethod
    def _graph_candidate_document_ids(graph_results: list[dict]) -> set[str]:
        candidate_ids: set[str] = set()
        for row in graph_results:
            doc_id = str(row.get("document_id") or "").strip()
            if doc_id:
                candidate_ids.add(doc_id)
        return candidate_ids

    async def _search_graph(
        self,
        query: str,
        *,
        metadata_filters: Optional[dict[str, Any]] = None,
    ) -> tuple[list[dict], list[str], int, int, str]:
        """GraphRAG Agent 검색."""
        if not self.graph_agent:
            return [], [], 0, 0, ""

        start_time = time.time()

        response = await self.graph_agent.process(query)

        elapsed_ms = int((time.time() - start_time) * 1000)

        results = []
        for node in response.results:
            metadata = {
                "source_id": node.get("source_id") or self.source_id,
                "dataset_id": node.get("dataset_id"),
                "snapshot_id": node.get("snapshot_id"),
                "document_uid": node.get("document_uid"),
                "relative_path": node.get("relative_path"),
                "source_path": node.get("source_path"),
                "file_name": node.get("file_name"),
                "project_name": node.get("project_name"),
                "project_id": node.get("project_id"),
                "document_group": node.get("document_group"),
                "document_category": node.get("document_category"),
                "section_type": node.get("section_type"),
                "project_type": node.get("project_type"),
                "organization_type": node.get("organization_type"),
                **(node.get("metadata") or {}),
            }
            candidate = {
                "document_id": node.get("document_id") or node.get("id", ""),
                "node_id": node.get("id", ""),
                "node_type": node.get("type", ""),
                "label": node.get("label", ""),
                "category": node.get("category", ""),
                "organization": node.get("organization", ""),
                "organization_type": node.get("organization_type", ""),
                "project_name": node.get("project_name", ""),
                "project_type": node.get("project_type", ""),
                "file_name": node.get("file_name", ""),
                "source_path": node.get("source_path", ""),
                "score": 1.0,  # Graph 결과는 기본 점수 1.0
                "source": SearchSource.GRAPH.value,
                "metadata": metadata,
            }
            if not self._matches_metadata_filters(candidate, metadata_filters or {}):
                continue
            results.append(candidate)

        # Fallback 결과 추가
        for fb in response.fallback_results:
            candidate = {
                "document_id": fb.get("document_id", ""),
                "chunk_id": fb.get("chunk_id", ""),
                "score": fb.get("score", 0.5),
                "category": fb.get("category", ""),
                "organization": fb.get("organization", ""),
                "file_name": fb.get("file_name", ""),
                "text_preview": fb.get("text_preview", ""),
                "source": f"{SearchSource.GRAPH.value}_fallback",
                "metadata": fb.get("metadata") or {},
            }
            if not self._matches_metadata_filters(candidate, metadata_filters or {}):
                continue
            results.append(candidate)

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
        category: Optional[str] = None,
        organization: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        """LLM-Wiki 검색."""
        if not self.wiki_service:
            return [], 0

        start_time = time.time()

        response = self.wiki_service.search(
            query=query,
            top_k=top_k,
            category=category,
            organization=organization,
        )

        elapsed_ms = int((time.time() - start_time) * 1000)

        if not response.success:
            return [], elapsed_ms

        results = []
        for r in response.results:
            results.append({
                "document_id": r.id,
                "title": r.title,
                "category": r.category,
                "organization": r.organization,
                "project_type": r.project_type,
                "technologies": r.technologies,
                "score": r.score,
                "rank": r.rank,
                "text_preview": r.text_preview,
                "source": SearchSource.WIKI.value,
            })

        return results, elapsed_ms

    def _classic_rag_fallback(
        self,
        *,
        question: str,
        faiss_query: str,
        top_k: int,
        max_results: int,
        category: Optional[str],
        organization: Optional[str],
        year: Optional[str],
        document_group: Optional[str],
        document_category: Optional[str],
        section_type: Optional[str],
    ) -> tuple[list[dict], list[MergedDocument], Optional[str]]:
        """Hybrid 0건 시 classic RAG 검색으로 리콜을 보장한다."""
        active_snapshot = self.faiss_service.get_index_stats().get("active_snapshot")
        if not active_snapshot:
            return [], [], None

        payload = run_rag_query(
            query=faiss_query or question,
            original_query=question,
            top_k=max(top_k * 10, top_k),
            top_docs=max_results,
            answer_provider="none",
            answer_model="",
            category=category,
            organization=organization,
            year=year,
            max_chunks_per_doc=3,
            mode="search",
            snapshot=active_snapshot,
            document_group=document_group,
            document_category=document_category,
            section_type=section_type,
        )
        documents = payload.get("documents") or []
        if not documents:
            return [], [], active_snapshot

        faiss_results: list[dict] = []
        merged_docs: list[MergedDocument] = []
        for rank, doc in enumerate(documents, start=1):
            metadata = {
                "source_id": doc.get("source_id") or self.source_id,
                "snapshot_id": doc.get("snapshot") or active_snapshot,
                "source_path": doc.get("source_path"),
                "original_source_path": doc.get("original_source_path"),
                "relative_path": doc.get("relative_path"),
                "document_group": doc.get("document_group"),
                "document_category": doc.get("document_category"),
                "section_label": doc.get("section_label"),
                "project_name": doc.get("project_name"),
                "search_keywords": doc.get("search_keywords") or [],
                "fallback_strategy": "classic_rag_query",
            }
            snippet = (doc.get("evidence_snippets") or [""])[0]
            score = float(doc.get("best_score") or 0.0)
            ranking_score = float(doc.get("ranking_score") or score)
            document_id = str(doc.get("document_id") or "")

            faiss_results.append({
                "document_id": document_id,
                "score": score,
                "rank": rank,
                "category": doc.get("category"),
                "organization": doc.get("organization"),
                "file_name": doc.get("file_name"),
                "text_preview": snippet,
                "source_id": metadata.get("source_id"),
                "snapshot_id": metadata.get("snapshot_id"),
                "relative_path": metadata.get("relative_path"),
                "source_path": metadata.get("source_path"),
                "metadata": metadata,
                "source": SearchSource.FAISS.value,
            })
            merged_docs.append(MergedDocument(
                document_id=document_id or f"classic_{rank}",
                source=SearchSource.FAISS,
                rank=rank,
                score=score,
                title=doc.get("project_name"),
                category=doc.get("category"),
                organization=doc.get("organization"),
                file_name=doc.get("file_name"),
                text_preview=snippet,
                metadata=metadata,
                ranking_score=ranking_score,
                faiss_score=score,
            ))

        return faiss_results, merged_docs, active_snapshot

    def _merge_results(
        self,
        faiss_results: list[dict],
        graph_results: list[dict],
        wiki_results: list[dict],
        question: str = "",
        max_results: int = 20,
        soft_metadata_hints: Optional[dict[str, Any]] = None,
    ) -> list[MergedDocument]:
        """결과 병합 및 중복 제거."""
        # 문서 ID 기준 병합
        doc_map: dict[str, MergedDocument] = {}

        # FAISS 결과 추가
        for i, r in enumerate(faiss_results):
            doc_id = r.get("document_id", "")
            if not doc_id:
                doc_id = r.get("chunk_id", f"faiss_{i}")

            faiss_score = r.get("score", 0.0)
            if doc_id not in doc_map:
                doc_map[doc_id] = MergedDocument(
                    document_id=doc_id,
                    source=SearchSource.FAISS,
                    rank=i + 1,
                    score=faiss_score,
                    faiss_score=faiss_score,
                    category=r.get("category"),
                    organization=r.get("organization"),
                    file_name=r.get("file_name"),
                    text_preview=r.get("text_preview"),
                    chunk_id=r.get("chunk_id"),
                    metadata={
                        **(r.get("metadata") or {}),
                        "source_id": r.get("source_id"),
                        "dataset_id": r.get("dataset_id"),
                        "snapshot_id": r.get("snapshot_id"),
                        "document_uid": r.get("document_uid"),
                        "relative_path": r.get("relative_path"),
                        "source_path": r.get("source_path"),
                    },
                )
            else:
                # 이미 있으면 점수 업데이트
                existing = doc_map[doc_id]
                existing.score = max(existing.score, faiss_score)
                existing.faiss_score = max(existing.faiss_score, faiss_score)

        # Graph 결과 추가
        for i, r in enumerate(graph_results):
            doc_id = r.get("document_id", "") or r.get("node_id", f"graph_{i}")

            graph_score = r.get("score", 1.0)
            if doc_id not in doc_map:
                doc_map[doc_id] = MergedDocument(
                    document_id=doc_id,
                    source=SearchSource.GRAPH,
                    rank=i + 1,
                    score=graph_score,
                    graph_score=graph_score,
                    title=r.get("label"),
                    category=r.get("category"),
                    organization=r.get("organization"),
                    file_name=r.get("file_name") or r.get("source_path"),
                    metadata={
                        **(r.get("metadata") or {}),
                        "node_type": r.get("node_type"),
                        "project_name": r.get("project_name"),
                        "source_path": r.get("source_path"),
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
                existing.graph_score = max(existing.graph_score, graph_score)
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

        query_lower = question.lower()
        prefers_proposal = "제안서" in query_lower or "proposal" in query_lower
        prefers_slide = any(token in query_lower for token in ("장표", "슬라이드", "slide", "ppt", "pptx"))
        prefers_security = any(token in query_lower for token in ("보안", "누출금지", "정보보호"))

        normalized_hints = self._normalize_soft_hints(soft_metadata_hints)

        # ranking_score 계산 (assemble_rag_response.py와 유사한 가중치 적용)
        for doc in merged:
            metadata = doc.metadata or {}
            base_score = doc.score * 5.0
            source_bonus = 1.0 if doc.source == SearchSource.FAISS else 1.5 if doc.source == SearchSource.GRAPH else 0.5
            relation_bonus = len(doc.graph_relations) * 0.3
            hybrid_bonus = 1.0 if (doc.faiss_score > 0 and doc.graph_score > 0) else 0.0
            intent_bonus = 0.0

            document_group = str(metadata.get("document_group") or "").strip().lower()
            document_category = str(metadata.get("document_category") or "").strip().lower()
            project_type = str(metadata.get("project_type") or doc.metadata.get("project_type") or "").strip().lower()
            organization = str(doc.organization or metadata.get("organization") or "").strip().lower()
            organization_type = str(metadata.get("organization_type") or metadata.get("client_type") or "").strip().lower()
            extension = str(metadata.get("extension") or "").strip().lower()
            title = str(doc.title or "").strip().lower()
            file_name = str(doc.file_name or "").strip().lower()
            text_preview = str(doc.text_preview or "").strip().lower()
            section_text = " ".join(
                str(value or "")
                for value in (
                    metadata.get("section_title"),
                    metadata.get("section_heading"),
                    metadata.get("section_label"),
                    metadata.get("document_category"),
                    metadata.get("section_type"),
                    " ".join(str(v or "") for v in (metadata.get("search_keywords") or [])),
                    doc.file_name,
                    metadata.get("file_name"),
                    metadata.get("project_name"),
                    doc.organization,
                    doc.title,
                    doc.text_preview,
                    metadata.get("project_type"),
                    metadata.get("organization_type"),
                )
            ).lower()

            if prefers_proposal and document_group == "제안서":
                intent_bonus += 2.5
            elif prefers_proposal and document_group == "rfp":
                intent_bonus -= 1.5

            if prefers_slide and extension in (".ppt", ".pptx"):
                intent_bonus += 2.0
            elif prefers_slide and extension in (".hwp", ".hwpx", ".doc", ".docx"):
                intent_bonus -= 0.8

            if prefers_security and any(token in section_text for token in ("보안", "누출금지", "정보보호")):
                intent_bonus += 1.2

            if normalized_hints.get("organization") and normalized_hints["organization"] in organization:
                intent_bonus += 1.0
            if normalized_hints.get("organization_type") and normalized_hints["organization_type"] in organization_type:
                intent_bonus += 1.8
            if normalized_hints.get("project_type") and normalized_hints["project_type"] in project_type:
                intent_bonus += 2.0
            if normalized_hints.get("document_group") and normalized_hints["document_group"] in document_group:
                intent_bonus += 0.8
            if normalized_hints.get("document_category") and normalized_hints["document_category"] in document_category:
                intent_bonus += 1.0
            if normalized_hints.get("section_type") and normalized_hints["section_type"] in section_text:
                intent_bonus += 0.8
            if normalized_hints.get("topic") and normalized_hints["topic"] in section_text:
                intent_bonus += 1.5

            inferred_terms = normalized_hints.get("inferred_terms") or []
            term_hits = sum(1 for term in inferred_terms if term and term in section_text)
            if term_hits:
                intent_bonus += min(term_hits * 0.25, 1.5)
            elif doc.source == SearchSource.GRAPH and len(inferred_terms) >= 2:
                has_structured_context = any(
                    str(metadata.get(key) or "").strip()
                    for key in ("section_title", "section_heading", "section_label")
                ) or bool(text_preview) or bool(metadata.get("search_keywords"))
                if not has_structured_context:
                    intent_bonus -= 5.0

            if (
                doc.source == SearchSource.GRAPH
                and len(inferred_terms) >= 2
                and not text_preview
                and not metadata.get("search_keywords")
                and not any(str(metadata.get(key) or "").strip() for key in ("section_title", "section_heading", "section_label"))
            ):
                intent_bonus -= 2.0

            # 문서 찾기 질문에서 파일/제목이 없는 Graph 결과가 상단을 오염시키지 않도록 감점한다.
            if not file_name and not title:
                intent_bonus -= 2.5 if doc.source == SearchSource.GRAPH else 1.0

            # 사례 분석 질문은 본문/섹션/파일명에 실제 토픽이 드러난 문서를 우선한다.
            if any(token in query_lower for token in ("선진사례", "유사사례", "사례분석", "벤치마크")):
                if any(token in section_text for token in ("선진사례", "유사사례", "사례분석", "벤치마크")):
                    intent_bonus += 1.8
                elif any(token in text_preview for token in ("선진사례", "유사사례", "사례분석", "벤치마크")):
                    intent_bonus += 1.2

            # 고객 유형 + 컨설팅 질문은 메타데이터와 파일명/본문에 해당 단서가 드러나면 추가 가중한다.
            if "연구기관" in query_lower and any(token in section_text for token in ("연구원", "연구소", "연구센터", "kitech")):
                intent_bonus += 1.3
            if "컨설팅" in query_lower and any(token in section_text for token in ("컨설팅", "isp", "ismp")):
                intent_bonus += 1.0

            doc.ranking_score = base_score + source_bonus + relation_bonus + hybrid_bonus + intent_bonus

        if self.merge_strategy == MergeStrategy.SCORE_BASED:
            merged.sort(key=lambda x: x.ranking_score, reverse=True)
        elif self.merge_strategy == MergeStrategy.FAISS_FIRST:
            merged.sort(key=lambda x: (x.source != SearchSource.FAISS, -x.ranking_score))
        elif self.merge_strategy == MergeStrategy.GRAPH_FIRST:
            merged.sort(key=lambda x: (x.source != SearchSource.GRAPH, -x.ranking_score))
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
        *,
        expanded_query: Optional[str] = None,
        category: Optional[str] = None,
        organization: Optional[str] = None,
        year: Optional[str] = None,
        document_group: Optional[str] = None,
        document_category: Optional[str] = None,
        section_type: Optional[str] = None,
        inferred_organization: Optional[str] = None,
        inferred_project_type: Optional[str] = None,
        inferred_document_group: Optional[str] = None,
        inferred_document_category: Optional[str] = None,
        inferred_terms: Optional[list[str]] = None,
        force_search_order: Optional[str] = None,
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
            # 1. Query Router로 질문 분석
            query_analysis: Optional[QueryAnalysis] = None
            query_analysis_time = 0
            search_order = "parallel"
            sources_to_use = []

            if self.query_router:
                analysis_start = time.time()
                query_analysis = self.query_router.analyze(question)
                query_analysis_time = int((time.time() - analysis_start) * 1000)
                search_order = query_analysis.search_order
                sources_to_use = [s.value for s in query_analysis.search_sources]
            if force_search_order:
                search_order = force_search_order

            # 1.5. LLM 기반 핵심 키워드 추출 (하이라이트용)
            extracted_keywords: list[str] = []
            try:
                extracted_keywords = await extract_keywords_with_llm(question)
            except Exception:
                # 실패 시 규칙 기반 폴백
                if query_analysis:
                    extracted_keywords = query_analysis.keywords[:5]
            extracted_keywords = self._sanitize_inferred_terms(extracted_keywords)
            question_hints = self._infer_question_hints(question)
            if not extracted_keywords:
                extracted_keywords = list(question_hints.get("inferred_terms") or [])

            # 2. 질문 유형별 검색 전략 결정
            faiss_results, faiss_time = [], 0
            graph_results, graph_cypher, graph_retry, graph_time, graph_question_type = [], [], 0, 0, ""
            wiki_results, wiki_time = [], 0
            query_lower = question.lower()
            prefers_document_recall = (
                (query_analysis and query_analysis.intent == QueryIntent.FIND_DOCUMENT)
                or any(token in query_lower for token in ("장표", "슬라이드", "slide", "ppt", "pptx", "제안서"))
            )

            # 사용자 직접 입력 또는 화면 선택값만 strict filter 로 사용한다.
            router_filters = query_analysis.filters if query_analysis else {}
            router_document_section = None
            if isinstance(router_filters.get("document_section"), str):
                router_document_section = router_filters.get("document_section")
            if isinstance(question_hints.get("document_category"), str):
                router_document_section = question_hints["document_category"]
            literal_section_hint = self._extract_literal_section_hint(question)
            if literal_section_hint:
                router_document_section = literal_section_hint
            explicit_document_group_in_question = bool(
                re.search(r"\bRFP\b|제안요청서|제안서|산출물", question, re.IGNORECASE)
            )

            strict_project_type = inferred_project_type or question_hints.get("project_type")
            router_project_type = router_filters.get("project_type") if isinstance(router_filters.get("project_type"), str) else None
            if not strict_project_type and router_project_type:
                normalized_project_type = self._normalize_project_type_value(router_project_type)
                if normalized_project_type in {"시스템개선", "플랫폼고도화", "isp수립", "bprisp", "연구용역", "시스템구축"}:
                    strict_project_type = router_project_type
                elif normalized_project_type == "컨설팅":
                    strict_project_type = router_project_type

            normalized_inferred_terms = self._sanitize_inferred_terms(
                inferred_terms if isinstance(inferred_terms, list) else extracted_keywords
            )
            metadata_filters = {
                "category": category,
                "organization": organization,
                "year": year,
                "organization_type": question_hints.get("organization_type"),
                "project_type": strict_project_type,
                "document_group": document_group or question_hints.get("document_group") or (
                    router_filters.get("document_group")
                    if explicit_document_group_in_question and isinstance(router_filters.get("document_group"), str)
                    else None
                ),
                "document_category": document_category or question_hints.get("document_category") or router_document_section,
                "section_type": section_type or question_hints.get("section_type") or router_document_section,
            }
            soft_metadata_hints = self._normalize_soft_hints({
                "organization": inferred_organization,
                "organization_type": question_hints.get("organization_type") or (router_filters.get("organization_type") if isinstance(router_filters.get("organization_type"), str) else None),
                "project_type": inferred_project_type or question_hints.get("project_type") or router_project_type,
                "document_group": inferred_document_group or question_hints.get("document_group") or router_filters.get("document_group"),
                "document_category": inferred_document_category or question_hints.get("document_category") or router_document_section,
                "section_type": document_category or section_type or inferred_document_category or question_hints.get("section_type") or router_document_section,
                "topic": question_hints.get("topic") or (router_filters.get("topic") if isinstance(router_filters.get("topic"), str) else None),
                "inferred_terms": normalized_inferred_terms,
            })
            faiss_query = self._normalize_search_query_text((expanded_query or "").strip() or question)
            faiss_org_filter = organization
            fallback_strategy: Optional[str] = None

            if search_order == "faiss_only":
                # 단순 키워드 검색: FAISS만
                faiss_results, faiss_time = await self._search_faiss(
                    faiss_query,
                    top_k,
                    category_filter=category,
                    organization_filter=faiss_org_filter,
                    metadata_filters=metadata_filters,
                )

            elif search_order == "graph_first":
                # Graph 우선: Graph → FAISS 순차
                if self.enable_graph:
                    graph_results, graph_cypher, graph_retry, graph_time, graph_question_type = await self._search_graph(
                        question,
                        metadata_filters=metadata_filters,
                    )

                graph_doc_ids = self._graph_candidate_document_ids(graph_results)

                # Graph 결과가 없거나 문서 리콜을 우선할 경우 FAISS에서 전체 검색
                # graph_doc_ids가 빈 집합이면 FAISS 전체 검색으로 fallback
                use_graph_filter = bool(graph_doc_ids) and not prefers_document_recall

                faiss_results, faiss_time = await self._search_faiss(
                    faiss_query,
                    max(top_k * 5, top_k) if graph_doc_ids else top_k,
                    category_filter=category,
                    organization_filter=faiss_org_filter,
                    allowed_document_ids=graph_doc_ids if use_graph_filter else None,
                    metadata_filters=metadata_filters,
                )

                # Wiki 검색 (필요시)
                if self.enable_wiki and RouterSearchSource.WIKI.value in sources_to_use:
                    wiki_results, wiki_time = await self._search_wiki(
                        question, top_k // 2, organization=organization
                    )

            elif search_order == "wiki_first":
                # Wiki 우선: 요약 요청
                if self.enable_wiki:
                    wiki_results, wiki_time = await self._search_wiki(
                        faiss_query, top_k, organization=organization
                    )
                faiss_results, faiss_time = await self._search_faiss(
                    faiss_query,
                    top_k // 2,
                    category_filter=category,
                    organization_filter=faiss_org_filter,
                    metadata_filters=metadata_filters,
                )

            else:
                # 기본: 병렬 검색
                tasks = [self._search_faiss(
                    faiss_query,
                    top_k,
                    category_filter=category,
                    organization_filter=faiss_org_filter,
                    metadata_filters=metadata_filters,
                )]

                if self.enable_graph:
                    tasks.append(self._search_graph(
                        question,
                        metadata_filters=metadata_filters,
                    ))

                if self.enable_wiki:
                    tasks.append(self._search_wiki(faiss_query, top_k // 2, organization=organization))

                results = await asyncio.gather(*tasks, return_exceptions=True)

                result_idx = 0

                if not isinstance(results[result_idx], Exception):
                    faiss_results, faiss_time = results[result_idx]
                result_idx += 1

                if self.enable_graph and result_idx < len(results):
                    if not isinstance(results[result_idx], Exception):
                        graph_results, graph_cypher, graph_retry, graph_time, graph_question_type = results[result_idx]
                    result_idx += 1

                if self.enable_wiki and result_idx < len(results):
                    if not isinstance(results[result_idx], Exception):
                        wiki_results, wiki_time = results[result_idx]

            # 3. 결과 병합
            merge_start = time.time()
            merged_docs = self._merge_results(
                faiss_results,
                graph_results,
                wiki_results,
                question=question,
                max_results=max_results,
                soft_metadata_hints=soft_metadata_hints,
            )

            # project_type strict filter가 너무 강해 0건이 되는 경우, 문서그룹/섹션 필터는 유지하고 재검색한다.
            if not merged_docs and metadata_filters.get("project_type"):
                relaxed_filters = self._relax_project_type_filter(metadata_filters)
                retry_faiss_results, retry_faiss_time = await self._search_faiss(
                    faiss_query,
                    max(top_k * 10, top_k),
                    category_filter=category,
                    organization_filter=faiss_org_filter,
                    metadata_filters=relaxed_filters,
                )
                retry_graph_results = graph_results
                retry_graph_cypher = graph_cypher
                retry_graph_retry = graph_retry
                retry_graph_time = graph_time
                retry_graph_question_type = graph_question_type

                if self.enable_graph and search_order in {"graph_first", "parallel"}:
                    (
                        retry_graph_results,
                        retry_graph_cypher,
                        retry_graph_retry,
                        retry_graph_time,
                        retry_graph_question_type,
                    ) = await self._search_graph(
                        question,
                        metadata_filters=relaxed_filters,
                    )

                retry_merged_docs = self._merge_results(
                    retry_faiss_results,
                    retry_graph_results,
                    wiki_results,
                    question=question,
                    max_results=max_results,
                    soft_metadata_hints=soft_metadata_hints,
                )
                if retry_merged_docs:
                    metadata_filters = relaxed_filters
                    faiss_results = retry_faiss_results
                    faiss_time = retry_faiss_time
                    graph_results = retry_graph_results
                    graph_cypher = retry_graph_cypher
                    graph_retry = retry_graph_retry
                    graph_time = retry_graph_time
                    graph_question_type = retry_graph_question_type
                    merged_docs = retry_merged_docs

            # strict metadata filter로 0건이 되면 source 범위는 유지한 채
            # FAISS 무필터 검색으로 한 번 더 폴백한다.
            if not merged_docs and any(value for value in (metadata_filters or {}).values()):
                fallback_faiss_results, fallback_faiss_time = await self._search_faiss(
                    faiss_query,
                    max(top_k * 10, top_k),
                    category_filter=category,
                    organization_filter=faiss_org_filter,
                    metadata_filters=None,
                )
                fallback_merged_docs = self._merge_results(
                    fallback_faiss_results,
                    graph_results,
                    wiki_results,
                    question=question,
                    max_results=max_results,
                    soft_metadata_hints=soft_metadata_hints,
                )
                if fallback_merged_docs:
                    faiss_results = fallback_faiss_results
                    faiss_time = max(faiss_time, fallback_faiss_time)
                    merged_docs = fallback_merged_docs

            if not merged_docs:
                (
                    classic_faiss_results,
                    classic_merged_docs,
                    classic_snapshot,
                ) = self._classic_rag_fallback(
                    question=question,
                    faiss_query=faiss_query,
                    top_k=top_k,
                    max_results=max_results,
                    category=category,
                    organization=organization,
                    year=year,
                    document_group=document_group,
                    document_category=document_category,
                    section_type=section_type,
                )
                if classic_merged_docs:
                    faiss_results = classic_faiss_results
                    merged_docs = classic_merged_docs
                    fallback_strategy = f"classic_rag_query:{classic_snapshot or 'unknown'}"
                    if "classic_rag" not in sources_to_use:
                        sources_to_use.append("classic_rag")

            merge_time = int((time.time() - merge_start) * 1000)

            # 4. 근거 생성
            evidence = self._build_evidence(merged_docs, graph_cypher)
            if fallback_strategy:
                evidence.append({
                    "type": "fallback_strategy",
                    "strategy": fallback_strategy,
                    "reason": "hybrid_empty_result_guard",
                })

            # 5. 답변 생성 (옵션)
            answer = None
            if generate_answer and merged_docs:
                # TODO: LLM 답변 생성 구현
                answer = None

            total_time = int((time.time() - total_start) * 1000)

            return HybridRAGResponse(
                success=True,
                question=question,
                answer=answer,
                query_analysis=query_analysis.to_dict() if query_analysis else None,
                faiss_results=faiss_results,
                graph_results=graph_results,
                wiki_results=wiki_results,
                merged_documents=[
                    {
                        "organization_type": d.metadata.get("organization_type"),
                        "client_type": d.metadata.get("client_type"),
                        "project_type": d.metadata.get("project_type"),
                        "section_type": d.metadata.get("section_type"),
                        "search_keywords": d.metadata.get("search_keywords") or [],
                        "document_id": d.document_id,
                        "source": d.source.value,
                        "rank": d.rank,
                        "score": d.score,
                        "ranking_score": d.ranking_score,
                        "faiss_score": d.faiss_score,
                        "graph_score": d.graph_score,
                        "title": d.title,
                        "category": d.category,
                        "organization": d.organization,
                        "file_name": d.file_name,
                        "text_preview": d.text_preview,
                        "chunk_id": d.chunk_id,
                        "source_id": d.metadata.get("source_id"),
                        "dataset_id": d.metadata.get("dataset_id"),
                        "snapshot_id": d.metadata.get("snapshot_id"),
                        "document_uid": d.metadata.get("document_uid"),
                        "relative_path": d.metadata.get("relative_path"),
                        "source_path": d.metadata.get("source_path"),
                        "page_no": d.metadata.get("page_no"),
                        "slide_no": d.metadata.get("slide_no"),
                        "section_title": d.metadata.get("section_title") or d.metadata.get("section_heading"),
                        "section_id": d.metadata.get("section_id"),
                        "document_group": d.metadata.get("document_group"),
                        "document_category": d.metadata.get("document_category"),
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
                query_analysis_time_ms=query_analysis_time,
                faiss_time_ms=faiss_time,
                graph_time_ms=graph_time,
                wiki_time_ms=wiki_time,
                merge_time_ms=merge_time,
                total_time_ms=total_time,
                search_order=search_order,
                sources_used=sources_to_use,
                extracted_keywords=extracted_keywords,
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
