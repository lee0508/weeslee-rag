# 문서 소스(DocumentSource) CRUD + 접근 테스트 API
import os
from datetime import datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import require_admin_token
from app.services.platform_store import (
    list_records, get_record, create_record, update_record,
    delete_record, seed_if_empty,
)

STORE = "document_sources"
ID_FIELD = "source_id"

_WEESLEE_DEFAULT = {
    "source_id": "rag_source",
    "client_id": "weeslee",
    "source_name": "00. RAG 소스",
    "source_type": "smb",
    "source_uri": "\\\\diskstation\\W2_프로젝트폴더\\00. RAG 소스",
    "mount_path": "/mnt/w2_project/00. RAG 소스",
    "root_subpath": "",
    "readonly": True,
    "enabled": True,
    "status": "unknown",
    "last_checked_at": None,
    "last_scanned_at": None,
}

router = APIRouter(
    prefix="/admin/document-sources",
    tags=["Platform - Document Sources"],
    dependencies=[Depends(require_admin_token)],
)


class DocumentSourceCreate(BaseModel):
    source_id: str
    client_id: str
    source_name: str
    source_type: str = "smb"
    source_uri: str
    mount_path: Optional[str] = ""
    root_subpath: Optional[str] = ""
    readonly: bool = True
    enabled: bool = True


class DocumentSourceUpdate(BaseModel):
    client_id: Optional[str] = None
    source_name: Optional[str] = None
    source_type: Optional[str] = None
    source_uri: Optional[str] = None
    mount_path: Optional[str] = None
    root_subpath: Optional[str] = None
    readonly: Optional[bool] = None
    enabled: Optional[bool] = None


class PathTestRequest(BaseModel):
    path: Optional[str] = None


def _seed():
    seed_if_empty(STORE, [_WEESLEE_DEFAULT], id_field=ID_FIELD)


def _is_safe_path(path: str) -> bool:
    """관리자 입력 경로의 기본 안전성을 검증한다 (null 바이트·경로 순회 방지)."""
    if not path or len(path) > 512 or "\x00" in path:
        return False
    try:
        parts = PurePosixPath(path).parts + PureWindowsPath(path).parts
        return ".." not in parts
    except Exception:
        return False


def _check_path_accessible(path: str) -> dict:
    """경로 접근 가능 여부를 확인하고 결과를 반환한다."""
    if not path:
        return {"accessible": False, "reason": "경로가 비어있습니다."}
    if not _is_safe_path(path):
        return {"accessible": False, "reason": "유효하지 않은 경로입니다."}
    try:
        accessible = os.path.exists(path)
        if accessible:
            is_dir = os.path.isdir(path)
            return {"accessible": True, "is_directory": is_dir, "path": path}
        return {"accessible": False, "reason": f"경로를 찾을 수 없습니다: {path}"}
    except PermissionError:
        return {"accessible": False, "reason": "접근 권한이 없습니다."}
    except Exception as e:
        return {"accessible": False, "reason": str(e)}


@router.get("")
async def list_sources(client_id: Optional[str] = None):
    _seed()
    records = list_records(STORE)
    if client_id:
        records = [r for r in records if r.get("client_id") == client_id]
    return records


@router.post("", status_code=201)
async def create_source(body: DocumentSourceCreate):
    _seed()
    if get_record(STORE, ID_FIELD, body.source_id):
        raise HTTPException(status_code=409, detail=f"source_id '{body.source_id}' already exists")
    data = body.model_dump()
    data["status"] = "unknown"
    data["last_checked_at"] = None
    data["last_scanned_at"] = None
    return create_record(STORE, data, id_field=ID_FIELD)


@router.get("/{source_id}")
async def get_source(source_id: str):
    _seed()
    rec = get_record(STORE, ID_FIELD, source_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Document source not found")
    return rec


@router.put("/{source_id}")
async def update_source(source_id: str, body: DocumentSourceUpdate):
    updates = body.model_dump(exclude_unset=True)
    rec = update_record(STORE, ID_FIELD, source_id, updates)
    if not rec:
        raise HTTPException(status_code=404, detail="Document source not found")
    return rec


@router.delete("/{source_id}", status_code=204)
async def delete_source(source_id: str):
    if not delete_record(STORE, ID_FIELD, source_id):
        raise HTTPException(status_code=404, detail="Document source not found")


@router.post("/{source_id}/test")
async def test_source_access(source_id: str):
    """마운트 경로 또는 소스 URI의 접근 가능 여부를 확인한다."""
    _seed()
    rec = get_record(STORE, ID_FIELD, source_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Document source not found")

    mount_path = rec.get("mount_path", "")
    source_uri = rec.get("source_uri", "")

    mount_result = _check_path_accessible(mount_path) if mount_path else None
    uri_result = _check_path_accessible(source_uri) if source_uri else None

    now = datetime.now(timezone.utc).isoformat()
    accessible = bool(
        (mount_result and mount_result["accessible"])
        or (uri_result and uri_result["accessible"])
    )
    status = "accessible" if accessible else "inaccessible"

    update_record(STORE, ID_FIELD, source_id, {"status": status, "last_checked_at": now})
    return {
        "source_id": source_id,
        "status": status,
        "checked_at": now,
        "mount_path_result": mount_result,
        "source_uri_result": uri_result,
    }


@router.post("/{source_id}/scan")
async def scan_source(source_id: str):
    """소스 경로를 스캔해 파일 수를 확인한다. (초기 버전: 파일 수 카운트만 수행)"""
    _seed()
    rec = get_record(STORE, ID_FIELD, source_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Document source not found")

    scan_path = rec.get("mount_path") or rec.get("source_uri", "")
    now = datetime.now(timezone.utc).isoformat()

    if not _is_safe_path(scan_path or ""):
        return {"source_id": source_id, "scanned_at": now, "success": False, "reason": "유효하지 않은 경로입니다."}

    if not scan_path or not os.path.exists(scan_path):
        update_record(STORE, ID_FIELD, source_id, {"last_scanned_at": now})
        return {
            "source_id": source_id,
            "scanned_at": now,
            "success": False,
            "reason": f"경로에 접근할 수 없습니다: {scan_path}",
        }

    try:
        file_count = sum(1 for _ in _walk_files(scan_path))
    except Exception as e:
        return {"source_id": source_id, "scanned_at": now, "success": False, "reason": str(e)}

    update_record(STORE, ID_FIELD, source_id, {"last_scanned_at": now})
    return {
        "source_id": source_id,
        "scanned_at": now,
        "success": True,
        "file_count": file_count,
        "scan_path": scan_path,
    }


def _walk_files(root: str):
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            yield os.path.join(dirpath, f)
