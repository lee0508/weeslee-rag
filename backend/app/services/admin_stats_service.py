# 관리자 통계 스냅샷을 사전 집계하는 서비스
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
FAISS_DIR = PROJECT_ROOT / "data" / "indexes" / "faiss"
GRAPH_DIR = PROJECT_ROOT / "data" / "indexes" / "graph"

_CATEGORIES = ["rfp", "proposal", "kickoff", "final_report", "presentation"]


def _stats_path(snapshot: str) -> Path:
    return FAISS_DIR / f"{snapshot}_admin_stats.json"


def _manifest_path(snapshot: str) -> Path:
    return FAISS_DIR / f"{snapshot}_ollama.manifest.json"


def _metadata_path(snapshot: str) -> Path:
    return FAISS_DIR / f"{snapshot}_ollama_metadata.jsonl"


def _source_paths(snapshot: str) -> list[Path]:
    paths = [
        _manifest_path(snapshot),
        _metadata_path(snapshot),
        GRAPH_DIR / "graph_manifest.json",
        GRAPH_DIR / "graph_nodes.jsonl",
        GRAPH_DIR / "graph_edges.jsonl",
    ]
    paths.extend(FAISS_DIR / f"{snapshot}_{cat}_ollama_metadata.jsonl" for cat in _CATEGORIES)
    return [path for path in paths if path.exists()]


def _count_jsonl_rows(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _graph_stats() -> dict[str, int]:
    manifest_path = GRAPH_DIR / "graph_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            return {
                "node_count": int(manifest.get("project_count", 0)) + int(manifest.get("document_count", 0)),
                "edge_count": int(manifest.get("edge_count", 0)),
            }
        except Exception:
            pass

    nodes = GRAPH_DIR / "graph_nodes.jsonl"
    edges = GRAPH_DIR / "graph_edges.jsonl"
    return {
        "node_count": _count_jsonl_rows(nodes) if nodes.exists() else 0,
        "edge_count": _count_jsonl_rows(edges) if edges.exists() else 0,
    }


def _build_stats(snapshot: str) -> dict[str, Any]:
    manifest = {}
    manifest_path = _manifest_path(snapshot)
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}

    meta_path = _metadata_path(snapshot)
    chunk_count = int(manifest.get("vector_count", 0))
    document_count = int(manifest.get("document_count", 0))
    if chunk_count == 0 and meta_path.exists():
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
            "index_exists": (FAISS_DIR / f"{snapshot}_ollama.index").exists(),
        },
        "categories": categories,
        "graph": _graph_stats(),
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
