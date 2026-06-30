"""
Build a FAISS index from chunk JSONL.

Embedding providers:
- hashing: deterministic fallback for pipeline validation only
- ollama: uses the local/server Ollama embedding endpoint
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

try:
    import faiss  # type: ignore
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "faiss is not installed. Install `faiss-cpu` in the target environment before building the index."
    ) from exc


TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣_]+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build FAISS index from chunk JSONL")
    parser.add_argument("--chunks-jsonl", required=True)
    parser.add_argument("--output-index", required=True)
    parser.add_argument("--output-metadata", required=True)
    parser.add_argument("--output-manifest", default="")
    parser.add_argument("--snapshot-id", default="", help="Snapshot identifier for metadata")
    parser.add_argument("--embedding-provider", choices=["hashing", "ollama"], default="hashing")
    parser.add_argument("--embedding-dim", type=int, default=768)
    parser.add_argument("--max-embed-chars", type=int, default=1800)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434/api/embeddings")
    parser.add_argument("--ollama-model", default="nomic-embed-text")
    return parser.parse_args()


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def normalize_vector(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    if norm == 0.0:
        return vector
    return vector / norm


def truncate_for_embedding(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head
    return f"{text[:head]}\n...\n{text[-tail:]}"


def hashing_embedding(text: str, dim: int) -> np.ndarray:
    vector = np.zeros(dim, dtype=np.float32)
    for token in tokenize(text):
        digest = hashlib.sha1(token.encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) % dim
        sign = -1.0 if int(digest[8:10], 16) % 2 else 1.0
        vector[bucket] += sign
    return normalize_vector(vector)


def ollama_embedding(text: str, model: str, url: str, max_retries: int = 3) -> np.ndarray:
    payload = json.dumps({"model": model, "prompt": text}).encode("utf-8")
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
            embedding = np.array(data.get("embedding", []), dtype=np.float32)
            if embedding.size == 0:
                raise RuntimeError("Ollama returned an empty embedding")
            return normalize_vector(embedding)
        except (urllib.error.URLError, RuntimeError) as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Ollama embedding failed after {max_retries} attempts: {last_exc}") from last_exc


def load_chunks(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _is_faiss_gpu_requested() -> bool:
    return os.environ.get("WEESLEE_GPU_MODE") == "1" and os.environ.get("WEESLEE_GPU_FAISS") == "1"


def _build_faiss_index(matrix: np.ndarray) -> tuple["faiss.Index", bool]:
    dim = matrix.shape[1]
    cpu_index = faiss.IndexFlatIP(dim)

    if _is_faiss_gpu_requested():
        gpu_api_ready = all(
            hasattr(faiss, attr)
            for attr in ("StandardGpuResources", "index_cpu_to_gpu", "index_gpu_to_cpu")
        )
        if gpu_api_ready:
            try:
                resources = faiss.StandardGpuResources()
                gpu_index = faiss.index_cpu_to_gpu(resources, 0, cpu_index)
                gpu_index.add(matrix)
                return faiss.index_gpu_to_cpu(gpu_index), True
            except Exception as exc:
                print(f"WARN FAISS GPU fallback to CPU: {exc}", flush=True)

    cpu_index.add(matrix)
    return cpu_index, False


def main() -> int:
    args = parse_args()
    chunks_jsonl = Path(args.chunks_jsonl).resolve()
    output_index = Path(args.output_index).resolve()
    output_metadata = Path(args.output_metadata).resolve()
    output_manifest = (
        Path(args.output_manifest).resolve()
        if args.output_manifest
        else output_index.with_suffix(".manifest.json")
    )

    output_index.parent.mkdir(parents=True, exist_ok=True)
    output_metadata.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.parent.mkdir(parents=True, exist_ok=True)

    rows = load_chunks(chunks_jsonl)
    if not rows:
        raise SystemExit("No chunks found in input JSONL")

    embeddings: list[np.ndarray] = []
    metadata_rows: list[dict] = []

    total = len(rows)
    fallback_count = 0
    detected_dim: int | None = None  # 첫 번째 성공한 임베딩에서 차원 감지
    for i, row in enumerate(rows, start=1):
        # 진행률 출력 (JSON 형식)
        progress_pct = int((i / max(total, 1)) * 100)
        print(json.dumps({"progress": progress_pct, "current": i, "total": total, "stage": "임베딩"}), flush=True)

        text = row.get("text", "")
        embedding_text = truncate_for_embedding(text, args.max_embed_chars)
        if args.embedding_provider == "ollama":
            try:
                vector = ollama_embedding(embedding_text, args.ollama_model, args.ollama_url)
                # 첫 성공 시 차원 감지
                if detected_dim is None:
                    detected_dim = vector.size
            except RuntimeError as exc:
                print(f"  WARN [{i}/{total}] embedding failed, using hashing fallback: {exc}", flush=True)
                # fallback 시 감지된 차원 사용 (없으면 기본값)
                fallback_dim = detected_dim or args.embedding_dim
                vector = hashing_embedding(embedding_text, fallback_dim)
                fallback_count += 1
        else:
            vector = hashing_embedding(embedding_text, args.embedding_dim)
        embeddings.append(vector.astype(np.float32))

        # 메타데이터 추출 (source_id, dataset_id, snapshot_id, document_uid 최상위 레벨에 포함)
        meta = row.get("metadata", {}) or {}
        metadata_rows.append(
            {
                "chunk_id": row.get("chunk_id"),
                "document_id": row.get("document_id"),
                "source_id": meta.get("source_id", ""),
                "dataset_id": meta.get("dataset_id", ""),
                "snapshot_id": args.snapshot_id,
                "document_uid": meta.get("document_uid", ""),
                "category": row.get("category"),
                "section_heading": row.get("section_heading"),
                "char_count": row.get("char_count"),
                "source_path": row.get("source_path"),
                "input_path": row.get("input_path"),
                "organization": meta.get("organization", ""),
                "folder_year": meta.get("folder_year", ""),
                "root_group": meta.get("root_group", ""),
                "sub_group": meta.get("sub_group", ""),
                "section_label": meta.get("section_label", ""),
                "relative_path": meta.get("relative_path", ""),
                "original_source_path": meta.get("original_source_path", ""),
                "file_name": meta.get("file_name", ""),
                "document_category": meta.get("document_category", ""),
                "document_group": meta.get("document_group", ""),
                "project_name": meta.get("project_name", ""),
                "embedding_text_length": len(embedding_text),
                "original_text_length": len(text),
                # Phase 2: 페이지/슬라이드 정보
                "page_no": row.get("page_no") or meta.get("page_no", 0),
                "slide_no": row.get("slide_no") or meta.get("slide_no"),
                "start_char": row.get("start_char", 0),
                "total_pages": meta.get("total_pages", 0),
                "metadata": meta,
            }
        )
        if i % 200 == 0 or i == total:
            print(f"  [{i}/{total}] embedded (fallbacks={fallback_count})", flush=True)

    matrix = np.vstack(embeddings).astype(np.float32)
    dim = matrix.shape[1]
    index, gpu_used = _build_faiss_index(matrix)
    faiss.write_index(index, str(output_index))

    with output_metadata.open("w", encoding="utf-8") as handle:
        for row in metadata_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    by_document: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for row in metadata_rows:
        doc_id = row["document_id"]
        source_id = row.get("source_id", "") or "unknown"
        by_document[doc_id] = by_document.get(doc_id, 0) + 1
        by_source[source_id] = by_source.get(source_id, 0) + 1

    manifest = {
        "chunks_jsonl": str(chunks_jsonl),
        "output_index": str(output_index),
        "output_metadata": str(output_metadata),
        "embedding_provider": args.embedding_provider,
        "embedding_dim": dim,
        "max_embed_chars": args.max_embed_chars,
        "vector_count": int(index.ntotal),
        "document_count": len(by_document),
        "source_count": len(by_source),
        "counts_by_document": by_document,
        "counts_by_source": by_source,
        "gpu_requested": _is_faiss_gpu_requested(),
        "gpu_used": gpu_used,
        "notes": [
            "hashing provider is for pipeline validation only",
            "use ollama embeddings for meaningful retrieval quality",
        ],
    }
    output_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
