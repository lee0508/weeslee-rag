from datetime import datetime, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from app.services.platform_store import get_record, update_record


_STORE = "document_sources"
_ID_FIELD = "source_id"
_KST = ZoneInfo("Asia/Seoul")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dataset_stamp(value: Optional[str] = None) -> str:
    if value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(_KST).strftime("%Y%m%d_%H%M%S")
        except Exception:
            pass
    return datetime.now(_KST).strftime("%Y%m%d_%H%M%S")


def generate_dataset_id(source_id: str, created_at: Optional[str] = None) -> str:
    return f"dataset_{source_id}_{_dataset_stamp(created_at)}"


def get_source_dataset_context(source_id: str) -> dict:
    record = get_record(_STORE, _ID_FIELD, source_id) or {}
    dataset_id = (record.get("dataset_id") or "").strip() or None
    dataset_status = (record.get("dataset_status") or "").strip()

    if not dataset_status:
        dataset_status = "draft" if dataset_id else "pending"

    return {
        "source_id": source_id,
        "dataset_id": dataset_id,
        "dataset_status": dataset_status,
        "dataset_created_at": record.get("dataset_created_at"),
        "record": record or None,
    }


def ensure_source_dataset_context(source_id: str, force_new: bool = False) -> Tuple[Optional[dict], bool]:
    record = get_record(_STORE, _ID_FIELD, source_id)
    if not record:
        return None, False

    current_dataset_id = (record.get("dataset_id") or "").strip()
    updates = {}
    generated = False

    if not current_dataset_id or force_new:
        updates["dataset_id"] = generate_dataset_id(source_id)
        updates["dataset_status"] = "draft"
        updates["dataset_created_at"] = _utc_now_iso()
        generated = True
    else:
        if not record.get("dataset_status") or record.get("dataset_status") == "pending":
            updates["dataset_status"] = "draft"
        if not record.get("dataset_created_at"):
            updates["dataset_created_at"] = _utc_now_iso()

    if updates:
        record = update_record(_STORE, _ID_FIELD, source_id, updates) or {**record, **updates}

    return {
        "source_id": source_id,
        "dataset_id": (record.get("dataset_id") or "").strip() or None,
        "dataset_status": (record.get("dataset_status") or "").strip() or ("draft" if record.get("dataset_id") else "pending"),
        "dataset_created_at": record.get("dataset_created_at"),
        "record": record,
    }, generated


def update_source_dataset_status(
    source_id: str,
    dataset_status: str,
    *,
    dataset_id: Optional[str] = None,
) -> Optional[dict]:
    source_id = str(source_id or "").strip()
    dataset_status = str(dataset_status or "").strip()
    if not source_id or not dataset_status:
        return None

    record = get_record(_STORE, _ID_FIELD, source_id)
    if not record:
        return None

    updates = {
        "dataset_status": dataset_status,
    }
    resolved_dataset_id = str(dataset_id or record.get("dataset_id") or "").strip()
    if resolved_dataset_id:
        updates["dataset_id"] = resolved_dataset_id
        if not record.get("dataset_created_at"):
            updates["dataset_created_at"] = _utc_now_iso()

    return update_record(_STORE, _ID_FIELD, source_id, updates)
