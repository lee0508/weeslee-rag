# -*- coding: utf-8 -*-
"""
Document Graph API.

GET  /api/graph/summary              — 전체 그래프 통계
GET  /api/graph/projects             — 프로젝트 노드 목록
GET  /api/graph/project/{name}       — 특정 프로젝트의 노드+엣지
GET  /api/graph/document/{doc_id}    — 특정 문서의 노드+연결 엣지
POST /api/graph/cytoscape/documents  — 검색 결과 문서 묶음의 Cytoscape 그래프
POST /api/graph/build                — build_graph_jsonl.py 실행
POST /api/graph/node                 — 노드 추가 (수동)
DELETE /api/graph/node/{node_id}     — 노드 삭제
POST /api/graph/edge                 — 엣지 추가 (수동)
DELETE /api/graph/edge/{edge_id}     — 엣지 삭제

Knowledge Graph 확장 API:
GET  /api/graph/query/organization   — 기관명으로 프로젝트 검색
GET  /api/graph/query/methodology    — 방법론으로 프로젝트 검색
POST /api/graph/query/technologies   — 기술 키워드로 프로젝트 검색
GET  /api/graph/query/similar        — 유사 프로젝트 검색
GET  /api/graph/query/document-chain — 문서 체인 조회
GET  /api/graph/statistics           — 노드/엣지 타입별 통계

GraphRAG Schema API (Phase 2):
GET  /api/graph/schema               — Graph Schema 조회 (Text2Cypher용)
GET  /api/graph/schema/json          — Graph Schema JSON 형식 조회
GET  /api/graph/schema/cypher        — Neo4j 제약조건 Cypher 조회
GET  /api/graph/schema/node-types    — 노드 유형 목록
GET  /api/graph/schema/relation-types — 관계 유형 목록

Graph Build API (Phase 3):
POST /api/graph/schema/build         — 스키마 기반 그래프 재빌드
GET  /api/graph/status               — 그래프 빌드 상태
GET  /api/graph/documents/{doc_id}/relations — 문서의 관계 목록
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import require_admin_token

router = APIRouter(prefix="/graph", tags=["Graph"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
GRAPH_DIR = DATA_DIR / "indexes" / "graph"
_BUILD_SCRIPT = PROJECT_ROOT / "backend" / "scripts" / "build_graph_jsonl.py"


def _get_graph_dir(source_id: Optional[str] = None) -> Path:
    """source_id별 Graph 디렉토리 반환."""
    if source_id:
        return DATA_DIR / "indexes" / "graph" / source_id
    return GRAPH_DIR


# ── File-based cache (invalidates when JSONL mtime changes) ──────────────────
# source_id별 캐시 지원
_caches: dict[str, dict] = {}


def _get_cache_key(source_id: Optional[str]) -> str:
    return source_id or "_default_"


_cache: dict = {"nodes": [], "edges": [], "mtime": 0.0}


def _load_graph(source_id: Optional[str] = None) -> dict:
    """source_id별 그래프 데이터 로드 및 캐시 반환."""
    cache_key = _get_cache_key(source_id)
    graph_dir = _get_graph_dir(source_id)

    if cache_key not in _caches:
        _caches[cache_key] = {"nodes": [], "edges": [], "mtime": 0.0}

    cache = _caches[cache_key]
    nodes_path = graph_dir / "graph_nodes.jsonl"
    edges_path = graph_dir / "graph_edges.jsonl"

    if not nodes_path.exists():
        cache["nodes"] = []
        cache["edges"] = []
        cache["mtime"] = 0.0
        return cache

    mtime = nodes_path.stat().st_mtime
    if mtime == cache["mtime"]:
        return cache

    nodes = [json.loads(line) for line in nodes_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    edges = []
    if edges_path.exists():
        edges = [json.loads(line) for line in edges_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    cache["nodes"] = nodes
    cache["edges"] = edges
    cache["mtime"] = mtime

    # 기본 캐시 업데이트 (source_id=None인 경우)
    if source_id is None:
        global _cache
        _cache = cache

    return cache


def _manifest(source_id: Optional[str] = None) -> dict:
    graph_dir = _get_graph_dir(source_id)
    p = graph_dir / "graph_manifest.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/summary")
async def graph_summary(source_id: Optional[str] = None):
    """그래프 전체 통계."""
    cache = _load_graph(source_id)
    m = _manifest(source_id)
    return {
        "source_id":      source_id or "all",
        "built_at":       m.get("built_at"),
        "source_type":    m.get("source_type"),
        "project_count":  sum(1 for n in cache["nodes"] if n.get("type") == "project"),
        "document_count": sum(1 for n in cache["nodes"] if n.get("type") == "document"),
        "edge_count":     len(cache["edges"]),
        "has_data":       bool(cache["nodes"]),
    }


@router.get("/projects")
async def list_projects(source_id: Optional[str] = None):
    """프로젝트 노드 목록."""
    cache = _load_graph(source_id)
    projects = [n for n in cache["nodes"] if n.get("type") == "project"]
    projects.sort(key=lambda n: n.get("year", "") or "", reverse=True)
    return {"source_id": source_id or "all", "projects": projects}


@router.get("/project/{project_name:path}")
async def get_project(project_name: str, source_id: Optional[str] = None):
    """특정 프로젝트의 노드와 엣지."""
    cache = _load_graph(source_id)
    proj_id = f"project:{project_name}"
    proj_node = next((n for n in cache["nodes"] if n["id"] == proj_id), None)
    if not proj_node:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_name}")

    # Collect directly connected nodes
    direct_edges = [e for e in cache["edges"]
                    if e["source"] == proj_id or e["target"] == proj_id]
    connected_ids = {proj_id}
    for e in direct_edges:
        connected_ids.add(e["source"])
        connected_ids.add(e["target"])

    # Add edges between those connected nodes (doc→category, doc→doc sequences)
    all_edges = list(direct_edges)
    seen_edge_ids = {e["id"] for e in all_edges}
    for e in cache["edges"]:
        if e["id"] not in seen_edge_ids and e["source"] in connected_ids:
            all_edges.append(e)
            connected_ids.add(e["target"])
            seen_edge_ids.add(e["id"])

    # Category nodes used by this project's docs
    cat_ids = {e["target"] for e in all_edges if e["relation"] == "has_category"}
    connected_ids.update(cat_ids)

    nodes = [n for n in cache["nodes"] if n["id"] in connected_ids]
    return {"source_id": source_id or "all", "project": proj_node, "nodes": nodes, "edges": all_edges}


@router.get("/document/{document_id}")
async def get_document(document_id: str, source_id: Optional[str] = None):
    """특정 문서 노드와 연결 엣지."""
    cache = _load_graph(source_id)
    doc_id = f"doc:{document_id}"
    doc_node = next((n for n in cache["nodes"] if n["id"] == doc_id), None)
    if not doc_node:
        raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")

    related_edges = [e for e in cache["edges"]
                     if e["source"] == doc_id or e["target"] == doc_id]
    connected_ids = {doc_id}
    for e in related_edges:
        connected_ids.add(e["source"])
        connected_ids.add(e["target"])
    nodes = [n for n in cache["nodes"] if n["id"] in connected_ids]
    return {"source_id": source_id or "all", "document": doc_node, "nodes": nodes, "edges": related_edges}


@router.post("/build", dependencies=[Depends(require_admin_token)])
async def build_graph(source_id: Optional[str] = None):
    """build_graph_jsonl.py 를 실행하여 그래프 데이터를 재생성.

    Args:
        source_id: Document Source ID. 지정 시 해당 source 문서만 처리.
    """
    if not _BUILD_SCRIPT.exists():
        raise HTTPException(status_code=500, detail="build_graph_jsonl.py not found")

    cmd = [sys.executable, str(_BUILD_SCRIPT)]
    if source_id:
        cmd += ["--source-id", source_id]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True, encoding="utf-8", timeout=300,
            cwd=str(PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Build timed out (300s)")

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr.strip() or "Build failed")

    # Invalidate cache for this source_id
    cache_key = _get_cache_key(source_id)
    if cache_key in _caches:
        _caches[cache_key]["mtime"] = 0.0
    _load_graph(source_id)

    for line in reversed(proc.stdout.strip().splitlines()):
        try:
            data = json.loads(line)
            if data.get("graph_complete"):
                data["source_id"] = source_id or "all"
                return data
        except Exception:
            pass

    return {"graph_complete": True, "source_id": source_id or "all", "output": proc.stdout.strip()[-500:]}


# ── CRUD Helper Functions ───────────────────────────────────────────────────


def _save_graph(source_id: Optional[str] = None) -> None:
    """JSONL 파일에 현재 캐시 내용 저장."""
    graph_dir = _get_graph_dir(source_id)
    cache_key = _get_cache_key(source_id)
    cache = _caches.get(cache_key, _cache)

    nodes_path = graph_dir / "graph_nodes.jsonl"
    edges_path = graph_dir / "graph_edges.jsonl"
    manifest_path = graph_dir / "graph_manifest.json"

    graph_dir.mkdir(parents=True, exist_ok=True)

    with open(nodes_path, "w", encoding="utf-8") as f:
        for node in cache["nodes"]:
            f.write(json.dumps(node, ensure_ascii=False) + "\n")

    with open(edges_path, "w", encoding="utf-8") as f:
        for edge in cache["edges"]:
            f.write(json.dumps(edge, ensure_ascii=False) + "\n")

    # manifest 업데이트
    manifest = _manifest(source_id)
    manifest["updated_at"] = datetime.now().isoformat()
    manifest["source_id"] = source_id or "all"
    manifest["project_count"] = sum(1 for n in cache["nodes"] if n.get("type") == "project")
    manifest["document_count"] = sum(1 for n in cache["nodes"] if n.get("type") == "document")
    manifest["edge_count"] = len(cache["edges"])
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # mtime 갱신
    cache["mtime"] = nodes_path.stat().st_mtime


# ── Request/Response Models ─────────────────────────────────────────────────


class NodeCreateRequest(BaseModel):
    node_type: str = Field(..., description="노드 타입: project, document, category")
    node_id: str = Field(..., description="노드 ID (예: doc:uuid, project:name)")
    label: str = Field(..., description="표시 라벨")
    project_name: Optional[str] = None
    category: Optional[str] = None
    organization: Optional[str] = None
    source_path: Optional[str] = None
    document_id: Optional[str] = None


class EdgeCreateRequest(BaseModel):
    source: str = Field(..., description="소스 노드 ID")
    target: str = Field(..., description="타겟 노드 ID")
    relation: str = Field(..., description="관계 타입: belongs_to, has_category, sequence 등")
    weight: float = 1.0


class DocumentGraphRequest(BaseModel):
    document_ids: List[str] = Field(default_factory=list, description="RAG 검색 결과 document_id 목록")
    source_id: Optional[str] = Field(default=None, description="Document Source ID")
    limit: int = Field(default=160, ge=20, le=500, description="최대 노드 수")


# ── CRUD Endpoints ──────────────────────────────────────────────────────────


@router.post("/node", dependencies=[Depends(require_admin_token)])
async def create_node(request: NodeCreateRequest):
    """그래프에 노드 추가."""
    _load_graph()

    # 중복 체크
    if any(n["id"] == request.node_id for n in _cache["nodes"]):
        raise HTTPException(status_code=409, detail=f"Node already exists: {request.node_id}")

    new_node = {
        "id": request.node_id,
        "type": request.node_type,
        "label": request.label,
    }
    if request.project_name:
        new_node["project_name"] = request.project_name
    if request.category:
        new_node["category"] = request.category
    if request.organization:
        new_node["organization"] = request.organization
    if request.source_path:
        new_node["source_path"] = request.source_path
    if request.document_id:
        new_node["document_id"] = request.document_id

    _cache["nodes"].append(new_node)
    _save_graph()

    return {"success": True, "node": new_node}


@router.delete("/node/{node_id:path}", dependencies=[Depends(require_admin_token)])
async def delete_node(node_id: str):
    """그래프에서 노드 삭제 (연결된 엣지도 함께 삭제)."""
    _load_graph()

    # 노드 찾기
    node_idx = next((i for i, n in enumerate(_cache["nodes"]) if n["id"] == node_id), None)
    if node_idx is None:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")

    deleted_node = _cache["nodes"].pop(node_idx)

    # 연결된 엣지 삭제
    edges_before = len(_cache["edges"])
    _cache["edges"] = [e for e in _cache["edges"]
                       if e["source"] != node_id and e["target"] != node_id]
    edges_deleted = edges_before - len(_cache["edges"])

    _save_graph()

    return {
        "success": True,
        "deleted_node": deleted_node,
        "edges_deleted": edges_deleted,
    }


@router.post("/edge", dependencies=[Depends(require_admin_token)])
async def create_edge(request: EdgeCreateRequest):
    """그래프에 엣지 추가."""
    _load_graph()

    # 소스/타겟 노드 존재 확인
    source_exists = any(n["id"] == request.source for n in _cache["nodes"])
    target_exists = any(n["id"] == request.target for n in _cache["nodes"])

    if not source_exists:
        raise HTTPException(status_code=404, detail=f"Source node not found: {request.source}")
    if not target_exists:
        raise HTTPException(status_code=404, detail=f"Target node not found: {request.target}")

    # 중복 엣지 체크
    edge_id = f"{request.source}->{request.target}:{request.relation}"
    if any(e["id"] == edge_id for e in _cache["edges"]):
        raise HTTPException(status_code=409, detail=f"Edge already exists: {edge_id}")

    new_edge = {
        "id": edge_id,
        "source": request.source,
        "target": request.target,
        "relation": request.relation,
        "weight": request.weight,
    }

    _cache["edges"].append(new_edge)
    _save_graph()

    return {"success": True, "edge": new_edge}


@router.delete("/edge/{edge_id:path}", dependencies=[Depends(require_admin_token)])
async def delete_edge(edge_id: str):
    """그래프에서 엣지 삭제."""
    _load_graph()

    edge_idx = next((i for i, e in enumerate(_cache["edges"]) if e["id"] == edge_id), None)
    if edge_idx is None:
        raise HTTPException(status_code=404, detail=f"Edge not found: {edge_id}")

    deleted_edge = _cache["edges"].pop(edge_idx)
    _save_graph()

    return {"success": True, "deleted_edge": deleted_edge}


@router.get("/edges")
async def list_edges(project_name: Optional[str] = None, source_id: Optional[str] = None, limit: int = 100):
    """엣지 목록 조회 (프로젝트별 필터 가능)."""
    cache = _load_graph(source_id)

    if project_name:
        proj_id = f"project:{project_name}"
        # 해당 프로젝트와 연결된 문서 ID 추출
        doc_ids = {n["id"] for n in cache["nodes"]
                   if n.get("type") == "document" and n.get("project_name") == project_name}
        doc_ids.add(proj_id)
        edges = [e for e in cache["edges"]
                 if e["source"] in doc_ids or e["target"] in doc_ids]
    else:
        edges = cache["edges"]

    return {"source_id": source_id or "all", "edges": edges[:limit], "total": len(edges)}


# ── 유사 프로젝트 검색 API (개선방안 5) ──────────────────────────────────────────────


@router.get("/similar/{project_name:path}")
async def get_similar_projects(project_name: str, top_k: int = 5):
    """유사 프로젝트 검색."""
    from app.services.graph_traversal import find_similar_projects, get_project_info

    similar = find_similar_projects(project_name, top_k=top_k)
    project_info = get_project_info(project_name)

    return {
        "project_name": project_name,
        "project_info": project_info,
        "similar_projects": similar,
    }


# ── Knowledge Graph 확장 API ─────────────────────────────────────────────────


class TechnologiesQueryRequest(BaseModel):
    technologies: List[str] = Field(..., description="기술 키워드 목록")
    match_all: bool = Field(True, description="True=AND, False=OR")


@router.get("/query/organization")
async def query_by_organization(
    org_name: str,
    category: Optional[str] = None,
):
    """
    기관명으로 프로젝트 검색 (동의어 지원).

    질문 예시: "한국수자원공사와 관련된 과거 수행사업은?"

    - org_name: 기관명 (K-water, 수공, 한국수자원공사 등 동의어 자동 확장)
    - category: 문서 카테고리 필터 (proposal, final_report 등)
    """
    from app.services.graph_traversal import query_by_organization as _query

    return _query(org_name, category_filter=category)


@router.get("/query/methodology")
async def query_by_methodology(method_name: str):
    """
    방법론으로 프로젝트 검색.

    질문 예시: "ISP 방법론이 적용된 사업들은?"

    - method_name: 방법론명 (ISP, ISMP, EA, DX 등)
    """
    from app.services.graph_traversal import query_by_methodology as _query

    return _query(method_name)


@router.post("/query/technologies")
async def query_by_technologies(request: TechnologiesQueryRequest):
    """
    기술 키워드로 프로젝트 검색.

    질문 예시: "AI OCR, RAG, 클라우드, 빅데이터가 포함된 제안서는?"

    - technologies: 기술 키워드 목록
    - match_all: True면 모든 기술 포함 (AND), False면 하나라도 포함 (OR)
    """
    from app.services.graph_traversal import query_by_technologies as _query

    return _query(request.technologies, match_all=request.match_all)


@router.get("/query/similar")
async def query_similar_projects(org_name: str, top_k: int = 5):
    """
    특정 기관의 사업과 유사한 프로젝트 검색.

    질문 예시: "경기주택도시공사 사업과 유사한 회사 문서는?"

    - org_name: 기관명
    - top_k: 반환할 유사 프로젝트 수
    """
    from app.services.graph_traversal import query_similar_to_organization as _query

    return _query(org_name, top_k=top_k)


@router.get("/query/document-chain")
async def query_document_chain(
    org_name: str,
    project_name: Optional[str] = None,
):
    """
    특정 기관의 제안서, 완료보고서, 발표자료 연결 조회.

    질문 예시: "특정 기관의 제안서, 완료보고서, 발표자료는 어떻게 연결되는가?"

    - org_name: 기관명
    - project_name: 특정 프로젝트명 (없으면 전체)
    """
    from app.services.graph_traversal import query_project_document_chain as _query

    return _query(org_name, project_name=project_name)


@router.get("/statistics")
async def get_statistics():
    """
    Knowledge Graph 전체 통계.

    노드/엣지 타입별 카운트 반환.
    """
    from app.services.graph_traversal import get_graph_statistics as _stats

    return _stats()


# ── Cytoscape 시각화 API ─────────────────────────────────────────────────────


def _to_cytoscape_elements(
    nodes: list[dict],
    edges: list[dict],
    center_id: Optional[str] = None,
) -> dict:
    """
    노드/엣지를 Cytoscape.js 포맷으로 변환.

    노드 타입별 색상/크기 지정, 엣지 관계별 스타일 지정.
    """
    NODE_COLORS = {
        "project": "#E8971F",
        "document": "#3b82f6",
        "category": "#6b7280",
        "organization": "#22c55e",
        "technology": "#8b5cf6",
        "methodology": "#ef4444",
        "domain": "#f59e0b",
    }
    NODE_SIZES = {
        "project": 70,
        "document": 44,
        "category": 32,
        "organization": 60,
        "technology": 50,
        "methodology": 50,
        "domain": 45,
    }

    cy_nodes = []
    for n in nodes:
        node_type = n.get("type", "unknown")
        is_center = center_id and n.get("id") == center_id
        cy_nodes.append({
            "data": {
                "id": n.get("id"),
                "label": n.get("label", n.get("id", "")),
                "type": node_type,
                "color": NODE_COLORS.get(node_type, "#6b7280"),
                "size": NODE_SIZES.get(node_type, 40),
                "isCenter": is_center,
                **{k: v for k, v in n.items() if k not in ("id", "label", "type")},
            }
        })

    cy_edges = []
    for e in edges:
        cy_edges.append({
            "data": {
                "id": e.get("id"),
                "source": e.get("source"),
                "target": e.get("target"),
                "relation": e.get("relation", ""),
                "label": e.get("label", e.get("relation", "")),
                "weight": e.get("weight", 1),
            }
        })

    return {
        "nodes": cy_nodes,
        "edges": cy_edges,
        "nodeCount": len(cy_nodes),
        "edgeCount": len(cy_edges),
    }


def _find_document_nodes(cache: dict, document_ids: list[str]) -> tuple[list[dict], list[str]]:
    node_by_id = {n.get("id"): n for n in cache["nodes"]}
    node_by_document_id = {
        str(n.get("document_id")): n
        for n in cache["nodes"]
        if n.get("type") == "document" and n.get("document_id")
    }

    found: list[dict] = []
    missing: list[str] = []
    seen: set[str] = set()

    for raw_id in document_ids:
        document_id = str(raw_id or "").strip()
        if not document_id:
            continue

        node = node_by_id.get(document_id)
        if not node and not document_id.startswith("doc:"):
            node = node_by_id.get(f"doc:{document_id}")
        if not node:
            node = node_by_document_id.get(document_id)

        if not node:
            missing.append(document_id)
            continue

        node_id = node.get("id")
        if node_id not in seen:
            seen.add(node_id)
            found.append(node)

    return found, missing


def _build_document_result_graph(cache: dict, document_ids: list[str], limit: int) -> dict:
    node_by_id = {n.get("id"): n for n in cache["nodes"]}
    document_nodes, missing = _find_document_nodes(cache, document_ids)
    result_doc_ids = {n.get("id") for n in document_nodes if n.get("id")}

    selected_nodes: dict[str, dict] = {}
    selected_edges: dict[str, dict] = {}

    def add_node(node_id: str) -> None:
        if node_id in selected_nodes:
            return
        node = node_by_id.get(node_id)
        if node and len(selected_nodes) < limit:
            selected_nodes[node_id] = node

    def add_edge(edge: dict) -> None:
        edge_id = edge.get("id") or f"{edge.get('source')}->{edge.get('target')}:{edge.get('relation', '')}"
        if edge_id not in selected_edges:
            selected_edges[edge_id] = edge

    for node in document_nodes:
        add_node(node["id"])

    project_ids: set[str] = set()
    for edge in cache["edges"]:
        source = edge.get("source")
        target = edge.get("target")
        if source not in result_doc_ids and target not in result_doc_ids:
            continue

        other_id = target if source in result_doc_ids else source
        add_node(other_id)
        add_edge(edge)

        other_node = node_by_id.get(other_id)
        if other_node and other_node.get("type") == "project":
            project_ids.add(other_id)

    for node in document_nodes:
        project_id = node.get("project_id")
        if project_id:
            add_node(project_id)
            project_ids.add(project_id)

    for edge in cache["edges"]:
        source = edge.get("source")
        target = edge.get("target")
        if source not in project_ids and target not in project_ids:
            continue

        other_id = target if source in project_ids else source
        other_node = node_by_id.get(other_id)
        if not other_node:
            continue
        if other_node.get("type") == "document" and other_id not in result_doc_ids:
            continue
        if other_node.get("type") == "project" and other_id not in project_ids:
            continue

        add_node(source)
        add_node(target)
        add_edge(edge)

    nodes = list(selected_nodes.values())
    node_ids = {n.get("id") for n in nodes}
    edges = [
        e for e in selected_edges.values()
        if e.get("source") in node_ids and e.get("target") in node_ids
    ]
    result = _to_cytoscape_elements(nodes, edges)
    for node in result["nodes"]:
        if node["data"].get("id") in result_doc_ids:
            node["data"]["isCenter"] = True
    result["requestedDocumentCount"] = len([d for d in document_ids if str(d or "").strip()])
    result["matchedDocumentCount"] = len(document_nodes)
    result["missingDocumentIds"] = missing
    return result


@router.post("/cytoscape/documents")
async def cytoscape_by_documents(request: DocumentGraphRequest):
    """
    RAG 검색 결과 문서 목록을 중심으로 검증용 Cytoscape 그래프를 반환.
    """
    source_id = (request.source_id or "").strip() or None
    cache = _load_graph(source_id)
    result = _build_document_result_graph(cache, request.document_ids, request.limit)
    used_source_id = source_id or "all"

    if source_id and result["matchedDocumentCount"] == 0:
        fallback_cache = _load_graph(None)
        fallback = _build_document_result_graph(fallback_cache, request.document_ids, request.limit)
        if fallback["matchedDocumentCount"] > 0:
            result = fallback
            used_source_id = "all"

    result["source_id"] = used_source_id
    result["graphPurpose"] = "query_result_validation"
    return result


@router.get("/cytoscape/organization")
async def cytoscape_by_organization(
    org_name: str,
    depth: int = 2,
    source_id: Optional[str] = None,
):
    """
    기관 중심 Cytoscape 그래프 반환.

    기관 → 프로젝트 → 문서/기술/방법론 관계를 시각화.
    """
    from app.services.knowledge_graph import normalize_organization

    cache = _load_graph(source_id)
    canonical = normalize_organization(org_name)
    org_id = f"org:{canonical}"

    visited_nodes: set[str] = set()
    visited_edges: set[str] = set()
    result_nodes = []
    result_edges = []

    # BFS로 depth만큼 탐색
    queue = [(org_id, 0)]
    visited_nodes.add(org_id)

    while queue:
        current_id, current_depth = queue.pop(0)
        node = next((n for n in cache["nodes"] if n["id"] == current_id), None)
        if node:
            result_nodes.append(node)

        if current_depth >= depth:
            continue

        # 연결된 엣지 탐색
        for edge in cache["edges"]:
            if edge["source"] == current_id or edge["target"] == current_id:
                edge_id = edge.get("id", f"{edge['source']}->{edge['target']}")
                if edge_id in visited_edges:
                    continue
                visited_edges.add(edge_id)
                result_edges.append(edge)

                # 다음 노드
                next_id = edge["target"] if edge["source"] == current_id else edge["source"]
                if next_id not in visited_nodes:
                    visited_nodes.add(next_id)
                    queue.append((next_id, current_depth + 1))

    result = _to_cytoscape_elements(result_nodes, result_edges, center_id=org_id)
    result["source_id"] = source_id or "all"
    return result


@router.get("/cytoscape/methodology")
async def cytoscape_by_methodology(method_name: str, depth: int = 2, source_id: Optional[str] = None):
    """
    방법론 중심 Cytoscape 그래프 반환.
    """
    from app.services.knowledge_graph import normalize_methodology

    cache = _load_graph(source_id)
    canonical = normalize_methodology(method_name)
    method_id = f"method:{canonical}"

    visited_nodes: set[str] = set()
    visited_edges: set[str] = set()
    result_nodes = []
    result_edges = []

    queue = [(method_id, 0)]
    visited_nodes.add(method_id)

    while queue:
        current_id, current_depth = queue.pop(0)
        node = next((n for n in cache["nodes"] if n["id"] == current_id), None)
        if node:
            result_nodes.append(node)

        if current_depth >= depth:
            continue

        for edge in cache["edges"]:
            if edge["source"] == current_id or edge["target"] == current_id:
                edge_id = edge.get("id", f"{edge['source']}->{edge['target']}")
                if edge_id in visited_edges:
                    continue
                visited_edges.add(edge_id)
                result_edges.append(edge)

                next_id = edge["target"] if edge["source"] == current_id else edge["source"]
                if next_id not in visited_nodes:
                    visited_nodes.add(next_id)
                    queue.append((next_id, current_depth + 1))

    result = _to_cytoscape_elements(result_nodes, result_edges, center_id=method_id)
    result["source_id"] = source_id or "all"
    return result


@router.get("/cytoscape/technology")
async def cytoscape_by_technology(tech_name: str, depth: int = 2, source_id: Optional[str] = None):
    """
    기술 중심 Cytoscape 그래프 반환.
    """
    from app.services.knowledge_graph import normalize_technology

    cache = _load_graph(source_id)
    canonical = normalize_technology(tech_name)
    tech_id = f"tech:{canonical}"

    visited_nodes: set[str] = set()
    visited_edges: set[str] = set()
    result_nodes = []
    result_edges = []

    queue = [(tech_id, 0)]
    visited_nodes.add(tech_id)

    while queue:
        current_id, current_depth = queue.pop(0)
        node = next((n for n in cache["nodes"] if n["id"] == current_id), None)
        if node:
            result_nodes.append(node)

        if current_depth >= depth:
            continue

        for edge in cache["edges"]:
            if edge["source"] == current_id or edge["target"] == current_id:
                edge_id = edge.get("id", f"{edge['source']}->{edge['target']}")
                if edge_id in visited_edges:
                    continue
                visited_edges.add(edge_id)
                result_edges.append(edge)

                next_id = edge["target"] if edge["source"] == current_id else edge["source"]
                if next_id not in visited_nodes:
                    visited_nodes.add(next_id)
                    queue.append((next_id, current_depth + 1))

    result = _to_cytoscape_elements(result_nodes, result_edges, center_id=tech_id)
    result["source_id"] = source_id or "all"
    return result


@router.get("/cytoscape/full")
async def cytoscape_full_graph(limit: int = 200, source_id: Optional[str] = None):
    """
    전체 Knowledge Graph를 Cytoscape 형식으로 반환 (노드 수 제한).
    """
    cache = _load_graph(source_id)

    # 노드 타입 우선순위 (중요한 노드 먼저)
    priority = {"organization": 0, "methodology": 1, "technology": 2, "project": 3, "domain": 4, "document": 5}
    sorted_nodes = sorted(cache["nodes"], key=lambda n: priority.get(n.get("type"), 99))
    limited_nodes = sorted_nodes[:limit]
    node_ids = {n["id"] for n in limited_nodes}

    # 해당 노드들만 연결하는 엣지
    limited_edges = [
        e for e in cache["edges"]
        if e["source"] in node_ids and e["target"] in node_ids
    ]

    result = _to_cytoscape_elements(limited_nodes, limited_edges)
    result["source_id"] = source_id or "all"
    return result


# ── GraphRAG Schema API (Phase 2) ─────────────────────────────────────────────


@router.get("/schema")
async def get_schema_text():
    """
    Text2Cypher가 참조할 Graph Schema를 텍스트로 반환.

    이 스키마는 LLM이 Cypher 쿼리를 생성할 때 참조하는 노드/관계 정의이다.
    """
    from app.models.graph_schema import generate_schema_text

    return {
        "schema": generate_schema_text(),
        "format": "text",
        "purpose": "text2cypher",
    }


@router.get("/schema/json")
async def get_schema_json():
    """
    Graph Schema를 JSON 형식으로 반환.

    노드 속성, 관계 source/target 규칙 등을 포함한다.
    """
    from app.models.graph_schema import generate_schema_json, NodeType, RelationType

    return {
        "schema": generate_schema_json(),
        "node_types": [nt.value for nt in NodeType],
        "relation_types": [rt.value for rt in RelationType],
        "format": "json",
    }


@router.get("/schema/cypher")
async def get_schema_cypher():
    """
    Neo4j 제약조건 및 인덱스 생성 Cypher 쿼리 반환.

    새 Graph DB 초기화 시 이 쿼리들을 실행하여 스키마를 설정한다.
    """
    from app.models.graph_schema import generate_cypher_constraints

    return {
        "cypher": generate_cypher_constraints(),
        "purpose": "neo4j_initialization",
    }


@router.get("/schema/node-types")
async def list_node_types():
    """
    Graph 노드 유형 목록 반환.

    각 노드 유형의 이름, 설명, 속성 목록을 포함한다.
    """
    from app.models.graph_schema import NodeType, generate_schema_json

    schema = generate_schema_json()
    node_types = []

    for nt in NodeType:
        node_info = schema["nodes"].get(nt.value, {})
        node_types.append({
            "type": nt.value,
            "description": node_info.get("description", ""),
            "properties": node_info.get("properties", []),
        })

    return {"node_types": node_types, "count": len(node_types)}


@router.get("/schema/relation-types")
async def list_relation_types():
    """
    Graph 관계 유형 목록 반환.

    각 관계 유형의 이름, source/target 노드 유형을 포함한다.
    """
    from app.models.graph_schema import RelationType, RELATION_RULES, NodeType

    relation_types = []

    for rt in RelationType:
        rule = RELATION_RULES.get(rt, {})
        source = rule.get("source")
        target = rule.get("target")

        # source/target이 리스트인 경우 처리
        if isinstance(source, list):
            source_types = [s.value for s in source]
        elif isinstance(source, NodeType):
            source_types = [source.value]
        else:
            source_types = []

        if isinstance(target, list):
            target_types = [t.value for t in target]
        elif isinstance(target, NodeType):
            target_types = [target.value]
        else:
            target_types = []

        relation_types.append({
            "type": rt.value,
            "source_types": source_types,
            "target_types": target_types,
        })

    return {"relation_types": relation_types, "count": len(relation_types)}


# ── Graph Build API (Phase 3) ─────────────────────────────────────────────────


class GraphBuildRequest(BaseModel):
    source_id: Optional[str] = Field(None, description="Document Source ID (없으면 전체)")
    rebuild: bool = Field(False, description="기존 그래프 삭제 후 재빌드")


@router.post("/schema/build", dependencies=[Depends(require_admin_token)])
async def build_graph_with_schema(request: GraphBuildRequest):
    """
    Phase 2 스키마 기반으로 그래프를 빌드한다.

    기존 build_graph_jsonl.py를 실행하되, 새 스키마 노드/관계 유형을 적용한다.
    """
    if not _BUILD_SCRIPT.exists():
        raise HTTPException(status_code=500, detail="build_graph_jsonl.py not found")

    cmd = [sys.executable, str(_BUILD_SCRIPT)]
    if request.source_id:
        cmd += ["--source-id", request.source_id]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True, encoding="utf-8", timeout=300,
            cwd=str(PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Build timed out (300s)")

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr.strip() or "Build failed")

    # 캐시 무효화
    cache_key = _get_cache_key(request.source_id)
    if cache_key in _caches:
        _caches[cache_key]["mtime"] = 0.0
    _load_graph(request.source_id)

    # 결과 파싱
    for line in reversed(proc.stdout.strip().splitlines()):
        try:
            data = json.loads(line)
            if data.get("graph_complete"):
                data["source_id"] = request.source_id or "all"
                data["schema_version"] = "phase2"
                return data
        except Exception:
            pass

    return {
        "graph_complete": True,
        "source_id": request.source_id or "all",
        "schema_version": "phase2",
        "output": proc.stdout.strip()[-500:],
    }


@router.get("/status")
async def get_graph_status(source_id: Optional[str] = None):
    """
    그래프 빌드 상태를 반환한다.

    - 마지막 빌드 시간
    - 노드/엣지 수
    - 스키마 버전
    - 각 노드 타입별 수
    """
    cache = _load_graph(source_id)
    m = _manifest(source_id)

    # 노드 타입별 카운트
    node_type_counts = {}
    for node in cache["nodes"]:
        node_type = node.get("type", "unknown")
        node_type_counts[node_type] = node_type_counts.get(node_type, 0) + 1

    # 관계 타입별 카운트
    relation_type_counts = {}
    for edge in cache["edges"]:
        relation = edge.get("relation", "unknown")
        relation_type_counts[relation] = relation_type_counts.get(relation, 0) + 1

    return {
        "source_id": source_id or "all",
        "status": "ready" if cache["nodes"] else "empty",
        "built_at": m.get("built_at"),
        "schema_version": "phase2" if m.get("built_at") else None,
        "node_count": len(cache["nodes"]),
        "edge_count": len(cache["edges"]),
        "node_type_counts": node_type_counts,
        "relation_type_counts": relation_type_counts,
        "has_data": bool(cache["nodes"]),
    }


@router.get("/documents/{document_id}/relations")
async def get_document_relations(document_id: str, source_id: Optional[str] = None):
    """
    특정 문서의 모든 관계를 반환한다.

    - 문서가 속한 프로젝트
    - 문서의 카테고리
    - 관련 문서 (동일 프로젝트, 유사 문서 등)
    - 연결된 키워드, 기술, 기관 등
    """
    cache = _load_graph(source_id)

    # document_id 형식 정규화
    doc_id = document_id if document_id.startswith("doc:") else f"doc:{document_id}"

    # 문서 노드 찾기
    doc_node = next((n for n in cache["nodes"] if n["id"] == doc_id), None)
    if not doc_node:
        # document_id 필드로 검색
        doc_node = next(
            (n for n in cache["nodes"]
             if n.get("type") == "document" and n.get("document_id") == document_id),
            None
        )
        if doc_node:
            doc_id = doc_node["id"]

    if not doc_node:
        raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")

    # 관련 엣지 수집
    outgoing_relations = []
    incoming_relations = []

    for edge in cache["edges"]:
        if edge["source"] == doc_id:
            target_node = next((n for n in cache["nodes"] if n["id"] == edge["target"]), None)
            outgoing_relations.append({
                "relation_type": edge.get("relation", ""),
                "target_id": edge["target"],
                "target_type": target_node.get("type") if target_node else "unknown",
                "target_label": target_node.get("label") if target_node else "",
                "weight": edge.get("weight", 1.0),
                "properties": {k: v for k, v in edge.items()
                              if k not in ("id", "source", "target", "relation", "weight")},
            })
        elif edge["target"] == doc_id:
            source_node = next((n for n in cache["nodes"] if n["id"] == edge["source"]), None)
            incoming_relations.append({
                "relation_type": edge.get("relation", ""),
                "source_id": edge["source"],
                "source_type": source_node.get("type") if source_node else "unknown",
                "source_label": source_node.get("label") if source_node else "",
                "weight": edge.get("weight", 1.0),
                "properties": {k: v for k, v in edge.items()
                              if k not in ("id", "source", "target", "relation", "weight")},
            })

    # 프로젝트 정보
    project_info = None
    project_id = doc_node.get("project_id")
    if project_id:
        project_node = next((n for n in cache["nodes"] if n["id"] == project_id), None)
        if project_node:
            project_info = {
                "id": project_node["id"],
                "name": project_node.get("label", ""),
                "year": project_node.get("year", ""),
                "organization": project_node.get("organization", ""),
            }

    # 동일 프로젝트 문서
    same_project_docs = []
    if project_id:
        for node in cache["nodes"]:
            if (node.get("type") == "document"
                and node.get("project_id") == project_id
                and node["id"] != doc_id):
                same_project_docs.append({
                    "id": node["id"],
                    "label": node.get("label", ""),
                    "category": node.get("category", ""),
                })

    return {
        "source_id": source_id or "all",
        "document": {
            "id": doc_id,
            "label": doc_node.get("label", ""),
            "category": doc_node.get("category", ""),
            "source_path": doc_node.get("source_path", ""),
        },
        "project": project_info,
        "outgoing_relations": outgoing_relations,
        "incoming_relations": incoming_relations,
        "same_project_documents": same_project_docs,
        "relation_count": len(outgoing_relations) + len(incoming_relations),
    }
