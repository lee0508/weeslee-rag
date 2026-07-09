from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.document_metadata import DocumentMetadata
from app.services.dataset_context import get_source_dataset_context
from app.services.snapshot_registry_service import list_snapshot_registry


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
DOCUMENTS_DIR = DATA_DIR / "documents"
SOURCE_DIR = DATA_DIR / "source"


def _document_artifact_flags(document_id: int) -> dict[str, bool]:
    base = DOCUMENTS_DIR / str(document_id)
    return {
        "document_root": base.exists(),
        "ocr": (base / "ocr").exists(),
        "chunk": (base / "chunk").exists(),
        "embedding": (base / "embedding").exists(),
        "run_config": (base / "run_config").exists(),
        "id_contract": (base / "id_contract.json").exists(),
    }


def _source_file_flags(source_id: str) -> dict[str, bool]:
    base = SOURCE_DIR / str(source_id or "").strip()
    return {
        "source_root": base.exists(),
        "source_json": (base / "source.json").exists(),
        "dataset_json": (base / "dataset.json").exists(),
        "documents_jsonl": (base / "documents.jsonl").exists(),
        "snapshots_json": (base / "snapshots.json").exists(),
        "latest_snapshot_json": (base / "latest_snapshot.json").exists(),
        "inventory_json": (base / "inventory.json").exists(),
    }


def build_source_storage_audit(source_id: str, db: Session) -> dict[str, Any]:
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

    status_rows = (
        db.query(
            DocumentMetadata.status,
            func.count(DocumentMetadata.document_id),
        )
        .filter(DocumentMetadata.source_id == source_id)
        .group_by(DocumentMetadata.status)
        .all()
    )
    meta_status_rows = (
        db.query(
            DocumentMetadata.meta_status,
            func.count(DocumentMetadata.document_id),
        )
        .filter(DocumentMetadata.source_id == source_id)
        .group_by(DocumentMetadata.meta_status)
        .all()
    )

    artifact_counts = {
        "document_root": 0,
        "ocr": 0,
        "chunk": 0,
        "embedding": 0,
        "run_config": 0,
        "id_contract": 0,
    }
    sample_documents: list[dict[str, Any]] = []
    for row in rows:
        flags = _document_artifact_flags(row.document_id)
        for key, value in flags.items():
            if value:
                artifact_counts[key] += 1
        if len(sample_documents) < 5:
            sample_documents.append(
                {
                    "document_id": row.document_id,
                    "relative_path": row.relative_path or "",
                    "status": row.status or "",
                    "meta_status": row.meta_status or "",
                    "faiss_snapshot": row.faiss_snapshot or "",
                    "chunk_count": int(row.chunk_count or 0),
                    "artifacts": flags,
                }
            )

    snapshots = list_snapshot_registry(source_id=source_id)
    return {
        "source_id": source_id,
        "dataset_id": dataset_context.get("dataset_id"),
        "dataset_status": dataset_context.get("dataset_status"),
        "dataset_created_at": dataset_context.get("dataset_created_at"),
        "source_files": _source_file_flags(source_id),
        "document_count": len(rows),
        "status_counts": {str(status or ""): int(count or 0) for status, count in status_rows},
        "meta_status_counts": {str(status or ""): int(count or 0) for status, count in meta_status_rows},
        "artifact_counts": artifact_counts,
        "snapshots": snapshots,
        "sample_documents": sample_documents,
    }
