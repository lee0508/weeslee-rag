# -*- coding: utf-8 -*-
"""
Document Graph API.

GET  /api/graph/summary              — 전체 그래프 통계
GET  /api/graph/projects             — 프로젝트 노드 목록
GET  /api/graph/project/{name}       — 특정 프로젝트의 노드+엣지
GET  /api/graph/document/{doc_id}    — 특정 문서의 노드+연결 엣지
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
GRAPH_DIR = PROJECT_ROOT / "data" / "indexes" / "graph"
_BUILD_SCRIPT = PROJECT_ROOT / "backend" / "scripts" / "build_graph_jsonl.py"


# ── File-based cache (invalidates when JSONL mtime changes) ──────────────────

_cache: dict = {"nodes": [], "edges": [], "mtime": 0.0}


def _load_graph() -> None:
    nodes_path = GRAPH_DIR / "graph_nodes.jsonl"
    edges_path = GRAPH_DIR / "graph_edges.jsonl"
    if not nodes_path.exists():
        _cache["nodes"] = []
        _cache["edges"] = []
        _cache["mtime"] = 0.0
        return
    mtime = nodes_path.stat().st_mtime
    if mtime == _cache["mtime"]:
        return
    nodes = [json.loads(l) for l in nodes_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    edges = []
    if edges_path.exists():
        edges = [json.loads(l) for l in edges_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    _cache["nodes"] = nodes
    _cache["edges"] = edges
    _cache["mtime"] = mtime


def _manifest() -> dict:
    p = GRAPH_DIR / "graph_manifest.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/summary")
async def graph_summary():
    """그래프 전체 통계."""
    _load_graph()
    m = _manifest()
    return {
        "built_at":       m.get("built_at"),
        "source_type":    m.get("source_type"),
        "project_count":  sum(1 for n in _cache["nodes"] if n.get("type") == "project"),
        "document_count": sum(1 for n in _cache["nodes"] if n.get("type") == "document"),
        "edge_count":     len(_cache["edges"]),
        "has_data":       bool(_cache["nodes"]),
    }


@router.get("/projects")
async def list_projects():
    """프로젝트 노드 목록."""
    _load_graph()
    projects = [n for n in _cache["nodes"] if n.get("type") == "project"]
    projects.sort(key=lambda n: n.get("year", "") or "", reverse=True)
    return {"projects": projects}


@router.get("/project/{project_name:path}")
async def get_project(project_name: str):
    """특정 프로젝트의 노드와 엣지."""
    _load_graph()
    proj_id = f"project:{project_name}"
    proj_node = next((n for n in _cache["nodes"] if n["id"] == proj_id), None)
    if not proj_node:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_name}")

    # Collect directly connected nodes
    direct_edges = [e for e in _cache["edges"]
                    if e["source"] == proj_id or e["target"] == proj_id]
    connected_ids = {proj_id}
    for e in direct_edges:
        connected_ids.add(e["source"])
        connected_ids.add(e["target"])

    # Add edges between those connected nodes (doc→category, doc→doc sequences)
    all_edges = list(direct_edges)
    seen_edge_ids = {e["id"] for e in all_edges}
    for e in _cache["edges"]:
        if e["id"] not in seen_edge_ids and e["source"] in connected_ids:
            all_edges.append(e)
            connected_ids.add(e["target"])
            seen_edge_ids.add(e["id"])

    # Category nodes used by this project's docs
    cat_ids = {e["target"] for e in all_edges if e["relation"] == "has_category"}
    connected_ids.update(cat_ids)

    nodes = [n for n in _cache["nodes"] if n["id"] in connected_ids]
    return {"project": proj_node, "nodes": nodes, "edges": all_edges}


@router.get("/document/{document_id}")
async def get_document(document_id: str):
    """특정 문서 노드와 연결 엣지."""
    _load_graph()
    doc_id = f"doc:{document_id}"
    doc_node = next((n for n in _cache["nodes"] if n["id"] == doc_id), None)
    if not doc_node:
        raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")

    related_edges = [e for e in _cache["edges"]
                     if e["source"] == doc_id or e["target"] == doc_id]
    connected_ids = {doc_id}
    for e in related_edges:
        connected_ids.add(e["source"])
        connected_ids.add(e["target"])
    nodes = [n for n in _cache["nodes"] if n["id"] in connected_ids]
    return {"document": doc_node, "nodes": nodes, "edges": related_edges}


@router.post("/build", dependencies=[Depends(require_admin_token)])
async def build_graph():
    """build_graph_jsonl.py 를 실행하여 그래프 데이터를 재생성."""
    if not _BUILD_SCRIPT.exists():
        raise HTTPException(status_code=500, detail="build_graph_jsonl.py not found")
    try:
        proc = subprocess.run(
            [sys.executable, str(_BUILD_SCRIPT)],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Build timed out")

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr.strip() or "Build failed")

    # Invalidate cache
    _cache["mtime"] = 0.0
    _load_graph()

    for line in reversed(proc.stdout.strip().splitlines()):
        try:
            data = json.loads(line)
            if data.get("graph_complete"):
                return data
        except Exception:
            pass

    return {"graph_complete": True, "output": proc.stdout.strip()[-500:]}


# ── CRUD Helper Functions ───────────────────────────────────────────────────


def _save_graph() -> None:
    """JSONL 파일에 현재 캐시 내용 저장."""
    nodes_path = GRAPH_DIR / "graph_nodes.jsonl"
    edges_path = GRAPH_DIR / "graph_edges.jsonl"
    manifest_path = GRAPH_DIR / "graph_manifest.json"

    GRAPH_DIR.mkdir(parents=True, exist_ok=True)

    with open(nodes_path, "w", encoding="utf-8") as f:
        for node in _cache["nodes"]:
            f.write(json.dumps(node, ensure_ascii=False) + "\n")

    with open(edges_path, "w", encoding="utf-8") as f:
        for edge in _cache["edges"]:
            f.write(json.dumps(edge, ensure_ascii=False) + "\n")

    # manifest 업데이트
    manifest = _manifest()
    manifest["updated_at"] = datetime.now().isoformat()
    manifest["project_count"] = sum(1 for n in _cache["nodes"] if n.get("type") == "project")
    manifest["document_count"] = sum(1 for n in _cache["nodes"] if n.get("type") == "document")
    manifest["edge_count"] = len(_cache["edges"])
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # mtime 갱신
    _cache["mtime"] = nodes_path.stat().st_mtime


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
async def list_edges(project_name: Optional[str] = None, limit: int = 100):
    """엣지 목록 조회 (프로젝트별 필터 가능)."""
    _load_graph()

    if project_name:
        proj_id = f"project:{project_name}"
        # 해당 프로젝트와 연결된 문서 ID 추출
        doc_ids = {n["id"] for n in _cache["nodes"]
                   if n.get("type") == "document" and n.get("project_name") == project_name}
        doc_ids.add(proj_id)
        edges = [e for e in _cache["edges"]
                 if e["source"] in doc_ids or e["target"] in doc_ids]
    else:
        edges = _cache["edges"]

    return {"edges": edges[:limit], "total": len(edges)}


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
