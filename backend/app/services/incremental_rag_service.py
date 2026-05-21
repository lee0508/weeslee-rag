# 선택 문서를 기존 active snapshot에 증분 반영하는 RAG 처리 서비스
from __future__ import annotations

import dataclasses
import datetime
import json
import sys
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

import faiss  # type: ignore
import numpy as np

from app.extractors.extractor import DocumentExtractor
from app.services.faiss_job_runner import read_active_index
from app.services.metadata_db import metadata_db_service

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
FAISS_DIR = DATA_DIR / "indexes" / "faiss"
EXTRACTED_TEXT_DIR = DATA_DIR / "extracted_text"
STAGED_TEXT_DIR = DATA_DIR / "staged" / "text"
STAGED_METADATA_DIR = DATA_DIR / "staged" / "metadata"
SUMMARIES_DIR = DATA_DIR / "summaries"
SCRIPTS_DIR = PROJECT_ROOT / "backend" / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from build_chunk_batch import build_chunks_for_document  # noqa: E402
from build_faiss_index import hashing_embedding, ollama_embedding, truncate_for_embedding  # noqa: E402
import build_rag_source_metadata as rag_meta_rules  # noqa: E402

COLLECTION_TO_CATEGORY = {
    "rag_source_rfp": "rfp",
    "rag_source_proposal": "proposal",
    "rag_source_deliverable": "deliverable",
}
CATEGORY_TO_COLLECTION = {value: key for key, value in COLLECTION_TO_CATEGORY.items()}


@dataclass
class IncrementalRagResult:
    snapshot: str
    document_ids: list[int]
    processed: int
    skipped: int
    chunk_count: int
    category_counts: dict[str, int]
    embedding_provider: str


def _index_paths(snapshot: str) -> dict[str, Path]:
    return {
        "index": FAISS_DIR / f"{snapshot}_ollama.index",
        "meta": FAISS_DIR / f"{snapshot}_ollama_metadata.jsonl",
        "manifest": FAISS_DIR / f"{snapshot}_ollama.manifest.json",
    }


def _derived_dir(document_id: int) -> Path:
    path = EXTRACTED_TEXT_DIR / str(document_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _raw_text_path(document_id: int) -> Path:
    return _derived_dir(document_id) / "raw_text.txt"


def _markdown_path(document_id: int) -> Path:
    return _derived_dir(document_id) / "document.md"


def _html_path(document_id: int) -> Path:
    return _derived_dir(document_id) / "document.html"


def _metadata_path(document_id: int) -> Path:
    return _derived_dir(document_id) / "metadata.json"


def _summary_path(document_id: int) -> Path:
    return SUMMARIES_DIR / str(document_id) / "summary.md"


def _staged_text_path(document_id: int) -> Path:
    return STAGED_TEXT_DIR / f"{document_id}.txt"


def _staged_metadata_path(document_id: int) -> Path:
    return STAGED_METADATA_DIR / f"{document_id}.json"


def _read_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists():
        return default or {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default or {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _detect_category(file_path: str, collection_key: str = "") -> tuple[str, dict[str, Any]]:
    if collection_key in COLLECTION_TO_CATEGORY:
        category = COLLECTION_TO_CATEGORY[collection_key]
    else:
        normalized = rag_meta_rules.normalize_path(file_path)
        parts = rag_meta_rules.split_path(normalized)
        root_group = rag_meta_rules.detect_root_group(parts)
        sub_group = rag_meta_rules.detect_sub_group(parts)
        category = rag_meta_rules.detect_document_metadata(root_group or "", sub_group or "").get("document_group", "unknown")

    normalized = rag_meta_rules.normalize_path(file_path)
    parts = rag_meta_rules.split_path(normalized)
    root_group = rag_meta_rules.detect_root_group(parts)
    sub_group = rag_meta_rules.detect_sub_group(parts)
    doc_meta = rag_meta_rules.detect_document_metadata(root_group or "", sub_group or "")
    return category, {
        "root_group": root_group or "",
        "root_group_key": rag_meta_rules.root_group_key(root_group),
        "sub_group": sub_group or "",
        "sub_group_key": rag_meta_rules.sub_group_key(root_group, sub_group, doc_meta),
        "proposal_section": doc_meta.get("proposal_section") or "",
        "deliverable_section": doc_meta.get("deliverable_section") or "",
        "section_label": rag_meta_rules.section_label(doc_meta),
        "collection_key": collection_key or CATEGORY_TO_COLLECTION.get(category, ""),
    }


def _embedding_provider(snapshot: str) -> str:
    manifest = _read_json(_index_paths(snapshot)["manifest"])
    provider = str(manifest.get("embedding_provider") or "ollama").strip().lower()
    return provider if provider in {"ollama", "hashing"} else "ollama"


def _save_derived_outputs(document_id: int, text: str, metadata: dict) -> None:
    _raw_text_path(document_id).write_text(text, encoding="utf-8")
    _markdown_path(document_id).write_text(text, encoding="utf-8")
    _html_path(document_id).write_text(
        "<html><head><meta charset=\"UTF-8\"></head><body>"
        f"<pre>{escape(text)}</pre></body></html>",
        encoding="utf-8",
    )
    _write_json(_metadata_path(document_id), metadata)
    _staged_text_path(document_id).parent.mkdir(parents=True, exist_ok=True)
    _staged_metadata_path(document_id).parent.mkdir(parents=True, exist_ok=True)
    _staged_text_path(document_id).write_text(text, encoding="utf-8")
    _write_json(_staged_metadata_path(document_id), metadata)


async def _extract_document(doc: dict[str, Any], collection_key: str) -> tuple[str, dict[str, Any]]:
    file_path = str(doc.get("file_path") or "")
    extractor = DocumentExtractor(use_ocr=True)
    result = await extractor.extract(file_path)
    if not result.get("success"):
        raise RuntimeError(result.get("error") or f"extract failed: {file_path}")

    text = result.get("content", "")
    category, derived = _detect_category(file_path, collection_key)
    project_name = doc.get("project_name") or rag_meta_rules.extract_project_name(Path(file_path).stem)
    organization = doc.get("organization") or rag_meta_rules.detect_organization(project_name) or ""
    relative_path = ""
    if "/00. RAG 소스/" in rag_meta_rules.normalize_path(file_path):
        relative_path = rag_meta_rules.normalize_path(file_path).split("/00. RAG 소스/", 1)[1]
    search_keywords = rag_meta_rules.build_search_keywords(
        root_group=derived["root_group"],
        sub_group=derived["sub_group"],
        project_name=project_name,
        document_group=category,
        proposal_section=derived["proposal_section"],
        deliverable_section=derived["deliverable_section"],
        tags=[],
        organization=organization,
        file_name=Path(file_path).name,
    )
    metadata = {
        "document_id": int(doc["id"]),
        "category": category,
        "document_group": category,
        "document_type": doc.get("document_type") or category,
        "root_group": derived["root_group"],
        "root_group_key": derived["root_group_key"],
        "sub_group": derived["sub_group"],
        "sub_group_key": derived["sub_group_key"],
        "proposal_section": derived["proposal_section"],
        "deliverable_section": derived["deliverable_section"],
        "section_label": derived["section_label"],
        "collection_key": derived["collection_key"],
        "source_root": "00. RAG 소스" if derived["root_group"] else "",
        "source_path": file_path,
        "original_source_path": file_path,
        "input_path": file_path,
        "relative_path": relative_path,
        "snapshot_path": "",
        "extension": Path(file_path).suffix.lower(),
        "file_name": Path(file_path).name,
        "project_name": project_name,
        "project_confidence": 1.0,
        "organization": organization,
        "organization_confidence": 0.8,
        "folder_year": doc.get("project_year") or rag_meta_rules.detect_year(project_name, file_path) or "",
        "folder_name": project_name,
        "search_keywords": search_keywords,
        "extraction_method": result.get("method", ""),
        "is_scanned": (result.get("metadata") or {}).get("is_scanned", False),
        "content_length": len(text),
        "page_count": (result.get("metadata") or {}).get("pages", 0),
        "metadata_confidence": {"project_name": 1.0, "organization": 0.8},
        "extracted_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "result": result,
    }
    return text, metadata


def _build_chunk_rows(document_id: int, text: str, metadata: dict) -> list[dict]:
    rows = build_chunks_for_document(
        metadata=metadata,
        text=text,
        max_chars=1400,
        overlap_chars=180,
        min_chars=250,
    )
    return [dataclasses.asdict(row) for row in rows]


def _embed_rows(rows: list[dict], provider: str) -> tuple[np.ndarray, list[dict]]:
    vectors: list[np.ndarray] = []
    metadata_rows: list[dict] = []
    for row in rows:
        text = row.get("text", "")
        embed_text = truncate_for_embedding(text, 1800)
        vector = ollama_embedding(embed_text, "nomic-embed-text", "http://127.0.0.1:11434/api/embeddings") if provider == "ollama" else hashing_embedding(embed_text, 768)
        vectors.append(vector.astype(np.float32))
        metadata_rows.append({
            "chunk_id": row.get("chunk_id"),
            "document_id": row.get("document_id"),
            "category": row.get("category"),
            "section_heading": row.get("section_heading"),
            "char_count": row.get("char_count"),
            "source_path": row.get("source_path"),
            "input_path": row.get("input_path"),
            "organization": (row.get("metadata", {}) or {}).get("organization", ""),
            "folder_year": (row.get("metadata", {}) or {}).get("folder_year", ""),
            "embedding_text_length": len(embed_text),
            "original_text_length": len(text),
            "metadata": row.get("metadata", {}),
        })
    return np.vstack(vectors).astype(np.float32), metadata_rows


def _append_index(index_path: Path, meta_path: Path, rows: list[dict], provider: str) -> int:
    if not index_path.exists() or not meta_path.exists():
        raise FileNotFoundError(f"snapshot index files not found: {index_path.name}")
    matrix, metadata_rows = _embed_rows(rows, provider)
    index = faiss.read_index(str(index_path))
    index.add(matrix)
    faiss.write_index(index, str(index_path))
    with meta_path.open("a", encoding="utf-8") as handle:
        for row in metadata_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(metadata_rows)


def _update_manifest(snapshot: str, document_ids: list[int], added_chunks: int) -> None:
    manifest_path = _index_paths(snapshot)["manifest"]
    manifest = _read_json(manifest_path, default={})
    counts = dict(manifest.get("counts_by_document") or {})
    for document_id in document_ids:
        counts[str(document_id)] = counts.get(str(document_id), 0)

    meta_rows = 0
    meta_path = _index_paths(snapshot)["meta"]
    if meta_path.exists():
        meta_rows = sum(1 for line in meta_path.read_text(encoding="utf-8").splitlines() if line.strip())

    manifest["embedding_provider"] = manifest.get("embedding_provider") or "ollama"
    manifest["vector_count"] = meta_rows
    manifest["document_count"] = len(counts)
    manifest["counts_by_document"] = counts
    manifest["notes"] = manifest.get("notes") or []
    _write_json(manifest_path, manifest)


def _append_category_index(snapshot: str, category: str, rows: list[dict], provider: str) -> int:
    index_path = FAISS_DIR / f"{snapshot}_{category}_ollama.index"
    meta_path = FAISS_DIR / f"{snapshot}_{category}_ollama_metadata.jsonl"
    if index_path.exists() and meta_path.exists():
        return _append_index(index_path, meta_path, rows, provider)

    matrix, metadata_rows = _embed_rows(rows, provider)
    index = faiss.IndexFlatIP(matrix.shape[1])
    index.add(matrix)
    faiss.write_index(index, str(index_path))
    with meta_path.open("w", encoding="utf-8") as handle:
        for row in metadata_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(metadata_rows)


def _resolve_snapshot(snapshot: str) -> str:
    if snapshot:
        return snapshot
    active = read_active_index() or {}
    resolved = str(active.get("snapshot") or "").strip()
    if not resolved:
        raise RuntimeError("활성 snapshot이 없습니다. 먼저 전체 파이프라인 또는 인덱스 활성화를 실행하세요.")
    return resolved


async def add_documents_to_active_snapshot(
    document_ids: list[int],
    snapshot: str = "",
    collection_key: str = "",
) -> IncrementalRagResult:
    target_snapshot = _resolve_snapshot(snapshot)
    provider = _embedding_provider(target_snapshot)
    paths = _index_paths(target_snapshot)
    if not paths["index"].exists() or not paths["meta"].exists():
        raise FileNotFoundError(f"active snapshot files missing: {target_snapshot}")

    processed = 0
    skipped = 0
    total_chunks = 0
    category_counts = {"rfp": 0, "proposal": 0, "deliverable": 0}

    for document_id in document_ids:
        doc = metadata_db_service.get_document(int(document_id))
        if not doc:
            skipped += 1
            continue

        text, metadata = await _extract_document(doc, collection_key)
        _save_derived_outputs(int(document_id), text, metadata)
        chunks = _build_chunk_rows(int(document_id), text, metadata)
        if not chunks:
            skipped += 1
            continue

        added = _append_index(paths["index"], paths["meta"], chunks, provider)
        _append_category_index(target_snapshot, metadata["category"], chunks, provider)
        total_chunks += added
        processed += 1
        category_counts[metadata["category"]] = category_counts.get(metadata["category"], 0) + 1
        metadata_db_service.update_document(int(document_id), {
            "status": "rag_ready",
            "faiss_snapshot": target_snapshot,
            "chunk_count": len(chunks),
        })
        counts_manifest = _read_json(paths["manifest"], default={})
        counts = dict(counts_manifest.get("counts_by_document") or {})
        counts[str(document_id)] = len(chunks)
        counts_manifest["counts_by_document"] = counts
        counts_manifest["document_count"] = len(counts)
        counts_manifest["vector_count"] = sum(counts.values())
        counts_manifest["embedding_provider"] = provider
        _write_json(paths["manifest"], counts_manifest)

    return IncrementalRagResult(
        snapshot=target_snapshot,
        document_ids=document_ids,
        processed=processed,
        skipped=skipped,
        chunk_count=total_chunks,
        category_counts=category_counts,
        embedding_provider=provider,
    )
