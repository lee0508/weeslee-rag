from __future__ import annotations

from typing import Any

from app.services.platform_store import create_record, get_record, update_record

STORE_NAME = "active_snapshot_state"
RECORD_ID = "default"

DEFAULT_ACTIVE_SNAPSHOT_STATE: dict[str, Any] = {
    "id": RECORD_ID,
    "active_snapshot_id": "",
    "snapshot_id": "",
    "snapshot_name": "",
    "faiss_index_id": "",
    "source_id": "",
    "dataset_id": "",
    "index_file": "",
    "metadata_file": "",
    "embedding_provider": "ollama",
    "vector_count": 0,
    "document_count": 0,
    "chunk_count": 0,
    "tag_keyword_build_id": "",
    "graph_build_id": "",
    "ontology_id": "",
    "wiki_build_id": "",
    "activated_at": "",
    "activated_by": "",
    "previous_snapshot_id": "",
    "rollback_available": False,
    "notes": "",
}


def _normalize_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    normalized = {
        **DEFAULT_ACTIVE_SNAPSHOT_STATE,
        **(payload or {}),
        "id": RECORD_ID,
    }
    snapshot_id = str(
        normalized.get("active_snapshot_id")
        or normalized.get("snapshot_id")
        or ""
    ).strip()
    normalized["active_snapshot_id"] = snapshot_id
    normalized["snapshot_id"] = snapshot_id
    normalized["faiss_index_id"] = str(
        normalized.get("faiss_index_id") or snapshot_id
    ).strip()
    normalized["embedding_provider"] = str(
        normalized.get("embedding_provider") or "ollama"
    ).strip() or "ollama"
    normalized["rollback_available"] = bool(normalized.get("rollback_available"))
    for key in ("vector_count", "document_count", "chunk_count"):
        try:
            normalized[key] = int(normalized.get(key) or 0)
        except Exception:
            normalized[key] = 0
    return normalized


def get_active_snapshot_state() -> dict[str, Any]:
    saved = get_record(STORE_NAME, "id", RECORD_ID) or {}
    return _normalize_payload(saved)


def get_active_snapshot_id() -> str:
    state = get_active_snapshot_state()
    return str(
        state.get("active_snapshot_id")
        or state.get("snapshot_id")
        or ""
    ).strip()


def save_active_snapshot_state(payload: dict[str, Any]) -> dict[str, Any]:
    current = get_record(STORE_NAME, "id", RECORD_ID)
    merged = _normalize_payload(
        {
            **(current or {}),
            **payload,
        }
    )
    if current:
        return update_record(STORE_NAME, "id", RECORD_ID, merged) or merged
    return create_record(STORE_NAME, merged, "id")
