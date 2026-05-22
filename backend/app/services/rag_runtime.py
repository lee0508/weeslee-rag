# RAG 검색과 생성 경로를 인프로세스로 처리하는 서비스
from __future__ import annotations

import importlib
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

try:
    import faiss  # type: ignore
except Exception as exc:  # pragma: no cover
    raise RuntimeError("faiss-cpu is required for rag_runtime") from exc

from app.core.config import settings


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = PROJECT_ROOT / "backend" / "scripts"
ACTIVE_INDEX_PATH = PROJECT_ROOT / "data" / "active_index.json"
FAISS_DIR = PROJECT_ROOT / "data" / "indexes" / "faiss"
CHUNKS_DIR = PROJECT_ROOT / "data" / "staged" / "chunks"

_cache_lock = threading.Lock()
_active_snapshot_cache: dict[str, Any] = {"path": None, "mtime": None, "snapshot": None}
_bundle_cache: dict[tuple[str, str], dict[str, Any]] = {}
_chunk_cache: dict[str, dict[str, Any]] = {}


def _assembler():
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    return importlib.import_module("assemble_rag_response")


def get_active_snapshot() -> str:
    if not ACTIVE_INDEX_PATH.exists():
        return settings.faiss_snapshot

    resolved = str(ACTIVE_INDEX_PATH.resolve())
    mtime = ACTIVE_INDEX_PATH.stat().st_mtime
    with _cache_lock:
        if (
            _active_snapshot_cache.get("path") == resolved
            and _active_snapshot_cache.get("mtime") == mtime
        ):
            return _active_snapshot_cache.get("snapshot") or settings.faiss_snapshot

        snapshot = settings.faiss_snapshot
        try:
            data = json.loads(ACTIVE_INDEX_PATH.read_text(encoding="utf-8"))
            snapshot = data.get("snapshot") or snapshot
        except Exception:
            pass

        _active_snapshot_cache.update(
            {"path": resolved, "mtime": mtime, "snapshot": snapshot}
        )
        return snapshot


def default_index_paths(snapshot: str, category: Optional[str] = None) -> tuple[Path, Path]:
    if category:
        cat_index = FAISS_DIR / f"{snapshot}_{category}_ollama.index"
        cat_meta = FAISS_DIR / f"{snapshot}_{category}_ollama_metadata.jsonl"
        if cat_index.exists() and cat_meta.exists():
            return cat_index, cat_meta
    return (
        FAISS_DIR / f"{snapshot}_ollama.index",
        FAISS_DIR / f"{snapshot}_ollama_metadata.jsonl",
    )


def default_chunks_path(snapshot: str) -> Path:
    return CHUNKS_DIR / f"{snapshot}_chunks.jsonl"


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _path_key(path: Path) -> str:
    return str(path.resolve())


def _get_chunk_map(chunks_path: Path) -> dict[str, dict]:
    resolved = chunks_path.resolve()
    key = _path_key(resolved)
    mtime = resolved.stat().st_mtime
    with _cache_lock:
        cached = _chunk_cache.get(key)
        if cached and cached.get("mtime") == mtime:
            return cached["chunk_map"]

    chunk_map = {row["chunk_id"]: row for row in _load_jsonl(resolved)}
    with _cache_lock:
        _chunk_cache[key] = {"mtime": mtime, "chunk_map": chunk_map}
    return chunk_map


def _get_bundle(index_path: Path, metadata_path: Path) -> dict[str, Any]:
    index_resolved = index_path.resolve()
    meta_resolved = metadata_path.resolve()
    key = (_path_key(index_resolved), _path_key(meta_resolved))
    index_mtime = index_resolved.stat().st_mtime
    meta_mtime = meta_resolved.stat().st_mtime

    with _cache_lock:
        cached = _bundle_cache.get(key)
        if cached and cached.get("index_mtime") == index_mtime and cached.get("meta_mtime") == meta_mtime:
            return cached

    bundle = {
        "index": faiss.read_index(str(index_resolved)),
        "metadata_rows": _load_jsonl(meta_resolved),
        "index_mtime": index_mtime,
        "meta_mtime": meta_mtime,
    }
    with _cache_lock:
        _bundle_cache[key] = bundle
    return bundle


def _build_args(
    query: str,
    answer_provider: str,
    answer_model: str,
    category: str,
    organization: str,
    year: str,
    top_k: int,
    top_docs: int,
    max_chunks_per_doc: int,
    mode: str,
) -> SimpleNamespace:
    assembler = _assembler()
    args = SimpleNamespace(
        query=query,
        top_k=top_k,
        top_docs=top_docs,
        embedding_provider="ollama",
        embedding_dim=768,
        ollama_embed_url="http://127.0.0.1:11434/api/embeddings",
        ollama_embed_model="",
        answer_provider=answer_provider,
        answer_model=answer_model,
        ollama_generate_url="http://127.0.0.1:11434/api/generate",
        openai_url="https://api.openai.com/v1/chat/completions",
        gemini_url="https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        openrouter_url="https://openrouter.ai/api/v1/chat/completions",
        env_file=str(PROJECT_ROOT / ".env"),
        output_json="",
        output_md="",
        category=category or "",
        max_chunks_per_doc=max_chunks_per_doc,
        mode=mode,
        original_query="",
        organization=organization or "",
        year=year or "",
    )
    assembler.load_env_file(Path(args.env_file))
    assembler.apply_env_defaults(args)
    return args


def _build_hits(bundle: dict[str, Any], chunk_map: dict[str, dict], args: SimpleNamespace) -> list[Any]:
    assembler = _assembler()
    vector = assembler.query_vector(args)
    scores, ids = bundle["index"].search(
        assembler.np.array([vector], dtype=assembler.np.float32),
        args.top_k,
    )

    hits = []
    metadata_rows = bundle["metadata_rows"]
    for rank, (idx, score) in enumerate(zip(ids[0], scores[0]), start=1):
        if idx < 0 or idx >= len(metadata_rows):
            continue
        row = metadata_rows[idx]
        chunk = chunk_map.get(row.get("chunk_id", ""), {})
        meta = row.get("metadata", {}) or {}
        hits.append(
            assembler.SearchHit(
                rank=rank,
                score=float(score),
                chunk_id=row.get("chunk_id", ""),
                document_id=row.get("document_id", ""),
                category=row.get("category", ""),
                section_heading=row.get("section_heading", ""),
                source_path=row.get("source_path", ""),
                input_path=row.get("input_path", ""),
                chunk_text=chunk.get("text", ""),
                organization=row.get("organization", "") or meta.get("organization", ""),
                folder_year=row.get("folder_year", "") or meta.get("folder_year", ""),
                root_group=meta.get("root_group", ""),
                sub_group=meta.get("sub_group", ""),
                section_label=meta.get("section_label", ""),
                proposal_section=meta.get("proposal_section", ""),
                deliverable_section=meta.get("deliverable_section", ""),
                collection_key=row.get("collection_key", "") or meta.get("collection_key", ""),
                relative_path=meta.get("relative_path", ""),
                original_source_path=meta.get("original_source_path", meta.get("source_path", "")),
                file_name=meta.get("file_name", ""),
                search_keywords=assembler.normalize_search_keywords(meta.get("search_keywords", [])),
            )
        )
    return hits


def _build_payload(
    display_query: str,
    expanded_query: str,
    mode: str,
    args: SimpleNamespace,
    documents: list[dict],
    answer: str,
) -> dict:
    return {
        "query": display_query,
        "expanded_query": expanded_query if expanded_query != display_query else None,
        "mode": mode,
        "top_k": args.top_k,
        "top_docs": args.top_docs,
        "category_filter": args.category or None,
        "max_chunks_per_doc": args.max_chunks_per_doc,
        "embedding_provider": args.embedding_provider,
        "answer_provider": args.answer_provider,
        "answer_model": args.answer_model,
        "documents": documents,
        "draft_answer": answer,
        "results": [
            {
                "rank": doc["rank"],
                "score": doc["best_score"],
                "file_name": Path(doc["source_path"]).name,
                "project_name": doc.get("project_name", ""),
                "category": doc.get("category", ""),
                "snippet": (doc.get("evidence_snippets") or [""])[0],
                "reason": "; ".join(doc.get("reasons", [])),
                "source_path": doc.get("source_path", ""),
                "original_source_path": doc.get("original_source_path", ""),
                "relative_path": doc.get("relative_path", ""),
                "root_group": doc.get("root_group", ""),
                "sub_group": doc.get("sub_group", ""),
                "section_label": doc.get("section_label", ""),
            }
            for doc in documents
        ],
        "answer": answer,
    }


def run_rag_query(
    *,
    query: str,
    top_k: int,
    top_docs: int,
    answer_provider: str,
    answer_model: str,
    category: Optional[str],
    organization: Optional[str],
    year: Optional[str],
    max_chunks_per_doc: int,
    mode: str,
    original_query: Optional[str] = None,
    index_path: Optional[str] = None,
    metadata_path: Optional[str] = None,
    chunks_jsonl: Optional[str] = None,
) -> dict:
    assembler = _assembler()
    snapshot = get_active_snapshot()
    default_index, default_meta = default_index_paths(snapshot, category)
    resolved_index = Path(index_path).resolve() if index_path else default_index.resolve()
    resolved_meta = Path(metadata_path).resolve() if metadata_path else default_meta.resolve()
    resolved_chunks = (
        Path(chunks_jsonl).resolve() if chunks_jsonl else default_chunks_path(snapshot).resolve()
    )

    args = _build_args(
        query=query,
        answer_provider=answer_provider,
        answer_model=answer_model,
        category=category or "",
        organization=organization or "",
        year=year or "",
        top_k=top_k,
        top_docs=top_docs,
        max_chunks_per_doc=max_chunks_per_doc,
        mode=mode,
    )

    bundle = _get_bundle(resolved_index, resolved_meta)
    chunk_map = _get_chunk_map(resolved_chunks)
    hits = _build_hits(bundle, chunk_map, args)
    hits = assembler.filter_by_category(hits, args.category)
    hits = assembler.filter_by_metadata(hits, args.organization, args.year)
    hits = assembler.limit_chunks_per_doc(hits, args.max_chunks_per_doc)
    display_query = original_query or query
    documents = assembler.aggregate_hits(query, hits, args.top_docs, mode)
    prompt = assembler.build_prompt(display_query, documents)
    answer = assembler.generate_answer(prompt, args)
    return _build_payload(display_query, query, mode, args, documents, answer)
