from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.document_metadata import DocumentMetadata
from app.services.dataset_context import get_source_dataset_context
from app.services.platform_store import get_record
from app.services.snapshot_registry_service import list_snapshot_registry

# [2026-07-08] structured 파일 경로 확인을 위한 resolver 임포트
try:
    from app.services.structured_content_resolver import StructuredContentResolver
    HAS_STRUCTURED_RESOLVER = True
except ImportError:
    HAS_STRUCTURED_RESOLVER = False
    StructuredContentResolver = None


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
SOURCE_ROOT = DATA_DIR / "source"

# [2026-07-08] structured 파일 루트 경로 (네트워크 드라이브 매핑)
STRUCTURED_TXT_ROOT = Path("//c/xampp/htdocs/weeslee-mnt/structured_txt/00. RAG 소스")
STRUCTURED_JSON_ROOT = Path("//c/xampp/htdocs/weeslee-mnt/structured_json/00. RAG 소스")


def _now_iso() -> str:
    return datetime.now().isoformat()


def _find_structured_paths(relative_path: str) -> dict[str, Optional[str]]:
    """
    [2026-07-08] 문서의 relative_path로 structured_txt/structured_json 파일 경로를 찾음.

    Returns:
        {"structured_txt_path": "...", "structured_json_path": "..."} 또는 None
    """
    result: dict[str, Optional[str]] = {
        "structured_txt_path": None,
        "structured_json_path": None,
    }

    if not relative_path:
        return result

    # relative_path에서 파일명 추출하고 확장자 변경
    rel_path = Path(relative_path)
    stem = rel_path.stem  # 확장자 제외한 파일명
    parent = rel_path.parent

    # structured_txt 경로 확인 (.txt)
    txt_candidates = [
        STRUCTURED_TXT_ROOT / parent / f"{stem}.txt",
        STRUCTURED_TXT_ROOT / relative_path.replace(".hwp", ".txt").replace(".hwpx", ".txt").replace(".pdf", ".txt"),
    ]
    for txt_path in txt_candidates:
        if txt_path.exists():
            # 상대 경로로 저장 (structured_txt 루트 기준)
            try:
                result["structured_txt_path"] = str(txt_path.relative_to(STRUCTURED_TXT_ROOT.parent))
            except ValueError:
                result["structured_txt_path"] = str(txt_path)
            break

    # structured_json 경로 확인 (.json)
    json_candidates = [
        STRUCTURED_JSON_ROOT / parent / f"{stem}.json",
        STRUCTURED_JSON_ROOT / relative_path.replace(".hwp", ".json").replace(".hwpx", ".json").replace(".pdf", ".json"),
    ]
    for json_path in json_candidates:
        if json_path.exists():
            try:
                result["structured_json_path"] = str(json_path.relative_to(STRUCTURED_JSON_ROOT.parent))
            except ValueError:
                result["structured_json_path"] = str(json_path)
            break

    return result


def _source_dir(source_id: str) -> Path:
    return SOURCE_ROOT / str(source_id or "").strip()


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def _serialize_document(row: DocumentMetadata) -> dict[str, Any]:
    # [2026-07-08] structured 파일 경로 추가
    structured_paths = _find_structured_paths(row.relative_path or "")

    return {
        "document_id": row.document_id,
        "source_id": row.source_id or "",
        "dataset_id": row.dataset_id or "",
        "document_uid": row.document_uid or "",
        "relative_path": row.relative_path or "",
        "file_name": row.file_name or "",
        "file_type": row.file_type or "",
        "file_size": int(row.file_size or 0),
        "category_id": row.category_id or "",
        "document_group": row.document_group or "",
        "section_type": row.section_type or "",
        "status": row.status or "",
        "meta_status": row.meta_status or "",
        "faiss_snapshot": row.faiss_snapshot or "",
        "chunk_count": int(row.chunk_count or 0),
        "include_in_rag": bool(row.include_in_rag),
        "include_in_graph": bool(row.include_in_graph),
        "include_in_wiki": bool(row.include_in_wiki),
        "removed_at": row.removed_at.isoformat() if row.removed_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        # [2026-07-08] structured 파일 경로 필드 추가
        "structured_txt_path": structured_paths.get("structured_txt_path"),
        "structured_json_path": structured_paths.get("structured_json_path"),
        "has_structured_content": bool(
            structured_paths.get("structured_txt_path") or structured_paths.get("structured_json_path")
        ),
    }


def sync_source_record(source_id: str, source_record: Optional[dict[str, Any]] = None) -> Optional[Path]:
    sid = str(source_id or "").strip()
    if not sid:
        return None
    record = source_record or get_record("document_sources", "source_id", sid) or {}
    payload = {
        **record,
        "source_id": sid,
        "synced_at": _now_iso(),
    }
    return _write_json(_source_dir(sid) / "source.json", payload)


def sync_source_dataset(source_id: str, source_record: Optional[dict[str, Any]] = None) -> Optional[Path]:
    sid = str(source_id or "").strip()
    if not sid:
        return None
    record = source_record or get_record("document_sources", "source_id", sid) or {}
    ctx = get_source_dataset_context(sid)
    payload = {
        "source_id": sid,
        "dataset_id": ctx.get("dataset_id") or "",
        "dataset_status": ctx.get("dataset_status") or "",
        "dataset_created_at": ctx.get("dataset_created_at"),
        "client_id": record.get("client_id") or "",
        "source_name": record.get("source_name") or "",
        "last_checked_at": record.get("last_checked_at"),
        "last_scanned_at": record.get("last_scanned_at"),
        "needs_rag_build": bool(record.get("needs_rag_build")),
        "next_action": record.get("next_action") or "",
        "synced_at": _now_iso(),
    }
    return _write_json(_source_dir(sid) / "dataset.json", payload)


def sync_source_documents(source_id: str, db: Session) -> Optional[Path]:
    sid = str(source_id or "").strip()
    if not sid:
        return None
    rows = (
        db.query(DocumentMetadata)
        .filter(DocumentMetadata.source_id == sid)
        .order_by(DocumentMetadata.document_id.asc())
        .all()
    )
    payload = [_serialize_document(row) for row in rows]
    return _write_jsonl(_source_dir(sid) / "documents.jsonl", payload)


def sync_source_snapshots(source_id: str) -> Optional[Path]:
    sid = str(source_id or "").strip()
    if not sid:
        return None
    snapshots = list_snapshot_registry(source_id=sid)
    payload = {
        "source_id": sid,
        "count": len(snapshots),
        "items": snapshots,
        "synced_at": _now_iso(),
    }
    _write_json(_source_dir(sid) / "snapshots.json", payload)

    latest = next((item for item in snapshots if item.get("is_active")), None) or (snapshots[0] if snapshots else None)
    latest_payload = {
        "source_id": sid,
        "latest_snapshot": latest or {},
        "synced_at": _now_iso(),
    }
    return _write_json(_source_dir(sid) / "latest_snapshot.json", latest_payload)


def sync_source_inventory(source_id: str, inventory_payload: Optional[dict[str, Any]]) -> Optional[Path]:
    sid = str(source_id or "").strip()
    if not sid or inventory_payload is None:
        return None
    payload = {
        "source_id": sid,
        "inventory": inventory_payload,
        "synced_at": _now_iso(),
    }
    return _write_json(_source_dir(sid) / "inventory.json", payload)


def sync_source_index(
    source_id: str,
    db: Optional[Session] = None,
    source_record: Optional[dict[str, Any]] = None,
    inventory_payload: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    sid = str(source_id or "").strip()
    if not sid:
        return {}

    paths: dict[str, str] = {}
    source_path = sync_source_record(sid, source_record=source_record)
    if source_path:
        paths["source"] = str(source_path)
    dataset_path = sync_source_dataset(sid, source_record=source_record)
    if dataset_path:
        paths["dataset"] = str(dataset_path)
    inventory_path = sync_source_inventory(sid, inventory_payload)
    if inventory_path:
        paths["inventory"] = str(inventory_path)
    if db is not None:
        docs_path = sync_source_documents(sid, db)
        if docs_path:
            paths["documents"] = str(docs_path)
    snapshots_path = sync_source_snapshots(sid)
    if snapshots_path:
        paths["latest_snapshot"] = str(snapshots_path)
    return paths
