from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.platform_store import list_records
from app.services.rag_runtime import get_active_snapshot
from app.services.snapshot_registry_service import list_snapshot_registry


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
FAISS_DIR = DATA_DIR / "indexes" / "faiss"
CONFIG_DIR = DATA_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "search_profiles.json"
_CATEGORY_SUFFIXES = {"rfp", "proposal", "deliverable"}


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _default_config() -> dict[str, Any]:
    return {
        "default_scope_id": "active_snapshot",
        "profiles": [],
        "updated_at": None,
    }


def _load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return _default_config()
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return _default_config()
    if not isinstance(data, dict):
        return _default_config()
    return {
        "default_scope_id": str(data.get("default_scope_id") or "active_snapshot"),
        "profiles": data.get("profiles") if isinstance(data.get("profiles"), list) else [],
        "updated_at": data.get("updated_at"),
    }


def save_default_scope_id(scope_id: str) -> dict[str, Any]:
    config = _load_config()
    config["default_scope_id"] = str(scope_id or "active_snapshot").strip() or "active_snapshot"
    config["updated_at"] = _now_iso()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return config


def _faiss_index_exists(snapshot: dict[str, Any]) -> bool:
    faiss_id = str(snapshot.get("faiss_index_id") or snapshot.get("snapshot_id") or "").strip()
    if not faiss_id:
        return False
    # 메인 인덱스 확인
    index_path = FAISS_DIR / f"{faiss_id}_ollama.index"
    meta_path = FAISS_DIR / f"{faiss_id}_ollama_metadata.jsonl"
    if index_path.exists() and meta_path.exists():
        return True
    # 카테고리별 인덱스 fallback (rfp, proposal, deliverable)
    for cat in _CATEGORY_SUFFIXES:
        cat_index = FAISS_DIR / f"{faiss_id}_{cat}_ollama.index"
        cat_meta = FAISS_DIR / f"{faiss_id}_{cat}_ollama_metadata.jsonl"
        if cat_index.exists() and cat_meta.exists():
            return True
    return False


def _snapshot_sort_key(snapshot: dict[str, Any]) -> tuple:
    return (
        1 if snapshot.get("is_active") else 0,
        1 if _faiss_index_exists(snapshot) else 0,
        int(snapshot.get("vector_count") or 0),
        snapshot.get("activated_at") or "",
        snapshot.get("created_at") or "",
    )


def _source_record_map() -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    try:
        for row in list_records("document_sources"):
            source_id = str(row.get("source_id") or "").strip()
            if not source_id:
                continue
            records[source_id] = row
    except Exception:
        return records
    return records


def _parse_source_id_from_snapshot(snapshot_id: str) -> str:
    value = str(snapshot_id or "").strip()
    if not value.startswith("snapshot_"):
        return ""
    parts = value.replace("snapshot_", "", 1).split("_")
    if len(parts) < 3:
        return ""
    source_parts = [part for part in parts[1:] if not part.lower().startswith("v")]
    return "_".join(source_parts).strip()


def _list_faiss_snapshot_names() -> list[str]:
    if not FAISS_DIR.exists():
        return []
    names: set[str] = set()
    for path in FAISS_DIR.glob("*_ollama.index"):
        stem = path.name[: -len("_ollama.index")]
        parts = stem.rsplit("_", 1)
        # 카테고리 인덱스면 base snapshot ID 추출
        if len(parts) == 2 and parts[1] in _CATEGORY_SUFFIXES:
            names.add(parts[0])
        else:
            names.add(stem)
    return sorted(names, reverse=True)


def _build_snapshot_registry() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    source_records = _source_record_map()
    source_names = {
        source_id: str(row.get("source_name") or source_id).strip() or source_id
        for source_id, row in source_records.items()
    }
    registry: dict[str, dict[str, Any]] = {}
    known_snapshot_ids: set[str] = set()
    known_faiss_index_ids: set[str] = set()
    snapshot_rows = list_snapshot_registry()
    for snap in sorted(snapshot_rows, key=_snapshot_sort_key, reverse=True):
        source_id = str(snap.get("source_id") or "").strip()
        if not source_id:
            continue
        known_snapshot_ids.add(str(snap.get("snapshot_id") or ""))
        info = registry.setdefault(
            source_id,
            {
                "source_id": source_id,
                "source_name": source_names.get(source_id, source_id),
                "dataset_id": str(snap.get("dataset_id") or source_records.get(source_id, {}).get("dataset_id") or "").strip(),
                "dataset_status": str(source_records.get(source_id, {}).get("dataset_status") or "").strip(),
                "snapshots": [],
                "latest_queryable_snapshot": "",
                "active_snapshot_id": "",
            },
        )
        faiss_index_id = str(snap.get("faiss_index_id") or snap.get("snapshot_id") or "").strip()
        if faiss_index_id:
            known_faiss_index_ids.add(faiss_index_id)
        snapshot_entry = {
            "snapshot_id": str(snap.get("snapshot_id") or ""),
            "faiss_index_id": faiss_index_id,
            "dataset_id": str(snap.get("dataset_id") or ""),
            "is_active": bool(snap.get("is_active")),
            "status": str(snap.get("status") or ""),
            "vector_count": int(snap.get("vector_count") or 0),
            "chunk_count": int(snap.get("chunk_count") or 0),
            "document_count": int(snap.get("document_count") or 0),
            "created_at": snap.get("created_at"),
            "activated_at": snap.get("activated_at"),
            "queryable": bool(snap.get("queryable")) or _faiss_index_exists(snap),
        }
        info["snapshots"].append(snapshot_entry)
        if snapshot_entry["is_active"] and not info["active_snapshot_id"]:
            info["active_snapshot_id"] = snapshot_entry["snapshot_id"]
        if snapshot_entry["queryable"] and not info["latest_queryable_snapshot"]:
            info["latest_queryable_snapshot"] = snapshot_entry["snapshot_id"]

    for snapshot_id in _list_faiss_snapshot_names():
        if snapshot_id in known_snapshot_ids or snapshot_id in known_faiss_index_ids:
            continue
        source_id = _parse_source_id_from_snapshot(snapshot_id)
        if not source_id:
            continue
        if source_id not in source_names and not (
            source_id.startswith("src_") or source_id.startswith("rag_source")
        ):
            continue
        info = registry.setdefault(
            source_id,
            {
                "source_id": source_id,
                "source_name": source_names.get(source_id, source_id),
                "dataset_id": str(source_records.get(source_id, {}).get("dataset_id") or "").strip(),
                "dataset_status": str(source_records.get(source_id, {}).get("dataset_status") or "").strip(),
                "snapshots": [],
                "latest_queryable_snapshot": "",
                "active_snapshot_id": "",
            },
        )
        if any(str(item.get("snapshot_id") or "") == snapshot_id for item in info["snapshots"]):
            continue
        info["snapshots"].append(
            {
                "snapshot_id": snapshot_id,
                "dataset_id": "",
                "is_active": snapshot_id == get_active_snapshot(),
                "status": "indexed",
                "vector_count": 0,
                "chunk_count": 0,
                "document_count": 0,
                "created_at": None,
                "activated_at": None,
                "queryable": True,
            }
        )
        if not info["latest_queryable_snapshot"]:
            info["latest_queryable_snapshot"] = snapshot_id
    return registry, source_names


def _scope_record(
    *,
    scope_id: str,
    label: str,
    description: str,
    scope_type: str,
    snapshot_ids: list[str],
    source_ids: list[str],
    system: bool,
) -> dict[str, Any]:
    snapshots = [value for value in snapshot_ids if value]
    sources = [value for value in source_ids if value]
    return {
        "scope_id": scope_id,
        "label": label,
        "description": description,
        "scope_type": scope_type,
        "snapshot_ids": snapshots,
        "source_ids": sources,
        "snapshot_count": len(snapshots),
        "source_count": len(sources),
        "queryable": bool(snapshots),
        "system": system,
    }


def _resolve_custom_profile(
    profile: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    profile_id = str(profile.get("profile_id") or "").strip()
    label = str(profile.get("label") or profile_id or "Custom Scope").strip()
    description = str(profile.get("description") or "").strip()
    entries = profile.get("entries") if isinstance(profile.get("entries"), list) else []
    snapshot_ids: list[str] = []
    source_ids: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source_id = str(entry.get("source_id") or "").strip()
        snapshot_id = str(entry.get("snapshot_id") or "").strip()
        if snapshot_id:
            snapshot_ids.append(snapshot_id)
        elif source_id and registry.get(source_id, {}).get("latest_queryable_snapshot"):
            snapshot_ids.append(str(registry[source_id]["latest_queryable_snapshot"]))
        if source_id:
            source_ids.append(source_id)
    dedup_snapshot_ids = list(dict.fromkeys(snapshot_ids))
    dedup_source_ids = list(dict.fromkeys(source_ids))
    return _scope_record(
        scope_id=profile_id,
        label=label,
        description=description,
        scope_type="custom",
        snapshot_ids=dedup_snapshot_ids,
        source_ids=dedup_source_ids,
        system=False,
    )


def get_search_scope_catalog() -> dict[str, Any]:
    config = _load_config()
    active_snapshot = get_active_snapshot()
    registry, source_names = _build_snapshot_registry()
    active_source_ids = [
        source_id
        for source_id, info in registry.items()
        if any(
            str(snap.get("snapshot_id") or "") == active_snapshot
            or str(snap.get("faiss_index_id") or "") == active_snapshot
            for snap in info.get("snapshots", [])
        )
    ][:1]

    source_latest = [
        (source_id, info["latest_queryable_snapshot"])
        for source_id, info in registry.items()
        if info.get("latest_queryable_snapshot")
    ]
    source_latest.sort(key=lambda item: source_names.get(item[0], item[0]))

    scopes = [
        _scope_record(
            scope_id="active_snapshot",
            label="현재 Active Snapshot",
            description="기존 운영 방식과 동일하게 현재 활성 스냅샷 1개만 검색합니다.",
            scope_type="active_snapshot",
            snapshot_ids=[active_snapshot] if active_snapshot else [],
            source_ids=active_source_ids,
            system=True,
        ),
        _scope_record(
            scope_id="all_sources",
            label="전체 데이터셋",
            description="Source별 최신 검색 가능 Snapshot을 합쳐서 조회합니다.",
            scope_type="all_sources",
            snapshot_ids=[snapshot_id for _, snapshot_id in source_latest],
            source_ids=[source_id for source_id, _ in source_latest],
            system=True,
        ),
    ]

    for source_id, snapshot_id in source_latest:
        info = registry.get(source_id) or {}
        source_name = str(info.get("source_name") or source_names.get(source_id, source_id))
        scopes.append(
            _scope_record(
                scope_id=f"source:{source_id}",
                label=source_name,
                description=f"{source_name} Source의 최신 검색 가능 Snapshot을 조회합니다.",
                scope_type="source",
                snapshot_ids=[snapshot_id],
                source_ids=[source_id],
                system=True,
            )
        )

    for raw_profile in config.get("profiles", []):
        if not isinstance(raw_profile, dict):
            continue
        profile_id = str(raw_profile.get("profile_id") or "").strip()
        if not profile_id:
            continue
        scopes.append(_resolve_custom_profile(raw_profile, registry))

    by_scope_id = {scope["scope_id"]: scope for scope in scopes}
    default_scope_id = str(config.get("default_scope_id") or "active_snapshot").strip() or "active_snapshot"
    if default_scope_id not in by_scope_id or not by_scope_id[default_scope_id].get("queryable"):
        fallback = next((scope["scope_id"] for scope in scopes if scope.get("queryable")), "active_snapshot")
        default_scope_id = fallback

    for scope in scopes:
        scope["is_default"] = scope["scope_id"] == default_scope_id

    return {
        "default_scope_id": default_scope_id,
        "active_snapshot": active_snapshot,
        "scopes": scopes,
        "sources": list(registry.values()),
        "datasets": [
            {
                "source_id": info.get("source_id") or "",
                "source_name": info.get("source_name") or "",
                "dataset_id": info.get("dataset_id") or "",
                "dataset_status": info.get("dataset_status") or "",
                "selected_snapshot_id": info.get("active_snapshot_id") or info.get("latest_queryable_snapshot") or "",
                "queryable_snapshot_count": len([snap for snap in info.get("snapshots", []) if snap.get("queryable")]),
                "snapshot_count": len(info.get("snapshots", [])),
                "scope_id": f"source:{info.get('source_id')}",
            }
            for info in registry.values()
        ],
        "updated_at": config.get("updated_at"),
    }


def resolve_search_scope(requested_scope_id: str | None) -> dict[str, Any]:
    catalog = get_search_scope_catalog()
    scopes = catalog.get("scopes") or []
    by_scope_id = {scope["scope_id"]: scope for scope in scopes}
    requested = str(requested_scope_id or "").strip()
    selected = by_scope_id.get(requested)
    if not selected:
        selected = by_scope_id.get(str(catalog.get("default_scope_id") or "active_snapshot"))
    if not selected and scopes:
        selected = next((scope for scope in scopes if scope.get("queryable")), scopes[0])
    if not selected:
        selected = _scope_record(
            scope_id="active_snapshot",
            label="현재 Active Snapshot",
            description="검색 가능한 Snapshot이 아직 없습니다.",
            scope_type="active_snapshot",
            snapshot_ids=[],
            source_ids=[],
            system=True,
        )
    return {
        **selected,
        "requested_scope_id": requested or None,
        "default_scope_id": catalog.get("default_scope_id"),
        "active_snapshot": catalog.get("active_snapshot"),
    }
