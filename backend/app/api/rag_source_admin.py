# RAG 소스 관리 API — 스캔/메타데이터 생성/파이프라인 현황
from __future__ import annotations

import importlib
import json
import os
import re
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
MAIN_COLLECTION_NAME = "weeslee_rag_main"

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
    source_id: str
    overwrite: bool = False


class MetadataBuildRequest(BaseModel):
    client_id: str
    source_id: str
    inventory_ids: List[int] = []
    collection: Optional[str] = None
    overwrite: bool = False
    only_missing: bool = True
    dry_run: bool = False


class CollectionsBootstrapRequest(BaseModel):
    client_id: str
    source_id: str
    overwrite: bool = False


class KeywordsExtractRequest(BaseModel):
    overwrite: bool = False
    limit: int = 1000


# ─────────────────────────────────────────────────────────────────────────────
# 내부 유틸
# ─────────────────────────────────────────────────────────────────────────────

def _get_source_mount_path(source_id: str) -> Optional[str]:
    """Document Source에서 로컬 마운트 경로를 반환한다."""
    rec = get_record("document_sources", "source_id", source_id)
    if not rec:
        return None
    return rec.get("mount_path") or rec.get("source_uri") or None


def _get_source_name(source_id: str) -> str:
    rec = get_record("document_sources", "source_id", source_id) or {}
    return rec.get("source_name") or rec.get("name") or source_id


def _normalize_compare_path(path: str) -> str:
    normalized = str(path or "").replace("\\", "/").rstrip("/")
    return normalized.casefold() if re.match(r"^[a-zA-Z]:/", normalized) else normalized


def _is_document_under_source(doc: dict, source_root: str) -> bool:
    file_path = _normalize_compare_path(doc.get("file_path", ""))
    root = _normalize_compare_path(source_root)
    return bool(file_path and root and (file_path == root or file_path.startswith(root + "/")))


def _list_documents_under_source(
    source_root: str,
    *,
    meta_status: Optional[str] = None,
    limit: int = 0,
) -> list[dict]:
    normalized_root = str(source_root or "").replace("\\", "/").rstrip("/")
    if not normalized_root:
        return []

    sql = """
        SELECT *
        FROM documents
        WHERE (replace(file_path, '\\', '/') = ?
           OR replace(file_path, '\\', '/') LIKE ?)
    """
    params: list[object] = [normalized_root, f"{normalized_root}/%"]
    if meta_status:
        sql += " AND meta_status = ?"
        params.append(meta_status)
    sql += " ORDER BY updated_at DESC"
    if limit and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)

    with get_db_connection() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


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
    collection_name = MAIN_COLLECTION_NAME
    document_group = doc_meta.get("document_group", "unknown")
    document_category = rules_mod.section_label(doc_meta) or doc_meta.get("document_type", "unknown")

    windows_path = normalized.replace(
        "/mnt/w2_project",
        "\\\\diskstation\\W2_프로젝트폴더"
    ).replace("/", "\\")

    return {
        "source_root": "00. RAG 소스",
        "collection": collection_name,
        "collection_name": collection_name,
        "collection_key": document_group,
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
        "document_group": document_group,
        "document_category": document_category,
        "document_type": doc_meta.get("document_type", "unknown"),
        "category": doc_meta.get("category", "unknown"),
        "proposal_section": doc_meta.get("proposal_section"),
        "deliverable_section": doc_meta.get("deliverable_section"),
        "tags": rules_mod.detect_tags(project_name),
        "index_policy": "index",
        "search_priority": "high",
        "confidential_level": "internal",
    }


def _filter_docs_by_source(docs: list[dict], source_id: str) -> tuple[list[dict], str, str]:
    mount_path = _get_source_mount_path(source_id)
    if not mount_path:
        raise HTTPException(
            status_code=422,
            detail=f"source_id '{source_id}'의 Document Source 경로를 찾을 수 없습니다.",
        )

    source_name = _get_source_name(source_id)
    return [
        doc for doc in docs if doc and _is_document_under_source(doc, mount_path)
    ], mount_path, source_name


def _normalize_keyword_value(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _collection_name_from_file_path(file_path: str) -> str:
    return MAIN_COLLECTION_NAME


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
        "scanned_at": _now(),
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

    source_root = _get_source_mount_path(body.source_id)
    if not source_root:
        raise HTTPException(
            status_code=422,
            detail=f"source_id '{body.source_id}'의 Document Source 경로를 찾을 수 없습니다.",
        )
    source_name = _get_source_name(body.source_id)

    # 처리 대상 문서 목록 조회
    if body.inventory_ids:
        docs = [metadata_db_service.get_document(i) for i in body.inventory_ids if metadata_db_service.get_document(i)]
        docs = [doc for doc in docs if doc and _is_document_under_source(doc, source_root)]
    elif body.only_missing and not body.overwrite:
        docs = _list_documents_under_source(source_root, meta_status="pending")
    else:
        docs = _list_documents_under_source(source_root)

    if body.collection:
        docs = docs if body.collection == MAIN_COLLECTION_NAME else []

    updated = skipped = failed = 0
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
            meta["source_id"] = body.source_id
            meta["source_name"] = source_name
            meta["source_root_path"] = source_root
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
            "document_category": meta.get("document_category"),
            "proposal_section": meta.get("proposal_section"),
            "deliverable_section": meta.get("deliverable_section"),
            "collection": meta.get("collection"),
            "collection_key": meta.get("collection_key"),
            "source_id": body.source_id,
            "source_name": source_name,
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
        "source_name": source_name,
        "source_root": source_root,
        "total": len(docs),
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "items": result_items[:100],
    }


@router.post("/collections/bootstrap")
async def bootstrap_collections(body: CollectionsBootstrapRequest):
    from app.api.collections import bootstrap_collection_config
    return bootstrap_collection_config(body.client_id, body.source_id, body.overwrite)


@router.post("/tags/bootstrap")
async def bootstrap_tags(overwrite: bool = False):
    from app.api.tags import bootstrap_default_tags
    return bootstrap_default_tags(overwrite=overwrite)


@router.post("/keywords/extract")
async def extract_keywords(body: KeywordsExtractRequest = KeywordsExtractRequest()):
    from app.api.keywords import extract_keywords_from_metadata
    return extract_keywords_from_metadata(body)


class ScanV2Request(BaseModel):
    overwrite: bool = False


@router.post("/scan-v2")
async def scan_rag_source_v2(body: ScanV2Request):
    """B안: source_scan.py 스크립트를 호출하여 JSONL 생성 및 SQLite 동기화를 수행한다."""
    import subprocess

    script_path = SCRIPTS_DIR / "source_scan.py"
    if not script_path.exists():
        raise HTTPException(status_code=500, detail=f"스크립트를 찾을 수 없습니다: {script_path}")

    cmd = ["python3", str(script_path)]
    if body.overwrite:
        cmd.append("--overwrite")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(PROJECT_ROOT),
        )

        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr or "스크립트 실행 실패",
                "stdout": result.stdout,
                "returncode": result.returncode,
            }

        # 스냅샷 파일에서 결과 읽기
        snapshots_dir = PROJECT_ROOT / "data" / "metadata" / "snapshots"
        snapshot_files = sorted(snapshots_dir.glob("snap_*.json"), reverse=True) if snapshots_dir.exists() else []

        snapshot_data = {}
        if snapshot_files:
            try:
                with open(snapshot_files[0], "r", encoding="utf-8") as f:
                    snapshot_data = json.load(f)
            except Exception:
                pass

        return {
            "success": True,
            "scanned_at": _now(),
            "snapshot_id": snapshot_data.get("snapshot_id"),
            "document_count": snapshot_data.get("document_count", 0),
            "sqlite_sync": snapshot_data.get("sqlite_sync", {}),
            "stdout": result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout,
        }

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="스크립트 실행 시간 초과 (5분)")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"스크립트 실행 오류: {exc}")


class DocumentUpdateRequest(BaseModel):
    project_name: Optional[str] = None
    organization: Optional[str] = None
    project_type: Optional[str] = None
    project_year: Optional[str] = None
    business_domain: Optional[str] = None
    document_type: Optional[str] = None
    tags: Optional[str] = None  # JSON 문자열
    meta_status: Optional[str] = None


@router.patch("/documents/{document_id}")
async def update_document(document_id: int, body: DocumentUpdateRequest):
    """문서 메타데이터를 업데이트한다. (3순위: 관리자 검수 기능)"""
    # 기존 문서 확인
    doc = metadata_db_service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"문서를 찾을 수 없습니다: {document_id}")

    # 업데이트할 필드만 추출
    update_data = {}
    for field in ["project_name", "organization", "project_type", "project_year",
                  "business_domain", "document_type", "tags", "meta_status"]:
        value = getattr(body, field, None)
        if value is not None:
            update_data[field] = value

    if not update_data:
        return {"success": True, "message": "업데이트할 필드가 없습니다.", "document_id": document_id}

    # 메타데이터 DB 서비스를 통해 업데이트
    try:
        # tags 필드 처리 - 새 컬럼이므로 직접 SQL 실행
        with get_db_connection() as conn:
            # 필드별 업데이트 쿼리 생성
            updates = []
            params = []
            for field, value in update_data.items():
                updates.append(f"{field} = ?")
                params.append(value)
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(document_id)

            query = f"UPDATE documents SET {', '.join(updates)} WHERE id = ?"
            conn.execute(query, params)
            conn.commit()

        return {
            "success": True,
            "message": "메타데이터가 업데이트되었습니다.",
            "document_id": document_id,
            "updated_fields": list(update_data.keys()),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"업데이트 실패: {exc}")


@router.get("/documents/{document_id}")
async def get_document(document_id: int):
    """문서 상세 정보를 조회한다."""
    doc = metadata_db_service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"문서를 찾을 수 없습니다: {document_id}")
    return doc


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


# ─────────────────────────────────────────────────────────────────────────────
# Tag/Keyword 통합 생성 API (QA2 기반, 2026-06-15)
# ─────────────────────────────────────────────────────────────────────────────

class TagKeywordGenerateRequest(BaseModel):
    """
    Tag/Keyword 생성 요청 모델.

    source_id: 현재 선택된 Document Source ID
    snapshot_id: 현재 작업 또는 활성 Snapshot ID
    overwrite: 기존 자동 생성 태그/키워드를 덮어쓸지 여부 (manual 태그는 보존)
    """
    source_id: str
    snapshot_id: Optional[str] = None
    overwrite: bool = False


@router.post("/tag-keyword/generate")
async def generate_tag_keyword(body: TagKeywordGenerateRequest):
    from app.api.admin_dataset_builder_simple import generate_tag_keyword_for_source
    return generate_tag_keyword_for_source(body)
