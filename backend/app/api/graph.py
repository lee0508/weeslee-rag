# -*- coding: utf-8 -*-
"""
Document Graph API.

GET  /api/graph/summary              — 전체 그래프 통계
GET  /api/graph/projects             — 프로젝트 노드 목록
GET  /api/graph/project/{name}       — 특정 프로젝트의 노드+엣지
GET  /api/graph/document/{doc_id}    — 특정 문서의 노드+연결 엣지
POST /api/graph/build                — build_graph_jsonl.py 실행
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

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
