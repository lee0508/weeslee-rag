from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.api.graph import _manifest as graph_manifest
from app.api.wiki import _get_wiki_type_dir
from app.models.document_metadata import DocumentMetadata, MetaStatus, ProcessingStatus
from app.services.dataset_context import get_source_dataset_context
from app.services.processed_text_store import processed_text_store
from app.services.snapshot_registry_service import list_snapshot_registry


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

    for row in rows:
        doc_id = str(row.document_id)
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

        ocr_report = processed_text_store.get_report(doc_id)
        if ocr_report:
            ocr_report_count += 1
        if processed_text_store.get_text(doc_id, "txt"):
            ocr_text_count += 1
        if processed_text_store.get_stage_file_path(doc_id, "ocr", "pages.jsonl"):
            ocr_pages_count += 1
        if processed_text_store.get_structured_data(doc_id):
            structured_data_count += 1
        if processed_text_store.get_stage_file_path(doc_id, "chunk", "chunks.json"):
            chunk_file_count += 1
        if processed_text_store.get_stage_file_path(doc_id, "chunk", "chunk_pages.json"):
            chunk_pages_count += 1
        if processed_text_store.get_stage_file_path(doc_id, "embedding", "embeddings.pkl"):
            embedding_file_count += 1
        embedding_meta = processed_text_store.load_embedding_metadata(doc_id)
        if embedding_meta:
            embedding_meta_count += 1

        doc_root = processed_text_store.get_document_root(doc_id)
        if (doc_root / "id_contract.json").exists():
            id_contract_count += 1
        if (doc_root / "run_config" / "latest.json").exists():
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
                    "id_contract": (doc_root / "id_contract.json").exists(),
                    "ocr_report": bool(ocr_report),
                    "chunk_file": processed_text_store.get_stage_file_path(doc_id, "chunk", "chunks.json") is not None,
                    "embedding_file": processed_text_store.get_stage_file_path(doc_id, "embedding", "embeddings.pkl") is not None,
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
        index_file_exists = _safe_exists(item.get("index_file"))
        metadata_file_exists = _safe_exists(item.get("metadata_file"))
        manifest_exists = _safe_exists(item.get("manifest_path"))
        staged_chunks_exists = (DATA_DIR / "staged" / "chunks" / f"{item.get('snapshot_id')}_chunks.jsonl").exists()
        if item.get("queryable"):
            queryable_count += 1
        if item.get("is_active"):
            active_count += 1
        if index_file_exists and metadata_file_exists and manifest_exists:
            snapshot_artifact_complete += 1
        snapshot_artifacts.append(
            {
                "snapshot_id": item.get("snapshot_id"),
                "dataset_id": item.get("dataset_id"),
                "status": item.get("status"),
                "queryable": bool(item.get("queryable")),
                "is_active": bool(item.get("is_active")),
                "index_file_exists": index_file_exists,
                "metadata_file_exists": metadata_file_exists,
                "manifest_exists": manifest_exists,
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
                "snapshot_linked_count": snapshot_linked_count,
            },
            "embedding": {
                "state": _stage_state(min(embedding_file_count, embedding_meta_count), total_docs),
                "status_ready_count": embedding_ready_count,
                "embedding_file_count": embedding_file_count,
                "embedding_meta_count": embedding_meta_count,
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
