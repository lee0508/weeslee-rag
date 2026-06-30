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

Text2Cypher API (Phase 4):
POST /api/graph/text2cypher/generate — 자연어 → Cypher 변환
POST /api/graph/text2cypher/execute  — Cypher 쿼리 실행
POST /api/graph/text2cypher/test     — 변환 + 실행 통합 테스트
GET  /api/graph/text2cypher/logs     — 쿼리 로그 조회

GraphRAG Agent API (Phase 6):
POST /api/graph/agent/query          — Agent 질문 처리 (자동 수정 루프 + FAISS fallback)
GET  /api/graph/agent/schema         — Agent가 사용하는 스키마 요약
POST /api/graph/agent/search         — FAISS 직접 검색 (fallback 테스트용)

LPG GraphRAG API (Phase 8) - 4-layer RAG 시스템:
GET  /api/graph/lpg/status           — LPG 시스템 상태
GET  /api/graph/lpg/schema           — LPG 스키마 조회
POST /api/graph/lpg/route            — 쿼리 라우팅 (검색 레이어 결정)
GET  /api/graph/lpg/nodes            — LPG 노드 목록 조회
GET  /api/graph/lpg/node/{node_id}   — 특정 노드 상세 및 이웃 조회
GET  /api/graph/lpg/document/{doc_id}/context — 문서 전체 컨텍스트 조회
POST /api/graph/lpg/related-documents — 관련 문서 검색
POST /api/graph/lpg/subgraph         — 서브그래프 추출 (시각화용)
GET  /api/graph/lpg/path             — 두 노드 간 경로 찾기
GET  /api/graph/lpg/ontology/terms   — 온톨로지 용어 목록
POST /api/graph/lpg/expand-terms     — 온톨로지 기반 용어 확장
POST /api/graph/lpg/build/nodes      — 노드 빌드 실행
POST /api/graph/lpg/build/edges      — 엣지 빌드 실행
POST /api/graph/lpg/reload           — 그래프 캐시 리로드
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
_DOCUMENT_PREFIXES = ("document", "doc")
_CATEGORY_PREFIXES = ("category", "cat")
_ORGANIZATION_PREFIXES = ("organization", "org")
_TECHNOLOGY_PREFIXES = ("technology", "tech")
_METHODOLOGY_PREFIXES = ("methodology", "method")


def _get_graph_dir(source_id: Optional[str] = None) -> Path:
    """source_id별 Graph 디렉토리 반환."""
    if source_id:
        return DATA_DIR / "indexes" / "graph" / source_id
    return GRAPH_DIR


def _prefixed_node_id(value: str, prefixes: tuple[str, ...]) -> str:
    return f"{prefixes[0]}:{value}"


def _prefixed_node_candidates(value: str, prefixes: tuple[str, ...]) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    if ":" in raw:
        head, tail = raw.split(":", 1)
        if head in prefixes:
            return [f"{prefix}:{tail}" for prefix in prefixes]
        return [raw]
    return [f"{prefix}:{raw}" for prefix in prefixes]


def _resolve_existing_node_id(node_by_id: dict[str, dict], value: str, prefixes: tuple[str, ...]) -> Optional[str]:
    for candidate in _prefixed_node_candidates(value, prefixes):
        if candidate in node_by_id:
            return candidate
    return None


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


def _graph_summary_from_manifest(manifest: dict) -> dict | None:
    """manifest에 집계값이 있으면 graph JSONL 전체 로드 없이 summary 반환."""
    if not manifest:
        return None
    node_count = int(manifest.get("node_count") or 0)
    edge_count = int(manifest.get("edge_count") or 0)
    project_count = int(manifest.get("project_count") or 0)
    document_count = int(manifest.get("document_count") or 0)
    if not any([node_count, edge_count, project_count, document_count]):
        return None
    return {
        "built_at": manifest.get("built_at"),
        "source_type": manifest.get("source_type"),
        "project_count": project_count,
        "document_count": document_count,
        "edge_count": edge_count,
        "has_data": node_count > 0,
    }


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/stats")
async def graph_stats(source_id: Optional[str] = None):
    """Graph Overview UI용 통계 (Frontend 호환)."""
    from app.services.graph_traversal import get_graph_statistics

    stats = get_graph_statistics()
    cache = _load_graph(source_id)
    manifest = _manifest(source_id)

    return {
        "total_nodes": stats["total_nodes"],
        "total_edges": stats["total_edges"],
        "node_counts": stats["node_types"],
        "last_build": manifest.get("built_at", "-"),
    }


@router.get("/summary")
async def graph_summary(source_id: Optional[str] = None):
    """그래프 전체 통계."""
    m = _manifest(source_id)
    manifest_summary = _graph_summary_from_manifest(m)
    if manifest_summary:
        return {
            "source_id": source_id or "all",
            **manifest_summary,
        }

    cache = _load_graph(source_id)
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
    node_by_id = {n.get("id"): n for n in cache["nodes"]}
    doc_id = _resolve_existing_node_id(node_by_id, document_id, _DOCUMENT_PREFIXES) or _prefixed_node_id(document_id, _DOCUMENT_PREFIXES)
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
    node_id: str = Field(..., description="노드 ID (예: document:uuid, doc:uuid, project:name)")
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
        if not node:
            resolved_id = _resolve_existing_node_id(node_by_id, document_id, _DOCUMENT_PREFIXES)
            if resolved_id:
                node = node_by_id.get(resolved_id)
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
    node_by_id = {n.get("id"): n for n in cache["nodes"]}
    org_id = _resolve_existing_node_id(node_by_id, canonical, _ORGANIZATION_PREFIXES) or _prefixed_node_id(canonical, _ORGANIZATION_PREFIXES)

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
    node_by_id = {n.get("id"): n for n in cache["nodes"]}
    method_id = _resolve_existing_node_id(node_by_id, canonical, _METHODOLOGY_PREFIXES) or _prefixed_node_id(canonical, _METHODOLOGY_PREFIXES)

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
    node_by_id = {n.get("id"): n for n in cache["nodes"]}
    tech_id = _resolve_existing_node_id(node_by_id, canonical, _TECHNOLOGY_PREFIXES) or _prefixed_node_id(canonical, _TECHNOLOGY_PREFIXES)

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
    node_by_id = {n.get("id"): n for n in cache["nodes"]}
    doc_id = _resolve_existing_node_id(node_by_id, document_id, _DOCUMENT_PREFIXES) or _prefixed_node_id(document_id, _DOCUMENT_PREFIXES)

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


# ── Text2Cypher API (Phase 4) ─────────────────────────────────────────────────


class Text2CypherGenerateRequest(BaseModel):
    question: str = Field(..., description="자연어 질문")
    model: Optional[str] = Field(None, description="LLM 모델 (기본값 사용 시 None)")
    temperature: float = Field(0.1, ge=0.0, le=1.0, description="생성 온도")


class Text2CypherExecuteRequest(BaseModel):
    cypher: str = Field(..., description="실행할 Cypher 쿼리")
    source_id: Optional[str] = Field(None, description="Document Source ID")


class Text2CypherTestRequest(BaseModel):
    question: str = Field(..., description="자연어 질문")
    model: Optional[str] = Field(None, description="LLM 모델")
    source_id: Optional[str] = Field(None, description="Document Source ID")
    save_log: bool = Field(True, description="로그 저장 여부")


@router.post("/text2cypher/generate", dependencies=[Depends(require_admin_token)])
async def text2cypher_generate(request: Text2CypherGenerateRequest):
    """
    자연어 질문을 Cypher 쿼리로 변환한다.

    LLM이 Graph Schema를 참조하여 Cypher 쿼리를 생성하고,
    Cypher Guard로 읽기 전용 여부를 검증한다.
    """
    from app.services.text2cypher_service import get_text2cypher_service

    service = get_text2cypher_service()
    result = await service.generate_cypher(
        question=request.question,
        model=request.model,
        temperature=request.temperature,
    )

    return {
        "success": result.success,
        "question": result.question,
        "cypher": result.cypher,
        "validation": {
            "is_valid": result.validation.is_valid if result.validation else None,
            "message": result.validation.message if result.validation else None,
            "blocked_keyword": result.validation.blocked_keyword if result.validation else None,
        } if result.validation else None,
        "error": result.error,
        "model": result.model,
        "generation_time_ms": result.generation_time_ms,
        "timestamp": result.timestamp,
    }


@router.post("/text2cypher/execute", dependencies=[Depends(require_admin_token)])
async def text2cypher_execute(request: Text2CypherExecuteRequest):
    """
    Cypher 쿼리를 실행한다.

    현재는 JSONL 기반 그래프 데이터에서 시뮬레이션 실행한다.
    향후 Neo4j 연동 시 실제 쿼리 실행으로 전환 가능하다.
    """
    from app.services.text2cypher_service import get_text2cypher_service
    from app.services.cypher_guard import validate_cypher

    # 먼저 Cypher Guard로 검증
    validation = validate_cypher(request.cypher)
    if not validation.is_valid:
        return {
            "success": False,
            "cypher": request.cypher,
            "error": validation.message,
            "blocked_keyword": validation.blocked_keyword,
        }

    # 그래프 데이터 로드
    cache = _load_graph(request.source_id)

    # 쿼리 실행
    service = get_text2cypher_service()
    result = service.execute_cypher_on_jsonl(
        cypher=validation.sanitized_query or request.cypher,
        nodes=cache["nodes"],
        edges=cache["edges"],
    )

    return {
        "success": result.success,
        "cypher": result.cypher,
        "results": result.results,
        "row_count": result.row_count,
        "execution_time_ms": result.execution_time_ms,
        "error": result.error,
        "source_id": request.source_id or "all",
    }


@router.post("/text2cypher/test", dependencies=[Depends(require_admin_token)])
async def text2cypher_test(request: Text2CypherTestRequest):
    """
    Text2Cypher 통합 테스트: 질문 → Cypher 생성 → 실행 → 결과 반환.

    전체 파이프라인을 한 번에 테스트하고 로그를 저장한다.
    """
    from app.services.text2cypher_service import get_text2cypher_service
    import time

    service = get_text2cypher_service()
    start_time = time.time()

    # 1. Cypher 생성
    gen_result = await service.generate_cypher(
        question=request.question,
        model=request.model,
    )

    if not gen_result.success:
        # 로그 저장
        if request.save_log:
            service.save_log(
                question=request.question,
                cypher=gen_result.cypher,
                success=False,
                error=gen_result.error,
            )

        return {
            "success": False,
            "stage": "generation",
            "question": request.question,
            "cypher": gen_result.cypher,
            "error": gen_result.error,
            "model": gen_result.model,
            "generation_time_ms": gen_result.generation_time_ms,
        }

    # 2. Cypher 실행
    cache = _load_graph(request.source_id)
    exec_result = service.execute_cypher_on_jsonl(
        cypher=gen_result.cypher,
        nodes=cache["nodes"],
        edges=cache["edges"],
    )

    total_time_ms = int((time.time() - start_time) * 1000)

    # 로그 저장
    if request.save_log:
        service.save_log(
            question=request.question,
            cypher=gen_result.cypher,
            success=exec_result.success,
            error=exec_result.error,
            results_count=exec_result.row_count,
            execution_time_ms=total_time_ms,
        )

    return {
        "success": exec_result.success,
        "stage": "complete",
        "question": request.question,
        "cypher": gen_result.cypher,
        "results": exec_result.results,
        "row_count": exec_result.row_count,
        "model": gen_result.model,
        "generation_time_ms": gen_result.generation_time_ms,
        "execution_time_ms": exec_result.execution_time_ms,
        "total_time_ms": total_time_ms,
        "source_id": request.source_id or "all",
        "error": exec_result.error,
    }


@router.get("/text2cypher/logs", dependencies=[Depends(require_admin_token)])
async def text2cypher_logs(
    date: Optional[str] = None,
    limit: int = 100,
    success_only: bool = False,
    error_only: bool = False,
):
    """
    Text2Cypher 쿼리 로그 조회.

    - date: YYYYMMDD 형식 (없으면 최근 로그)
    - limit: 최대 로그 수
    - success_only: 성공 로그만
    - error_only: 실패 로그만
    """
    from app.services.text2cypher_service import get_text2cypher_service

    service = get_text2cypher_service()
    logs = service.get_logs(
        date=date,
        limit=limit,
        success_only=success_only,
        error_only=error_only,
    )

    return {
        "logs": logs,
        "count": len(logs),
        "filters": {
            "date": date,
            "success_only": success_only,
            "error_only": error_only,
        },
    }


# ── GraphRAG Agent API (Phase 6) ───────────────────────────────────────────────


class AgentQueryRequest(BaseModel):
    question: str = Field(..., description="자연어 질문")
    source_id: Optional[str] = Field(None, description="Document Source ID")
    enable_fallback: bool = Field(True, description="FAISS fallback 활성화")
    top_k: int = Field(10, ge=1, le=50, description="최대 결과 수")


class AgentSearchRequest(BaseModel):
    query: str = Field(..., description="검색 쿼리")
    source_id: Optional[str] = Field(None, description="Document Source ID")
    top_k: int = Field(10, ge=1, le=50, description="최대 결과 수")
    category_filter: Optional[str] = Field(None, description="카테고리 필터")
    organization_filter: Optional[str] = Field(None, description="기관 필터")


@router.post("/agent/query")
async def agent_query(request: AgentQueryRequest):
    """
    GraphRAG Agent 질문 처리.

    자연어 질문을 받아서:
    1. 질문 유형 분석
    2. Cypher 쿼리 생성 및 실행
    3. 결과가 없거나 오류 시 자동 수정 (최대 2회)
    4. 실패 시 FAISS 검색 fallback

    반환값에는 실행 단계별 상세 정보가 포함된다.
    """
    from app.agents.graphrag_agent import get_graphrag_agent

    agent = get_graphrag_agent(
        source_id=request.source_id,
        enable_fallback=request.enable_fallback,
    )

    response = await agent.process(request.question)

    return {
        "success": response.status.value in ("success", "fallback"),
        "status": response.status.value,
        "question": response.question,
        "question_type": response.question_type.value,
        "results": response.results,
        "result_count": response.result_count,
        "cypher_queries": response.cypher_queries,
        "steps": [
            {
                "step_name": step.step_name,
                "status": step.status,
                "details": step.details,
                "timestamp": step.timestamp,
            }
            for step in response.steps
        ],
        "fallback_used": response.fallback_used,
        "fallback_results": response.fallback_results,
        "fallback_result_count": len(response.fallback_results),
        "error": response.error,
        "total_time_ms": response.total_time_ms,
        "source_id": request.source_id or "all",
    }


@router.get("/agent/schema")
async def agent_schema():
    """
    GraphRAG Agent가 사용하는 스키마 요약.

    노드 유형, 관계 유형, 스키마 텍스트를 반환한다.
    """
    from app.agents.graphrag_agent import get_graphrag_agent

    agent = get_graphrag_agent()
    summary = agent.get_schema_summary()

    return {
        "node_types": summary["node_types"],
        "relation_types": summary["relation_types"],
        "schema_text": summary["schema_text"],
        "agent_config": {
            "max_retries": agent.MAX_RETRIES,
            "enable_fallback": agent.enable_fallback,
        },
    }


@router.post("/agent/search")
async def agent_search(request: AgentSearchRequest):
    """
    FAISS 직접 검색 (Agent fallback 테스트용).

    GraphRAG Agent의 FAISS fallback 기능을 직접 테스트할 수 있다.
    벡터 기반 유사도 검색을 수행한다.
    """
    from app.services.faiss_search_service import get_faiss_search_service

    service = get_faiss_search_service(source_id=request.source_id)
    response = service.search(
        query=request.query,
        top_k=request.top_k,
        category_filter=request.category_filter,
        organization_filter=request.organization_filter,
    )

    return {
        "success": response.success,
        "query": response.query,
        "results": [
            {
                "rank": r.rank,
                "score": r.score,
                "chunk_id": r.chunk_id,
                "document_id": r.document_id,
                "category": r.category,
                "organization": r.organization,
                "file_name": r.file_name,
                "text_preview": r.text_preview,
            }
            for r in response.results
        ],
        "result_count": response.result_count,
        "search_time_ms": response.search_time_ms,
        "embedding_provider": response.embedding_provider,
        "error": response.error,
        "source_id": request.source_id or "all",
    }


@router.get("/agent/stats")
async def agent_stats(source_id: Optional[str] = None):
    """
    GraphRAG Agent 통계.

    Graph 및 FAISS 인덱스 상태를 반환한다.
    """
    from app.services.faiss_search_service import get_faiss_search_service
    from app.services.graph_query_service import get_graph_query_service

    faiss_service = get_faiss_search_service(source_id)
    graph_service = get_graph_query_service(source_id)

    # Graph 통계
    cache = _load_graph(source_id)
    graph_stats = {
        "node_count": len(cache["nodes"]),
        "edge_count": len(cache["edges"]),
        "has_data": bool(cache["nodes"]),
    }

    # FAISS 통계
    faiss_stats = faiss_service.get_index_stats()

    return {
        "source_id": source_id or "all",
        "graph": graph_stats,
        "faiss": faiss_stats,
        "agent_ready": graph_stats["has_data"] or faiss_stats["loaded"],
    }


# ── LPG GraphRAG API (Phase 8) ─────────────────────────────────────────────────
# 4-layer RAG 시스템을 위한 LPG(Labeled Property Graph) 기반 API
# 1차: FAISS Index → 2차: Ontology → 3차: GraphRAG → 4차: LLM Wiki

ONTOLOGY_DIR = DATA_DIR / "ontology"
_lpg_graph = None  # LPGGraph 싱글톤


def _get_lpg_graph():
    """LPG 그래프 싱글톤 로드."""
    global _lpg_graph

    nodes_path = ONTOLOGY_DIR / "graph_nodes.jsonl"
    edges_path = ONTOLOGY_DIR / "graph_edges.jsonl"
    schema_path = ONTOLOGY_DIR / "schema.json"

    if not nodes_path.exists():
        return None

    if _lpg_graph is None:
        from scripts.lpg_graph import LPGGraph
        _lpg_graph = LPGGraph()
        if schema_path.exists():
            _lpg_graph.load_schema(schema_path)
        _lpg_graph.load_from_jsonl(nodes_path, edges_path)

    return _lpg_graph


def _get_query_router():
    """Query Router 싱글톤 로드."""
    from scripts.query_router import QueryRouter
    terms_path = ONTOLOGY_DIR / "terms.jsonl"
    return QueryRouter(terms_path=terms_path if terms_path.exists() else None)


class LPGQueryRequest(BaseModel):
    query: str = Field(..., description="자연어 검색 쿼리")
    top_k: int = Field(10, ge=1, le=50, description="최대 결과 수")
    layers: Optional[List[int]] = Field(None, description="사용할 검색 레이어 (1=FAISS, 2=Ontology, 3=GraphRAG, 4=Wiki)")


class LPGSubgraphRequest(BaseModel):
    seed_node_ids: List[str] = Field(..., description="시드 노드 ID 목록")
    depth: int = Field(2, ge=1, le=5, description="탐색 깊이")
    edge_types: Optional[List[str]] = Field(None, description="필터링할 엣지 타입")
    max_nodes: int = Field(100, ge=10, le=500, description="최대 노드 수")


class LPGRelatedDocsRequest(BaseModel):
    document_id: str = Field(..., description="문서 ID")
    relation_types: Optional[List[str]] = Field(None, description="관계 타입 필터")
    max_results: int = Field(10, ge=1, le=50, description="최대 결과 수")


@router.get("/lpg/status")
async def lpg_status():
    """
    LPG GraphRAG 시스템 상태.

    - 노드/엣지 통계
    - 스키마 로드 상태
    - 온톨로지 용어 수
    """
    graph = _get_lpg_graph()
    if not graph:
        return {
            "status": "not_initialized",
            "message": "LPG graph files not found. Run build_graph_nodes.py and build_graph_edges.py first.",
            "nodes_path": str(ONTOLOGY_DIR / "graph_nodes.jsonl"),
            "edges_path": str(ONTOLOGY_DIR / "graph_edges.jsonl"),
        }

    stats = graph.get_statistics()
    terms_path = ONTOLOGY_DIR / "terms.jsonl"
    terms_count = 0
    if terms_path.exists():
        with open(terms_path, 'r', encoding='utf-8') as f:
            terms_count = sum(1 for line in f if line.strip())

    return {
        "status": "ready",
        "total_nodes": stats["total_nodes"],
        "total_edges": stats["total_edges"],
        "node_types": stats["node_types"],
        "edge_types": stats["edge_types"],
        "schema_loaded": graph.schema is not None,
        "ontology_terms": terms_count,
        "loaded_at": stats["loaded_at"],
    }


@router.get("/lpg/schema")
async def lpg_schema():
    """
    LPG 스키마 조회.

    노드 타입, 엣지 타입, ID 규칙 등을 반환한다.
    """
    schema_path = ONTOLOGY_DIR / "schema.json"
    if not schema_path.exists():
        raise HTTPException(status_code=404, detail="LPG schema not found")

    with open(schema_path, 'r', encoding='utf-8') as f:
        schema = json.load(f)

    return {
        "version": schema.get("version", "1.0"),
        "node_types": list(schema.get("node_types", {}).keys()),
        "edge_types": list(schema.get("edge_types", {}).keys()),
        "schema": schema,
    }


@router.post("/lpg/route")
async def lpg_route_query(request: LPGQueryRequest):
    """
    쿼리 라우팅: 자연어 쿼리를 분석하여 최적의 검색 레이어를 결정한다.

    반환값:
    - query_type: factual, conceptual, relational, summary
    - layers: 검색 레이어 순서 (1=FAISS, 2=Ontology, 3=GraphRAG, 4=Wiki)
    - extracted_entities: 추출된 엔티티
    - expanded_terms: 확장된 검색어
    - filters: 검색 필터
    """
    router_instance = _get_query_router()
    result = router_instance.route(request.query)
    return router_instance.to_dict(result)


@router.get("/lpg/nodes")
async def lpg_list_nodes(
    node_type: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
):
    """
    LPG 노드 목록 조회.

    - node_type: 노드 타입 필터 (Document, Project, Organization 등)
    - search: 검색어 (라벨, 속성에서 검색)
    - limit: 최대 반환 수
    """
    graph = _get_lpg_graph()
    if not graph:
        raise HTTPException(status_code=503, detail="LPG graph not initialized")

    if search:
        node_types = [node_type] if node_type else None
        nodes = graph.search_nodes(search, node_types=node_types, limit=limit)
    elif node_type:
        nodes = graph.get_nodes_by_type(node_type)[:limit]
    else:
        nodes = list(graph.nodes.values())[:limit]

    return {
        "nodes": nodes,
        "count": len(nodes),
        "filters": {"node_type": node_type, "search": search},
    }


@router.get("/lpg/node/{node_id:path}")
async def lpg_get_node(node_id: str):
    """
    특정 노드 상세 정보 및 이웃 노드 조회.
    """
    graph = _get_lpg_graph()
    if not graph:
        raise HTTPException(status_code=503, detail="LPG graph not initialized")

    node = graph.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")

    neighbors = graph.get_neighbors(node_id)

    return {
        "node": node,
        "neighbors": neighbors,
        "neighbor_count": len(neighbors),
    }


@router.get("/lpg/document/{doc_id}/context")
async def lpg_document_context(doc_id: str):
    """
    문서의 전체 컨텍스트 조회.

    프로젝트, 카테고리, 조직, 기술, 방법론, 도메인, 관련 문서 정보를 포함한다.
    """
    graph = _get_lpg_graph()
    if not graph:
        raise HTTPException(status_code=503, detail="LPG graph not initialized")

    resolved_doc_id = _resolve_existing_node_id(graph.nodes, doc_id, _DOCUMENT_PREFIXES)
    if resolved_doc_id:
        doc_id = resolved_doc_id
    else:
        doc_id = _prefixed_node_id(doc_id, _DOCUMENT_PREFIXES)

    context = graph.get_document_context(doc_id)
    if not context.get("document"):
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    return context


@router.post("/lpg/related-documents")
async def lpg_related_documents(request: LPGRelatedDocsRequest):
    """
    특정 문서와 관련된 문서 목록 조회.

    SIMILAR_TO, RELATED_SEQUENCE, 동일 프로젝트 문서 등을 반환한다.
    """
    graph = _get_lpg_graph()
    if not graph:
        raise HTTPException(status_code=503, detail="LPG graph not initialized")

    doc_id = request.document_id
    resolved_doc_id = _resolve_existing_node_id(graph.nodes, doc_id, _DOCUMENT_PREFIXES)
    if resolved_doc_id:
        doc_id = resolved_doc_id
    else:
        doc_id = _prefixed_node_id(doc_id, _DOCUMENT_PREFIXES)

    if doc_id not in graph.nodes:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    related = graph.find_related_documents(
        doc_id,
        relation_types=request.relation_types,
        max_results=request.max_results,
    )

    return {
        "document_id": doc_id,
        "related_documents": related,
        "count": len(related),
    }


@router.post("/lpg/subgraph")
async def lpg_subgraph(request: LPGSubgraphRequest):
    """
    시드 노드들로부터 서브그래프 추출.

    vis.js/Cytoscape 시각화에 사용할 수 있는 형식으로 반환한다.
    """
    graph = _get_lpg_graph()
    if not graph:
        raise HTTPException(status_code=503, detail="LPG graph not initialized")

    subgraph = graph.get_subgraph(
        seed_node_ids=request.seed_node_ids,
        depth=request.depth,
        edge_types=request.edge_types,
        max_nodes=request.max_nodes,
    )

    # vis.js 형식으로 변환
    vis_format = graph.to_vis_format(subgraph)

    return {
        "subgraph": subgraph,
        "vis_format": vis_format,
        "seed_node_ids": request.seed_node_ids,
    }


@router.get("/lpg/path")
async def lpg_find_path(
    start_id: str,
    end_id: str,
    max_depth: int = 5,
    edge_types: Optional[str] = None,
):
    """
    두 노드 사이의 최단 경로 찾기.

    - start_id: 시작 노드 ID
    - end_id: 종료 노드 ID
    - max_depth: 최대 탐색 깊이
    - edge_types: 엣지 타입 필터 (쉼표 구분)
    """
    graph = _get_lpg_graph()
    if not graph:
        raise HTTPException(status_code=503, detail="LPG graph not initialized")

    edge_type_list = edge_types.split(",") if edge_types else None
    path = graph.find_path(start_id, end_id, max_depth=max_depth, edge_types=edge_type_list)

    if not path:
        return {
            "found": False,
            "start_id": start_id,
            "end_id": end_id,
            "path": None,
            "message": f"No path found within depth {max_depth}",
        }

    return {
        "found": True,
        "start_id": start_id,
        "end_id": end_id,
        "path": path,
        "path_length": len(path) - 1,
    }


@router.get("/lpg/ontology/terms")
async def lpg_ontology_terms(
    term_type: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
):
    """
    온톨로지 용어 목록 조회.

    - term_type: 용어 타입 필터 (organization, technology, methodology, domain, category)
    - search: 검색어
    - limit: 최대 반환 수
    """
    terms_path = ONTOLOGY_DIR / "terms.jsonl"
    if not terms_path.exists():
        raise HTTPException(status_code=404, detail="Ontology terms file not found")

    terms = []
    with open(terms_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            term = json.loads(line)

            # 타입 필터
            if term_type and term.get("type") != term_type:
                continue

            # 검색 필터
            if search:
                search_lower = search.lower()
                label = term.get("label", "").lower()
                synonyms = [s.lower() for s in term.get("synonyms", [])]
                if search_lower not in label and not any(search_lower in s for s in synonyms):
                    continue

            terms.append(term)

            if len(terms) >= limit:
                break

    return {
        "terms": terms,
        "count": len(terms),
        "filters": {"term_type": term_type, "search": search},
    }


@router.post("/lpg/expand-terms")
async def lpg_expand_terms(term_ids: List[str]):
    """
    온톨로지 기반 용어 확장.

    입력된 용어 ID들의 부모/자식 용어와 동의어를 함께 반환한다.
    """
    graph = _get_lpg_graph()
    if not graph:
        raise HTTPException(status_code=503, detail="LPG graph not initialized")

    expanded = graph.expand_by_ontology(term_ids, include_parents=True)

    return {
        "original_terms": term_ids,
        "expanded_terms": expanded,
        "expansion_count": len(expanded) - len(term_ids),
    }


@router.post("/lpg/build/nodes", dependencies=[Depends(require_admin_token)])
async def lpg_build_nodes():
    """
    LPG 노드 빌드 스크립트 실행.
    """
    script_path = PROJECT_ROOT / "backend" / "scripts" / "build_graph_nodes.py"
    if not script_path.exists():
        raise HTTPException(status_code=500, detail="build_graph_nodes.py not found")

    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True, text=True, encoding="utf-8", timeout=300,
            cwd=str(PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Build timed out (300s)")

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr.strip() or "Build failed")

    # 그래프 캐시 무효화
    global _lpg_graph
    _lpg_graph = None

    return {
        "success": True,
        "output": proc.stdout.strip()[-1000:],
    }


@router.post("/lpg/build/edges", dependencies=[Depends(require_admin_token)])
async def lpg_build_edges():
    """
    LPG 엣지 빌드 스크립트 실행.
    """
    script_path = PROJECT_ROOT / "backend" / "scripts" / "build_graph_edges.py"
    if not script_path.exists():
        raise HTTPException(status_code=500, detail="build_graph_edges.py not found")

    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True, text=True, encoding="utf-8", timeout=300,
            cwd=str(PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Build timed out (300s)")

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr.strip() or "Build failed")

    # 그래프 캐시 무효화
    global _lpg_graph
    _lpg_graph = None

    return {
        "success": True,
        "output": proc.stdout.strip()[-1000:],
    }


@router.post("/lpg/reload", dependencies=[Depends(require_admin_token)])
async def lpg_reload():
    """
    LPG 그래프 캐시를 강제 리로드.
    """
    global _lpg_graph
    _lpg_graph = None

    graph = _get_lpg_graph()
    if not graph:
        return {
            "success": False,
            "message": "Failed to reload graph. Check if JSONL files exist.",
        }

    stats = graph.get_statistics()
    return {
        "success": True,
        "message": "LPG graph reloaded successfully",
        "stats": stats,
    }
