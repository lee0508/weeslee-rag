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

NODE_TYPE_ALIASES = {
    "organization": "organization",
    "organizationtype": "organization_type",
    "project": "project",
    "projecttype": "project_type",
    "document": "document",
    "documentsection": "document_section",
    "documentkeyword": "document_keyword",
    "keyword": "keyword",
    "category": "category",
    "technology": "technology",
    "methodology": "methodology",
    "domain": "domain",
    "person": "person",
}

RELATION_TYPE_ALIASES = {
    "ORDERED": {"발주"},
    "HAS_DOCUMENT": {"has_document"},
    "HAS_SECTION": {"문서섹션"},
    "HAS_DOC_KEYWORD": {"관련키워드", "MENTIONS"},
    "BELONGS_TO_TYPE": {"소속유형", "발주기관유형"},
    "HAS_PROJECT_TYPE": {"사업유형"},
    "USES_TECH": {"적용기술"},
    "USES_METHODOLOGY": {"사용방법론"},
    "RELATED_DOMAIN": {"관련도메인"},
    "SIMILAR_PROJECT": {"similar_project"},
}

CATEGORY_VALUE_ALIASES = {
    "rfp": {"rfp", "cat_rfp"},
    "proposal": {"proposal", "cat_proposal"},
    "deliverable": {"deliverable", "cat_deliverable"},
}


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
        alias_specs = self._parse_node_specs(cypher)
        if not alias_specs:
            return []

        relations = self._parse_relation_specs(cypher)
        candidate_map = {
            alias: [node for node in self._nodes if self._match_node_spec(node, spec)]
            for alias, spec in alias_specs.items()
        }

        if relations:
            candidate_map = self._apply_relation_constraints(candidate_map, relations)

        return_alias = self._extract_return_alias(cypher) or next(iter(alias_specs.keys()))
        results = candidate_map.get(return_alias, [])

        limit_match = re.search(r"LIMIT\s+(\d+)", cypher, re.IGNORECASE)
        limit = int(limit_match.group(1)) if limit_match else 20
        return results[:limit]

    @staticmethod
    def _normalize_node_type(node_type: str) -> str:
        return NODE_TYPE_ALIASES.get((node_type or "").replace("_", "").lower(), (node_type or "").lower())

    @staticmethod
    def _normalize_relation_aliases(relation: str) -> set[str]:
        if not relation:
            return set()
        return RELATION_TYPE_ALIASES.get(relation.upper(), {relation})

    @staticmethod
    def _normalize_category_value(value: str) -> set[str]:
        normalized = (value or "").strip().lower()
        return CATEGORY_VALUE_ALIASES.get(normalized, {normalized})

    def _parse_properties(self, raw_props: str) -> dict[str, str]:
        props: dict[str, str] = {}
        if not raw_props:
            return props
        for key, quoted, numeric in re.findall(r"(\w+)\s*:\s*(?:['\"]([^'\"]+)['\"]|(\d+))", raw_props):
            props[key] = quoted or numeric
        return props

    def _parse_node_specs(self, cypher: str) -> dict[str, dict[str, Any]]:
        specs: dict[str, dict[str, Any]] = {}
        node_pattern = re.compile(
            r"\((?P<alias>\w+)(?::(?P<type>\w+))?(?:\s*\{(?P<props>[^}]*)\})?\)"
        )
        for match in node_pattern.finditer(cypher):
            alias = match.group("alias")
            specs.setdefault(alias, {"type": "", "props": {}})
            if match.group("type"):
                specs[alias]["type"] = self._normalize_node_type(match.group("type"))
            specs[alias]["props"].update(self._parse_properties(match.group("props") or ""))

        for alias, prop, value in re.findall(r"\b(\w+)\.(\w+)\s*=\s*['\"]([^'\"]+)['\"]", cypher):
            specs.setdefault(alias, {"type": "", "props": {}})
            specs[alias]["props"][prop] = value

        return specs

    def _parse_relation_specs(self, cypher: str) -> list[dict[str, Any]]:
        relations: list[dict[str, Any]] = []

        outgoing = re.compile(
            r"\((\w+)(?::\w+)?(?:\s*\{[^}]*\})?\)\s*-\s*\[:\s*([A-Z_가-힣]+)\s*\]\s*->\s*\((\w+)(?::\w+)?(?:\s*\{[^}]*\})?\)"
        )
        incoming = re.compile(
            r"\((\w+)(?::\w+)?(?:\s*\{[^}]*\})?\)\s*<-\s*\[:\s*([A-Z_가-힣]+)\s*\]\s*-\s*\((\w+)(?::\w+)?(?:\s*\{[^}]*\})?\)"
        )

        for source, relation, target in outgoing.findall(cypher):
            relations.append({"source": source, "target": target, "relations": self._normalize_relation_aliases(relation)})
        for target, relation, source in incoming.findall(cypher):
            relations.append({"source": source, "target": target, "relations": self._normalize_relation_aliases(relation)})

        return relations

    def _match_node_spec(self, node: dict, spec: dict[str, Any]) -> bool:
        expected_type = spec.get("type") or ""
        if expected_type and node.get("type", "").lower() != expected_type:
            return False

        props = spec.get("props") or {}
        for key, expected in props.items():
            expected_text = str(expected or "").strip()
            if not expected_text:
                continue

            if key == "category":
                actual = str(node.get("category", "")).strip().lower()
                if actual not in self._normalize_category_value(expected_text):
                    return False
                continue

            if key == "year":
                if str(node.get("year", "")).strip() != expected_text:
                    return False
                continue

            haystacks = [
                str(node.get(key, "")).strip(),
                str(node.get("label", "")).strip(),
                str(node.get("name", "")).strip(),
                str(node.get("project_name", "")).strip(),
                str(node.get("file_name", "")).strip(),
                str(node.get("organization", "")).strip(),
            ]
            expected_lower = expected_text.lower()
            if not any(expected_lower in value.lower() for value in haystacks if value):
                return False

        return True

    def _apply_relation_constraints(
        self,
        candidate_map: dict[str, list[dict]],
        relations: list[dict[str, Any]],
    ) -> dict[str, list[dict]]:
        node_by_id = {node.get("id"): node for node in self._nodes if node.get("id")}
        candidate_ids = {
            alias: {node.get("id") for node in nodes if node.get("id")}
            for alias, nodes in candidate_map.items()
        }

        changed = True
        while changed:
            changed = False
            for rel in relations:
                source_alias = rel["source"]
                target_alias = rel["target"]
                allowed_relations = {name.lower() for name in rel["relations"]}
                source_ids = candidate_ids.get(source_alias, set())
                target_ids = candidate_ids.get(target_alias, set())
                if not source_ids or not target_ids:
                    candidate_ids[source_alias] = set()
                    candidate_ids[target_alias] = set()
                    continue

                matched_sources: set[str] = set()
                matched_targets: set[str] = set()
                for edge in self._edges:
                    relation_name = str(edge.get("relation", "")).lower()
                    if relation_name not in allowed_relations:
                        continue
                    source_id = edge.get("source")
                    target_id = edge.get("target")
                    if source_id in source_ids and target_id in target_ids:
                        matched_sources.add(source_id)
                        matched_targets.add(target_id)

                if matched_sources != source_ids:
                    candidate_ids[source_alias] = matched_sources
                    changed = True
                if matched_targets != target_ids:
                    candidate_ids[target_alias] = matched_targets
                    changed = True

        filtered: dict[str, list[dict]] = {}
        for alias, ids in candidate_ids.items():
            filtered[alias] = [node_by_id[node_id] for node_id in ids if node_id in node_by_id]
        return filtered

    @staticmethod
    def _extract_return_alias(cypher: str) -> Optional[str]:
        match = re.search(r"RETURN\s+(\w+)\b", cypher, re.IGNORECASE)
        return match.group(1) if match else None

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
