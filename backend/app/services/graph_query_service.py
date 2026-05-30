# Graph 쿼리 실행 및 결과 평가 서비스
# -*- coding: utf-8 -*-
"""
Graph Query Service - 그래프 데이터 쿼리 및 결과 평가.

Phase 6에서 GraphRAG Agent가 사용하는 쿼리 실행 및 평가 서비스.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
GRAPH_DIR = DATA_DIR / "indexes" / "graph"


class QueryResultQuality(Enum):
    """쿼리 결과 품질."""
    EXCELLENT = "excellent"  # 10개 이상의 관련 결과
    GOOD = "good"            # 5-9개의 관련 결과
    ACCEPTABLE = "acceptable"  # 1-4개의 관련 결과
    EMPTY = "empty"          # 결과 없음
    ERROR = "error"          # 실행 오류


@dataclass
class QueryEvaluation:
    """쿼리 결과 평가."""
    quality: QueryResultQuality
    result_count: int
    relevant_count: int
    message: str
    suggestions: list[str] = field(default_factory=list)
    should_retry: bool = False


@dataclass
class GraphQueryResult:
    """그래프 쿼리 결과."""
    success: bool
    cypher: str
    results: list[dict] = field(default_factory=list)
    evaluation: Optional[QueryEvaluation] = None
    error: Optional[str] = None
    execution_time_ms: int = 0


class GraphQueryService:
    """Graph 쿼리 서비스."""

    def __init__(self, source_id: Optional[str] = None):
        self.source_id = source_id
        self._nodes: list[dict] = []
        self._edges: list[dict] = []
        self._loaded = False

    def _get_graph_dir(self) -> Path:
        """source_id별 Graph 디렉토리 반환."""
        if self.source_id:
            return DATA_DIR / "indexes" / "graph" / self.source_id
        return GRAPH_DIR

    def _load_graph(self) -> None:
        """그래프 데이터 로드."""
        if self._loaded:
            return

        graph_dir = self._get_graph_dir()
        nodes_path = graph_dir / "graph_nodes.jsonl"
        edges_path = graph_dir / "graph_edges.jsonl"

        if nodes_path.exists():
            self._nodes = [
                json.loads(line)
                for line in nodes_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        if edges_path.exists():
            self._edges = [
                json.loads(line)
                for line in edges_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self._loaded = True

    def execute_query(self, cypher: str) -> GraphQueryResult:
        """
        Cypher 쿼리 실행 (JSONL 기반 시뮬레이션).

        Args:
            cypher: 실행할 Cypher 쿼리

        Returns:
            GraphQueryResult: 실행 결과
        """
        import time
        start_time = time.time()

        try:
            self._load_graph()
            results = self._simulate_cypher(cypher)
            execution_time_ms = int((time.time() - start_time) * 1000)

            # 결과 평가
            evaluation = self._evaluate_results(results, cypher)

            return GraphQueryResult(
                success=True,
                cypher=cypher,
                results=results,
                evaluation=evaluation,
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            return GraphQueryResult(
                success=False,
                cypher=cypher,
                error=str(e),
                evaluation=QueryEvaluation(
                    quality=QueryResultQuality.ERROR,
                    result_count=0,
                    relevant_count=0,
                    message=f"쿼리 실행 오류: {str(e)}",
                    should_retry=True,
                ),
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    def _simulate_cypher(self, cypher: str) -> list[dict]:
        """
        JSONL 데이터에서 Cypher 쿼리 시뮬레이션.

        간단한 패턴 매칭으로 구현.
        """
        results = []
        cypher_upper = cypher.upper()

        # 노드 타입 추출
        node_type_match = re.search(
            r":\s*(Organization|Project|Document|Keyword|Category|Technology|Person)",
            cypher, re.IGNORECASE
        )

        # 속성 필터 추출
        name_filter = self._extract_property(cypher, "name")
        year_filter = self._extract_property(cypher, "year")
        category_filter = self._extract_property(cypher, "category")
        organization_filter = self._extract_property(cypher, "organization")

        # 노드 검색
        for node in self._nodes:
            node_type = node.get("type", "").lower()

            # 타입 필터
            if node_type_match:
                expected_type = node_type_match.group(1).lower()
                if node_type != expected_type:
                    continue

            # 속성 필터
            if name_filter:
                label = node.get("label", "").lower()
                name = node.get("name", "").lower()
                if name_filter.lower() not in label and name_filter.lower() not in name:
                    continue

            if year_filter:
                if str(node.get("year", "")) != year_filter:
                    continue

            if category_filter:
                if node.get("category", "").lower() != category_filter.lower():
                    continue

            if organization_filter:
                org = node.get("organization", "").lower()
                if organization_filter.lower() not in org:
                    continue

            results.append(node)

        # 관계 탐색 (MATCH 패턴에 관계가 있는 경우)
        if "-[:" in cypher_upper or "]->" in cypher_upper or "<-[" in cypher_upper:
            results = self._traverse_relations(results, cypher)

        # LIMIT 처리
        limit_match = re.search(r"LIMIT\s+(\d+)", cypher, re.IGNORECASE)
        if limit_match:
            limit = int(limit_match.group(1))
            results = results[:limit]
        else:
            results = results[:20]  # 기본 20개 제한

        return results

    def _extract_property(self, cypher: str, prop_name: str) -> Optional[str]:
        """Cypher에서 속성 값 추출."""
        # {name: '값'} 또는 {name: "값"} 패턴
        pattern = rf"{prop_name}\s*:\s*['\"](.+?)['\"]"
        match = re.search(pattern, cypher, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def _traverse_relations(self, start_nodes: list[dict], cypher: str) -> list[dict]:
        """관계를 따라 노드 탐색."""
        if not start_nodes:
            return []

        # 관계 타입 추출
        rel_match = re.search(r"\[:\s*(\w+)\s*\]", cypher, re.IGNORECASE)
        rel_type = rel_match.group(1).upper() if rel_match else None

        start_ids = {n.get("id") for n in start_nodes}
        related_nodes = []
        seen_ids = set()

        for edge in self._edges:
            # 시작 노드에서 나가는 엣지
            if edge.get("source") in start_ids:
                if rel_type and edge.get("relation", "").upper() != rel_type:
                    continue
                target_id = edge.get("target")
                if target_id not in seen_ids:
                    seen_ids.add(target_id)
                    target_node = next(
                        (n for n in self._nodes if n.get("id") == target_id),
                        None
                    )
                    if target_node:
                        related_nodes.append(target_node)

            # 시작 노드로 들어오는 엣지
            elif edge.get("target") in start_ids:
                if rel_type and edge.get("relation", "").upper() != rel_type:
                    continue
                source_id = edge.get("source")
                if source_id not in seen_ids:
                    seen_ids.add(source_id)
                    source_node = next(
                        (n for n in self._nodes if n.get("id") == source_id),
                        None
                    )
                    if source_node:
                        related_nodes.append(source_node)

        return related_nodes if related_nodes else start_nodes

    def _evaluate_results(self, results: list[dict], cypher: str) -> QueryEvaluation:
        """쿼리 결과 품질 평가."""
        result_count = len(results)

        if result_count == 0:
            return QueryEvaluation(
                quality=QueryResultQuality.EMPTY,
                result_count=0,
                relevant_count=0,
                message="검색 결과가 없습니다.",
                suggestions=self._generate_suggestions(cypher, results),
                should_retry=True,
            )

        if result_count >= 10:
            quality = QueryResultQuality.EXCELLENT
            message = f"우수한 검색 결과: {result_count}건"
        elif result_count >= 5:
            quality = QueryResultQuality.GOOD
            message = f"좋은 검색 결과: {result_count}건"
        else:
            quality = QueryResultQuality.ACCEPTABLE
            message = f"검색 결과: {result_count}건"

        return QueryEvaluation(
            quality=quality,
            result_count=result_count,
            relevant_count=result_count,  # 단순화: 모든 결과를 관련 결과로 간주
            message=message,
            should_retry=False,
        )

    def _generate_suggestions(self, cypher: str, results: list[dict]) -> list[str]:
        """결과가 없을 때 쿼리 수정 제안 생성."""
        suggestions = []

        # 속성 필터가 너무 구체적인 경우
        if "name:" in cypher.lower():
            suggestions.append("검색어를 더 일반적인 용어로 변경해 보세요.")

        # 노드 타입 제안
        if ":Organization" in cypher:
            suggestions.append("기관명의 약어나 정식 명칭을 확인해 보세요.")
        elif ":Project" in cypher:
            suggestions.append("프로젝트명 일부만 사용하거나 연도로 검색해 보세요.")
        elif ":Document" in cypher:
            suggestions.append("문서 카테고리(rfp, proposal, deliverable)로 검색해 보세요.")

        # 관계 기반 검색 제안
        if "-[:" not in cypher:
            suggestions.append("관계를 통한 검색을 시도해 보세요.")

        return suggestions

    def get_node_by_id(self, node_id: str) -> Optional[dict]:
        """노드 ID로 노드 조회."""
        self._load_graph()
        return next((n for n in self._nodes if n.get("id") == node_id), None)

    def get_related_nodes(self, node_id: str, relation_type: Optional[str] = None) -> list[dict]:
        """노드와 연결된 다른 노드 조회."""
        self._load_graph()
        related = []

        for edge in self._edges:
            if relation_type and edge.get("relation") != relation_type:
                continue

            other_id = None
            if edge.get("source") == node_id:
                other_id = edge.get("target")
            elif edge.get("target") == node_id:
                other_id = edge.get("source")

            if other_id:
                node = self.get_node_by_id(other_id)
                if node:
                    related.append(node)

        return related

    def search_nodes(
        self,
        node_type: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """노드 검색."""
        self._load_graph()
        results = []

        for node in self._nodes:
            if node_type and node.get("type") != node_type:
                continue

            if keyword:
                label = node.get("label", "").lower()
                name = node.get("name", "").lower()
                if keyword.lower() not in label and keyword.lower() not in name:
                    continue

            results.append(node)

            if len(results) >= limit:
                break

        return results


# 싱글톤 인스턴스 캐시
_services: dict[str, GraphQueryService] = {}


def get_graph_query_service(source_id: Optional[str] = None) -> GraphQueryService:
    """GraphQueryService 싱글톤 반환."""
    key = source_id or "_default_"
    if key not in _services:
        _services[key] = GraphQueryService(source_id)
    return _services[key]
