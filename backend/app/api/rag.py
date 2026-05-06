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
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import settings


router = APIRouter(prefix="/rag", tags=["RAG"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = PROJECT_ROOT / "backend" / "scripts"
ASSEMBLE_SCRIPT = SCRIPTS_DIR / "assemble_rag_response.py"


def _default_index_path() -> Path:
    snapshot = settings.faiss_snapshot
    return PROJECT_ROOT / "data" / "indexes" / "faiss" / f"{snapshot}_ollama.index"


def _default_metadata_path() -> Path:
    snapshot = settings.faiss_snapshot
    return PROJECT_ROOT / "data" / "indexes" / "faiss" / f"{snapshot}_ollama_metadata.jsonl"


def _default_chunks_path() -> Path:
    snapshot = settings.faiss_snapshot
    return PROJECT_ROOT / "data" / "staged" / "chunks" / f"{snapshot}_chunks.jsonl"


class RagQueryRequest(BaseModel):
    query: str = Field(..., min_length=2)
    top_k: int = 20
    top_docs: int = 5
    answer_provider: str = "ollama"
    answer_model: str = "gemma4:latest"
    index_path: Optional[str] = None
    metadata_path: Optional[str] = None
    chunks_jsonl: Optional[str] = None


@router.post("/query")
async def query_rag(request: RagQueryRequest):
    index_path = request.index_path or str(_default_index_path())
    metadata_path = request.metadata_path or str(_default_metadata_path())
    chunks_jsonl = request.chunks_jsonl or str(_default_chunks_path())

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
        ]
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
        return payload
