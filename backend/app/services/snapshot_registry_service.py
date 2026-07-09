from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import update

from app.core.database import SessionLocal
from app.models.platform_config import PlatformSnapshot
from app.models.snapshot_manifest import SnapshotManifest
from app.services.active_snapshot_state import get_active_snapshot_id
from app.services.rag_runtime import get_active_snapshot as get_runtime_active_snapshot
from app.services.platform_store import get_record, update_record


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
FAISS_DIR = DATA_DIR / "indexes" / "faiss"
_CATEGORY_SUFFIXES = ("rfp", "proposal", "deliverable")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _index_exists(snapshot_id: str, faiss_index_id: Optional[str] = None) -> bool:
    base_id = str(faiss_index_id or snapshot_id or "").strip()
    if not base_id:
        return False

    primary_index = FAISS_DIR / f"{base_id}_ollama.index"
    primary_meta = FAISS_DIR / f"{base_id}_ollama_metadata.jsonl"
    if primary_index.exists() and primary_meta.exists():
        return True

    for category in _CATEGORY_SUFFIXES:
        cat_index = FAISS_DIR / f"{base_id}_{category}_ollama.index"
        cat_meta = FAISS_DIR / f"{base_id}_{category}_ollama_metadata.jsonl"
        if cat_index.exists() and cat_meta.exists():
            return True
    return False


def _serialize_row(row: PlatformSnapshot) -> dict[str, Any]:
    active_snapshot_id = get_runtime_active_snapshot() or get_active_snapshot_id()
    is_active = (row.snapshot_id == active_snapshot_id) if active_snapshot_id else bool(row.is_active)
    queryable = _index_exists(row.snapshot_id, row.faiss_index_id) or bool(row.queryable)
    return {
        "snapshot_id": row.snapshot_id,
        "snapshot_name": row.snapshot_name or row.snapshot_id,
        "source_id": row.source_id or "",
        "dataset_id": row.dataset_id or "",
        "faiss_index_id": row.faiss_index_id or row.snapshot_id,
        "status": row.status or "",
        "is_active": is_active,
        "queryable": queryable,
        "vector_count": int(row.vector_count or 0),
        "chunk_count": int(row.chunk_count or 0),
        "document_count": int(row.document_count or 0),
        "index_file": row.index_file or "",
        "metadata_file": row.metadata_file or "",
        "manifest_path": row.manifest_path or "",
        "created_at": row.created_at,
        "activated_at": row.activated_at,
        "dataset": {
            "source_id": row.source_id or "",
            "dataset_id": row.dataset_id or "",
            "document_count": int(row.document_count or 0),
            "chunk_count": int(row.chunk_count or 0),
        },
        "rag_build": {
            "faiss_index_id": row.faiss_index_id or row.snapshot_id,
            "vector_count": int(row.vector_count or 0),
            "chunk_count": int(row.chunk_count or 0),
            "index_file": row.index_file or "",
            "metadata_file": row.metadata_file or "",
        },
    }


def _payload_from_manifest(snapshot: SnapshotManifest) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_name": snapshot.snapshot_name or snapshot.snapshot_id,
        "source_id": snapshot.dataset.source_id,
        "dataset_id": snapshot.dataset.dataset_id,
        "faiss_index_id": snapshot.rag_build.faiss_index_id or snapshot.snapshot_id,
        "status": snapshot.status.value,
        "is_active": bool(snapshot.is_active),
        "queryable": _index_exists(snapshot.snapshot_id, snapshot.rag_build.faiss_index_id),
        "vector_count": int(snapshot.rag_build.vector_count or 0),
        "chunk_count": int(snapshot.rag_build.chunk_count or 0),
        "document_count": int(snapshot.dataset.document_count or 0),
        "index_file": snapshot.rag_build.index_file or "",
        "metadata_file": snapshot.rag_build.metadata_file or "",
        "manifest_path": str(SNAPSHOT_DIR / f"{snapshot.snapshot_id}.json"),
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "activated_at": snapshot.activated_at.isoformat() if snapshot.activated_at else None,
        "updated_at": _now_iso(),
    }


def upsert_snapshot_payload(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot_id = str(payload.get("snapshot_id") or "").strip()
    if not snapshot_id:
        raise ValueError("snapshot_id is required")

    data = {
        "snapshot_id": snapshot_id,
        "snapshot_name": payload.get("snapshot_name") or snapshot_id,
        "source_id": payload.get("source_id") or "",
        "dataset_id": payload.get("dataset_id") or "",
        "faiss_index_id": payload.get("faiss_index_id") or snapshot_id,
        "status": payload.get("status") or "",
        "is_active": bool(payload.get("is_active")),
        "queryable": bool(payload.get("queryable")),
        "vector_count": int(payload.get("vector_count") or 0),
        "chunk_count": int(payload.get("chunk_count") or 0),
        "document_count": int(payload.get("document_count") or 0),
        "index_file": payload.get("index_file") or "",
        "metadata_file": payload.get("metadata_file") or "",
        "manifest_path": payload.get("manifest_path") or "",
        "created_at": payload.get("created_at"),
        "activated_at": payload.get("activated_at"),
        "updated_at": _now_iso(),
    }

    db = SessionLocal()
    try:
        row = db.query(PlatformSnapshot).filter(PlatformSnapshot.snapshot_id == snapshot_id).first()
        if row is None:
            db.add(PlatformSnapshot(**data))
        else:
            for key, value in data.items():
                setattr(row, key, value)
        db.commit()
        row = db.query(PlatformSnapshot).filter(PlatformSnapshot.snapshot_id == snapshot_id).first()
        return _serialize_row(row) if row else data
    finally:
        db.close()


def upsert_snapshot_manifest(snapshot: SnapshotManifest) -> dict[str, Any]:
    return upsert_snapshot_payload(_payload_from_manifest(snapshot))


def _ensure_dataset_status(
    source_id: Optional[str],
    dataset_id: Optional[str],
    dataset_status: str,
) -> None:
    sid = str(source_id or "").strip()
    if not sid:
        return
    record = get_record("document_sources", "source_id", sid) or {}
    updates: dict[str, Any] = {
        "dataset_status": dataset_status,
    }
    resolved_dataset_id = str(dataset_id or record.get("dataset_id") or "").strip()
    if resolved_dataset_id:
        updates["dataset_id"] = resolved_dataset_id
        if not record.get("dataset_created_at"):
            updates["dataset_created_at"] = _now_iso()
    update_record("document_sources", "source_id", sid, updates)


def mark_snapshot_queryable(
    snapshot_id: str,
    *,
    source_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
    status: str = "queryable",
    vector_count: Optional[int] = None,
    chunk_count: Optional[int] = None,
    document_count: Optional[int] = None,
    index_file: Optional[str] = None,
    metadata_file: Optional[str] = None,
    manifest_path: Optional[str] = None,
) -> dict[str, Any]:
    current = get_snapshot_registry(snapshot_id) or {}
    payload = {
        "snapshot_id": snapshot_id,
        "snapshot_name": current.get("snapshot_name") or snapshot_id,
        "source_id": source_id or current.get("source_id") or "",
        "dataset_id": dataset_id or current.get("dataset_id") or "",
        "faiss_index_id": current.get("faiss_index_id") or snapshot_id,
        "status": status or current.get("status") or "queryable",
        "is_active": bool(current.get("is_active")),
        "queryable": True,
        "vector_count": vector_count if vector_count is not None else current.get("vector_count") or 0,
        "chunk_count": chunk_count if chunk_count is not None else current.get("chunk_count") or 0,
        "document_count": document_count if document_count is not None else current.get("document_count") or 0,
        "index_file": index_file or current.get("index_file") or "",
        "metadata_file": metadata_file or current.get("metadata_file") or "",
        "manifest_path": manifest_path or current.get("manifest_path") or "",
        "created_at": current.get("created_at"),
        "activated_at": current.get("activated_at"),
    }
    row = upsert_snapshot_payload(payload)
    _ensure_dataset_status(
        payload.get("source_id"),
        payload.get("dataset_id"),
        "queryable" if payload.get("queryable") else "draft",
    )
    return row


def activate_snapshot_registry(
    snapshot_id: str,
    *,
    source_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
    activated_at: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    snapshot_id = str(snapshot_id or "").strip()
    if not snapshot_id:
        return None

    current = get_snapshot_registry(snapshot_id) or {}
    resolved_source_id = str(source_id or current.get("source_id") or "").strip()
    resolved_dataset_id = str(dataset_id or current.get("dataset_id") or "").strip()
    activated_value = str(activated_at or _now_iso())

    db = SessionLocal()
    previous_active_source_ids: list[str] = []
    try:
        prev_rows = db.query(PlatformSnapshot).filter(PlatformSnapshot.is_active.is_(True)).all()
        previous_active_source_ids = [
            str(row.source_id or "").strip()
            for row in prev_rows
            if str(row.source_id or "").strip() and str(row.snapshot_id or "").strip() != snapshot_id
        ]
        db.execute(update(PlatformSnapshot).values(is_active=False))

        row = db.query(PlatformSnapshot).filter(PlatformSnapshot.snapshot_id == snapshot_id).first()
        if row is None:
            row = PlatformSnapshot(
                snapshot_id=snapshot_id,
                snapshot_name=snapshot_id,
                source_id=resolved_source_id,
                dataset_id=resolved_dataset_id,
                faiss_index_id=snapshot_id,
                status="active",
                is_active=True,
                queryable=True,
                activated_at=activated_value,
                updated_at=_now_iso(),
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            payload = _serialize_row(row)
        else:
            row.source_id = resolved_source_id or row.source_id
            row.dataset_id = resolved_dataset_id or row.dataset_id
            row.status = "active"
            row.is_active = True
            row.queryable = True
            row.activated_at = activated_value
            row.updated_at = _now_iso()
            db.commit()
            db.refresh(row)
            payload = _serialize_row(row)
    finally:
        db.close()

    _ensure_dataset_status(resolved_source_id, resolved_dataset_id, "active")
    for previous_source_id in previous_active_source_ids:
        if previous_source_id != resolved_source_id:
            _ensure_dataset_status(previous_source_id, None, "queryable")
    return payload


def sync_snapshot_registry_from_files(source_id: Optional[str] = None) -> list[dict[str, Any]]:
    if not SNAPSHOT_DIR.exists():
        return []

    synced: list[dict[str, Any]] = []
    for path in sorted(SNAPSHOT_DIR.glob("snapshot_*.json"), reverse=True):
        if path.name == "active_snapshot.json":
            continue
        try:
            snapshot = SnapshotManifest(**json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if source_id and str(snapshot.dataset.source_id or "").strip() != str(source_id).strip():
            continue
        synced.append(upsert_snapshot_manifest(snapshot))
    return synced


def list_snapshot_registry(source_id: Optional[str] = None, limit: Optional[int] = None) -> list[dict[str, Any]]:
    try:
        db = SessionLocal()
        try:
            query = db.query(PlatformSnapshot)
            if source_id:
                query = query.filter(PlatformSnapshot.source_id == source_id)
            rows = query.order_by(
                PlatformSnapshot.is_active.desc(),
                PlatformSnapshot.activated_at.desc(),
                PlatformSnapshot.created_at.desc(),
                PlatformSnapshot.snapshot_id.desc(),
            ).all()
        finally:
            db.close()
    except SQLAlchemyError:
        rows = []

    if not rows:
        sync_snapshot_registry_from_files(source_id=source_id)
        db = SessionLocal()
        try:
            query = db.query(PlatformSnapshot)
            if source_id:
                query = query.filter(PlatformSnapshot.source_id == source_id)
            rows = query.order_by(
                PlatformSnapshot.is_active.desc(),
                PlatformSnapshot.activated_at.desc(),
                PlatformSnapshot.created_at.desc(),
                PlatformSnapshot.snapshot_id.desc(),
            ).all()
        finally:
            db.close()

    serialized = [_serialize_row(row) for row in rows]
    return serialized[:limit] if limit and limit > 0 else serialized


def get_snapshot_registry(snapshot_id: str) -> Optional[dict[str, Any]]:
    snapshot_id = str(snapshot_id or "").strip()
    if not snapshot_id:
        return None

    db = SessionLocal()
    try:
        row = db.query(PlatformSnapshot).filter(PlatformSnapshot.snapshot_id == snapshot_id).first()
    finally:
        db.close()

    if row:
        return _serialize_row(row)

    sync_snapshot_registry_from_files()
    db = SessionLocal()
    try:
        row = db.query(PlatformSnapshot).filter(PlatformSnapshot.snapshot_id == snapshot_id).first()
        return _serialize_row(row) if row else None
    finally:
        db.close()
