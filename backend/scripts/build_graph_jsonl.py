# -*- coding: utf-8 -*-
"""
Build document graph JSONL from FAISS metadata (or manifest CSV fallback).

Output:
  data/indexes/graph/graph_nodes.jsonl
  data/indexes/graph/graph_edges.jsonl
  data/indexes/graph/graph_manifest.json

Node types:  project | document | category | organization | technology | methodology | domain
Edge types:  has_document | has_category | related_sequence | 발주 | 적용기술 | 사용방법론 | 관련도메인 | 동의어 | 유사기술
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
    ORGANIZATION_SYNONYMS,
    TECHNOLOGY_HIERARCHY,
    METHODOLOGY_SYNONYMS,
    DOMAIN_SYNONYMS,
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

    # 2. Technology 노드 생성 및 계층 엣지
    for tech_name, info in TECHNOLOGY_HIERARCHY.items():
        tech_id = f"tech:{tech_name}"
        add_node({
            "id": tech_id,
            "type": "technology",
            "label": tech_name,
            "synonyms": info.get("synonyms", []),
            "color": "#8b5cf6",
        })

        # 부모-자식 관계
        if info.get("parent"):
            parent_id = f"tech:{info['parent']}"
            add_edge(parent_id, tech_id, "유사기술", label="상위기술")

        for child in info.get("children", []):
            child_id = f"tech:{child}"
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

    # 5. 프로젝트에서 엔티티 추출 및 엣지 연결
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
    faiss_meta_path: Path | None = None
    if args.faiss_meta:
        faiss_meta_path = Path(args.faiss_meta)
    else:
        snapshot = args.snapshot or _read_active_snapshot()
        if snapshot:
            candidate = FAISS_DIR / f"{snapshot}_ollama_metadata.jsonl"
            if candidate.exists():
                faiss_meta_path = candidate

    # 진행률 출력: 데이터 로드 시작
    print(json.dumps({"progress": 10, "current": 1, "total": 5, "stage": "그래프 데이터 로드"}), flush=True)

    if faiss_meta_path and faiss_meta_path.exists():
        docs = _docs_from_faiss_meta(faiss_meta_path)
        source_type = "faiss_metadata"
        source_path = str(faiss_meta_path)
        print(json.dumps({"source": "faiss_metadata", "path": str(faiss_meta_path),
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

    # 진행률 출력: 노드/엣지 생성
    print(json.dumps({"progress": 45, "current": 3, "total": 5, "stage": "그래프 노드/엣지 생성"}), flush=True)
    nodes, edges = _build_nodes_edges(docs)

    nodes_path = out_dir / "graph_nodes.jsonl"
    edges_path = out_dir / "graph_edges.jsonl"
    manifest_path = out_dir / "graph_manifest.json"

    # 진행률 출력: 파일 저장
    print(json.dumps({"progress": 75, "current": 4, "total": 5, "stage": "그래프 파일 저장"}), flush=True)
    _write_jsonl(nodes_path, nodes)
    _write_jsonl(edges_path, edges)

    project_count  = sum(1 for n in nodes if n["type"] == "project")
    document_count = sum(1 for n in nodes if n["type"] == "document")

    # 진행률 출력: 완료
    print(json.dumps({"progress": 100, "current": 5, "total": 5, "stage": "그래프 빌드 완료"}), flush=True)

    manifest = {
        "built_at":       datetime.now().isoformat(timespec="seconds"),
        "source_id":      source_id or "all",
        "source_type":    source_type,
        "source_path":    source_path,
        "output_dir":     str(out_dir),
        "doc_count":      len(docs),
        "original_count": original_count if source_id else len(docs),
        "node_count":     len(nodes),
        "edge_count":     len(edges),
        "project_count":  project_count,
        "document_count": document_count,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"graph_complete": True, **manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
