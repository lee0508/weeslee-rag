"""
Validate HWPX extraction, metadata extraction, and retrieval quality.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.extractors.hwpx_extractor import HwpxExtractor  # noqa: E402

try:  # pragma: no cover - optional on some server snapshots
    from app.services.metadata_extractor import metadata_extractor_service  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover
    metadata_extractor_service = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate HWPX pipeline quality")
    parser.add_argument("--file", required=True)
    parser.add_argument("--index-path", required=True)
    parser.add_argument("--metadata-path", required=True)
    parser.add_argument("--chunks-jsonl", required=True)
    parser.add_argument("--query", default="")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--top-docs", type=int, default=5)
    parser.add_argument("--output-dir", default="/tmp")
    parser.add_argument("--answer-provider", default="ollama")
    parser.add_argument("--answer-model", default="gemma4:latest")
    parser.add_argument("--ollama-embed-model", default="nomic-embed-text")
    parser.add_argument("--ollama-embed-url", default="http://127.0.0.1:11434/api/embeddings")
    parser.add_argument("--ollama-generate-url", default="http://127.0.0.1:11434/api/generate")
    return parser.parse_args()


def heuristic_metadata(text: str, filename: str) -> dict:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = filename
    for line in lines[:20]:
        if len(line) >= 8 and len(line) <= 120:
            title = line.strip("<> ")
            break

    keyword_candidates = []
    for term in [
        "RFP",
        "제안요청서",
        "ISMP",
        "차세대",
        "업무시스템",
        "프로젝트",
        "일정관리",
        "보안요구사항",
        "산출물",
        "지적재산권",
    ]:
        if term in text and term not in keyword_candidates:
            keyword_candidates.append(term)

    return {
        "title": title,
        "summary": "HWPX RFP extracted for retrieval validation.",
        "keywords": keyword_candidates[:10],
        "category": "RFP",
        "document_type": "RFP",
        "organization": None,
        "project_name": None,
        "year": None,
        "language": "ko",
        "confidence_score": 0.6,
    }


async def run_metadata_extraction(text: str, filename: str) -> dict:
    if metadata_extractor_service is None:
        return heuristic_metadata(text, filename)
    metadata = await metadata_extractor_service.extract_metadata(text, filename=filename)
    return metadata.to_dict()


def run_rag_assembly(args: argparse.Namespace, query: str, output_dir: Path) -> dict:
    output_json = output_dir / "hwpx_validation_rag.json"
    output_md = output_dir / "hwpx_validation_rag.md"
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "backend" / "scripts" / "assemble_rag_response.py"),
        "--index-path",
        args.index_path,
        "--metadata-path",
        args.metadata_path,
        "--chunks-jsonl",
        args.chunks_jsonl,
        "--query",
        query,
        "--top-k",
        str(args.top_k),
        "--top-docs",
        str(args.top_docs),
        "--embedding-provider",
        "ollama",
        "--ollama-embed-model",
        args.ollama_embed_model,
        "--answer-provider",
        args.answer_provider,
        "--answer-model",
        args.answer_model,
        "--ollama-generate-url",
        args.ollama_generate_url,
        "--ollama-embed-url",
        args.ollama_embed_url,
        "--output-json",
        str(output_json),
        "--output-md",
        str(output_md),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return {
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "output_json": str(output_json),
        "output_md": str(output_md),
    }


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    file_path = Path(args.file)
    extracted = asyncio.run(HwpxExtractor().extract(str(file_path)))
    if not extracted.get("success"):
        print(json.dumps({"stage": "extract", "result": extracted}, ensure_ascii=False, indent=2))
        return 1

    content = extracted.get("content", "")
    metadata = asyncio.run(run_metadata_extraction(content, file_path.name))

    query = args.query.strip()
    if not query:
        keywords = metadata.get("keywords") or []
        title = metadata.get("title") or file_path.stem
        query = " ".join([title] + list(keywords[:6]))

    rag_result = run_rag_assembly(args, query, output_dir)

    summary = {
        "file": str(file_path),
        "extract_success": extracted.get("success"),
        "extract_method": extracted.get("method"),
        "extract_length": len(content),
        "metadata": metadata,
        "query": query,
        "rag_result": rag_result,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
