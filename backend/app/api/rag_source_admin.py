# RAG 소스 관리 API — 스캔/메타데이터 생성/파이프라인 현황
from __future__ import annotations

import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import require_admin_token
from app.services.metadata_db import get_db_connection, metadata_db_service
from app.services.platform_store import list_records, get_record

router = APIRouter(
    prefix="/admin/rag-source",
    tags=["RAG Source Admin"],
    dependencies=[Depends(require_admin_token)],
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = PROJECT_ROOT / "backend" / "scripts"
RAG_META_OUTPUT = PROJECT_ROOT / "data" / "rag_source_metadata.jsonl"

# 지원 파일 확장자
_INDEXABLE_EXTENSIONS = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".hwpx", ".hwp", ".xlsx", ".txt"}


def _rules():
    """build_rag_source_metadata 스크립트의 규칙 함수를 동적으로 로드한다."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    return importlib.import_module("build_rag_source_metadata")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response 모델
# ─────────────────────────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    source_id: str = "rag_source"
    overwrite: bool = False


class MetadataBuildRequest(BaseModel):
    client_id: str = "weeslee"
    source_id: str = "rag_source"
    inventory_ids: List[int] = []
    collection: Optional[str] = None
    overwrite: bool = False
    only_missing: bool = True
    dry_run: bool = False


class CollectionsBootstrapRequest(BaseModel):
    client_id: str = "weeslee"
    overwrite: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# 내부 유틸
# ─────────────────────────────────────────────────────────────────────────────

def _get_source_mount_path(source_id: str) -> Optional[str]:
    """Document Source에서 로컬 마운트 경로를 반환한다."""
    rec = get_record("document_sources", "source_id", source_id)
    if not rec:
        return None
    return rec.get("mount_path") or rec.get("source_uri") or None


def _file_exists_by_path(file_path: str) -> Optional[int]:
    """SQLite documents 테이블에서 file_path로 기존 레코드 ID를 반환한다."""
    with get_db_connection() as conn:
        cursor = conn.execute(
            "SELECT id FROM documents WHERE file_path = ?", (file_path,)
        )
        row = cursor.fetchone()
        return row["id"] if row else None


def _apply_rules_to_path(rules_mod, source_path: str) -> dict:
    """파일 경로를 규칙 함수에 통과시켜 메타데이터를 생성한다."""
    normalized = rules_mod.normalize_path(source_path)
    parts = rules_mod.split_path(normalized)
    file_name = parts[-1] if parts else ""
    file_stem = Path(file_name).stem
    file_ext = Path(file_name).suffix.lower().replace(".", "")

    root_group = rules_mod.detect_root_group(parts)
    sub_group = rules_mod.detect_sub_group(parts)
    doc_meta = rules_mod.detect_document_metadata(root_group or "", sub_group or "")
    project_name = rules_mod.extract_project_name(file_stem)

    windows_path = normalized.replace(
        "/mnt/w2_project",
        "\\\\diskstation\\W2_프로젝트폴더"
    ).replace("/", "\\")

    return {
        "source_root": "00. RAG 소스",
        "collection": doc_meta.get("category", "rag_source"),
        "source_path": windows_path,
        "linux_path": normalized,
        "file_name": file_name,
        "file_ext": file_ext,
        "root_group": root_group,
        "sub_group": sub_group,
        "project_name": project_name,
        "project_type": rules_mod.detect_project_type(project_name),
        "organization": rules_mod.detect_organization(project_name),
        "project_year": rules_mod.detect_year(project_name, normalized),
        "document_group": doc_meta.get("document_group", "unknown"),
        "document_type": doc_meta.get("document_type", "unknown"),
        "category": doc_meta.get("category", "unknown"),
        "proposal_section": doc_meta.get("proposal_section"),
        "deliverable_section": doc_meta.get("deliverable_section"),
        "tags": rules_mod.detect_tags(project_name),
        "index_policy": "index",
        "search_priority": "high",
        "confidential_level": "internal",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 엔드포인트
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/status")
async def rag_source_status():
    """RAG 소스 전체 현황 통계를 반환한다."""
    from app.services.admin_stats_service import get_snapshot_stats
    from app.core.config import settings

    snapshot = settings.faiss_snapshot
    faiss_stats = get_snapshot_stats(snapshot)

    try:
        doc_stats = metadata_db_service.get_document_stats()
    except Exception:
        doc_stats = {}

    return {
        "checked_at": _now(),
        "snapshot": snapshot,
        "faiss": faiss_stats,
        "documents": doc_stats,
    }


@router.get("/files")
async def list_rag_source_files(
    document_type: Optional[str] = None,
    status: Optional[str] = None,
    meta_status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """RAG 소스 파일 목록을 조회한다."""
    try:
        docs = metadata_db_service.list_documents(
            document_type=document_type,
            status=status,
            meta_status=meta_status,
            search=search,
            limit=limit,
            offset=offset,
        )
        total = metadata_db_service.count_documents(
            document_type=document_type,
            status=status,
            meta_status=meta_status,
        )
        return {"total": total, "offset": offset, "limit": limit, "files": docs}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/scan")
async def scan_rag_source(body: ScanRequest):
    """마운트 경로를 스캔해 파일 목록을 SQLite DB에 저장한다."""
    from app.services.knowledge_source import knowledge_source_service

    mount_path = _get_source_mount_path(body.source_id)
    # source_id 레코드가 없으면 knowledge_source_service의 루트 경로를 fallback으로 사용
    if not mount_path:
        if knowledge_source_service.is_accessible():
            mount_path = knowledge_source_service.get_root_path()
        else:
            raise HTTPException(
                status_code=422,
                detail=f"source_id '{body.source_id}' not found and fallback knowledge source is not accessible",
            )
    if not os.path.exists(mount_path):
        raise HTTPException(
            status_code=422,
            detail=f"마운트 경로에 접근할 수 없습니다: {mount_path}",
        )

    now = _now()
    created = updated = skipped = failed = 0
    items = []

    for dirpath, _, filenames in os.walk(mount_path):
        for fname in filenames:
            suffix = Path(fname).suffix.lower()
            if suffix not in _INDEXABLE_EXTENSIONS:
                continue
            full_path = os.path.join(dirpath, fname)
            try:
                file_size = os.path.getsize(full_path)
            except OSError:
                failed += 1
                continue

            existing_id = _file_exists_by_path(full_path)
            if existing_id and not body.overwrite:
                skipped += 1
                continue

            doc_data = {
                "file_name": fname,
                "file_path": full_path,
                "file_type": suffix.lstrip("."),
                "file_size": file_size,
                "status": "pending",
                "meta_status": "pending",
            }

            try:
                if existing_id and body.overwrite:
                    metadata_db_service.update_document(existing_id, doc_data)
                    updated += 1
                    doc_id = existing_id
                else:
                    doc_id = metadata_db_service.create_document(doc_data)
                    created += 1
                items.append({"id": doc_id, "file_name": fname, "action": "updated" if existing_id else "created"})
            except Exception:
                failed += 1

    return {
        "success": True,
        "source_id": body.source_id,
        "mount_path": mount_path,
        "scanned_at": now,
        "total": created + updated + skipped,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "items": items[:50],  # 응답 크기 제한
    }


@router.post("/metadata/build")
async def build_metadata(body: MetadataBuildRequest):
    """파일 경로와 폴더 구조를 기반으로 규칙 기반 메타데이터를 생성한다. LLM 호출 없음."""
    try:
        rules = _rules()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"규칙 모듈 로드 실패: {exc}")

    # 처리 대상 문서 목록 조회
    if body.inventory_ids:
        docs = [metadata_db_service.get_document(i) for i in body.inventory_ids if metadata_db_service.get_document(i)]
    elif body.only_missing and not body.overwrite:
        docs = metadata_db_service.list_documents(meta_status="pending", limit=10000)
    else:
        docs = metadata_db_service.list_documents(limit=10000)

    if body.collection:
        docs = [d for d in docs if d]

    now = _now()
    created = updated = skipped = failed = 0
    result_items = []
    jsonl_rows = []

    for doc in docs:
        if not doc:
            continue
        doc_id = doc.get("id")
        file_path = doc.get("file_path", "")

        if not file_path:
            skipped += 1
            continue
        if not body.overwrite and doc.get("meta_status") == "confirmed":
            skipped += 1
            continue

        try:
            meta = _apply_rules_to_path(rules, file_path)
        except Exception:
            failed += 1
            continue

        db_updates = {
            "document_type": meta.get("document_type", "unknown"),
            "project_name": meta.get("project_name", ""),
            "organization": meta.get("organization"),
            "project_year": meta.get("project_year"),
            "meta_status": "auto_suggested",
        }

        if not body.dry_run:
            try:
                metadata_db_service.update_document(doc_id, db_updates)
                updated += 1
            except Exception:
                failed += 1
                continue
        else:
            updated += 1

        jsonl_rows.append({**meta, "db_id": doc_id})
        result_items.append({
            "id": doc_id,
            "file_name": doc.get("file_name", ""),
            "project_name": meta.get("project_name"),
            "document_group": meta.get("document_group"),
            "proposal_section": meta.get("proposal_section"),
            "deliverable_section": meta.get("deliverable_section"),
            "collection": meta.get("category"),
            "status": "dry_run" if body.dry_run else "updated",
        })

    # 확장 메타데이터를 JSONL 파일에도 저장
    if not body.dry_run and jsonl_rows:
        try:
            RAG_META_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            with RAG_META_OUTPUT.open("a", encoding="utf-8") as f:
                for row in jsonl_rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass

    return {
        "success": True,
        "mode": "rule_based",
        "llm_used": False,
        "dry_run": body.dry_run,
        "client_id": body.client_id,
        "source_id": body.source_id,
        "total": len(docs),
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "items": result_items[:100],
    }


@router.post("/collections/bootstrap")
async def bootstrap_collections(body: CollectionsBootstrapRequest):
    """Collection Template 기반으로 기본 Collection을 자동 생성한다."""
    from app.services.platform_store import seed_if_empty

    templates = list_records("collection_templates")
    if body.client_id:
        templates = [t for t in templates if t.get("client_id") == body.client_id]

    if not templates:
        return {"success": True, "message": "생성할 템플릿이 없습니다.", "created": 0}

    from app.services.platform_store import create_record as ps_create, get_record as ps_get

    COLL_STORE = "collections_active"
    created = skipped = 0
    items = []

    for tmpl in templates:
        coll_key = tmpl.get("collection_key", "")
        if not coll_key:
            continue
        existing = ps_get(COLL_STORE, "collection_key", coll_key)
        if existing and not body.overwrite:
            skipped += 1
            continue
        record = {
            "collection_key": coll_key,
            "client_id": tmpl.get("client_id"),
            "name": tmpl.get("name"),
            "description": tmpl.get("description", ""),
            "enabled": True,
        }
        ps_create(COLL_STORE, record, id_field="collection_key")
        created += 1
        items.append({"collection_key": coll_key, "name": tmpl.get("name")})

    return {
        "success": True,
        "client_id": body.client_id,
        "created": created,
        "skipped": skipped,
        "items": items,
    }


@router.post("/tags/bootstrap")
async def bootstrap_tags(overwrite: bool = False):
    """기본 Tag 목록을 seed한다. 이미 존재하는 태그는 overwrite=True 일 때만 덮어씀."""
    from app.services.platform_store import list_records, create_record, update_record

    _DEFAULT_TAGS = [
        {"tag_id": "tag_ai",          "tag_type": "technology",       "tag_name": "AI",       "keywords": ["AI", "인공지능", "생성형", "LLM"],    "enabled": True},
        {"tag_id": "tag_isp",         "tag_type": "project_type",     "tag_name": "ISP",      "keywords": ["ISP", "정보화전략계획"],               "enabled": True},
        {"tag_id": "tag_ismp",        "tag_type": "project_type",     "tag_name": "ISMP",     "keywords": ["ISMP"],                               "enabled": True},
        {"tag_id": "tag_bprisp",      "tag_type": "project_type",     "tag_name": "BPR/ISP",  "keywords": ["BPRISP", "BPR/ISP"],                  "enabled": True},
        {"tag_id": "tag_bigdata",     "tag_type": "technology",       "tag_name": "빅데이터", "keywords": ["빅데이터", "데이터 플랫폼", "데이터허브"], "enabled": True},
        {"tag_id": "tag_cloud",       "tag_type": "technology",       "tag_name": "클라우드", "keywords": ["클라우드", "Cloud", "SaaS"],            "enabled": True},
        {"tag_id": "tag_gis",         "tag_type": "technology",       "tag_name": "공간정보", "keywords": ["공간정보", "GIS", "지리정보"],           "enabled": True},
        {"tag_id": "tag_health",      "tag_type": "business_domain",  "tag_name": "보건의료", "keywords": ["보건의료", "의료", "병원"],              "enabled": True},
        {"tag_id": "tag_education",   "tag_type": "business_domain",  "tag_name": "교육",     "keywords": ["교육", "학교", "대학"],                 "enabled": True},
        {"tag_id": "tag_public_safety","tag_type": "business_domain", "tag_name": "소방/치안","keywords": ["소방", "119", "경찰청"],                "enabled": True},
    ]

    STORE = "tags"
    ID_FIELD = "tag_id"
    existing_ids = {r.get(ID_FIELD) for r in list_records(STORE)}

    created = skipped = updated = 0
    for tag in _DEFAULT_TAGS:
        tid = tag[ID_FIELD]
        if tid in existing_ids:
            if overwrite:
                update_record(STORE, ID_FIELD, tid, tag)
                updated += 1
            else:
                skipped += 1
        else:
            create_record(STORE, tag, id_field=ID_FIELD)
            created += 1

    return {
        "success": True,
        "total": len(_DEFAULT_TAGS),
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }


@router.post("/faiss/build")
async def build_faiss(_body: dict = {}):
    """FAISS 인덱스 빌드를 요청한다. (기존 faiss_admin API로 위임)"""
    return {
        "success": True,
        "message": "FAISS 빌드는 /api/admin/faiss/build 엔드포인트를 사용해 주세요.",
        "redirect": "/api/admin/faiss/build",
    }


@router.post("/graph/build")
async def build_graph(_body: dict = {}):
    """Graph RAG 빌드를 요청한다. (graph API로 위임)"""
    return {
        "success": True,
        "message": "Graph 빌드는 /api/graph/build 엔드포인트를 사용해 주세요.",
        "redirect": "/api/graph/build",
    }


@router.post("/wiki/build")
async def build_wiki(_body: dict = {}):
    """LLM Wiki 빌드를 요청한다. (wiki API로 위임)"""
    return {
        "success": True,
        "message": "Wiki 빌드는 /api/wiki/build 엔드포인트를 사용해 주세요.",
        "redirect": "/api/wiki/build",
    }
