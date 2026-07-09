from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.api.graph import _manifest as graph_manifest
from app.api.wiki import _get_wiki_type_dir
from app.models.document_metadata import DocumentMetadata, MetaStatus, ProcessingStatus
from app.services.dataset_context import get_source_dataset_context
from app.services.processed_text_store import processed_text_store
from app.services.snapshot_registry_service import list_snapshot_registry
from app.services.source_data_paths import get_source_paths


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
FAISS_DIR = DATA_DIR / "indexes" / "faiss"
WIKI_DIR = DATA_DIR / "wiki"


def _stage_state(complete: int, total: int, *, allow_empty: bool = False) -> str:
    if total <= 0:
        return "empty" if allow_empty else "missing"
    if complete >= total:
        return "ready"
    if complete <= 0:
        return "missing"
    return "partial"


def _safe_exists(path_value: str | Path | None) -> bool:
    if not path_value:
        return False
    try:
        return Path(path_value).exists()
    except Exception:
        return False


def _count_document_ids_from_jsonl(path: Path, *keys: str) -> set[str]:
    if not path.exists():
        return set()
    document_ids: set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            candidate: Any = row
            for key in keys:
                if isinstance(candidate, dict):
                    candidate = candidate.get(key)
                else:
                    candidate = None
                if candidate is None:
                    break
            if candidate:
                document_ids.add(str(candidate))
    except Exception:
        return set()
    return document_ids


def _count_chunk_document_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    document_ids: set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            document_id = row.get("document_id")
            if not document_id:
                document_id = (row.get("metadata") or {}).get("document_id")
            if document_id:
                document_ids.add(str(document_id))
    except Exception:
        return set()
    return document_ids


def _count_wiki_files(source_id: str) -> dict[str, int]:
    project_dir = _get_wiki_type_dir("project", source_id)
    organization_dir = _get_wiki_type_dir("organization", source_id)
    technology_dir = _get_wiki_type_dir("technology", source_id)
    return {
        "project": len(list(project_dir.glob("*.md"))) if project_dir.exists() else 0,
        "organization": len(list(organization_dir.glob("*.md"))) if organization_dir.exists() else 0,
        "technology": len(list(technology_dir.glob("*.md"))) if technology_dir.exists() else 0,
        "build_info": 1 if (WIKI_DIR / source_id / "build_info.json").exists() else 0,
    }


def build_source_validation_report(source_id: str, db: Session) -> dict[str, Any]:
    source_id = str(source_id or "").strip()
    if not source_id:
        return {}

    dataset_context = get_source_dataset_context(source_id)
    source_paths = get_source_paths(source_id)
    rows = (
        db.query(DocumentMetadata)
        .filter(DocumentMetadata.source_id == source_id)
        .order_by(DocumentMetadata.document_id.asc())
        .all()
    )
    total_docs = len(rows)
    dataset_id = str(dataset_context.get("dataset_id") or "")

    id_contract_count = 0
    run_config_latest_count = 0
    document_uid_count = 0
    dataset_match_count = 0
    ocr_report_count = 0
    ocr_text_count = 0
    ocr_pages_count = 0
    structured_data_count = 0
    chunk_file_count = 0
    chunk_pages_count = 0
    chunk_db_count = 0
    embedding_file_count = 0
    embedding_meta_count = 0
    snapshot_linked_count = 0
    final_metadata_count = 0
    sample_documents: list[dict[str, Any]] = []

    source_chunk_doc_ids = _count_chunk_document_ids(source_paths.chunks_jsonl) | _count_chunk_document_ids(source_paths.active_chunks_jsonl)
    source_embedding_doc_ids = (
        _count_document_ids_from_jsonl(source_paths.faiss_metadata_jsonl, "document_id")
        | _count_document_ids_from_jsonl(source_paths.active_metadata_jsonl, "document_id")
    )

    for row in rows:
        doc_id = str(row.document_id)
        source_doc_dir = source_paths.document_dir(doc_id)
        source_ocr_report_path = source_paths.document_ocr_report(doc_id)
        source_full_text_path = source_paths.document_full_text(doc_id)
        source_structured_path = source_paths.document_structured_json(doc_id)
        source_id_contract_path = source_doc_dir / "id_contract.json"
        source_run_config_path = source_doc_dir / "run_config" / "latest.json"
        source_pages_path = source_doc_dir / "pages.jsonl"
        legacy_doc_root = processed_text_store.get_document_root(doc_id)

        if row.document_uid:
            document_uid_count += 1
        if dataset_id and str(row.dataset_id or "").strip() == dataset_id:
            dataset_match_count += 1
        if row.chunk_count and int(row.chunk_count) > 0:
            chunk_db_count += 1
        if row.faiss_snapshot:
            snapshot_linked_count += 1
        if any([
            row.final_project_name,
            row.final_organization,
            row.final_year,
            row.final_document_category,
        ]):
            final_metadata_count += 1

        ocr_report_exists = source_ocr_report_path.exists() or processed_text_store.get_report(doc_id) is not None
        if ocr_report_exists:
            ocr_report_count += 1
        full_text_exists = source_full_text_path.exists() or bool(processed_text_store.get_text(doc_id, "txt"))
        if full_text_exists:
            ocr_text_count += 1
        pages_exists = source_pages_path.exists() or processed_text_store.get_stage_file_path(doc_id, "ocr", "pages.jsonl") is not None
        if pages_exists:
            ocr_pages_count += 1
        structured_exists = source_structured_path.exists() or processed_text_store.get_structured_data(doc_id) is not None
        if structured_exists:
            structured_data_count += 1
        chunk_ready = doc_id in source_chunk_doc_ids or processed_text_store.get_stage_file_path(doc_id, "chunk", "chunks.json") is not None
        if chunk_ready:
            chunk_file_count += 1
        chunk_pages_exists = processed_text_store.get_stage_file_path(doc_id, "chunk", "chunk_pages.json") is not None
        if chunk_pages_exists:
            chunk_pages_count += 1
        embedding_ready = doc_id in source_embedding_doc_ids or processed_text_store.get_stage_file_path(doc_id, "embedding", "embeddings.pkl") is not None
        if embedding_ready:
            embedding_file_count += 1
        embedding_meta = processed_text_store.load_embedding_metadata(doc_id)
        if doc_id in source_embedding_doc_ids or embedding_meta:
            embedding_meta_count += 1

        id_contract_exists = source_id_contract_path.exists() or (legacy_doc_root / "id_contract.json").exists()
        if id_contract_exists:
            id_contract_count += 1
        run_config_exists = source_run_config_path.exists() or (legacy_doc_root / "run_config" / "latest.json").exists()
        if run_config_exists:
            run_config_latest_count += 1

        if len(sample_documents) < 5:
            sample_documents.append(
                {
                    "document_id": row.document_id,
                    "relative_path": row.relative_path or "",
                    "status": row.status or "",
                    "meta_status": row.meta_status or "",
                    "dataset_id": row.dataset_id or "",
                    "faiss_snapshot": row.faiss_snapshot or "",
                    "id_contract": id_contract_exists,
                    "ocr_report": ocr_report_exists,
                    "chunk_file": chunk_ready,
                    "embedding_file": embedding_ready,
                }
            )

    reviewed_count = sum(1 for row in rows if row.meta_status == MetaStatus.METADATA_REVIEWED.value)
    text_ready_count = sum(
        1 for row in rows
        if row.status in {
            ProcessingStatus.TEXT_EXTRACTED.value,
            ProcessingStatus.CHUNKED.value,
            ProcessingStatus.EMBEDDED.value,
            ProcessingStatus.FAISS_INDEXED.value,
            ProcessingStatus.GRAPH_CREATED.value,
            ProcessingStatus.WIKI_CREATED.value,
            ProcessingStatus.RAG_READY.value,
        }
    )
    chunk_ready_count = sum(
        1 for row in rows
        if row.status in {
            ProcessingStatus.CHUNKED.value,
            ProcessingStatus.EMBEDDED.value,
            ProcessingStatus.FAISS_INDEXED.value,
            ProcessingStatus.GRAPH_CREATED.value,
            ProcessingStatus.WIKI_CREATED.value,
            ProcessingStatus.RAG_READY.value,
        }
    )
    embedding_ready_count = sum(
        1 for row in rows
        if row.status in {
            ProcessingStatus.EMBEDDED.value,
            ProcessingStatus.FAISS_INDEXED.value,
            ProcessingStatus.GRAPH_CREATED.value,
            ProcessingStatus.WIKI_CREATED.value,
            ProcessingStatus.RAG_READY.value,
        }
    )

    snapshots = list_snapshot_registry(source_id=source_id)
    snapshot_artifacts = []
    queryable_count = 0
    active_count = 0
    snapshot_artifact_complete = 0
    for item in snapshots:
        snapshot_id = str(item.get("snapshot_id") or "").strip()
        snapshot_source_id = str(item.get("source_id") or source_id).strip()
        snapshot_source_paths = get_source_paths(snapshot_source_id) if snapshot_source_id else None
        index_file_exists = _safe_exists(item.get("index_file"))
        metadata_file_exists = _safe_exists(item.get("metadata_file"))
        manifest_exists = _safe_exists(item.get("manifest_path"))
        source_step6_exists = bool(
            snapshot_source_paths
            and snapshot_source_paths.faiss_index.exists()
            and snapshot_source_paths.faiss_metadata_jsonl.exists()
        )
        source_active_exists = bool(
            snapshot_source_paths
            and snapshot_source_paths.active_faiss_index.exists()
            and snapshot_source_paths.active_metadata_jsonl.exists()
        )
        source_snapshot_state_exists = bool(
            snapshot_source_paths
            and (snapshot_source_paths.latest_snapshot_json.exists() or snapshot_source_paths.snapshots_json.exists())
        )
        staged_chunks_exists = (DATA_DIR / "staged" / "chunks" / f"{snapshot_id}_chunks.jsonl").exists()
        if snapshot_source_paths and not staged_chunks_exists:
            staged_chunks_exists = snapshot_source_paths.chunks_jsonl.exists() or snapshot_source_paths.active_chunks_jsonl.exists()
        if item.get("queryable"):
            queryable_count += 1
        if item.get("is_active"):
            active_count += 1
        if (
            (index_file_exists and metadata_file_exists and manifest_exists)
            or (source_step6_exists and source_snapshot_state_exists)
            or (source_active_exists and source_snapshot_state_exists)
        ):
            snapshot_artifact_complete += 1
        snapshot_artifacts.append(
            {
                "snapshot_id": snapshot_id,
                "dataset_id": item.get("dataset_id"),
                "status": item.get("status"),
                "queryable": bool(item.get("queryable")),
                "is_active": bool(item.get("is_active")),
                "index_file_exists": index_file_exists,
                "metadata_file_exists": metadata_file_exists,
                "manifest_exists": manifest_exists,
                "source_step6_exists": source_step6_exists,
                "source_active_exists": source_active_exists,
                "staged_chunks_exists": staged_chunks_exists,
            }
        )

    graph_data = graph_manifest(source_id)
    graph_dir = DATA_DIR / "indexes" / "graph" / source_id
    graph_nodes_exists = (graph_dir / "graph_nodes.jsonl").exists()
    graph_edges_exists = (graph_dir / "graph_edges.jsonl").exists()
    graph_manifest_exists = (graph_dir / "graph_manifest.json").exists()

    wiki_counts = _count_wiki_files(source_id)
    wiki_total = wiki_counts["project"] + wiki_counts["organization"] + wiki_counts["technology"]

    return {
        "source_id": source_id,
        "dataset_id": dataset_id,
        "dataset_status": dataset_context.get("dataset_status"),
        "document_count": total_docs,
        "stages": {
            "id_management": {
                "state": _stage_state(min(document_uid_count, id_contract_count, run_config_latest_count), total_docs),
                "document_uid_count": document_uid_count,
                "id_contract_count": id_contract_count,
                "run_config_latest_count": run_config_latest_count,
                "dataset_match_count": dataset_match_count,
            },
            "metadata": {
                "state": _stage_state(max(reviewed_count, final_metadata_count), total_docs),
                "reviewed_count": reviewed_count,
                "final_metadata_count": final_metadata_count,
            },
            "ocr": {
                "state": _stage_state(min(ocr_report_count, ocr_text_count), total_docs),
                "status_ready_count": text_ready_count,
                "ocr_report_count": ocr_report_count,
                "full_text_count": ocr_text_count,
                "pages_count": ocr_pages_count,
                "structured_data_count": structured_data_count,
            },
            "chunk": {
                "state": _stage_state(min(chunk_file_count, chunk_db_count), total_docs),
                "status_ready_count": chunk_ready_count,
                "chunk_file_count": chunk_file_count,
                "chunk_pages_count": chunk_pages_count,
                "chunk_db_count": chunk_db_count,
                "source_chunk_document_count": len(source_chunk_doc_ids),
                "snapshot_linked_count": snapshot_linked_count,
            },
            "embedding": {
                "state": _stage_state(min(embedding_file_count, embedding_meta_count), total_docs),
                "status_ready_count": embedding_ready_count,
                "embedding_file_count": embedding_file_count,
                "embedding_meta_count": embedding_meta_count,
                "source_embedding_document_count": len(source_embedding_doc_ids),
            },
            "faiss": {
                "state": _stage_state(snapshot_artifact_complete, len(snapshots), allow_empty=True),
                "snapshot_count": len(snapshots),
                "queryable_count": queryable_count,
                "active_count": active_count,
                "artifact_complete_count": snapshot_artifact_complete,
                "snapshots": snapshot_artifacts,
            },
            "graph": {
                "state": "ready" if graph_nodes_exists and graph_edges_exists and graph_manifest_exists else "missing",
                "node_count": int(graph_data.get("node_count") or 0),
                "edge_count": int(graph_data.get("edge_count") or 0),
                "manifest_exists": graph_manifest_exists,
                "nodes_exists": graph_nodes_exists,
                "edges_exists": graph_edges_exists,
                "built_at": graph_data.get("built_at"),
            },
            "wiki": {
                "state": "ready" if wiki_total > 0 else "missing",
                "project_count": wiki_counts["project"],
                "organization_count": wiki_counts["organization"],
                "technology_count": wiki_counts["technology"],
                "build_info_exists": bool(wiki_counts["build_info"]),
                "total_count": wiki_total,
            },
        },
        "sample_documents": sample_documents,
    }
