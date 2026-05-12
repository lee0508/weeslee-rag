# -*- coding: utf-8 -*-
"""
Build document graph JSONL from FAISS metadata (or manifest CSV fallback).

Output:
  data/indexes/graph/graph_nodes.jsonl
  data/indexes/graph/graph_edges.jsonl
  data/indexes/graph/graph_manifest.json

Node types:  project | document | category
Edge types:  has_document | has_category | related_sequence
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
ACTIVE_INDEX_PATH = DATA_DIR / "active_index.json"
FAISS_DIR = DATA_DIR / "indexes" / "faiss"
MANIFEST_DIR = DATA_DIR / "staged" / "manifest"
GRAPH_DIR = DATA_DIR / "indexes" / "graph"

BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.metadata_enricher import enrich_confidence  # noqa: E402

# ── Category config ───────────────────────────────────────────────────────────

CATEGORY_ORDER = ["rfp", "proposal", "kickoff", "presentation", "final_report"]

CATEGORY_LABELS = {
    "rfp":          "RFP (제안요청서)",
    "proposal":     "제안서",
    "kickoff":      "착수보고",
    "presentation": "발표자료",
    "final_report": "최종보고",
}

CATEGORY_COLORS = {
    "rfp":          "#ef4444",
    "proposal":     "#3b82f6",
    "kickoff":      "#f59e0b",
    "presentation": "#8b5cf6",
    "final_report": "#22c55e",
}

_DATE_PREFIX = re.compile(r"^\d+\.\s*")


# ── Data loading ──────────────────────────────────────────────────────────────

def _read_active_snapshot() -> str:
    if ACTIVE_INDEX_PATH.exists():
        try:
            data = json.loads(ACTIVE_INDEX_PATH.read_text(encoding="utf-8"))
            return data.get("snapshot", "")
        except Exception:
            pass
    return ""


# 작성일: 2026-05-12 | 기능: source_path 폴더 구조에서 프로젝트명 추출 (project_name 빈 경우 폴백)
def _project_name_from_path(source_path: str) -> str:
    if not source_path:
        return ""
    parts = [p for p in re.split(r"[\\/]", source_path) if p and p != "."]
    # 드라이브 문자 제거 (예: "W:")
    if parts and len(parts[0]) == 2 and parts[0][1] == ":":
        parts = parts[1:]
    # 구조: [최상위 폴더, 프로젝트 폴더, ...]
    if len(parts) < 2:
        return ""
    return _DATE_PREFIX.sub("", parts[1]).strip()


def _docs_from_faiss_meta(path: Path) -> list[dict]:
    """Extract unique documents from a FAISS metadata JSONL."""
    seen: set[str] = set()
    docs: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            doc_id = row.get("document_id", "")
            if not doc_id or doc_id in seen:
                continue
            seen.add(doc_id)
            meta = row.get("metadata") or {}
            source_path = row.get("source_path") or meta.get("source_path", "")
            # 작성일: 2026-05-12 | 기능: metadata.project_name 없으면 source_path 경로에서 추출
            project_name = meta.get("project_name") or _project_name_from_path(source_path)
            docs.append({
                "document_id": doc_id,
                "category":    row.get("category") or meta.get("category", ""),
                "source_path": source_path,
                "extension":   meta.get("extension", ""),
                "project_name":             project_name,
                "organization":             meta.get("organization", ""),
                "organization_confidence":  meta.get("organization_confidence", 0.0),
                "project_confidence":       meta.get("project_confidence", 0.0),
            })
    return docs


def _docs_from_manifests() -> list[dict]:
    """Extract documents from manifest CSVs using folder_name enrichment."""
    seen: set[str] = set()
    docs: list[dict] = []
    for csv_path in sorted(MANIFEST_DIR.glob("snapshot_*.csv")):
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                doc_id = row.get("document_id", "")
                if not doc_id or doc_id in seen:
                    continue
                seen.add(doc_id)
                folder_name = row.get("folder_name", "")
                project_name = _DATE_PREFIX.sub("", folder_name).strip()
                confidence = enrich_confidence(folder_name, project_name)
                docs.append({
                    "document_id": doc_id,
                    "category":    row.get("category", ""),
                    "source_path": row.get("source_path", ""),
                    "extension":   Path(row.get("source_path", "")).suffix.lower(),
                    "project_name":             project_name,
                    "organization":             confidence["organization"],
                    "organization_confidence":  confidence["organization_confidence"],
                    "project_confidence":       confidence["project_confidence"],
                })
    return docs


# ── Graph builders ────────────────────────────────────────────────────────────

def _build_nodes_edges(docs: list[dict]) -> tuple[list[dict], list[dict]]:
    nodes: list[dict] = []
    edges: list[dict] = []
    node_ids: set[str] = set()
    edge_counter = [0]

    def add_node(n: dict) -> None:
        if n["id"] not in node_ids:
            nodes.append(n)
            node_ids.add(n["id"])

    def add_edge(src: str, tgt: str, relation: str, **extra) -> None:
        edge_counter[0] += 1
        edges.append({"id": f"e{edge_counter[0]}", "source": src, "target": tgt,
                      "relation": relation, **extra})

    # Static category nodes
    for cat in CATEGORY_ORDER:
        add_node({
            "id":    f"cat:{cat}",
            "type":  "category",
            "label": CATEGORY_LABELS.get(cat, cat),
            "color": CATEGORY_COLORS.get(cat, "#6b7280"),
        })

    # Group documents by project
    by_project: dict[str, list[dict]] = defaultdict(list)
    for doc in docs:
        key = doc["project_name"] or "미분류"
        by_project[key].append(doc)

    for project_name, proj_docs in by_project.items():
        proj_id = f"project:{project_name}"

        # Infer year from a doc's source_path or organization
        year = ""
        for d in proj_docs:
            m = re.search(r"/(20\d\d)/|\\(20\d\d)\\", d["source_path"])
            if m:
                year = m.group(1) or m.group(2)
                break

        # Organization (use first doc with non-empty value)
        organization = next(
            (d["organization"] for d in proj_docs if d.get("organization")), ""
        )

        add_node({
            "id":           proj_id,
            "type":         "project",
            "label":        project_name,
            "doc_count":    len(proj_docs),
            "year":         year,
            "organization": organization,
        })

        # Document nodes + project→doc edges
        for doc in proj_docs:
            doc_id = f"doc:{doc['document_id']}"
            filename = Path(doc["source_path"]).name
            add_node({
                "id":           doc_id,
                "type":         "document",
                "label":        filename,
                "document_id":  doc["document_id"],
                "category":     doc["category"],
                "project_id":   proj_id,
                "project_name": project_name,
                "source_path":  doc["source_path"],
                "extension":    doc["extension"],
                "color":        CATEGORY_COLORS.get(doc["category"], "#6b7280"),
            })
            add_edge(proj_id, doc_id, "has_document")
            cat_node_id = f"cat:{doc['category']}"
            if cat_node_id in node_ids:
                add_edge(doc_id, cat_node_id, "has_category")

        # related_sequence edges: rfp→proposal→kickoff→presentation→final_report
        ordered: list[dict] = []
        for cat in CATEGORY_ORDER:
            ordered.extend(d for d in proj_docs if d["category"] == cat)
        for i in range(len(ordered) - 1):
            src = f"doc:{ordered[i]['document_id']}"
            tgt = f"doc:{ordered[i + 1]['document_id']}"
            label = f"{ordered[i]['category']} → {ordered[i + 1]['category']}"
            add_edge(src, tgt, "related_sequence", label=label)

    return nodes, edges


# ── Output ────────────────────────────────────────────────────────────────────

def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build graph JSONL from indexed documents")
    p.add_argument("--snapshot", default="",
                   help="Snapshot name (auto-detect from active_index.json if omitted)")
    p.add_argument("--faiss-meta", default="",
                   help="Direct path to FAISS metadata JSONL (overrides --snapshot)")
    p.add_argument("--output-dir", default=str(GRAPH_DIR))
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.output_dir)

    # Resolve source
    faiss_meta_path: Path | None = None
    if args.faiss_meta:
        faiss_meta_path = Path(args.faiss_meta)
    else:
        snapshot = args.snapshot or _read_active_snapshot()
        if snapshot:
            candidate = FAISS_DIR / f"{snapshot}_ollama_metadata.jsonl"
            if candidate.exists():
                faiss_meta_path = candidate

    if faiss_meta_path and faiss_meta_path.exists():
        docs = _docs_from_faiss_meta(faiss_meta_path)
        source_type = "faiss_metadata"
        source_path = str(faiss_meta_path)
        print(json.dumps({"source": "faiss_metadata", "path": str(faiss_meta_path),
                          "doc_count": len(docs)}, ensure_ascii=False))
    else:
        docs = _docs_from_manifests()
        source_type = "manifest_csv"
        source_path = str(MANIFEST_DIR)
        print(json.dumps({"source": "manifest_csv", "dir": str(MANIFEST_DIR),
                          "doc_count": len(docs)}, ensure_ascii=False))

    if not docs:
        print(json.dumps({"error": "No documents found — run pipeline first"}))
        return 1

    nodes, edges = _build_nodes_edges(docs)

    nodes_path = out_dir / "graph_nodes.jsonl"
    edges_path = out_dir / "graph_edges.jsonl"
    manifest_path = out_dir / "graph_manifest.json"

    _write_jsonl(nodes_path, nodes)
    _write_jsonl(edges_path, edges)

    project_count  = sum(1 for n in nodes if n["type"] == "project")
    document_count = sum(1 for n in nodes if n["type"] == "document")

    manifest = {
        "built_at":      datetime.now().isoformat(timespec="seconds"),
        "source_type":   source_type,
        "source_path":   source_path,
        "doc_count":     len(docs),
        "node_count":    len(nodes),
        "edge_count":    len(edges),
        "project_count": project_count,
        "document_count": document_count,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"graph_complete": True, **manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
