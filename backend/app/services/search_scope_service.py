from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.models.snapshot_manifest import SnapshotManifest
from app.services.platform_store import list_records
from app.services.rag_runtime import get_active_snapshot


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


def _load_snapshot_manifests() -> list[SnapshotManifest]:
    if not SNAPSHOT_DIR.exists():
        return []
    manifests: list[SnapshotManifest] = []
    for path in SNAPSHOT_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            manifests.append(SnapshotManifest(**data))
        except Exception:
            continue
    return manifests


def _faiss_index_exists(snapshot: SnapshotManifest) -> bool:
    faiss_id = (snapshot.rag_build.faiss_index_id or snapshot.snapshot_id or "").strip()
    if not faiss_id:
        return False
    index_path = FAISS_DIR / f"{faiss_id}_ollama.index"
    meta_path = FAISS_DIR / f"{faiss_id}_ollama_metadata.jsonl"
    return index_path.exists() and meta_path.exists()


def _snapshot_sort_key(snapshot: SnapshotManifest) -> tuple:
    return (
        1 if snapshot.is_active else 0,
        1 if _faiss_index_exists(snapshot) else 0,
        int(snapshot.rag_build.vector_count or 0),
        snapshot.activated_at or datetime.min,
        snapshot.created_at or datetime.min,
    )


def _source_name_map() -> dict[str, str]:
    names: dict[str, str] = {}
    try:
        for row in list_records("document_sources"):
            source_id = str(row.get("source_id") or "").strip()
            if not source_id:
                continue
            source_name = str(row.get("source_name") or source_id).strip() or source_id
            names[source_id] = source_name
    except Exception:
        return names
    return names


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
        if len(parts) == 2 and parts[1] in _CATEGORY_SUFFIXES:
            continue
        names.add(stem)
    return sorted(names, reverse=True)


def _build_snapshot_registry() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    source_names = _source_name_map()
    registry: dict[str, dict[str, Any]] = {}
    known_snapshot_ids: set[str] = set()
    known_faiss_index_ids: set[str] = set()
    for snap in sorted(_load_snapshot_manifests(), key=_snapshot_sort_key, reverse=True):
        source_id = str(snap.dataset.source_id or "").strip()
        if not source_id:
            continue
        known_snapshot_ids.add(snap.snapshot_id)
        info = registry.setdefault(
            source_id,
            {
                "source_id": source_id,
                "source_name": source_names.get(source_id, source_id),
                "snapshots": [],
                "latest_queryable_snapshot": "",
            },
        )
        faiss_index_id = (snap.rag_build.faiss_index_id or snap.snapshot_id or "").strip()
        if faiss_index_id:
            known_faiss_index_ids.add(faiss_index_id)
        snapshot_entry = {
            "snapshot_id": snap.snapshot_id,
            "faiss_index_id": faiss_index_id,
            "dataset_id": snap.dataset.dataset_id,
            "is_active": bool(snap.is_active),
            "status": snap.status.value,
            "vector_count": int(snap.rag_build.vector_count or 0),
            "chunk_count": int(snap.rag_build.chunk_count or 0),
            "document_count": int(snap.dataset.document_count or 0),
            "created_at": snap.created_at.isoformat() if snap.created_at else None,
            "activated_at": snap.activated_at.isoformat() if snap.activated_at else None,
            "queryable": _faiss_index_exists(snap),
        }
        info["snapshots"].append(snapshot_entry)
        if snapshot_entry["queryable"] and not info["latest_queryable_snapshot"]:
            info["latest_queryable_snapshot"] = snap.snapshot_id

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
                "snapshots": [],
                "latest_queryable_snapshot": "",
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
