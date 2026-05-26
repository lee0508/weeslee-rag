# 00. RAG 소스 manifest와 배치 파이프라인 입력을 준비하는 서비스
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

from app.services.knowledge_source import knowledge_source_service
from app.services.metadata_db import metadata_db_service
from app.services.platform_store import get_record

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
MANIFEST_DIR = DATA_DIR / "staged" / "manifest"
SCRIPTS_DIR = PROJECT_ROOT / "backend" / "scripts"

SUPPORTED_EXTENSIONS = {".pdf", ".hwp", ".hwpx", ".docx", ".pptx", ".xlsx"}
MAIN_COLLECTION_NAME = "weeslee_rag_main"
MANIFEST_FIELDS = [
    "document_id",
    "category",
    "collection_name",
    "collection_key",
    "document_group",
    "document_category",
    "document_type",
    "proposal_section",
    "deliverable_section",
    "section_label",
    "source_root",
    "source_path",
    "original_source_path",
    "relative_path",
    "snapshot_name",
    "snapshot_path",
    "extension",
    "file_name",
    "folder_name",
    "project_name",
    "organization",
    "project_year",
    "root_group",
    "root_group_key",
    "sub_group",
    "sub_group_key",
    "search_keywords",
]


def _rules():
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import build_rag_source_metadata  # noqa: WPS433

    return build_rag_source_metadata


def resolve_source_path(source_id: str = "rag_source") -> Path:
    record = get_record("document_sources", "source_id", source_id)
    candidate = None
    if record:
        candidate = record.get("mount_path") or record.get("source_uri")
    if not candidate and knowledge_source_service.is_accessible():
        candidate = knowledge_source_service.get_root_path()
    if not candidate:
        raise FileNotFoundError(f"source_id '{source_id}' 경로를 찾을 수 없습니다.")

    root = Path(candidate).resolve()
    if not root.exists():
        raise FileNotFoundError(f"RAG source root not found: {root}")
    return root


def iter_source_documents(source_root: Path, limit: int = 0) -> list[dict[str, Any]]:
    docs = metadata_db_service.list_documents(limit=100000, offset=0)
    prefix = str(source_root).replace("\\", "/").rstrip("/")
    rows: list[dict[str, Any]] = []

    for doc in docs:
        file_path = str(doc.get("file_path") or "")
        normalized = file_path.replace("\\", "/")
        extension = Path(file_path).suffix.lower()
        if not normalized.startswith(prefix):
            continue
        if extension not in SUPPORTED_EXTENSIONS:
            continue
        if not Path(file_path).exists():
            continue
        rows.append(doc)

    rows.sort(key=lambda item: int(item.get("id") or 0))
    if limit and limit > 0:
        return rows[:limit]
    return rows


COLLECTION_KEY_DISPLAY = {
    "rfp": "RFP",
    "proposal": "제안서",
    "deliverable": "산출물",
}


def _collection_key(document_group: str) -> str:
    """document_group을 한글 collection_key로 변환한다."""
    group = (document_group or "unknown").strip().lower()
    return COLLECTION_KEY_DISPLAY.get(group, group)


def _document_category(rules_mod, doc_meta: dict[str, Any]) -> str:
    section_label = rules_mod.section_label(doc_meta)
    if section_label:
        return section_label
    return doc_meta.get("document_type", "unknown")


def build_manifest_row(doc: dict[str, Any], source_root: Path, snapshot_name: str) -> dict[str, Any]:
    rules = _rules()
    source_path = Path(str(doc.get("file_path") or "")).resolve()
    relative_path = source_path.relative_to(source_root).as_posix()
    normalized = str(source_path).replace("\\", "/")
    parts = rules.split_path(rules.normalize_path(normalized))
    root_group = rules.detect_root_group(parts)
    sub_group = rules.detect_sub_group(parts)
    doc_meta = rules.detect_document_metadata(root_group or "", sub_group or "")
    project_name = doc.get("project_name") or rules.extract_project_name(source_path.stem)
    document_group_raw = doc_meta.get("document_group", "unknown")
    document_group = _collection_key(document_group_raw)  # 한글 표시값으로 변환
    collection_key = document_group  # document_group과 동일한 한글 표시값
    document_category = _document_category(rules, doc_meta)

    return {
        "document_id": str(doc.get("id")),
        "category": document_group,
        "collection_name": MAIN_COLLECTION_NAME,
        "collection_key": collection_key,
        "document_group": document_group,
        "document_category": document_category,
        "document_type": doc.get("document_type") or doc_meta.get("document_type", "unknown"),
        "proposal_section": doc_meta.get("proposal_section") or "",
        "deliverable_section": doc_meta.get("deliverable_section") or "",
        "section_label": rules.section_label(doc_meta),
        "source_root": str(source_root),
        "source_path": str(source_path),
        "original_source_path": str(source_path),
        "relative_path": relative_path,
        "snapshot_name": snapshot_name,
        "snapshot_path": "",
        "extension": source_path.suffix.lower(),
        "file_name": doc.get("file_name") or source_path.name,
        "folder_name": project_name,
        "project_name": project_name,
        "organization": doc.get("organization") or rules.detect_organization(project_name) or "",
        "project_year": doc.get("project_year") or rules.detect_year(project_name, normalized) or "",
        "root_group": root_group or "",
        "root_group_key": rules.root_group_key(root_group),
        "sub_group": sub_group or "",
        "sub_group_key": rules.sub_group_key(root_group, sub_group, doc_meta),
        "search_keywords": "|".join(
            rules.build_search_keywords(
                root_group=root_group,
                sub_group=sub_group,
                project_name=project_name,
                document_group=document_group,  # 이미 한글 표시값
                proposal_section=doc_meta.get("proposal_section"),
                deliverable_section=doc_meta.get("deliverable_section"),
                tags=[],
                organization=doc.get("organization") or rules.detect_organization(project_name) or "",
                file_name=doc.get("file_name") or source_path.name,
            )
        ),
    }


def build_manifest(
    snapshot_name: str,
    source_id: str = "rag_source",
    limit: int = 0,
    overwrite: bool = True,
) -> dict[str, Any]:
    source_root = resolve_source_path(source_id)
    docs = iter_source_documents(source_root, limit=limit)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    manifest_csv = MANIFEST_DIR / f"{snapshot_name}_manifest.csv"
    manifest_jsonl = MANIFEST_DIR / f"{snapshot_name}_manifest.jsonl"

    if not overwrite and manifest_csv.exists() and manifest_jsonl.exists():
        return {
            "source_id": source_id,
            "source_root": str(source_root),
            "snapshot": snapshot_name,
            "total": len(docs),
            "manifest_csv": str(manifest_csv),
            "manifest_jsonl": str(manifest_jsonl),
            "reused": True,
        }

    if not docs:
        raise FileNotFoundError(
            f"manifest 대상 문서를 찾지 못했습니다. source_id={source_id}, root={source_root}"
        )

    rows = [build_manifest_row(doc, source_root, snapshot_name) for doc in docs]
    category_counts = {"rfp": 0, "proposal": 0, "deliverable": 0, "unknown": 0}
    for row in rows:
        category_counts[row["category"] if row["category"] in category_counts else "unknown"] += 1

    with manifest_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    with manifest_jsonl.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    return {
        "source_id": source_id,
        "source_root": str(source_root),
        "snapshot": snapshot_name,
        "total": len(rows),
        "category_counts": category_counts,
        "manifest_csv": str(manifest_csv),
        "manifest_jsonl": str(manifest_jsonl),
        "reused": False,
    }
