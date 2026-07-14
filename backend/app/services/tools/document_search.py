# 문서 검색 도구
"""
RAG 문서 검색, GraphRAG 관계 조회 도구.
"""
from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path
from typing import Any, Optional

from app.services.tool_registry import register_tool

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _rag_runtime():
    return importlib.import_module("app.services.rag_runtime")


@register_tool(
    name="search_documents",
    description="RAG 기반 문서 검색을 수행합니다. 쿼리와 유사한 문서 청크를 반환합니다.",
    parameters={
        "query": {
            "type": "string",
            "description": "검색 쿼리 (자연어)",
        },
        "category": {
            "type": "string",
            "enum": ["all", "rfp", "proposal", "deliverable", "policy"],
            "description": "검색 카테고리: all(전체), rfp(제안요청서), proposal(제안서), deliverable(산출물), policy(정책자료)",
        },
        "top_k": {
            "type": "integer",
            "description": "반환할 최대 문서 수 (기본: 10)",
        },
    },
    required=["query"],
)
def search_documents(
    query: str,
    category: str = "all",
    top_k: int = 10,
) -> dict[str, Any]:
    """RAG 문서 검색을 수행합니다."""
    try:
        runtime = _rag_runtime()
        snapshot = runtime.get_active_snapshot()

        cat_filter = None if category == "all" else category
        index_path, meta_path = runtime.default_index_paths(snapshot, cat_filter)

        if not index_path.exists():
            return {
                "error": f"인덱스 없음: {snapshot}",
                "query": query,
                "results": [],
            }

        # FAISS 검색 수행
        results = runtime.search_similar(
            query=query,
            snapshot=snapshot,
            category=cat_filter,
            top_k=top_k,
        )

        return {
            "query": query,
            "category": category,
            "total_results": len(results),
            "results": results[:top_k],
        }

    except Exception as e:
        logger.exception(f"[search_documents] 실패: {query}")
        return {"error": str(e), "query": query, "results": []}


@register_tool(
    name="query_graph_relations",
    description="GraphRAG를 사용하여 엔티티 간 관계를 조회합니다. 프로젝트, 기관, 기술 등의 연결 관계를 탐색합니다.",
    parameters={
        "entity": {
            "type": "string",
            "description": "조회할 엔티티 (예: 프로젝트명, 기관명, 기술명)",
        },
        "relation_type": {
            "type": "string",
            "enum": ["all", "project", "organization", "technology", "person"],
            "description": "관계 유형 필터",
        },
        "depth": {
            "type": "integer",
            "description": "탐색 깊이 (기본: 2)",
        },
    },
    required=["entity"],
)
def query_graph_relations(
    entity: str,
    relation_type: str = "all",
    depth: int = 2,
) -> dict[str, Any]:
    """GraphRAG 관계를 조회합니다."""
    try:
        # GraphRAG 서비스 호출
        graph_service = importlib.import_module("app.services.graph_service")

        relations = graph_service.query_entity_relations(
            entity=entity,
            relation_filter=None if relation_type == "all" else relation_type,
            max_depth=depth,
        )

        return {
            "entity": entity,
            "relation_type": relation_type,
            "depth": depth,
            "relations": relations,
        }

    except ImportError:
        # GraphRAG 서비스가 없는 경우 기본 응답
        return {
            "entity": entity,
            "relation_type": relation_type,
            "depth": depth,
            "relations": [],
            "note": "GraphRAG 서비스가 활성화되지 않았습니다.",
        }
    except Exception as e:
        logger.exception(f"[query_graph_relations] 실패: {entity}")
        return {"error": str(e), "entity": entity, "relations": []}


@register_tool(
    name="get_document_details",
    description="특정 문서의 상세 정보를 조회합니다. 메타데이터, 요약, 관련 문서 등을 반환합니다.",
    parameters={
        "document_id": {
            "type": "string",
            "description": "문서 ID",
        },
        "include_chunks": {
            "type": "boolean",
            "description": "청크 목록 포함 여부 (기본: false)",
        },
    },
    required=["document_id"],
)
def get_document_details(
    document_id: str,
    include_chunks: bool = False,
) -> dict[str, Any]:
    """문서 상세 정보를 조회합니다."""
    try:
        runtime = _rag_runtime()
        snapshot = runtime.get_active_snapshot()

        # 메타데이터 조회
        meta_path = PROJECT_ROOT / "data" / "indexes" / "faiss" / f"{snapshot}_ollama_metadata.jsonl"

        document = None
        chunks = []

        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    meta = json.loads(line)
                    if meta.get("document_id") == document_id:
                        document = meta
                        if include_chunks:
                            chunks.append(meta)

        if not document:
            return {"error": f"문서를 찾을 수 없음: {document_id}", "document_id": document_id}

        result = {
            "document_id": document_id,
            "metadata": document,
            "summary": document.get("summary", ""),
        }

        if include_chunks:
            result["chunks"] = chunks
            result["chunk_count"] = len(chunks)

        return result

    except Exception as e:
        logger.exception(f"[get_document_details] 실패: {document_id}")
        return {"error": str(e), "document_id": document_id}
