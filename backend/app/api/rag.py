# -*- coding: utf-8 -*-
"""
RAG query API endpoints.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import sys
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import settings


router = APIRouter(prefix="/rag", tags=["RAG"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = PROJECT_ROOT / "backend" / "scripts"
ASSEMBLE_SCRIPT = SCRIPTS_DIR / "assemble_rag_response.py"
_ACTIVE_INDEX_PATH = PROJECT_ROOT / "data" / "active_index.json"


def _active_snapshot() -> str:
    """Read active_index.json; fall back to settings.faiss_snapshot."""
    if _ACTIVE_INDEX_PATH.exists():
        try:
            data = json.loads(_ACTIVE_INDEX_PATH.read_text(encoding="utf-8"))
            snap = data.get("snapshot", "")
            if snap:
                return snap
        except Exception:
            pass
    return settings.faiss_snapshot


def _index_paths(snapshot: str, category: Optional[str] = None) -> tuple[Path, Path]:
    """Return (index_path, metadata_path) for the given snapshot.

    If a per-category sub-index exists and category is specified, prefer it
    (true pre-filter). Falls back to the combined all-category index.
    """
    faiss_dir = PROJECT_ROOT / "data" / "indexes" / "faiss"
    if category:
        cat_index = faiss_dir / f"{snapshot}_{category}_ollama.index"
        cat_meta = faiss_dir / f"{snapshot}_{category}_ollama_metadata.jsonl"
        if cat_index.exists() and cat_meta.exists():
            return cat_index, cat_meta
    return (
        faiss_dir / f"{snapshot}_ollama.index",
        faiss_dir / f"{snapshot}_ollama_metadata.jsonl",
    )


def _default_chunks_path() -> Path:
    return PROJECT_ROOT / "data" / "staged" / "chunks" / f"{_active_snapshot()}_chunks.jsonl"


GRAPH_NODES_PATH = PROJECT_ROOT / "data" / "indexes" / "graph" / "graph_nodes.jsonl"
PROPOSAL_SCRIPT = SCRIPTS_DIR / "generate_proposal_draft.py"


# 작성일: 2026-05-12 | 기능: FAISS 결과에서 프로젝트 추출 → 그래프 관련 문서 조회
def _enrich_with_graph_context(payload: dict) -> dict:
    if not GRAPH_NODES_PATH.exists():
        payload["graph_context"] = []
        return payload

    found_projects = {
        doc.get("project_name", "")
        for doc in payload.get("documents", [])
        if doc.get("project_name")
    }
    if not found_projects:
        payload["graph_context"] = []
        return payload

    by_project: dict[str, list[dict]] = {}
    for line in GRAPH_NODES_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        node = json.loads(line)
        if node.get("type") != "document":
            continue
        proj = node.get("project_name", "")
        if proj not in found_projects:
            continue
        by_project.setdefault(proj, []).append({
            "document_id": node.get("document_id", ""),
            "category":    node.get("category", ""),
            "label":       node.get("label", ""),
            "source_path": node.get("source_path", ""),
        })

    payload["graph_context"] = [
        {"project_name": proj, "related_docs": docs}
        for proj, docs in by_project.items()
    ]
    return payload


class RagQueryRequest(BaseModel):
    query: str = Field(..., min_length=2)
    top_k: int = 20
    top_docs: int = 5
    answer_provider: str = "ollama"
    answer_model: str = "gemma4:latest"
    index_path: Optional[str] = None
    metadata_path: Optional[str] = None
    chunks_jsonl: Optional[str] = None
    category: Optional[str] = None
    organization: Optional[str] = None
    year: Optional[str] = None
    max_chunks_per_doc: int = 3
    mode: str = "general"  # "general" | "bid_project" | "rfp_analysis" | "graph_rag"


@router.post("/query")
async def query_rag(request: RagQueryRequest):
    from app.services.query_expander import expand_bid_query, expand_rfp_query

    snapshot = _active_snapshot()
    default_index, default_meta = _index_paths(snapshot, request.category)
    index_path = request.index_path or str(default_index)
    metadata_path = request.metadata_path or str(default_meta)
    chunks_jsonl = request.chunks_jsonl or str(_default_chunks_path())

    if request.mode == "bid_project":
        effective_query = expand_bid_query(request.query)
    elif request.mode == "rfp_analysis":
        effective_query = expand_rfp_query(request.query)
    else:
        effective_query = request.query  # general, graph_rag 모두 확장 없음

    with tempfile.TemporaryDirectory() as temp_dir:
        output_json = Path(temp_dir) / "rag_response.json"
        output_md = Path(temp_dir) / "rag_response.md"
        cmd = [
            sys.executable,
            str(ASSEMBLE_SCRIPT),
            "--index-path",
            index_path,
            "--metadata-path",
            metadata_path,
            "--chunks-jsonl",
            chunks_jsonl,
            "--query",
            effective_query,
            "--original-query",
            request.query,
            "--top-k",
            str(request.top_k),
            "--top-docs",
            str(request.top_docs),
            "--embedding-provider",
            "ollama",
            "--answer-provider",
            request.answer_provider,
            "--answer-model",
            request.answer_model,
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--max-chunks-per-doc",
            str(request.max_chunks_per_doc),
            "--mode",
            request.mode,
        ]
        if request.category:
            cmd += ["--category", request.category]
        if request.organization:
            cmd += ["--organization", request.organization]
        if request.year:
            cmd += ["--year", request.year]
        # cwd=SCRIPTS_DIR is required: assemble_rag_response.py imports
        # build_faiss_index as a local module (no package prefix)
        proc = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(SCRIPTS_DIR)
        )
        if proc.returncode != 0:
            return {
                "success": False,
                "error": proc.stderr.strip() or "RAG query failed",
                "stdout": proc.stdout,
            }

        payload = json.loads(output_json.read_text(encoding="utf-8"))
        payload["success"] = True

        if request.mode in ("bid_project", "rfp_analysis"):
            from app.services.reranker import rerank
            payload["documents"] = rerank(request.query, payload.get("documents", []), request.mode)

        # 작성일: 2026-05-12 | 기능: graph_rag 모드 — 동일 프로젝트 관련 문서 체인 추가
        if request.mode == "graph_rag":
            payload = _enrich_with_graph_context(payload)

        return payload


class ProposalRequest(BaseModel):
    project_name: str = Field(..., min_length=2)
    organization: str = ""
    category: str = "proposal"
    sections: List[str] = ["overview", "current", "strategy", "schedule", "track", "effect"]
    top_k: int = 15
    top_docs: int = 4
    answer_model: str = "gemma4:latest"
    index_path: Optional[str] = None
    metadata_path: Optional[str] = None
    chunks_jsonl: Optional[str] = None


@router.post("/proposal")
async def generate_proposal(request: ProposalRequest):
    snapshot = _active_snapshot()
    default_index, default_meta = _index_paths(snapshot, None)
    index_path   = request.index_path   or str(default_index)
    metadata_path = request.metadata_path or str(default_meta)
    chunks_jsonl  = request.chunks_jsonl  or str(_default_chunks_path())

    with tempfile.TemporaryDirectory() as temp_dir:
        output_json = Path(temp_dir) / "proposal_draft.json"
        cmd = [
            sys.executable,
            str(PROPOSAL_SCRIPT),
            "--index-path",    index_path,
            "--metadata-path", metadata_path,
            "--chunks-jsonl",  chunks_jsonl,
            "--project-name",  request.project_name,
            "--organization",  request.organization,
            "--category",      request.category,
            "--sections",      ",".join(request.sections),
            "--top-k",         str(request.top_k),
            "--top-docs",      str(request.top_docs),
            "--answer-model",  request.answer_model,
            "--embedding-provider", "ollama",
            "--output-json",   str(output_json),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(SCRIPTS_DIR))
        if proc.returncode != 0:
            return {
                "success": False,
                "error": proc.stderr.strip() or "Proposal generation failed",
                "stdout": proc.stdout,
            }
        payload = json.loads(output_json.read_text(encoding="utf-8"))
        payload["success"] = True
        return payload
