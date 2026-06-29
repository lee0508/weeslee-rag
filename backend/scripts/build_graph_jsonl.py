# -*- coding: utf-8 -*-
"""
Build document graph JSONL from FAISS metadata (or manifest CSV fallback).

Output:
  data/indexes/graph/graph_nodes.jsonl
  data/indexes/graph/graph_edges.jsonl
  data/indexes/graph/graph_manifest.json

Node types:  project | document | document_section | category | organization | technology | methodology | domain | chunk_section
Edge types:  has_document | has_category | CONTAINS_SECTION | related_sequence | 발주 | 적용기술 | 사용방법론 | 관련도메인 | 동의어 | 유사기술 | APPEARS_IN | MENTIONS

Phase 2 enhancements:
- chunk_section 노드: FAISS 청크의 section_heading 기반 섹션 노드 생성
- APPEARS_IN 엣지: Chunk → Section 연결
- page_no 메타데이터 포함

Phase 3 enhancements:
- MENTIONS 엣지: Document → Keyword 연결 (청크 텍스트 기반)
- 문서별 키워드 집계 및 빈도 정보 포함
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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
ACTIVE_INDEX_PATH = DATA_DIR / "active_index.json"
FAISS_DIR = DATA_DIR / "indexes" / "faiss"
MANIFEST_DIR = DATA_DIR / "staged" / "manifest"
GRAPH_DIR = DATA_DIR / "indexes" / "graph"
PLATFORM_STORE_PATH = DATA_DIR / "platform_store.json"

BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.metadata_enricher import enrich_confidence  # noqa: E402
from app.services.knowledge_graph import (  # noqa: E402
    normalize_organization,
    get_organization_synonyms,
    extract_technologies,
    extract_methodologies,
    extract_domains,
    get_technology_color,
    ORGANIZATION_SYNONYMS,
    TECHNOLOGY_HIERARCHY,
    METHODOLOGY_SYNONYMS,
    DOMAIN_SYNONYMS,
    # 확장된 분류 함수들
    get_organization_type,
    get_all_organization_types,
    get_organizations_by_type,
    classify_project_type,
    get_all_project_types,
    classify_document_section,
    get_all_document_sections,
    extract_document_keywords,
    get_all_document_keywords,
)

# ── Category config ───────────────────────────────────────────────────────────

CATEGORY_ORDER = ["rfp", "proposal", "deliverable"]

CATEGORY_LABELS = {
    "rfp":          "RFP (제안요청서)",
    "proposal":     "제안서",
    "deliverable":  "산출물",
}

CATEGORY_COLORS = {
    "rfp":          "#ef4444",
    "proposal":     "#3b82f6",
    "deliverable":  "#22c55e",
}

_DATE_PREFIX = re.compile(r"^\d+\.\s*")


# ── Source ID helpers ─────────────────────────────────────────────────────────

def _load_platform_store() -> dict:
    """platform_store.json 로드."""
    if not PLATFORM_STORE_PATH.exists():
        return {}
    try:
        return json.loads(PLATFORM_STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_source_mount_path(source_id: str) -> str | None:
    """Document Source의 mount_path 반환."""
    store = _load_platform_store()
    for rec in store.get("document_sources", []):
        if rec.get("source_id") == source_id:
            return rec.get("mount_path") or rec.get("source_uri")
    return None


def _filter_docs_by_source(docs: list[dict], source_id: str) -> list[dict]:
    """source_id의 mount_path 기준으로 문서 필터링."""
    mount_path = _get_source_mount_path(source_id)
    if not mount_path:
        print(f"[WARN] source_id '{source_id}' not found, returning all docs")
        return docs

    mount_normalized = mount_path.replace("\\", "/").rstrip("/")
    filtered = []
    for doc in docs:
        source_path = doc.get("source_path", "").replace("\\", "/")
        if source_path.startswith(mount_normalized):
            filtered.append(doc)
    return filtered


def _get_graph_dir(source_id: str | None) -> Path:
    """source_id별 Graph 디렉토리 반환."""
    if source_id:
        return DATA_DIR / "indexes" / "graph" / source_id
    return GRAPH_DIR


# ── Data loading ──────────────────────────────────────────────────────────────

def _read_active_snapshot() -> str:
    if ACTIVE_INDEX_PATH.exists():
        try:
            data = json.loads(ACTIVE_INDEX_PATH.read_text(encoding="utf-8"))
            return data.get("snapshot", "")
        except Exception:
            pass
    return ""


# 작성일: 2026-05-12 | 기능: source_path 폴더 구조에서 프로젝트명 추출 (project_name 빈 경우 폴백)
def _project_name_from_path(source_path: str) -> str:
    if not source_path:
        return ""
    parts = [p for p in re.split(r"[\\/]", source_path) if p and p != "."]
    # 드라이브 문자 제거 (예: "W:")
    if parts and len(parts[0]) == 2 and parts[0][1] == ":":
        parts = parts[1:]
    # 구조: [최상위 폴더, 프로젝트 폴더, ...]
    if len(parts) < 2:
        return ""
    return _DATE_PREFIX.sub("", parts[1]).strip()


def _docs_from_faiss_meta(path: Path) -> list[dict]:
    """Extract unique documents from a FAISS metadata JSONL."""
    seen: set[str] = set()
    docs: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            doc_id = row.get("document_id", "")
            if not doc_id or doc_id in seen:
                continue
            seen.add(doc_id)
            meta = row.get("metadata") or {}
            source_path = row.get("source_path") or meta.get("source_path", "")
            # 작성일: 2026-05-12 | 기능: metadata.project_name 없으면 source_path 경로에서 추출
            project_name = meta.get("project_name") or _project_name_from_path(source_path)
            docs.append({
                "document_id": doc_id,
                "category":    row.get("category") or meta.get("category", ""),
                "source_path": source_path,
                "extension":   meta.get("extension", ""),
                "project_name":             project_name,
                "organization":             meta.get("organization", ""),
                "organization_confidence":  meta.get("organization_confidence", 0.0),
                "project_confidence":       meta.get("project_confidence", 0.0),
            })
    return docs


def _chunks_from_faiss_meta(path: Path, allowed_doc_ids: set[str] | None = None) -> list[dict]:
    """Extract chunks with section_heading info from FAISS metadata JSONL."""
    chunks: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            document_id = row.get("document_id", "")
            if allowed_doc_ids is not None and document_id not in allowed_doc_ids:
                continue
            chunk_id = row.get("chunk_id", "")
            if not chunk_id:
                continue
            meta = row.get("metadata") or {}
            chunks.append({
                "chunk_id": chunk_id,
                "document_id": document_id,
                "section_heading": row.get("section_heading", ""),
                "section_title": row.get("section_title") or meta.get("section_title", ""),
                "section_id": row.get("section_id") or meta.get("section_id"),
                "page_no": row.get("page_no") or meta.get("page_no", 0),
                "slide_no": row.get("slide_no") or meta.get("slide_no"),
                "char_count": row.get("char_count", 0),
            })
    return chunks


def _load_document_texts_by_source_path(allowed_source_paths: set[str] | None = None) -> dict[str, str]:
    """Load combined document texts from processed_text/{doc_id}/ files.

    source_path를 키로 사용하여 FAISS document_id와 매핑 가능하게 함.

    Returns:
        dict: source_path (normalized) -> combined text of all chunks
    """
    source_path_texts: dict[str, str] = {}

    # 청크 텍스트는 data/processed_text/{doc_id}/chunks.json 에 저장됨
    processed_text_dir = DATA_DIR / "processed_text"

    if not processed_text_dir.exists():
        return source_path_texts

    try:
        for doc_dir in processed_text_dir.iterdir():
            if not doc_dir.is_dir():
                continue

            # ocr_report.json에서 source_path 추출
            ocr_report_file = doc_dir / "ocr_report.json"
            chunks_file = doc_dir / "chunks.json"

            if not ocr_report_file.exists() or not chunks_file.exists():
                continue

            try:
                # source_path 추출
                with ocr_report_file.open("r", encoding="utf-8") as f:
                    ocr_data = json.load(f)
                source_path = ocr_data.get("source_path", "")
                if not source_path:
                    continue

                # 경로 정규화 (역슬래시 → 슬래시)
                source_path_key = source_path.replace("\\", "/")
                if allowed_source_paths is not None and source_path_key not in allowed_source_paths:
                    continue

                # chunks.json에서 텍스트 추출
                with chunks_file.open("r", encoding="utf-8") as f:
                    chunks_data = json.load(f)

                combined_text = ""
                for chunk in chunks_data.get("chunks", []):
                    content = chunk.get("content", "")
                    if content:
                        combined_text += " " + content

                if combined_text.strip():
                    source_path_texts[source_path_key] = combined_text.strip()

            except Exception:
                continue  # 개별 파일 오류는 무시

    except Exception as e:
        print(json.dumps({"warning": f"Failed to load document texts: {e}"}))

    return source_path_texts


def _docs_from_manifests() -> list[dict]:
    """Extract documents from manifest CSVs using folder_name enrichment."""
    seen: set[str] = set()
    docs: list[dict] = []
    for csv_path in sorted(MANIFEST_DIR.glob("snapshot_*.csv")):
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                doc_id = row.get("document_id", "")
                if not doc_id or doc_id in seen:
                    continue
                seen.add(doc_id)
                folder_name = row.get("folder_name", "")
                project_name = _DATE_PREFIX.sub("", folder_name).strip()
                confidence = enrich_confidence(folder_name, project_name)
                docs.append({
                    "document_id": doc_id,
                    "category":    row.get("category", ""),
                    "source_path": row.get("source_path", ""),
                    "extension":   Path(row.get("source_path", "")).suffix.lower(),
                    "project_name":             project_name,
                    "organization":             confidence["organization"],
                    "organization_confidence":  confidence["organization_confidence"],
                    "project_confidence":       confidence["project_confidence"],
                })
    return docs


# ── Graph builders ────────────────────────────────────────────────────────────

def _build_nodes_edges(docs: list[dict]) -> tuple[list[dict], list[dict]]:
    nodes: list[dict] = []
    edges: list[dict] = []
    node_ids: set[str] = set()
    edge_counter = [0]

    def add_node(n: dict) -> None:
        if n["id"] not in node_ids:
            nodes.append(n)
            node_ids.add(n["id"])

    def add_edge(src: str, tgt: str, relation: str, **extra) -> None:
        edge_counter[0] += 1
        edges.append({"id": f"e{edge_counter[0]}", "source": src, "target": tgt,
                      "relation": relation, **extra})

    # Static category nodes
    for cat in CATEGORY_ORDER:
        add_node({
            "id":    f"cat:{cat}",
            "type":  "category",
            "label": CATEGORY_LABELS.get(cat, cat),
            "color": CATEGORY_COLORS.get(cat, "#6b7280"),
        })

    # Group documents by project
    by_project: dict[str, list[dict]] = defaultdict(list)
    for doc in docs:
        key = doc["project_name"] or "미분류"
        by_project[key].append(doc)

    for project_name, proj_docs in by_project.items():
        proj_id = f"project:{project_name}"

        # Infer year from a doc's source_path or organization
        year = ""
        for d in proj_docs:
            m = re.search(r"/(20\d\d)/|\\(20\d\d)\\", d["source_path"])
            if m:
                year = m.group(1) or m.group(2)
                break

        # Organization (use first doc with non-empty value)
        organization = next(
            (d["organization"] for d in proj_docs if d.get("organization")), ""
        )

        add_node({
            "id":           proj_id,
            "type":         "project",
            "label":        project_name,
            "doc_count":    len(proj_docs),
            "year":         year,
            "organization": organization,
        })

        # Document nodes + project→doc edges
        for doc in proj_docs:
            doc_id = f"doc:{doc['document_id']}"
            filename = Path(doc["source_path"]).name
            add_node({
                "id":           doc_id,
                "type":         "document",
                "label":        filename,
                "document_id":  doc["document_id"],
                "category":     doc["category"],
                "project_id":   proj_id,
                "project_name": project_name,
                "source_path":  doc["source_path"],
                "extension":    doc["extension"],
                "color":        CATEGORY_COLORS.get(doc["category"], "#6b7280"),
            })
            add_edge(proj_id, doc_id, "has_document")
            cat_node_id = f"cat:{doc['category']}"
            if cat_node_id in node_ids:
                add_edge(doc_id, cat_node_id, "has_category")

        # related_sequence edges: rfp→proposal→deliverable
        ordered: list[dict] = []
        for cat in CATEGORY_ORDER:
            ordered.extend(d for d in proj_docs if d["category"] == cat)
        for i in range(len(ordered) - 1):
            src = f"doc:{ordered[i]['document_id']}"
            tgt = f"doc:{ordered[i + 1]['document_id']}"
            label = f"{ordered[i]['category']} → {ordered[i + 1]['category']}"
            add_edge(src, tgt, "related_sequence", label=label)

    # 개선방안 5: 유사 프로젝트 엣지 생성 (SIMILAR_PROJECT)
    _add_similar_project_edges(nodes, edges, by_project, edge_counter)

    # Knowledge Graph 확장: organization, technology, methodology, domain 노드 및 엣지
    _add_knowledge_graph_nodes(nodes, edges, by_project, edge_counter, node_ids)

    return nodes, edges


# ── Knowledge Graph 확장 ─────────────────────────────────────────────────────


def _add_knowledge_graph_nodes(
    nodes: list[dict],
    edges: list[dict],
    by_project: dict[str, list[dict]],
    edge_counter: list[int],
    node_ids: set[str],
) -> None:
    """
    Knowledge Graph 확장: organization, technology, methodology, domain 노드 생성.
    추가로 organization_type, project_type, document_section, document_keyword 노드 생성.

    각 프로젝트에서 엔티티를 추출하고 노드/엣지로 연결.
    """

    def add_node(n: dict) -> bool:
        if n["id"] not in node_ids:
            nodes.append(n)
            node_ids.add(n["id"])
            return True
        return False

    def add_edge(src: str, tgt: str, relation: str, **extra) -> None:
        edge_id = f"{src}->{tgt}:{relation}"
        if any(e["id"] == edge_id for e in edges):
            return
        edge_counter[0] += 1
        edges.append({"id": edge_id, "source": src, "target": tgt,
                      "relation": relation, **extra})

    # 1. Organization 노드 생성 및 동의어 엣지
    org_nodes_created: set[str] = set()
    for canonical, synonyms in ORGANIZATION_SYNONYMS.items():
        org_id = f"org:{canonical}"
        if add_node({
            "id": org_id,
            "type": "organization",
            "label": canonical,
            "synonyms": synonyms,
            "color": "#0ea5e9",
        }):
            org_nodes_created.add(canonical)

    # 1-1. Organization Type 노드 생성 (공공기관, 공기업, 연구기관 등)
    org_type_colors = {
        "공공기관": "#1d4ed8",
        "공기업": "#0891b2",
        "연구기관": "#7c3aed",
        "건강보험": "#059669",
        "민간기업": "#dc2626",
    }
    for org_type in get_all_organization_types():
        org_type_id = f"org_type:{org_type}"
        members = get_organizations_by_type(org_type)
        add_node({
            "id": org_type_id,
            "type": "organization_type",
            "label": org_type,
            "member_count": len(members),
            "color": org_type_colors.get(org_type, "#64748b"),
        })
        # 기관 → 기관유형 엣지
        for member in members:
            member_org_id = f"org:{member}"
            if member_org_id in node_ids:
                add_edge(member_org_id, org_type_id, "소속유형")

    # 2. Technology 노드 생성 및 계층 엣지
    for tech_name, info in TECHNOLOGY_HIERARCHY.items():
        tech_id = f"tech:{tech_name}"
        add_node({
            "id": tech_id,
            "type": "technology",
            "label": tech_name,
            "synonyms": info.get("synonyms", []),
            "color": info.get("color", get_technology_color(tech_name)),
        })

        # 부모-자식 관계
        if info.get("parent"):
            parent_id = f"tech:{info['parent']}"
            add_edge(parent_id, tech_id, "유사기술", label="상위기술")

        for child in info.get("children", []):
            child_id = f"tech:{child}"
            # 자식 노드가 없으면 먼저 생성
            add_node({
                "id": child_id,
                "type": "technology",
                "label": child,
                "synonyms": [],
                "color": get_technology_color(child),
            })
            add_edge(tech_id, child_id, "유사기술", label="하위기술")

    # 3. Methodology 노드 생성
    for method_name, synonyms in METHODOLOGY_SYNONYMS.items():
        method_id = f"method:{method_name}"
        add_node({
            "id": method_id,
            "type": "methodology",
            "label": method_name,
            "synonyms": synonyms,
            "color": "#f59e0b",
        })

    # 4. Domain 노드 생성
    for domain_name, synonyms in DOMAIN_SYNONYMS.items():
        domain_id = f"domain:{domain_name}"
        add_node({
            "id": domain_id,
            "type": "domain",
            "label": domain_name,
            "synonyms": synonyms,
            "color": "#22c55e",
        })

    # 5. Project Type 노드 생성 (ISP수립, 시스템구축, 플랫폼고도화 등)
    project_type_colors = {
        "ISP수립": "#7c3aed",
        "ISMP수립": "#8b5cf6",
        "시스템구축": "#3b82f6",
        "시스템개선": "#0ea5e9",
        "플랫폼고도화": "#06b6d4",
        "로드맵수립": "#14b8a6",
        "연구용역": "#f59e0b",
        "운영유지보수": "#64748b",
    }
    for proj_type in get_all_project_types():
        proj_type_id = f"proj_type:{proj_type}"
        add_node({
            "id": proj_type_id,
            "type": "project_type",
            "label": proj_type,
            "color": project_type_colors.get(proj_type, "#64748b"),
        })

    # 6. Document Section 노드 생성 (제안서 섹션, 산출물 섹션)
    section_colors = {
        # 제안서 섹션
        "전략및방법론": "#6366f1",
        "기술및기능": "#8b5cf6",
        "프로젝트관리": "#a855f7",
        "프로젝트지원": "#c026d3",
        "연구과제": "#db2777",
        # 산출물 섹션
        "환경분석": "#059669",
        "현황분석": "#0d9488",
        "목표모델": "#0891b2",
        "이행계획": "#0284c7",
    }
    all_sections = get_all_document_sections()
    for section_type, sections in all_sections.items():
        for section_name in sections:
            section_id = f"section:{section_name}"
            add_node({
                "id": section_id,
                "type": "document_section",
                "label": section_name,
                "section_type": section_type.replace("_sections", ""),
                "color": section_colors.get(section_name, "#64748b"),
            })

    # 7. Document Keyword 노드 생성 (보안, 의사소통관리, 품질관리 등)
    keyword_colors = {
        "보안": "#dc2626",
        "의사소통관리": "#2563eb",
        "품질관리": "#16a34a",
        "위험관리": "#ea580c",
        "선진사례": "#7c3aed",
        "데이터관리": "#0891b2",
    }
    for keyword in get_all_document_keywords():
        keyword_id = f"keyword:{keyword}"
        add_node({
            "id": keyword_id,
            "type": "document_keyword",
            "label": keyword,
            "color": keyword_colors.get(keyword, "#64748b"),
        })

    # 8. 프로젝트에서 엔티티 추출 및 엣지 연결
    for project_name, proj_docs in by_project.items():
        if project_name == "미분류":
            continue

        proj_id = f"project:{project_name}"

        # 프로젝트명 + 문서 경로에서 텍스트 추출
        text_for_extraction = project_name
        for doc in proj_docs:
            text_for_extraction += " " + doc.get("source_path", "")

        # Organization 연결 (기존 organization 필드 활용 + 추출)
        org_from_meta = next((d.get("organization") for d in proj_docs if d.get("organization")), "")
        if org_from_meta:
            canonical_org = normalize_organization(org_from_meta)
            org_id = f"org:{canonical_org}"
            if org_id.replace("org:", "") in org_nodes_created or canonical_org in ORGANIZATION_SYNONYMS:
                add_edge(org_id, proj_id, "발주")

            # 기관유형 연결
            org_type = get_organization_type(canonical_org)
            if org_type:
                org_type_id = f"org_type:{org_type}"
                add_edge(proj_id, org_type_id, "발주기관유형")

        # Technology 추출 및 연결
        techs = extract_technologies(text_for_extraction)
        for tech in techs:
            tech_id = f"tech:{tech}"
            add_edge(proj_id, tech_id, "적용기술")

        # Methodology 추출 및 연결
        methods = extract_methodologies(text_for_extraction)
        for method in methods:
            method_id = f"method:{method}"
            add_edge(proj_id, method_id, "사용방법론")

        # Domain 추출 및 연결
        domains = extract_domains(text_for_extraction)
        for domain in domains:
            domain_id = f"domain:{domain}"
            add_edge(proj_id, domain_id, "관련도메인")

        # Project Type 추출 및 연결
        proj_types = classify_project_type(text_for_extraction)
        for proj_type in proj_types:
            proj_type_id = f"proj_type:{proj_type}"
            add_edge(proj_id, proj_type_id, "사업유형")

    # 9. 문서별 섹션/키워드 연결 (source_path 기반)
    for project_name, proj_docs in by_project.items():
        for doc in proj_docs:
            doc_id = f"doc:{doc['document_id']}"
            if doc_id not in node_ids:
                continue

            source_path = doc.get("source_path", "")
            doc_category = doc.get("category", "")

            # 문서 섹션 추출 및 연결
            sections = classify_document_section(source_path, doc_category)
            for section in sections:
                section_id = f"section:{section}"
                add_edge(doc_id, section_id, "문서섹션")

            # 문서 키워드 추출 및 연결
            keywords = extract_document_keywords(source_path)
            for keyword in keywords:
                keyword_id = f"keyword:{keyword}"
                add_edge(doc_id, keyword_id, "관련키워드")


# ── DocumentSection 노드 및 CONTAINS_SECTION 엣지 ──────────────────────────────


def _add_document_section_nodes_and_edges(
    nodes: list[dict],
    edges: list[dict],
    chunks: list[dict],
    node_ids: set[str],
    edge_counter: list[int],
) -> None:
    """
    문서의 구조적 섹션(목차 기반) DocumentSection 노드를 생성하고,
    Document → DocumentSection CONTAINS_SECTION 엣지를 추가한다.

    DocumentSection은 문서의 논리적 구조를 나타내며, chunk_section과는 구별된다:
    - DocumentSection: 문서 목차 기반 구조적 섹션 (예: "1. 사업개요", "2. 기술제안")
    - chunk_section: FAISS 청크의 section_heading 기반 (실제 검색 대상)
    """
    from app.services.knowledge_graph import classify_document_section

    def add_node(n: dict) -> bool:
        if n["id"] not in node_ids:
            nodes.append(n)
            node_ids.add(n["id"])
            return True
        return False

    def add_edge(src: str, tgt: str, relation: str, **extra) -> None:
        edge_id = f"{src}->{tgt}:{relation}"
        if any(e["id"] == edge_id for e in edges):
            return
        edge_counter[0] += 1
        edges.append({"id": edge_id, "source": src, "target": tgt,
                      "relation": relation, **extra})

    # 1. 문서별로 청크 그룹화
    doc_chunks: dict[str, list[dict]] = defaultdict(list)
    for chunk in chunks:
        doc_id = chunk.get("document_id", "")
        if doc_id:
            doc_chunks[doc_id].append(chunk)

    # 2. 각 문서의 섹션 추출 및 DocumentSection 노드 생성
    section_colors = {
        "사업개요": "#3b82f6",
        "현황분석": "#0d9488",
        "환경분석": "#059669",
        "목표모델": "#0891b2",
        "기술제안": "#8b5cf6",
        "기술및기능": "#8b5cf6",
        "프로젝트관리": "#a855f7",
        "프로젝트지원": "#c026d3",
        "전략및방법론": "#6366f1",
        "이행계획": "#0284c7",
        "연구과제": "#db2777",
        "보안요구사항": "#dc2626",
        "품질관리": "#16a34a",
    }

    for doc_id, chunks_list in doc_chunks.items():
        doc_node_id = f"doc:{doc_id}"

        # 문서 노드가 그래프에 없으면 스킵
        if doc_node_id not in node_ids:
            continue

        # 섹션 헤딩 추출 및 그룹화
        section_headings: dict[str, list[dict]] = defaultdict(list)
        for chunk in chunks_list:
            section_title = chunk.get("section_title", "").strip()
            if not section_title:
                # section_title이 없으면 section_heading 사용
                section_title = chunk.get("section_heading", "").strip()

            if section_title:
                # 번호 제거 (예: "1. 사업개요" → "사업개요")
                clean_title = re.sub(r"^\d+\.\s*", "", section_title).strip()
                section_headings[clean_title].append(chunk)

        # 3. DocumentSection 노드 생성 (핵심 섹션만)
        for section_title, section_chunks in section_headings.items():
            # 핵심 섹션인지 확인
            matched_sections = classify_document_section(section_title, "")
            is_key_section = len(matched_sections) > 0

            # 핵심 섹션이거나 청크가 3개 이상인 경우만 노드 생성
            if not is_key_section and len(section_chunks) < 3:
                continue

            # DocumentSection 노드 ID
            section_node_id = f"doc_section:{doc_id}:{section_title}"

            # 페이지 범위 계산
            page_nos = [c.get("page_no") for c in section_chunks if c.get("page_no")]
            start_page = min(page_nos) if page_nos else None
            end_page = max(page_nos) if page_nos else None

            # section_id 추출 (첫 번째 청크의 section_id)
            section_id = next((c.get("section_id") for c in section_chunks if c.get("section_id")), None)

            # 노드 생성
            add_node({
                "id": section_node_id,
                "type": "document_section",
                "label": section_title,
                "document_id": doc_id,
                "section_id": section_id,
                "chunk_count": len(section_chunks),
                "is_key_section": is_key_section,
                "start_page": start_page,
                "end_page": end_page,
                "matched_entity_sections": list(matched_sections),
                "color": section_colors.get(section_title, "#64748b"),
            })

            # Document → DocumentSection CONTAINS_SECTION 엣지
            add_edge(doc_node_id, section_node_id, "CONTAINS_SECTION",
                     chunk_count=len(section_chunks),
                     start_page=start_page,
                     end_page=end_page)

            # 핵심 섹션이면 entity section 노드와도 연결
            for matched in matched_sections:
                entity_section_id = f"section:{matched}"
                if entity_section_id in node_ids:
                    add_edge(section_node_id, entity_section_id, "MAPS_TO")


# ── Phase 2: Chunk Section 노드 및 APPEARS_IN 엣지 ──────────────────────────────


def _add_chunk_section_nodes_and_edges(
    nodes: list[dict],
    edges: list[dict],
    chunks: list[dict],
    node_ids: set[str],
    edge_counter: list[int],
) -> None:
    """
    FAISS 청크의 section_heading 기반으로 chunk_section 노드를 생성하고,
    Document → ChunkSection APPEARS_IN 엣지를 추가한다.

    또한 chunk를 DocumentSection과 연결하여 section_id 기반 연결을 강화한다.

    Q2 결정: B (핵심 섹션만 Graph 노드화) - entity_mappings 기반 핵심 섹션만 노드로 생성
    """
    from app.services.knowledge_graph import classify_document_section

    def add_node(n: dict) -> bool:
        if n["id"] not in node_ids:
            nodes.append(n)
            node_ids.add(n["id"])
            return True
        return False

    def add_edge(src: str, tgt: str, relation: str, **extra) -> None:
        edge_id = f"{src}->{tgt}:{relation}"
        if any(e["id"] == edge_id for e in edges):
            return
        edge_counter[0] += 1
        edges.append({"id": edge_id, "source": src, "target": tgt,
                      "relation": relation, **extra})

    # 1. 문서별로 청크 그룹화
    doc_chunks: dict[str, list[dict]] = defaultdict(list)
    for chunk in chunks:
        doc_id = chunk.get("document_id", "")
        if doc_id:
            doc_chunks[doc_id].append(chunk)

    # 2. 각 문서의 섹션 헤딩 추출 및 노드 생성
    section_colors = {
        "기술및기능": "#8b5cf6",
        "프로젝트관리": "#a855f7",
        "프로젝트지원": "#c026d3",
        "전략및방법론": "#6366f1",
        "연구과제": "#db2777",
        "현황분석": "#0d9488",
        "환경분석": "#059669",
        "목표모델": "#0891b2",
        "이행계획": "#0284c7",
    }

    for doc_id, chunks_list in doc_chunks.items():
        doc_node_id = f"doc:{doc_id}"

        # 문서 노드가 그래프에 없으면 스킵
        if doc_node_id not in node_ids:
            continue

        # 유니크한 섹션 헤딩 추출
        section_headings: dict[str, list[dict]] = defaultdict(list)
        for chunk in chunks_list:
            heading = chunk.get("section_heading", "").strip()
            if heading:
                section_headings[heading].append(chunk)

        for heading, heading_chunks in section_headings.items():
            # 섹션 헤딩에서 번호 제거 (예: "1. 기술및기능" → "기술및기능")
            clean_heading = re.sub(r"^\d+\.\s*", "", heading).strip()

            # 핵심 섹션인지 확인 (entity_mappings 기반)
            matched_sections = classify_document_section(clean_heading, "")
            is_key_section = len(matched_sections) > 0

            # chunk_section 노드 ID: doc_id + heading (중복 방지)
            section_node_id = f"chunk_section:{doc_id}:{clean_heading}"

            # 페이지 범위 계산
            page_nos = [c["page_no"] for c in heading_chunks if c.get("page_no")]
            start_page = min(page_nos) if page_nos else None
            end_page = max(page_nos) if page_nos else None

            # 노드 생성 (핵심 섹션만 또는 청크가 2개 이상인 경우)
            if is_key_section or len(heading_chunks) >= 2:
                add_node({
                    "id": section_node_id,
                    "type": "chunk_section",
                    "label": clean_heading,
                    "document_id": doc_id,
                    "chunk_count": len(heading_chunks),
                    "is_key_section": is_key_section,
                    "start_page": start_page,
                    "end_page": end_page,
                    "matched_entity_sections": list(matched_sections),
                    "color": section_colors.get(clean_heading, "#64748b"),
                })

                # Document → ChunkSection APPEARS_IN 엣지
                add_edge(doc_node_id, section_node_id, "APPEARS_IN",
                         chunk_count=len(heading_chunks),
                         start_page=start_page,
                         end_page=end_page)

                # 핵심 섹션이면 기존 section 노드와도 연결
                for matched in matched_sections:
                    entity_section_id = f"section:{matched}"
                    if entity_section_id in node_ids:
                        add_edge(section_node_id, entity_section_id, "MAPS_TO")

    # 3. Chunk → DocumentSection 연결 강화
    # chunk의 section_heading을 DocumentSection 노드와 매칭하여 연결
    # DocumentSection 노드에 chunk_ids 리스트를 추가하여 검색 효율성 향상
    doc_section_chunk_map: dict[str, list[str]] = defaultdict(list)

    for chunk in chunks:
        doc_id = chunk.get("document_id", "")
        section_heading = chunk.get("section_heading", "").strip()
        chunk_id = chunk.get("chunk_id", "")

        if not doc_id or not section_heading or not chunk_id:
            continue

        # section_heading에서 번호 제거
        clean_heading = re.sub(r"^\d+\.\s*", "", section_heading).strip()
        if not clean_heading:
            continue

        # 해당 DocumentSection 노드 ID 생성
        doc_section_id = f"doc_section:{doc_id}:{clean_heading}"

        # DocumentSection 노드가 존재하면 chunk_id 매핑
        if doc_section_id in node_ids:
            doc_section_chunk_map[doc_section_id].append(chunk_id)

    # DocumentSection 노드에 chunk_ids 속성 추가
    chunk_to_doc_section_count = 0
    doc_sections_with_chunks = 0
    for node in nodes:
        if node.get("type") == "document_section":
            node_id = node["id"]
            if node_id in doc_section_chunk_map:
                node["chunk_ids"] = doc_section_chunk_map[node_id]
                chunk_to_doc_section_count += len(doc_section_chunk_map[node_id])
                doc_sections_with_chunks += 1

    # 통계 출력
    print(json.dumps({
        "phase2_enhancement": "chunk_to_document_section_mapping",
        "document_sections_with_chunks": doc_sections_with_chunks,
        "total_chunks_mapped": chunk_to_doc_section_count
    }, ensure_ascii=False), flush=True)


# ── Phase 3: MENTIONS 엣지 (Document → Keyword) ──────────────────────────────


def _add_document_keyword_mentions(
    nodes: list[dict],
    edges: list[dict],
    source_path_texts: dict[str, str],
    node_ids: set[str],
    edge_counter: list[int],
) -> int:
    """
    문서 텍스트에서 키워드를 추출하고 Document → Keyword MENTIONS 엣지를 생성한다.

    Args:
        nodes: 노드 리스트
        edges: 엣지 리스트
        source_path_texts: source_path -> combined text 매핑
        node_ids: 노드 ID 집합
        edge_counter: 엣지 카운터

    Returns:
        생성된 MENTIONS 엣지 수
    """

    def add_edge(src: str, tgt: str, relation: str, **extra) -> bool:
        edge_id = f"{src}->{tgt}:{relation}"
        if any(e["id"] == edge_id for e in edges):
            return False
        edge_counter[0] += 1
        edges.append({"id": edge_id, "source": src, "target": tgt,
                      "relation": relation, **extra})
        return True

    # 문서 노드의 source_path → doc_node_id 매핑 구축
    source_path_to_doc_node: dict[str, str] = {}
    for node in nodes:
        if node.get("type") == "document":
            source_path = node.get("source_path", "").replace("\\", "/")
            if source_path:
                source_path_to_doc_node[source_path] = node["id"]

    mentions_count = 0

    for source_path, text in source_path_texts.items():
        # source_path로 문서 노드 찾기
        doc_node_id = source_path_to_doc_node.get(source_path)
        if not doc_node_id:
            continue

        if not text.strip():
            continue

        # 키워드 추출 (knowledge_graph.py의 extract_document_keywords 사용)
        found_keywords = extract_document_keywords(text)

        # 키워드별 MENTIONS 엣지 생성
        for keyword in found_keywords:
            keyword_node_id = f"keyword:{keyword}"
            if keyword_node_id in node_ids:
                if add_edge(doc_node_id, keyword_node_id, "MENTIONS"):
                    mentions_count += 1

    return mentions_count


# ── 유사 프로젝트 연결 (개선방안 5) ────────────────────────────────────────────────

def _add_similar_project_edges(
    nodes: list[dict],
    edges: list[dict],
    by_project: dict[str, list[dict]],
    edge_counter: list[int],
) -> None:
    """
    동일 발주기관 또는 유사 카테고리 구성을 가진 프로젝트 간 SIMILAR_PROJECT 엣지 생성.

    규칙:
    1. 동일 발주기관 프로젝트 → 연결 (weight 0.8)
    2. ISP → 구축/고도화 연계 패턴 → 연결 (weight 0.7)
    3. 유사 카테고리 구성 (60% 이상 일치) → 연결 (weight 0.5)
    """
    project_nodes = [n for n in nodes if n["type"] == "project"]
    if len(project_nodes) < 2:
        return

    # 프로젝트별 메타데이터 수집
    project_info: dict[str, dict] = {}
    for pn in project_nodes:
        proj_name = pn["label"]
        org = pn.get("organization", "")
        year = pn.get("year", "")
        docs = by_project.get(proj_name, [])
        categories = set(d["category"] for d in docs if d.get("category"))

        # 프로젝트 유형 추론 (ISP, 구축, 고도화 등)
        proj_type = ""
        proj_name_lower = proj_name.lower()
        if "isp" in proj_name_lower or "정보화전략" in proj_name_lower:
            proj_type = "isp"
        elif "ismp" in proj_name_lower or "마스터플랜" in proj_name_lower:
            proj_type = "ismp"
        elif "구축" in proj_name_lower or "개발" in proj_name_lower:
            proj_type = "build"
        elif "고도화" in proj_name_lower or "개선" in proj_name_lower:
            proj_type = "upgrade"
        elif "운영" in proj_name_lower or "유지보수" in proj_name_lower:
            proj_type = "operation"

        project_info[proj_name] = {
            "id": pn["id"],
            "organization": org,
            "year": year,
            "categories": categories,
            "proj_type": proj_type,
        }

    added_pairs: set[tuple[str, str]] = set()

    def add_similar_edge(p1: str, p2: str, reason: str, weight: float) -> None:
        pair = tuple(sorted([p1, p2]))
        if pair in added_pairs:
            return
        added_pairs.add(pair)
        edge_counter[0] += 1
        edges.append({
            "id": f"e{edge_counter[0]}",
            "source": project_info[p1]["id"],
            "target": project_info[p2]["id"],
            "relation": "similar_project",
            "label": reason,
            "weight": weight,
        })

    project_names = list(project_info.keys())

    for i, p1 in enumerate(project_names):
        info1 = project_info[p1]
        if p1 == "미분류":
            continue

        for p2 in project_names[i + 1:]:
            info2 = project_info[p2]
            if p2 == "미분류":
                continue

            # 1. 동일 발주기관 연결
            if info1["organization"] and info1["organization"] == info2["organization"]:
                add_similar_edge(p1, p2, f"동일기관({info1['organization']})", 0.8)
                continue

            # 2. ISP → 구축/고도화 연계 패턴
            if info1["proj_type"] == "isp" and info2["proj_type"] in ("build", "upgrade"):
                if info1["organization"] == info2["organization"]:
                    add_similar_edge(p1, p2, "ISP→구축연계", 0.7)
                    continue
            if info2["proj_type"] == "isp" and info1["proj_type"] in ("build", "upgrade"):
                if info1["organization"] == info2["organization"]:
                    add_similar_edge(p2, p1, "ISP→구축연계", 0.7)
                    continue

            # 3. 유사 카테고리 구성 (60% 이상 일치)
            if info1["categories"] and info2["categories"]:
                intersection = len(info1["categories"] & info2["categories"])
                union = len(info1["categories"] | info2["categories"])
                if union > 0:
                    similarity = intersection / union
                    if similarity >= 0.6:
                        add_similar_edge(p1, p2, f"유사구성({similarity:.0%})", 0.5)


# ── Output ────────────────────────────────────────────────────────────────────

def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build graph JSONL from indexed documents")
    p.add_argument("--snapshot", default="",
                   help="Snapshot name (auto-detect from active_index.json if omitted)")
    p.add_argument("--faiss-meta", default="",
                   help="Direct path to FAISS metadata JSONL (overrides --snapshot)")
    p.add_argument("--output-dir", default="",
                   help="Output directory (default: data/indexes/graph or data/indexes/graph/{source_id})")
    p.add_argument("--source-id", default="",
                   help="Document Source ID. Filters documents and outputs to source-specific directory.")
    p.add_argument("--rebuild", action="store_true",
                   help="Force rebuild (always rebuilds, kept for API compatibility)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    source_id = args.source_id or None

    # 출력 디렉토리 결정: --output-dir > source_id별 디렉토리 > 기본 디렉토리
    if args.output_dir:
        out_dir = Path(args.output_dir)
    else:
        out_dir = _get_graph_dir(source_id)

    # Resolve source
    faiss_meta_paths: list[Path] = []
    snapshot = args.snapshot or _read_active_snapshot()  # Phase 3용으로 미리 추출
    if args.faiss_meta:
        faiss_meta_paths = [Path(args.faiss_meta)]
    else:
        if snapshot:
            # 1차: 단일 통합 메타데이터 파일 시도
            candidate = FAISS_DIR / f"{snapshot}_ollama_metadata.jsonl"
            if candidate.exists():
                faiss_meta_paths = [candidate]
            else:
                # 2차: 카테고리별 메타데이터 파일 병합 (rfp, proposal, deliverable)
                category_files = sorted(FAISS_DIR.glob(f"{snapshot}_*_ollama_metadata.jsonl"))
                if category_files:
                    faiss_meta_paths = category_files
                    print(json.dumps({"info": f"카테고리별 FAISS 메타데이터 {len(category_files)}개 병합",
                                      "files": [f.name for f in category_files]}, ensure_ascii=False))

    # 진행률 출력: 데이터 로드 시작
    print(json.dumps({"progress": 10, "current": 1, "total": 5, "stage": "그래프 데이터 로드"}), flush=True)

    if faiss_meta_paths:
        # 여러 FAISS metadata 파일에서 문서 추출 (중복 제거)
        docs = []
        for meta_path in faiss_meta_paths:
            docs.extend(_docs_from_faiss_meta(meta_path))
        # document_id 기준 중복 제거
        seen_doc_ids: set[str] = set()
        unique_docs = []
        for doc in docs:
            doc_id = doc.get("document_id", "")
            if doc_id and doc_id not in seen_doc_ids:
                seen_doc_ids.add(doc_id)
                unique_docs.append(doc)
        docs = unique_docs
        source_type = "faiss_metadata"
        source_path = ", ".join(str(p) for p in faiss_meta_paths)
        print(json.dumps({"source": "faiss_metadata", "files": [p.name for p in faiss_meta_paths],
                          "doc_count": len(docs)}, ensure_ascii=False))
    else:
        docs = _docs_from_manifests()
        source_type = "manifest_csv"
        source_path = str(MANIFEST_DIR)
        print(json.dumps({"source": "manifest_csv", "dir": str(MANIFEST_DIR),
                          "doc_count": len(docs)}, ensure_ascii=False))

    if not docs:
        print(json.dumps({"error": "No documents found — run pipeline first"}))
        return 1

    # source_id 필터링 적용
    original_count = len(docs)
    if source_id:
        print(json.dumps({"progress": 25, "current": 2, "total": 5, "stage": f"source_id '{source_id}' 필터링"}), flush=True)
        docs = _filter_docs_by_source(docs, source_id)
        print(json.dumps({"source_id": source_id, "filtered_count": len(docs),
                          "original_count": original_count}, ensure_ascii=False))
        if not docs:
            print(json.dumps({"error": f"No documents found for source_id '{source_id}'"}))
            return 1

    allowed_doc_ids = {doc["document_id"] for doc in docs if doc.get("document_id")}
    allowed_source_paths = {
        doc.get("source_path", "").replace("\\", "/")
        for doc in docs
        if doc.get("source_path")
    }

    # Phase 2: 청크 데이터도 로드 (section_heading, page_no 추출용)
    chunks: list[dict] = []
    if faiss_meta_paths:
        for meta_path in faiss_meta_paths:
            chunks.extend(_chunks_from_faiss_meta(meta_path, allowed_doc_ids=allowed_doc_ids))
        print(json.dumps({"phase2": "filtered_chunks_loaded", "chunk_count": len(chunks)}, ensure_ascii=False))

    # 진행률 출력: 노드/엣지 생성
    print(json.dumps({"progress": 45, "current": 3, "total": 6, "stage": "그래프 노드/엣지 생성"}), flush=True)
    nodes, edges = _build_nodes_edges(docs)

    # DocumentSection 노드 및 CONTAINS_SECTION 엣지 추가
    mentions_count = 0
    if chunks:
        print(json.dumps({"progress": 50, "current": 4, "total": 8, "stage": "DocumentSection 노드/CONTAINS_SECTION 엣지 생성"}), flush=True)
        node_ids = {n["id"] for n in nodes}
        edge_counter = [max(int(e["id"].lstrip("e")) for e in edges if e["id"].startswith("e")) if edges else 0]
        _add_document_section_nodes_and_edges(nodes, edges, chunks, node_ids, edge_counter)

        # Phase 2: Chunk Section 노드 및 APPEARS_IN 엣지 추가
        print(json.dumps({"progress": 60, "current": 5, "total": 8, "stage": "Chunk Section 노드/APPEARS_IN 엣지 생성"}), flush=True)
        node_ids = {n["id"] for n in nodes}  # 새 노드 추가 후 갱신
        _add_chunk_section_nodes_and_edges(nodes, edges, chunks, node_ids, edge_counter)

        # Phase 3: MENTIONS 엣지 추가 (문서 텍스트 기반 키워드 추출)
        print(json.dumps({"progress": 70, "current": 5, "total": 7, "stage": "문서 텍스트 로드 및 MENTIONS 엣지 생성"}), flush=True)
        source_path_texts = _load_document_texts_by_source_path(allowed_source_paths=allowed_source_paths)
        if source_path_texts:
            node_ids = {n["id"] for n in nodes}  # 새 노드 추가 후 갱신
            mentions_count = _add_document_keyword_mentions(nodes, edges, source_path_texts, node_ids, edge_counter)
            print(json.dumps({"phase3": "mentions", "documents_with_text": len(source_path_texts),
                              "mentions_edges_created": mentions_count}, ensure_ascii=False))
        else:
            print(json.dumps({"warning": "No document texts loaded, skipping MENTIONS edges"}))

    nodes_path = out_dir / "graph_nodes.jsonl"
    edges_path = out_dir / "graph_edges.jsonl"
    manifest_path = out_dir / "graph_manifest.json"

    # 진행률 출력: 파일 저장
    print(json.dumps({"progress": 75, "current": 4, "total": 5, "stage": "그래프 파일 저장"}), flush=True)
    _write_jsonl(nodes_path, nodes)
    _write_jsonl(edges_path, edges)

    project_count  = sum(1 for n in nodes if n["type"] == "project")
    document_count = sum(1 for n in nodes if n["type"] == "document")
    document_section_count = sum(1 for n in nodes if n["type"] == "document_section")
    chunk_section_count = sum(1 for n in nodes if n["type"] == "chunk_section")
    contains_section_count = sum(1 for e in edges if e["relation"] == "CONTAINS_SECTION")
    appears_in_count = sum(1 for e in edges if e["relation"] == "APPEARS_IN")
    mentions_edge_count = sum(1 for e in edges if e["relation"] == "MENTIONS")

    # 진행률 출력: 완료
    print(json.dumps({"progress": 100, "current": 7, "total": 7, "stage": "그래프 빌드 완료"}), flush=True)

    manifest = {
        "built_at":       datetime.now().isoformat(timespec="seconds"),
        "source_id":      source_id or "all",
        "source_type":    source_type,
        "source_path":    source_path,
        "output_dir":     str(out_dir),
        "doc_count":      len(docs),
        "chunk_count":    len(chunks),
        "original_count": original_count if source_id else len(docs),
        "node_count":     len(nodes),
        "edge_count":     len(edges),
        "project_count":  project_count,
        "document_count": document_count,
        # DocumentSection 통계
        "document_section_count": document_section_count,
        "contains_section_edge_count": contains_section_count,
        # Phase 2: Chunk Section 통계
        "chunk_section_count": chunk_section_count,
        "appears_in_edge_count": appears_in_count,
        # Phase 3: MENTIONS 통계
        "mentions_edge_count": mentions_edge_count,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"graph_complete": True, **manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
