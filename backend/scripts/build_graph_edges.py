# LPG 스키마 기반 그래프 엣지 생성 스크립트
# -*- coding: utf-8 -*-
"""
LPG 스키마(data/ontology/schema.json) 기반 그래프 엣지 생성.

입력:
  - data/ontology/schema.json (스키마 정의)
  - data/ontology/graph_nodes.jsonl (노드 목록)
  - data/ontology/terms.jsonl (용어 사전 - 계층 관계용)

출력:
  - data/ontology/graph_edges.jsonl (LPG 엣지)

엣지 타입:
  HAS_SOURCE, HAS_CATEGORY, HAS_DOCUMENT, BELONGS_TO, ISSUED_BY,
  IN_DOMAIN, USES_TECH, USES_METHOD, HAS_CHUNK, SIMILAR_TO,
  RELATED_SEQUENCE, PARENT_TECH, SYNONYM_OF, DESCRIBED_IN, IN_COLLECTION
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
ONTOLOGY_DIR = DATA_DIR / "ontology"
SCHEMA_PATH = ONTOLOGY_DIR / "schema.json"
NODES_PATH = ONTOLOGY_DIR / "graph_nodes.jsonl"
TERMS_PATH = ONTOLOGY_DIR / "terms.jsonl"
LEGACY_GRAPH_DIR = DATA_DIR / "indexes" / "graph"

BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 선택적 import
try:
    from app.services.knowledge_graph import (
        normalize_organization,
        extract_technologies,
        extract_methodologies,
        extract_domains,
    )
    HAS_KG_SERVICE = True
except ImportError:
    HAS_KG_SERVICE = False
    def normalize_organization(name: str) -> str:
        return name
    def extract_technologies(text: str) -> list[str]:
        return []
    def extract_methodologies(text: str) -> list[str]:
        return []
    def extract_domains(text: str) -> list[str]:
        return []


class LPGEdgeBuilder:
    """LPG 스키마 기반 엣지 빌더."""

    def __init__(
        self,
        schema_path: Path = SCHEMA_PATH,
        nodes_path: Path = NODES_PATH,
        terms_path: Path = TERMS_PATH,
    ):
        self.schema = self._load_schema(schema_path)
        self.nodes = self._load_nodes(nodes_path)
        self.terms = self._load_terms(terms_path)
        self.edges: dict[str, dict] = {}
        self.edge_types = self.schema.get("edge_types", {})
        self.relation_labels = self.schema.get("relation_labels", {})
        self.legacy_mapping = self.schema.get("legacy_mapping", {})
        self._edge_counter = 0

    def _load_schema(self, path: Path) -> dict:
        """스키마 로드."""
        if not path.exists():
            print(f"[WARN] Schema not found: {path}")
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_nodes(self, path: Path) -> dict[str, dict]:
        """노드 로드 (node_id -> node)."""
        nodes = {}
        if not path.exists():
            print(f"[WARN] Nodes not found: {path}")
            return nodes
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    node = json.loads(line)
                    nodes[node["node_id"]] = node
        return nodes

    def _load_terms(self, path: Path) -> dict[str, dict]:
        """용어 사전 로드."""
        terms = {}
        if not path.exists():
            return terms
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    term = json.loads(line)
                    terms[term["term_id"]] = term
        return terms

    def _generate_edge_id(self, source: str, target: str, edge_type: str) -> str:
        """엣지 ID 생성."""
        # 중복 방지용 해시 기반 ID
        return f"{source}->{target}:{edge_type}"

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: str,
        **properties
    ) -> bool:
        """엣지 추가. 이미 존재하면 False 반환."""
        edge_id = self._generate_edge_id(source_id, target_id, edge_type)
        if edge_id in self.edges:
            return False

        # 소스/타겟 노드 존재 확인
        if source_id not in self.nodes:
            return False
        if target_id not in self.nodes:
            return False

        self._edge_counter += 1
        label = self.relation_labels.get(edge_type, edge_type)

        edge = {
            "edge_id": edge_id,
            "edge_type": edge_type,
            "source_node": source_id,
            "target_node": target_id,
            "label": properties.pop("label", label),
            "properties": properties,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.edges[edge_id] = edge
        return True

    def get_nodes_by_type(self, node_type: str) -> list[dict]:
        """특정 타입의 노드 목록 반환."""
        return [n for n in self.nodes.values() if n.get("node_type") == node_type]

    # ── 엣지 생성 메서드 ──────────────────────────────────────────────────────

    def build_document_category_edges(self) -> int:
        """문서 → 카테고리 엣지 (HAS_CATEGORY)."""
        count = 0
        for node in self.get_nodes_by_type("Document"):
            props = node.get("properties", {})
            category = props.get("category", "")
            if not category:
                continue

            cat_id = f"cat:{category}"
            if self.add_edge(node["node_id"], cat_id, "HAS_CATEGORY"):
                count += 1
        return count

    def build_project_document_edges(self) -> int:
        """프로젝트 → 문서 엣지 (HAS_DOCUMENT) / 문서 → 프로젝트 (BELONGS_TO)."""
        count = 0
        for node in self.get_nodes_by_type("Document"):
            props = node.get("properties", {})
            project_id = props.get("project_id", "")
            if not project_id or project_id not in self.nodes:
                continue

            # 양방향 엣지
            if self.add_edge(project_id, node["node_id"], "HAS_DOCUMENT"):
                count += 1
            if self.add_edge(node["node_id"], project_id, "BELONGS_TO"):
                count += 1
        return count

    def build_project_organization_edges(self) -> int:
        """프로젝트 → 기관 엣지 (ISSUED_BY)."""
        count = 0
        for node in self.get_nodes_by_type("Project"):
            props = node.get("properties", {})
            org_id = props.get("organization_id", "")
            org_name = props.get("organization", "")

            # organization_id가 없으면 이름으로 찾기
            if not org_id and org_name:
                canonical = normalize_organization(org_name)
                org_id = f"org:{canonical}"

            if not org_id or org_id not in self.nodes:
                continue

            if self.add_edge(org_id, node["node_id"], "ISSUED_BY"):
                count += 1
        return count

    def build_technology_hierarchy_edges(self) -> int:
        """기술 계층 엣지 (PARENT_TECH)."""
        count = 0
        for term_id, term in self.terms.items():
            if term.get("term_type") != "technology":
                continue
            parent_id = term.get("parent_id")
            if not parent_id:
                continue
            if term_id not in self.nodes or parent_id not in self.nodes:
                continue

            if self.add_edge(parent_id, term_id, "PARENT_TECH", relation_type="하위기술"):
                count += 1
        return count

    def build_project_entity_edges(self) -> int:
        """프로젝트 → 기술/방법론/도메인 엣지."""
        count = 0

        # 노드 ID 인덱스 (빠른 검색용)
        tech_nodes = {n["node_id"]: n for n in self.get_nodes_by_type("Technology")}
        method_nodes = {n["node_id"]: n for n in self.get_nodes_by_type("Methodology")}
        domain_nodes = {n["node_id"]: n for n in self.get_nodes_by_type("Domain")}

        for node in self.get_nodes_by_type("Project"):
            props = node.get("properties", {})
            project_name = props.get("name", "")
            proj_id = node["node_id"]

            # 프로젝트명에서 엔티티 추출
            text = project_name

            # 기술 추출 및 연결
            if HAS_KG_SERVICE:
                techs = extract_technologies(text)
                for tech in techs:
                    tech_id = f"tech:{tech}"
                    if tech_id in tech_nodes:
                        if self.add_edge(proj_id, tech_id, "USES_TECH"):
                            count += 1

                # 방법론 추출 및 연결
                methods = extract_methodologies(text)
                for method in methods:
                    method_id = f"method:{method}"
                    if method_id in method_nodes:
                        if self.add_edge(proj_id, method_id, "USES_METHOD"):
                            count += 1

                # 도메인 추출 및 연결
                domains = extract_domains(text)
                for domain in domains:
                    domain_id = f"domain:{domain}"
                    if domain_id in domain_nodes:
                        if self.add_edge(proj_id, domain_id, "IN_DOMAIN"):
                            count += 1
            else:
                # knowledge_graph 서비스 없이 간단한 키워드 매칭
                text_lower = project_name.lower()

                # 방법론 키워드 매칭
                method_keywords = {
                    "method:ISP": ["isp", "정보화전략", "정보전략"],
                    "method:ISMP": ["ismp", "마스터플랜"],
                    "method:BPR": ["bpr", "업무재설계"],
                    "method:DX": ["dx", "디지털전환", "디지털트랜스포메이션"],
                    "method:AX": ["ax", "ai전환", "ai트랜스포메이션"],
                }
                for method_id, keywords in method_keywords.items():
                    if method_id in method_nodes:
                        if any(kw in text_lower for kw in keywords):
                            if self.add_edge(proj_id, method_id, "USES_METHOD"):
                                count += 1

                # 도메인 키워드 매칭
                domain_keywords = {
                    "domain:보건의료": ["의료", "보건", "병원", "헬스케어"],
                    "domain:수자원": ["수자원", "물관리", "댐", "하천"],
                    "domain:스마트시티": ["스마트시티", "스마트도시"],
                    "domain:농업": ["농업", "농정", "농촌"],
                    "domain:교통": ["교통", "도로", "철도"],
                }
                for domain_id, keywords in domain_keywords.items():
                    if domain_id in domain_nodes:
                        if any(kw in text_lower for kw in keywords):
                            if self.add_edge(proj_id, domain_id, "IN_DOMAIN"):
                                count += 1

        return count

    def build_document_sequence_edges(self) -> int:
        """문서 순서 엣지 (RELATED_SEQUENCE) - 동일 프로젝트 내 RFP→제안서→산출물."""
        count = 0
        category_order = ["rfp", "proposal", "kickoff", "presentation", "final_report", "output"]

        # 프로젝트별 문서 그룹화
        by_project: dict[str, list[dict]] = defaultdict(list)
        for node in self.get_nodes_by_type("Document"):
            props = node.get("properties", {})
            project_id = props.get("project_id", "")
            if project_id:
                by_project[project_id].append(node)

        for project_id, docs in by_project.items():
            # 카테고리 순서대로 정렬
            def sort_key(n):
                cat = n.get("properties", {}).get("category", "")
                return category_order.index(cat) if cat in category_order else 999

            sorted_docs = sorted(docs, key=sort_key)

            # 순차 연결
            for i in range(len(sorted_docs) - 1):
                src = sorted_docs[i]
                tgt = sorted_docs[i + 1]
                src_cat = src.get("properties", {}).get("category", "")
                tgt_cat = tgt.get("properties", {}).get("category", "")
                label = f"{src_cat} → {tgt_cat}"

                if self.add_edge(
                    src["node_id"],
                    tgt["node_id"],
                    "RELATED_SEQUENCE",
                    label=label,
                    sequence_order=i,
                ):
                    count += 1

        return count

    def build_similar_project_edges(self) -> int:
        """유사 프로젝트 엣지 (SIMILAR_TO)."""
        count = 0
        projects = self.get_nodes_by_type("Project")

        if len(projects) < 2:
            return count

        # 프로젝트별 메타데이터
        project_info: dict[str, dict] = {}
        for p in projects:
            props = p.get("properties", {})
            name = props.get("name", "")
            org = props.get("organization", "")

            # 프로젝트 유형 추론
            proj_type = ""
            name_lower = name.lower()
            if "isp" in name_lower or "정보화전략" in name_lower:
                proj_type = "isp"
            elif "ismp" in name_lower or "마스터플랜" in name_lower:
                proj_type = "ismp"
            elif "구축" in name_lower or "개발" in name_lower:
                proj_type = "build"
            elif "고도화" in name_lower or "개선" in name_lower:
                proj_type = "upgrade"

            # 문서 카테고리 수집
            categories = set()
            for doc in self.get_nodes_by_type("Document"):
                doc_props = doc.get("properties", {})
                if doc_props.get("project_id") == p["node_id"]:
                    cat = doc_props.get("category", "")
                    if cat:
                        categories.add(cat)

            project_info[p["node_id"]] = {
                "name": name,
                "organization": org,
                "proj_type": proj_type,
                "categories": categories,
            }

        added_pairs: set[tuple[str, str]] = set()
        project_ids = list(project_info.keys())

        for i, p1_id in enumerate(project_ids):
            info1 = project_info[p1_id]
            if info1["name"] == "미분류":
                continue

            for p2_id in project_ids[i + 1:]:
                info2 = project_info[p2_id]
                if info2["name"] == "미분류":
                    continue

                pair = tuple(sorted([p1_id, p2_id]))
                if pair in added_pairs:
                    continue

                # 동일 발주기관
                if info1["organization"] and info1["organization"] == info2["organization"]:
                    if self.add_edge(
                        p1_id, p2_id, "SIMILAR_TO",
                        label=f"동일기관({info1['organization']})",
                        similarity_score=0.8,
                        method="same_organization",
                    ):
                        count += 1
                        added_pairs.add(pair)
                    continue

                # 유사 카테고리 구성 (60% 이상)
                if info1["categories"] and info2["categories"]:
                    intersection = len(info1["categories"] & info2["categories"])
                    union = len(info1["categories"] | info2["categories"])
                    if union > 0:
                        similarity = intersection / union
                        if similarity >= 0.6:
                            if self.add_edge(
                                p1_id, p2_id, "SIMILAR_TO",
                                label=f"유사구성({similarity:.0%})",
                                similarity_score=round(similarity, 2),
                                method="category_similarity",
                            ):
                                count += 1
                                added_pairs.add(pair)

        return count

    def build_snapshot_source_edges(self) -> int:
        """스냅샷 → 소스 엣지 (HAS_SOURCE)."""
        count = 0
        snapshots = self.get_nodes_by_type("Snapshot")
        sources = self.get_nodes_by_type("Source")

        for snap in snapshots:
            for src in sources:
                if self.add_edge(snap["node_id"], src["node_id"], "HAS_SOURCE"):
                    count += 1
        return count

    # ── 기존 그래프 변환 ─────────────────────────────────────────────────────

    def import_legacy_edges(self, legacy_path: Path) -> int:
        """기존 graph_edges.jsonl에서 엣지 임포트 (스키마 매핑 적용)."""
        count = 0
        edges_file = legacy_path / "graph_edges.jsonl"

        if not edges_file.exists():
            print(f"[WARN] Legacy edges not found: {edges_file}")
            return count

        with edges_file.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                legacy = json.loads(line)

                # 기존 relation을 새 edge_type으로 매핑
                old_relation = legacy.get("relation", "")
                new_type = self.legacy_mapping.get(old_relation, old_relation.upper())

                source = legacy.get("source", "")
                target = legacy.get("target", "")
                label = legacy.get("label", "")

                # 속성 추출
                props = {}
                if "weight" in legacy:
                    props["weight"] = legacy["weight"]
                if "similarity_score" in legacy:
                    props["similarity_score"] = legacy["similarity_score"]

                if self.add_edge(source, target, new_type, label=label, **props):
                    count += 1

        return count

    # ── 출력 ─────────────────────────────────────────────────────────────────

    def export_edges(self, output_path: Path) -> int:
        """엣지를 JSONL로 출력."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            for edge in self.edges.values():
                f.write(json.dumps(edge, ensure_ascii=False) + "\n")
        return len(self.edges)

    def get_statistics(self) -> dict[str, int]:
        """엣지 타입별 통계."""
        stats: dict[str, int] = defaultdict(int)
        for edge in self.edges.values():
            stats[edge["edge_type"]] += 1
        return dict(stats)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build LPG graph edges from schema")
    p.add_argument("--nodes", default="",
                   help="Path to graph_nodes.jsonl (default: data/ontology/graph_nodes.jsonl)")
    p.add_argument("--import-legacy", action="store_true",
                   help="Import edges from existing data/indexes/graph/graph_edges.jsonl")
    p.add_argument("--output", default="",
                   help="Output path (default: data/ontology/graph_edges.jsonl)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    nodes_path = Path(args.nodes) if args.nodes else NODES_PATH
    output_path = Path(args.output) if args.output else ONTOLOGY_DIR / "graph_edges.jsonl"

    builder = LPGEdgeBuilder(nodes_path=nodes_path)
    print(f"[INFO] Schema loaded: {len(builder.edge_types)} edge types")
    print(f"[INFO] Nodes loaded: {len(builder.nodes)} nodes")
    print(f"[INFO] Terms loaded: {len(builder.terms)} terms")

    # 1. 기존 그래프에서 임포트 (선택)
    if args.import_legacy:
        print("[1/7] Importing legacy edges...")
        legacy_count = builder.import_legacy_edges(LEGACY_GRAPH_DIR)
        print(f"  -> {legacy_count} edges imported from legacy graph")
    else:
        print("[1/7] Skipping legacy import (use --import-legacy to enable)")

    # 2. 문서 → 카테고리
    print("[2/7] Building document-category edges (HAS_CATEGORY)...")
    cat_count = builder.build_document_category_edges()
    print(f"  -> {cat_count} edges")

    # 3. 프로젝트 ↔ 문서
    print("[3/7] Building project-document edges (HAS_DOCUMENT, BELONGS_TO)...")
    doc_count = builder.build_project_document_edges()
    print(f"  -> {doc_count} edges")

    # 4. 프로젝트 → 기관
    print("[4/7] Building project-organization edges (ISSUED_BY)...")
    org_count = builder.build_project_organization_edges()
    print(f"  -> {org_count} edges")

    # 5. 기술 계층
    print("[5/7] Building technology hierarchy edges (PARENT_TECH)...")
    tech_count = builder.build_technology_hierarchy_edges()
    print(f"  -> {tech_count} edges")

    # 6. 프로젝트 → 엔티티 (기술/방법론/도메인)
    print("[6/7] Building project-entity edges (USES_TECH, USES_METHOD, IN_DOMAIN)...")
    entity_count = builder.build_project_entity_edges()
    print(f"  -> {entity_count} edges")

    # 7. 문서 순서 + 유사 프로젝트 + 스냅샷-소스
    print("[7/7] Building sequence, similarity, and snapshot edges...")
    seq_count = builder.build_document_sequence_edges()
    sim_count = builder.build_similar_project_edges()
    snap_count = builder.build_snapshot_source_edges()
    print(f"  -> {seq_count} sequence, {sim_count} similarity, {snap_count} snapshot edges")

    # 출력
    total = builder.export_edges(output_path)
    stats = builder.get_statistics()

    print(f"\n[DONE] Exported {total} edges to {output_path}")
    print("Statistics:")
    for edge_type, count in sorted(stats.items()):
        print(f"  {edge_type}: {count}")

    # 매니페스트 저장
    manifest = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "nodes_path": str(nodes_path),
        "total_edges": total,
        "statistics": stats,
        "output_path": str(output_path),
    }
    manifest_path = output_path.parent / "graph_edges_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest: {manifest_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
