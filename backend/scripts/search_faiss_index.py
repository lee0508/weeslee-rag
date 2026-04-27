"""
Search a FAISS index built from chunk JSONL.

Supports the same embedding providers as build_faiss_index.py so that
hashing-based validation indexes can be queried immediately.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

try:
    import faiss  # type: ignore
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "faiss is not installed. Install `faiss-cpu` in the target environment before searching the index."
    ) from exc

from build_faiss_index import hashing_embedding, ollama_embedding


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search a FAISS chunk index")
    parser.add_argument("--index-path", required=True)
    parser.add_argument("--metadata-path", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--embedding-provider", choices=["hashing", "ollama"], default="hashing")
    parser.add_argument("--embedding-dim", type=int, default=768)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434/api/embeddings")
    parser.add_argument("--ollama-model", default="nomic-embed-text")
    return parser.parse_args()


def load_metadata(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def query_vector(args: argparse.Namespace) -> np.ndarray:
    if args.embedding_provider == "ollama":
        return ollama_embedding(args.query, args.ollama_model, args.ollama_url).astype(np.float32)
    return hashing_embedding(args.query, args.embedding_dim).astype(np.float32)


def main() -> int:
    args = parse_args()
    index_path = Path(args.index_path).resolve()
    metadata_path = Path(args.metadata_path).resolve()

    index = faiss.read_index(str(index_path))
    metadata_rows = load_metadata(metadata_path)
    vector = query_vector(args)
    scores, ids = index.search(np.array([vector], dtype=np.float32), args.top_k)

    results = []
    for rank, (idx, score) in enumerate(zip(ids[0], scores[0]), start=1):
        if idx < 0 or idx >= len(metadata_rows):
            continue
        row = metadata_rows[idx]
        results.append(
            {
                "rank": rank,
                "score": float(score),
                "chunk_id": row.get("chunk_id"),
                "document_id": row.get("document_id"),
                "category": row.get("category"),
                "section_heading": row.get("section_heading"),
                "source_path": row.get("source_path"),
                "input_path": row.get("input_path"),
            }
        )

    print(
        json.dumps(
            {
                "query": args.query,
                "top_k": args.top_k,
                "embedding_provider": args.embedding_provider,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
