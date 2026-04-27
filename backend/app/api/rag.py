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


router = APIRouter(prefix="/rag", tags=["RAG"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INDEX_PATH = PROJECT_ROOT / "data" / "indexes" / "faiss" / "snapshot_2026-04-27_batch-001-top5-v2_ollama.index"
DEFAULT_METADATA_PATH = PROJECT_ROOT / "data" / "indexes" / "faiss" / "snapshot_2026-04-27_batch-001-top5-v2_ollama_metadata.jsonl"
DEFAULT_CHUNKS_PATH = PROJECT_ROOT / "data" / "staged" / "chunks" / "snapshot_2026-04-27_batch-001-top5-v2_chunks.jsonl"
ASSEMBLE_SCRIPT = PROJECT_ROOT / "backend" / "scripts" / "assemble_rag_response.py"


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
    index_path = request.index_path or str(DEFAULT_INDEX_PATH)
    metadata_path = request.metadata_path or str(DEFAULT_METADATA_PATH)
    chunks_jsonl = request.chunks_jsonl or str(DEFAULT_CHUNKS_PATH)

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
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return {
                "success": False,
                "error": proc.stderr.strip() or "RAG query failed",
                "stdout": proc.stdout,
            }

        payload = json.loads(output_json.read_text(encoding="utf-8"))
        payload["success"] = True
        return payload
