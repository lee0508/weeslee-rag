# LPG 스키마 기반 그래프 노드 생성 스크립트
# -*- coding: utf-8 -*-
"""
LPG 스키마(data/ontology/schema.json) 기반 그래프 노드 생성.

입력:
  - data/ontology/schema.json (스키마 정의)
  - data/ontology/terms.jsonl (용어 사전)
  - data/indexes/faiss/*_metadata.jsonl (문서 메타데이터)
  - data/staged/manifest/*.csv (매니페스트 CSV)

출력:
  - data/ontology/graph_nodes.jsonl (LPG 노드)

노드 타입:
  Snapshot, Source, Category, Project, Document, Organization,
  Technology, Methodology, Domain, Chunk, Wiki, Collection
"""
from __future__ import annotations

import argparse
import csv
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
TERMS_PATH = ONTOLOGY_DIR / "terms.jsonl"
ACTIVE_INDEX_PATH = DATA_DIR / "active_index.json"
FAISS_DIR = DATA_DIR / "indexes" / "faiss"
MANIFEST_DIR = DATA_DIR / "staged" / "manifest"
LEGACY_GRAPH_DIR = DATA_DIR / "indexes" / "graph"

BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 선택적 import (knowledge_graph 서비스가 없을 경우 대비)
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


_DATE_PREFIX = re.compile(r"^\d+\.\s*")


class LPGNodeBuilder:
    """LPG 스키마 기반 노드 빌더."""

    def __init__(self, schema_path: Path = SCHEMA_PATH, terms_path: Path = TERMS_PATH):
        self.schema = self._load_schema(schema_path)
        self.terms = self._load_terms(terms_path)
        self.nodes: dict[str, dict] = {}
        self.node_types = self.schema.get("node_types", {})
        self.category_codes = self.schema.get("category_codes", {})

    def _load_schema(self, path: Path) -> dict:
        """스키마 로드."""
        if not path.exists():
            print(f"[WARN] Schema not found: {path}")
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_terms(self, path: Path) -> dict[str, dict]:
        """용어 사전 로드 (term_id -> term)."""
        terms = {}
        if not path.exists():
            print(f"[WARN] Terms not found: {path}")
            return terms
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    term = json.loads(line)
                    terms[term["term_id"]] = term
        return terms

    def add_node(self, node_id: str, node_type: str, **properties) -> bool:
        """노드 추가. 이미 존재하면 False 반환."""
        if node_id in self.nodes:
            return False

        type_schema = self.node_types.get(node_type, {})
        color = type_schema.get("color", "#6b7280")

        node = {
            "node_id": node_id,
            "node_type": node_type,
            "labels": [node_type],
            "properties": properties,
            "color": color,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.nodes[node_id] = node
        return True

    def get_node(self, node_id: str) -> dict | None:
        """노드 조회."""
        return self.nodes.get(node_id)

    def update_node(self, node_id: str, **properties) -> bool:
        """노드 속성 업데이트."""
        if node_id not in self.nodes:
            return False
        self.nodes[node_id]["properties"].update(properties)
        return True

    # ── 노드 생성 메서드 ──────────────────────────────────────────────────────

    def build_category_nodes(self) -> int:
        """카테고리 노드 생성."""
        count = 0
        for code, info in self.category_codes.items():
            node_id = f"cat:{code}"
            if self.add_node(
                node_id,
                "Category",
                category_id=node_id,
                label=info.get("label", code),
                code=code,
                color=info.get("color", "#6b7280"),
                order=info.get("order", 0),
            ):
                count += 1
        return count

    def build_term_nodes(self) -> int:
        """용어 사전에서 노드 생성 (Organization, Technology, Methodology, Domain)."""
        count = 0
        type_mapping = {
            "organization": "Organization",
            "technology": "Technology",
            "methodology": "Methodology",
            "domain": "Domain",
            "category": "Category",
        }

        for term_id, term in self.terms.items():
            term_type = term.get("term_type", "")
            node_type = type_mapping.get(term_type)
            if not node_type:
                continue

            # 카테고리는 이미 build_category_nodes에서 처리
            if term_type == "category":
                continue

            if self.add_node(
                term_id,
                node_type,
                label=term.get("label", ""),
                synonyms=term.get("synonyms", []),
                description=term.get("description", ""),
                parent_id=term.get("parent_id"),
            ):
                count += 1
        return count

    def build_project_nodes(self, docs: list[dict]) -> int:
        """문서 목록에서 프로젝트 노드 생성."""
        count = 0
        by_project: dict[str, list[dict]] = defaultdict(list)

        for doc in docs:
            project_name = doc.get("project_name") or "미분류"
            by_project[project_name].append(doc)

        for project_name, proj_docs in by_project.items():
            if project_name == "미분류":
                continue

            proj_id = f"project:{project_name}"

            # 연도 추출
            year = ""
            for d in proj_docs:
                m = re.search(r"/(20\d\d)/|\\(20\d\d)\\", d.get("source_path", ""))
                if m:
                    year = m.group(1) or m.group(2)
                    break

            # 발주기관 추출
            organization = next(
                (d.get("organization", "") for d in proj_docs if d.get("organization")),
                ""
            )
            organization_id = ""
            if organization:
                canonical = normalize_organization(organization)
                organization_id = f"org:{canonical}"

            if self.add_node(
                proj_id,
                "Project",
                project_id=proj_id,
                name=project_name,
                year=year,
                organization=organization,
                organization_id=organization_id,
                doc_count=len(proj_docs),
                status="active",
            ):
                count += 1

        return count

    def build_document_nodes(self, docs: list[dict]) -> int:
        """
        문서 노드 생성.

        B안: Chunk를 Document 속성으로 포함.
        - chunk_count, chunk_ids, total_chars, section_headings
        - content_length, page_count, extraction_method, is_scanned
        - embedding_status, ocr_completed_at

        [2026-07-12] 문서 체인 속성 추가:
        - chain_project_name: 정규화된 프로젝트명 (파일명 기반)
        - chain_document_role: rfp, proposal, deliverable
        - chain_section_name: 전략및방법론, 환경분석 등
        """
        count = 0
        for doc in docs:
            doc_id = doc.get("document_id", "")
            if not doc_id:
                continue

            node_id = f"doc:{doc_id}"
            source_path = doc.get("source_path", "")
            filename = Path(source_path).name if source_path else ""
            category = doc.get("category", "")
            project_name = doc.get("project_name") or "미분류"

            # [2026-07-12] 문서 체인 정보 추출
            chain_project_name = doc.get("chain_project_name", "")
            chain_document_role = doc.get("chain_document_role", "")
            chain_section_name = doc.get("chain_section_name", "")

            # chain_project_name이 있으면 project_name으로도 사용
            if chain_project_name and project_name == "미분류":
                project_name = chain_project_name

            # 카테고리 색상
            cat_info = self.category_codes.get(category, {})
            color = cat_info.get("color", "#6b7280")

            # B안: Chunk 메타데이터를 Document 속성으로 포함
            chunk_count = doc.get("chunk_count", 0)
            chunk_ids = doc.get("chunk_ids", [])

            # chunk_ids가 너무 많으면 처음/끝 일부만 저장 (그래프 크기 제한)
            if len(chunk_ids) > 20:
                chunk_ids_summary = chunk_ids[:10] + ["..."] + chunk_ids[-5:]
            else:
                chunk_ids_summary = chunk_ids

            if self.add_node(
                node_id,
                "Document",
                document_id=doc_id,
                label=filename,
                category=category,
                project_id=f"project:{project_name}" if project_name != "미분류" else "",
                project_name=project_name,
                source_path=source_path,
                extension=doc.get("extension", ""),
                color=color,
                status="indexed",
                # B안: Chunk 관련 속성
                chunk_count=chunk_count,
                chunk_ids=chunk_ids_summary,
                total_chars=doc.get("total_chars", 0),
                section_headings=doc.get("section_headings", []),
                content_length=doc.get("content_length", 0),
                page_count=doc.get("page_count", 0),
                extraction_method=doc.get("extraction_method", ""),
                is_scanned=doc.get("is_scanned", False),
                embedding_status="indexed" if chunk_count > 0 else "pending",
                ocr_completed_at=doc.get("ocr_completed_at", ""),
                # [2026-07-12] 문서 체인 속성 추가
                chain_project_name=chain_project_name,
                chain_document_role=chain_document_role,
                chain_section_name=chain_section_name,
            ):
                count += 1

        return count

    def build_snapshot_node(self, snapshot_name: str, doc_count: int) -> bool:
        """스냅샷 노드 생성."""
        node_id = f"snap:{snapshot_name}"
        return self.add_node(
            node_id,
            "Snapshot",
            snapshot_id=node_id,
            name=snapshot_name,
            document_count=doc_count,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )

    def build_source_nodes(self) -> int:
        """소스 노드 생성 (RFP, 제안서, 산출물)."""
        count = 0
        sources = [
            ("src:rfp", "RFP", "rfp"),
            ("src:proposal", "제안서", "proposal"),
            ("src:output", "산출물", "output"),
        ]
        for src_id, label, code in sources:
            if self.add_node(
                src_id,
                "Source",
                source_id=src_id,
                label=label,
                code=code,
            ):
                count += 1
        return count

    # ── 데이터 로드 ──────────────────────────────────────────────────────────

    def load_docs_from_faiss_meta(self, path: Path) -> list[dict]:
        """
        FAISS 메타데이터에서 문서 로드.

        B안: Chunk를 Document 속성으로 포함.
        - chunk_count: 총 chunk 수
        - chunk_ids: chunk ID 목록
        - total_chars: 전체 문자 수
        - section_headings: 섹션 제목 목록
        """
        # 문서별 chunk 집계
        doc_chunks: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "chunk_ids": [],
            "total_chars": 0,
            "section_headings": set(),
            "meta": None,
        })

        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                doc_id = row.get("document_id", "")
                if not doc_id:
                    continue

                chunk_id = row.get("chunk_id", "")
                char_count = row.get("char_count", 0)
                section = row.get("section_heading") or ""
                meta = row.get("metadata") or {}

                doc_data = doc_chunks[doc_id]
                if chunk_id:
                    doc_data["chunk_ids"].append(chunk_id)
                doc_data["total_chars"] += char_count
                if section:
                    doc_data["section_headings"].add(section)

                # 첫 번째 chunk에서 문서 메타데이터 저장
                if doc_data["meta"] is None:
                    doc_data["meta"] = {
                        "source_path": row.get("source_path") or meta.get("source_path", ""),
                        "category": row.get("category") or meta.get("category", ""),
                        "extension": meta.get("extension", ""),
                        "project_name": meta.get("project_name", ""),
                        "organization": meta.get("organization", ""),
                        "content_length": meta.get("content_length", 0),
                        "page_count": meta.get("page_count", 0),
                        "extraction_method": meta.get("extraction_method", ""),
                        "is_scanned": meta.get("is_scanned", False),
                        "created_at": meta.get("created_at", ""),
                    }

        # 문서 목록 생성
        docs: list[dict] = []
        for doc_id, data in doc_chunks.items():
            meta = data["meta"] or {}
            source_path = meta.get("source_path", "")
            project_name = meta.get("project_name") or self._project_from_path(source_path)

            docs.append({
                "document_id": doc_id,
                "category": meta.get("category", ""),
                "source_path": source_path,
                "extension": meta.get("extension", ""),
                "project_name": project_name,
                "organization": meta.get("organization", ""),
                # B안: Chunk 메타데이터를 Document 속성으로
                "chunk_count": len(data["chunk_ids"]),
                "chunk_ids": data["chunk_ids"],
                "total_chars": data["total_chars"],
                "section_headings": sorted(data["section_headings"]),
                "content_length": meta.get("content_length", 0),
                "page_count": meta.get("page_count", 0),
                "extraction_method": meta.get("extraction_method", ""),
                "is_scanned": meta.get("is_scanned", False),
                "ocr_completed_at": meta.get("created_at", ""),
            })

        return docs

    def load_docs_from_manifests(self, manifest_dir: Path) -> list[dict]:
        """매니페스트 CSV에서 문서 로드."""
        seen: set[str] = set()
        docs: list[dict] = []

        for csv_path in sorted(manifest_dir.glob("snapshot_*.csv")):
            with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    doc_id = row.get("document_id", "")
                    if not doc_id or doc_id in seen:
                        continue
                    seen.add(doc_id)

                    folder_name = row.get("folder_name", "")
                    project_name = _DATE_PREFIX.sub("", folder_name).strip()
                    source_path = row.get("source_path", "")

                    docs.append({
                        "document_id": doc_id,
                        "category": row.get("category", ""),
                        "source_path": source_path,
                        "extension": Path(source_path).suffix.lower() if source_path else "",
                        "project_name": project_name,
                        "organization": "",
                    })
        return docs

    def load_docs_from_legacy_graph(self, graph_dir: Path) -> list[dict]:
        """기존 graph_nodes.jsonl에서 문서 로드."""
        docs: list[dict] = []
        nodes_path = graph_dir / "graph_nodes.jsonl"

        if not nodes_path.exists():
            return docs

        with nodes_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                node = json.loads(line)
                if node.get("type") == "document":
                    docs.append({
                        "document_id": node.get("document_id", ""),
                        "category": node.get("category", ""),
                        "source_path": node.get("source_path", ""),
                        "extension": node.get("extension", ""),
                        "project_name": node.get("project_name", ""),
                        "organization": "",
                    })
        return docs

    def _project_from_path(self, source_path: str) -> str:
        """경로에서 프로젝트명 추출."""
        if not source_path:
            return ""
        parts = [p for p in re.split(r"[\\/]", source_path) if p and p != "."]
        if parts and len(parts[0]) == 2 and parts[0][1] == ":":
            parts = parts[1:]
        if len(parts) < 2:
            return ""
        return _DATE_PREFIX.sub("", parts[1]).strip()

    # ── 출력 ─────────────────────────────────────────────────────────────────

    def export_nodes(self, output_path: Path) -> int:
        """노드를 JSONL로 출력."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            for node in self.nodes.values():
                f.write(json.dumps(node, ensure_ascii=False) + "\n")
        return len(self.nodes)

    def get_statistics(self) -> dict[str, int]:
        """노드 타입별 통계."""
        stats: dict[str, int] = defaultdict(int)
        for node in self.nodes.values():
            stats[node["node_type"]] += 1
        return dict(stats)


def read_active_snapshot() -> str:
    """활성 스냅샷 읽기."""
    if ACTIVE_INDEX_PATH.exists():
        try:
            data = json.loads(ACTIVE_INDEX_PATH.read_text(encoding="utf-8"))
            return data.get("snapshot", "")
        except Exception:
            pass
    return ""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build LPG graph nodes from schema")
    p.add_argument("--snapshot", default="",
                   help="Snapshot name (auto-detect from active_index.json if omitted)")
    p.add_argument("--faiss-meta", default="",
                   help="Direct path to FAISS metadata JSONL")
    p.add_argument("--use-legacy", action="store_true",
                   help="Load from existing graph_nodes.jsonl instead of FAISS/manifest")
    p.add_argument("--output", default="",
                   help="Output path (default: data/ontology/graph_nodes.jsonl)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    builder = LPGNodeBuilder()
    print(f"[INFO] Schema loaded: {len(builder.node_types)} node types")
    print(f"[INFO] Terms loaded: {len(builder.terms)} terms")

    # 1. 정적 노드 생성
    print("[1/5] Building category nodes...")
    cat_count = builder.build_category_nodes()
    print(f"  -> {cat_count} category nodes")

    print("[2/5] Building source nodes...")
    src_count = builder.build_source_nodes()
    print(f"  -> {src_count} source nodes")

    print("[3/5] Building term nodes (org/tech/method/domain)...")
    term_count = builder.build_term_nodes()
    print(f"  -> {term_count} term nodes")

    # 2. 문서 데이터 로드
    docs: list[dict] = []

    if args.use_legacy:
        print("[4/5] Loading documents from legacy graph...")
        docs = builder.load_docs_from_legacy_graph(LEGACY_GRAPH_DIR)
        source_info = f"legacy_graph ({LEGACY_GRAPH_DIR})"
    elif args.faiss_meta:
        faiss_path = Path(args.faiss_meta)
        if faiss_path.exists():
            print(f"[4/5] Loading documents from FAISS metadata: {faiss_path}")
            docs = builder.load_docs_from_faiss_meta(faiss_path)
            source_info = f"faiss_meta ({faiss_path})"
        else:
            print(f"[WARN] FAISS metadata not found: {faiss_path}")
            docs = builder.load_docs_from_manifests(MANIFEST_DIR)
            source_info = f"manifest ({MANIFEST_DIR})"
    else:
        snapshot = args.snapshot or read_active_snapshot()
        faiss_path = FAISS_DIR / f"{snapshot}_ollama_metadata.jsonl" if snapshot else None

        if faiss_path and faiss_path.exists():
            print(f"[4/5] Loading documents from FAISS metadata: {faiss_path}")
            docs = builder.load_docs_from_faiss_meta(faiss_path)
            source_info = f"faiss_meta ({faiss_path})"
        else:
            print(f"[4/5] Loading documents from manifests: {MANIFEST_DIR}")
            docs = builder.load_docs_from_manifests(MANIFEST_DIR)
            source_info = f"manifest ({MANIFEST_DIR})"

    print(f"  -> {len(docs)} documents loaded from {source_info}")

    if not docs:
        print("[WARN] No documents found, using legacy graph as fallback...")
        docs = builder.load_docs_from_legacy_graph(LEGACY_GRAPH_DIR)
        print(f"  -> {len(docs)} documents from legacy graph")

    # 3. 프로젝트 및 문서 노드 생성
    print("[5/5] Building project and document nodes...")
    proj_count = builder.build_project_nodes(docs)
    doc_count = builder.build_document_nodes(docs)
    print(f"  -> {proj_count} project nodes, {doc_count} document nodes")

    # 4. 스냅샷 노드
    snapshot_name = args.snapshot or read_active_snapshot() or datetime.now().strftime("%Y%m%d")
    builder.build_snapshot_node(snapshot_name, len(docs))

    # 5. 출력
    output_path = Path(args.output) if args.output else ONTOLOGY_DIR / "graph_nodes.jsonl"
    total = builder.export_nodes(output_path)

    stats = builder.get_statistics()
    print(f"\n[DONE] Exported {total} nodes to {output_path}")
    print("Statistics:")
    for node_type, count in sorted(stats.items()):
        print(f"  {node_type}: {count}")

    # 매니페스트 저장
    manifest = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "source": source_info,
        "total_nodes": total,
        "statistics": stats,
        "output_path": str(output_path),
    }
    manifest_path = output_path.parent / "graph_nodes_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest: {manifest_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
