# 관리자 통계 스냅샷을 사전 집계하는 서비스
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.services.snapshot_registry_service import get_snapshot_registry
from app.services.source_data_paths import get_source_paths


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
FAISS_DIR = PROJECT_ROOT / "data" / "indexes" / "faiss"
GRAPH_DIR = PROJECT_ROOT / "data" / "indexes" / "graph"

_CATEGORIES = ["rfp", "proposal", "deliverable"]


def _stats_path(snapshot: str) -> Path:
    return FAISS_DIR / f"{snapshot}_admin_stats.json"


def _manifest_path(snapshot: str) -> Path:
    return FAISS_DIR / f"{snapshot}_ollama.manifest.json"


def _metadata_path(snapshot: str) -> Path:
    return FAISS_DIR / f"{snapshot}_ollama_metadata.jsonl"


def _safe_path(path_value: Optional[str]) -> Optional[Path]:
    value = str(path_value or "").strip()
    if not value:
        return None
    try:
        return Path(value).expanduser()
    except Exception:
        return None


def _load_json(path: Optional[Path]) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _snapshot_record(snapshot: str) -> dict[str, Any]:
    record = get_snapshot_registry(snapshot) or {}
    if record:
        return record

    manifest = _load_json(DATA_DIR / "snapshots" / f"{snapshot}.json")
    if not manifest:
        return {}

    dataset = manifest.get("dataset") or {}
    rag_build = manifest.get("rag_build") or {}
    return {
        "snapshot_id": snapshot,
        "source_id": dataset.get("source_id") or "",
        "dataset_id": dataset.get("dataset_id") or "",
        "document_count": int(dataset.get("document_count") or 0),
        "vector_count": int(rag_build.get("vector_count") or 0),
        "chunk_count": int(rag_build.get("chunk_count") or 0),
        "index_file": rag_build.get("index_file") or "",
        "metadata_file": rag_build.get("metadata_file") or "",
        "manifest_path": str(DATA_DIR / "snapshots" / f"{snapshot}.json"),
    }


def _graph_dir_for_snapshot(snapshot: str) -> Path:
    record = _snapshot_record(snapshot)
    source_id = str(record.get("source_id") or "").strip()
    return GRAPH_DIR / source_id if source_id else GRAPH_DIR


def _resolved_manifest(snapshot: str) -> dict[str, Any]:
    record = _snapshot_record(snapshot)

    explicit_manifest = _safe_path(record.get("manifest_path"))
    manifest = _load_json(explicit_manifest)
    if manifest:
        return manifest

    legacy_manifest = _load_json(_manifest_path(snapshot))
    if legacy_manifest:
        return legacy_manifest

    if record:
        return {
            "snapshot_id": snapshot,
            "vector_count": int(record.get("vector_count") or record.get("chunk_count") or 0),
            "chunk_count": int(record.get("chunk_count") or record.get("vector_count") or 0),
            "document_count": int(record.get("document_count") or 0),
        }
    return {}


def _resolved_metadata_path(snapshot: str) -> Optional[Path]:
    record = _snapshot_record(snapshot)
    explicit_metadata = _safe_path(record.get("metadata_file"))
    if explicit_metadata and explicit_metadata.exists():
        return explicit_metadata

    source_id = str(record.get("source_id") or "").strip()
    if source_id:
        source_paths = get_source_paths(source_id)
        for candidate in (source_paths.active_metadata_jsonl, source_paths.faiss_metadata_jsonl):
            if candidate.exists():
                return candidate

    legacy_meta = _metadata_path(snapshot)
    if legacy_meta.exists():
        return legacy_meta
    return explicit_metadata


def _resolved_index_exists(snapshot: str) -> bool:
    record = _snapshot_record(snapshot)
    index_path = _safe_path(record.get("index_file"))
    meta_path = _resolved_metadata_path(snapshot)
    if index_path and meta_path and index_path.exists() and meta_path.exists():
        return True

    source_id = str(record.get("source_id") or "").strip()
    if source_id:
        source_paths = get_source_paths(source_id)
        if source_paths.active_faiss_index.exists() and source_paths.active_metadata_jsonl.exists():
            return True
        if source_paths.faiss_index.exists() and source_paths.faiss_metadata_jsonl.exists():
            return True

    legacy_index = FAISS_DIR / f"{snapshot}_ollama.index"
    return legacy_index.exists() and meta_path is not None and meta_path.exists()


def _source_paths(snapshot: str) -> list[Path]:
    record = _snapshot_record(snapshot)
    source_id = str(record.get("source_id") or "").strip()
    graph_dir = GRAPH_DIR / source_id if source_id else GRAPH_DIR
    paths: list[Path] = []

    explicit_manifest = _safe_path(record.get("manifest_path"))
    explicit_metadata = _safe_path(record.get("metadata_file"))
    explicit_index = _safe_path(record.get("index_file"))
    for path in (explicit_manifest, explicit_metadata, explicit_index):
        if path and path.exists():
            paths.append(path)

    if source_id:
        source_paths = get_source_paths(source_id)
        for path in (
            source_paths.latest_snapshot_json,
            source_paths.snapshots_json,
            source_paths.faiss_index,
            source_paths.faiss_metadata_jsonl,
            source_paths.active_faiss_index,
            source_paths.active_metadata_jsonl,
        ):
            if path.exists():
                paths.append(path)

    paths = [
        *paths,
        _manifest_path(snapshot),
        _metadata_path(snapshot),
        graph_dir / "graph_manifest.json",
        graph_dir / "graph_nodes.jsonl",
        graph_dir / "graph_edges.jsonl",
    ]
    paths.extend(FAISS_DIR / f"{snapshot}_{cat}_ollama_metadata.jsonl" for cat in _CATEGORIES)
    return [path for path in paths if path.exists()]


def _count_jsonl_rows(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _graph_stats(snapshot: str) -> dict[str, int]:
    graph_dir = _graph_dir_for_snapshot(snapshot)
    manifest_path = graph_dir / "graph_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            return {
                "node_count": int(manifest.get("project_count", 0)) + int(manifest.get("document_count", 0)),
                "edge_count": int(manifest.get("edge_count", 0)),
            }
        except Exception:
            pass

    nodes = graph_dir / "graph_nodes.jsonl"
    edges = graph_dir / "graph_edges.jsonl"
    return {
        "node_count": _count_jsonl_rows(nodes) if nodes.exists() else 0,
        "edge_count": _count_jsonl_rows(edges) if edges.exists() else 0,
    }


def _build_stats(snapshot: str) -> dict[str, Any]:
    manifest = _resolved_manifest(snapshot)
    record = _snapshot_record(snapshot)

    meta_path = _resolved_metadata_path(snapshot)
    chunk_count = int(manifest.get("vector_count") or manifest.get("chunk_count") or record.get("vector_count") or record.get("chunk_count") or 0)
    document_count = int(manifest.get("document_count") or record.get("document_count") or 0)
    if chunk_count == 0 and meta_path is not None and meta_path.exists():
        chunk_count = _count_jsonl_rows(meta_path)

    categories: dict[str, int] = {}
    for category in _CATEGORIES:
        cat_meta = FAISS_DIR / f"{snapshot}_{category}_ollama_metadata.jsonl"
        categories[category] = _count_jsonl_rows(cat_meta) if cat_meta.exists() else 0

    stats = {
        "snapshot": snapshot,
        "index": {
            "chunk_count": chunk_count,
            "document_count": document_count,
            "index_exists": _resolved_index_exists(snapshot),
        },
        "categories": categories,
        "graph": _graph_stats(snapshot),
    }
    _stats_path(snapshot).write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return stats


def get_snapshot_stats(snapshot: str) -> dict[str, Any]:
    if not snapshot:
        return {
            "snapshot": "(none)",
            "index": {"chunk_count": 0, "document_count": 0, "index_exists": False},
            "categories": {category: 0 for category in _CATEGORIES},
            "graph": {"node_count": 0, "edge_count": 0},
        }

    stats_path = _stats_path(snapshot)
    source_paths = _source_paths(snapshot)
    if stats_path.exists():
        stats_mtime = stats_path.stat().st_mtime
        if all(path.stat().st_mtime <= stats_mtime for path in source_paths):
            try:
                return json.loads(stats_path.read_text(encoding="utf-8"))
            except Exception:
                pass

    return _build_stats(snapshot)
