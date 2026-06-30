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

_cache_lock = threading.Lock()
_active_snapshot_cache: dict[str, Any] = {"path": None, "mtime": None, "snapshot": None}
_bundle_cache: dict[tuple[str, str], dict[str, Any]] = {}
_chunk_cache: dict[str, dict[str, Any]] = {}
_snapshot_manifest_cache: dict[str, dict[str, Any]] = {}
_CATEGORY_SUFFIXES = ("rfp", "proposal", "deliverable")


def _resolve_setting_path(path_value: str) -> Path:
    return Path(path_value).expanduser().resolve()


def _snapshots_dir() -> Path:
    return PROJECT_ROOT / "data" / "snapshots"


def _active_snapshot_paths() -> list[Path]:
    return [
        # Snapshot V2 state should override the older flat active file.
        _snapshots_dir() / "active_snapshot.json",
        PROJECT_ROOT / "data" / "active_snapshot.json",
        _active_index_path(),
    ]


def _resolve_faiss_index_id(snapshot_id: str) -> str:
    """snapshot_id에 해당하는 faiss_index_id를 반환. manifest가 없으면 snapshot_id 그대로 반환."""
    snapshot_id = str(snapshot_id or "").strip()
    if not snapshot_id:
        return snapshot_id

    with _cache_lock:
        cached = _snapshot_manifest_cache.get(snapshot_id)
        if cached:
            return cached.get("faiss_index_id", snapshot_id)

    snapshots_dir = _snapshots_dir()
    for pattern in [f"snapshot_{snapshot_id}.json", f"{snapshot_id}.json", f"*{snapshot_id}*.json"]:
        for manifest_path in snapshots_dir.glob(pattern):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                if data.get("snapshot_id") == snapshot_id:
                    faiss_index_id = (data.get("rag_build") or {}).get("faiss_index_id", "")
                    with _cache_lock:
                        _snapshot_manifest_cache[snapshot_id] = {
                            "faiss_index_id": faiss_index_id or snapshot_id,
                            "manifest": data,
                        }
                    return faiss_index_id or snapshot_id
            except Exception:
                continue

    return snapshot_id


def _scripts_dir() -> Path:
    return _resolve_setting_path(settings.rag_scripts_dir)


def _active_index_path() -> Path:
    return _resolve_setting_path(settings.active_index_path)


def _faiss_dir() -> Path:
    return _resolve_setting_path(settings.faiss_index_dir)


def _chunks_dir() -> Path:
    return _resolve_setting_path(settings.staged_chunks_dir)


def _assembler():
    scripts_dir = _scripts_dir()
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    return importlib.import_module("assemble_rag_response")


def get_active_snapshot() -> str:
    active_paths = [path for path in _active_snapshot_paths() if path.exists()]
    if not active_paths:
        return settings.faiss_snapshot

    cache_key = "|".join(str(path.resolve()) for path in active_paths)
    latest_mtime = max(path.stat().st_mtime for path in active_paths)
    with _cache_lock:
        if (
            _active_snapshot_cache.get("path") == cache_key
            and _active_snapshot_cache.get("mtime") == latest_mtime
        ):
            return _active_snapshot_cache.get("snapshot") or settings.faiss_snapshot

        snapshot = settings.faiss_snapshot
        for path in active_paths:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue

            candidate = (
                data.get("active_snapshot_id")
                or data.get("snapshot_id")
                or data.get("snapshot")
                or data.get("active_snapshot")
            )
            candidate = str(candidate or "").strip()
            if candidate:
                snapshot = candidate
                break

        _active_snapshot_cache.update(
            {"path": cache_key, "mtime": latest_mtime, "snapshot": snapshot}
        )
        return snapshot


def default_index_paths(snapshot: str, category: Optional[str] = None) -> tuple[Path, Path]:
    faiss_dir = _faiss_dir()
    if category:
        cat_index = faiss_dir / f"{snapshot}_{category}_ollama.index"
        cat_meta = faiss_dir / f"{snapshot}_{category}_ollama_metadata.jsonl"
        if cat_index.exists() and cat_meta.exists():
            return cat_index, cat_meta
    primary_index = faiss_dir / f"{snapshot}_ollama.index"
    primary_meta = faiss_dir / f"{snapshot}_ollama_metadata.jsonl"
    if primary_index.exists() and primary_meta.exists():
        return primary_index, primary_meta
    for fallback_category in _CATEGORY_SUFFIXES:
        cat_index = faiss_dir / f"{snapshot}_{fallback_category}_ollama.index"
        cat_meta = faiss_dir / f"{snapshot}_{fallback_category}_ollama_metadata.jsonl"
        if cat_index.exists() and cat_meta.exists():
            return cat_index, cat_meta
    return primary_index, primary_meta


def category_index_paths(snapshot: str, category: str) -> tuple[Path, Path]:
    faiss_dir = _faiss_dir()
    cat_index = faiss_dir / f"{snapshot}_{category}_ollama.index"
    cat_meta = faiss_dir / f"{snapshot}_{category}_ollama_metadata.jsonl"
    return cat_index, cat_meta


def default_chunks_path(snapshot: str) -> Path:
    return _chunks_dir() / f"{snapshot}_chunks.jsonl"


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
    document_group: str = "",
    document_category: str = "",
    section_type: str = "",
    relative_path_prefix: str = "",
) -> SimpleNamespace:
    assembler = _assembler()
    args = SimpleNamespace(
        query=query,
        top_k=top_k,
        top_docs=top_docs,
        embedding_provider=settings.embedding_provider,
        embedding_dim=settings.embedding_dim,
        ollama_embed_url=settings.ollama_embed_url,
        ollama_embed_model=settings.ollama_embed_model,
        answer_provider=answer_provider or settings.answer_provider,
        answer_model=answer_model or settings.answer_model,
        ollama_generate_url=settings.ollama_generate_url,
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
        document_group=document_group or "",
        document_category=document_category or "",
        section_type=section_type or "",
        relative_path_prefix=relative_path_prefix or "",
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
                source_id=row.get("source_id", "") or meta.get("source_id", ""),
                snapshot=row.get("snapshot", "") or meta.get("snapshot", ""),
                category=row.get("category", "") or row.get("document_group", "") or meta.get("category", ""),
                section_heading=row.get("section_heading", ""),
                source_path=row.get("source_path", ""),
                input_path=row.get("input_path", ""),
                chunk_text=chunk.get("text", ""),
                organization=row.get("organization", "") or meta.get("organization", ""),
                folder_year=row.get("folder_year", "") or meta.get("folder_year", ""),
                document_group=row.get("document_group", "") or meta.get("document_group", "") or row.get("category", ""),
                document_category=row.get("document_category", "") or meta.get("document_category", "") or row.get("section_label", "") or meta.get("section_label", ""),
                root_group=row.get("root_group", "") or meta.get("root_group", ""),
                sub_group=row.get("sub_group", "") or meta.get("sub_group", ""),
                section_label=row.get("section_label", "") or meta.get("section_label", "") or row.get("document_category", "") or meta.get("document_category", ""),
                proposal_section=row.get("proposal_section", "") or meta.get("proposal_section", ""),
                deliverable_section=row.get("deliverable_section", "") or meta.get("deliverable_section", ""),
                collection_key=row.get("collection_key", "") or row.get("document_group", "") or meta.get("collection_key", "") or meta.get("document_group", ""),
                relative_path=row.get("relative_path", "") or meta.get("relative_path", ""),
                original_source_path=row.get("original_source_path", "") or meta.get("original_source_path", meta.get("source_path", "")),
                file_name=row.get("file_name", "") or meta.get("file_name", ""),
                search_keywords=assembler.normalize_search_keywords(meta.get("search_keywords", [])),
            )
        )
    return hits


def _build_hits_for_snapshot(
    snapshot: str,
    bundle: dict[str, Any],
    chunk_map: dict[str, dict],
    args: SimpleNamespace,
) -> list[Any]:
    hits = _build_hits(bundle, chunk_map, args)
    source_id = ""
    if snapshot.startswith("snapshot_"):
        parts = snapshot.replace("snapshot_", "", 1).split("_")
        if len(parts) > 2:
            source_id = "_".join(part for part in parts[1:] if not part.lower().startswith("v"))
    for hit in hits:
        if not getattr(hit, "snapshot", ""):
            hit.snapshot = snapshot
        if not getattr(hit, "source_id", ""):
            hit.source_id = source_id
    return hits


def _apply_structure_filters_with_fallback(assembler, hits: list[Any], args: SimpleNamespace) -> list[Any]:
    has_structure_filters = any(
        [
            args.document_group,
            args.document_category,
            args.section_type,
            args.relative_path_prefix,
        ]
    )
    if not has_structure_filters:
        return hits

    full_hits = assembler.filter_by_structure(
        hits,
        args.document_group,
        args.document_category,
        args.section_type,
        args.relative_path_prefix,
    )
    if full_hits:
        return full_hits

    if args.document_group and (args.document_category or args.section_type):
        group_only_hits = assembler.filter_by_structure(
            hits,
            args.document_group,
            "",
            "",
            args.relative_path_prefix,
        )
        if group_only_hits:
            return group_only_hits

    if args.document_category or args.section_type:
        section_only_hits = assembler.filter_by_structure(
            hits,
            "",
            args.document_category,
            args.section_type,
            args.relative_path_prefix,
        )
        if section_only_hits:
            return section_only_hits

    if args.relative_path_prefix:
        path_only_hits = assembler.filter_by_structure(
            hits,
            "",
            "",
            "",
            args.relative_path_prefix,
        )
        if path_only_hits:
            return path_only_hits

    return hits


def _build_payload(
    display_query: str,
    expanded_query: str,
    mode: str,
    args: SimpleNamespace,
    documents: list[dict],
    answer: str,
    *,
    snapshot: str,
    snapshots: list[str] | None = None,
) -> dict:
    return {
        "query": display_query,
        "expanded_query": expanded_query if expanded_query != display_query else None,
        "snapshot": snapshot,
        "resolved_snapshots": list(snapshots or [snapshot]),
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
                "source_id": doc.get("source_id", ""),
                "snapshot": doc.get("snapshot", snapshot),
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
    snapshot: Optional[str] = None,
    index_path: Optional[str] = None,
    metadata_path: Optional[str] = None,
    chunks_jsonl: Optional[str] = None,
    document_group: Optional[str] = None,
    document_category: Optional[str] = None,
    section_type: Optional[str] = None,
    relative_path_prefix: Optional[str] = None,
) -> dict:
    assembler = _assembler()
    resolved_snapshot = snapshot or get_active_snapshot()
    resolved_index_id = _resolve_faiss_index_id(resolved_snapshot)
    default_index, default_meta = default_index_paths(resolved_index_id, category)
    if category and not index_path and not metadata_path:
        strict_index, strict_meta = category_index_paths(resolved_index_id, category)
        if strict_index.exists() and strict_meta.exists():
            default_index, default_meta = strict_index, strict_meta
    resolved_index = Path(index_path).resolve() if index_path else default_index.resolve()
    resolved_meta = Path(metadata_path).resolve() if metadata_path else default_meta.resolve()
    resolved_chunks = (
        Path(chunks_jsonl).resolve() if chunks_jsonl else default_chunks_path(resolved_index_id).resolve()
    )

    args = _build_args(
        query=query,
        answer_provider=answer_provider,
        answer_model=answer_model,
        category=category or "",
        organization=organization or "",
        year=year or "",
        document_group=document_group or "",
        document_category=document_category or "",
        section_type=section_type or "",
        relative_path_prefix=relative_path_prefix or "",
        top_k=top_k,
        top_docs=top_docs,
        max_chunks_per_doc=max_chunks_per_doc,
        mode=mode,
    )

    bundle = _get_bundle(resolved_index, resolved_meta)
    chunk_map = _get_chunk_map(resolved_chunks)
    hits = _build_hits_for_snapshot(resolved_snapshot, bundle, chunk_map, args)
    hits = assembler.filter_by_category(hits, args.category)
    hits = assembler.filter_by_metadata(hits, args.organization, args.year)
    hits = _apply_structure_filters_with_fallback(assembler, hits, args)
    hits = assembler.limit_chunks_per_doc(hits, args.max_chunks_per_doc)
    display_query = original_query or query
    documents = assembler.aggregate_hits(query, hits, args.top_docs, mode)
    prompt = assembler.build_prompt(display_query, documents)
    answer = assembler.generate_answer(prompt, args)
    return _build_payload(
        display_query,
        query,
        mode,
        args,
        documents,
        answer,
        snapshot=resolved_snapshot,
        snapshots=[resolved_snapshot],
    )


def run_multi_rag_query(
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
    snapshots: list[str],
    original_query: Optional[str] = None,
    document_group: Optional[str] = None,
    document_category: Optional[str] = None,
    section_type: Optional[str] = None,
    relative_path_prefix: Optional[str] = None,
) -> dict:
    assembler = _assembler()
    resolved_snapshots = [str(value).strip() for value in snapshots if str(value).strip()]
    if not resolved_snapshots:
        raise RuntimeError("검색 가능한 Snapshot이 없습니다.")

    args = _build_args(
        query=query,
        answer_provider=answer_provider,
        answer_model=answer_model,
        category=category or "",
        organization=organization or "",
        year=year or "",
        document_group=document_group or "",
        document_category=document_category or "",
        section_type=section_type or "",
        relative_path_prefix=relative_path_prefix or "",
        top_k=top_k,
        top_docs=top_docs,
        max_chunks_per_doc=max_chunks_per_doc,
        mode=mode,
    )

    all_hits: list[Any] = []
    skipped_snapshots: list[dict[str, str]] = []
    resolved_index_ids: list[str] = []
    for snapshot_id in resolved_snapshots:
        try:
            faiss_index_id = _resolve_faiss_index_id(snapshot_id)
            if category:
                index_path, meta_path = category_index_paths(faiss_index_id, category)
                if not (index_path.exists() and meta_path.exists()):
                    skipped_snapshots.append(
                        {"snapshot": snapshot_id, "faiss_index_id": faiss_index_id, "error": f"missing category index: {category}"}
                    )
                    continue
            else:
                index_path, meta_path = default_index_paths(faiss_index_id, category)
            chunks_path = default_chunks_path(faiss_index_id)
            if not (index_path.exists() and meta_path.exists() and chunks_path.exists()):
                skipped_snapshots.append(
                    {"snapshot": snapshot_id, "faiss_index_id": faiss_index_id, "error": "required files missing"}
                )
                continue
            resolved_index_ids.append(faiss_index_id)
            bundle = _get_bundle(index_path.resolve(), meta_path.resolve())
            chunk_map = _get_chunk_map(chunks_path.resolve())
            all_hits.extend(_build_hits_for_snapshot(snapshot_id, bundle, chunk_map, args))
        except Exception as exc:
            skipped_snapshots.append(
                {"snapshot": snapshot_id, "error": str(exc) or exc.__class__.__name__}
            )
            continue

    if not all_hits:
        detail = ", ".join(
            f"{item['snapshot']}: {item['error']}" for item in skipped_snapshots[:3]
        )
        if detail:
            raise RuntimeError(
                f"선택한 검색 범위에서 사용할 Snapshot 로드에 실패했습니다. {detail}"
            )
        raise RuntimeError("선택한 검색 범위에 사용할 FAISS Snapshot 파일이 없습니다.")

    all_hits.sort(key=lambda hit: float(getattr(hit, "score", 0.0)), reverse=True)
    hits = assembler.filter_by_category(all_hits, args.category)
    hits = assembler.filter_by_metadata(hits, args.organization, args.year)
    hits = _apply_structure_filters_with_fallback(assembler, hits, args)
    hits = assembler.limit_chunks_per_doc(hits, args.max_chunks_per_doc)
    display_query = original_query or query
    documents = assembler.aggregate_hits(query, hits, args.top_docs, mode)
    prompt = assembler.build_prompt(display_query, documents)
    answer = assembler.generate_answer(prompt, args)
    payload = _build_payload(
        display_query,
        query,
        mode,
        args,
        documents,
        answer,
        snapshot=resolved_index_ids[0] if resolved_index_ids else resolved_snapshots[0],
        snapshots=resolved_index_ids or resolved_snapshots,
    )
    payload["skipped_snapshots"] = skipped_snapshots
    payload["requested_snapshots"] = resolved_snapshots
    payload["resolved_index_ids"] = resolved_index_ids
    return payload
