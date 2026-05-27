# 문서 소스(DocumentSource) CRUD + 접근 테스트 API
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
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
PROJECT_ROOT = Path(__file__).resolve().parents[3]
INVENTORY_DIR = PROJECT_ROOT / "platform_config" / "document_source_inventories"

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
    "last_scan_file_count": 0,
    "new_file_count": 0,
    "changed_file_count": 0,
    "removed_file_count": 0,
    "needs_rag_build": False,
    "next_action": "Source Document 기준 스캔을 먼저 실행하세요.",
}

router = APIRouter(
    prefix="/admin/document-sources",
    tags=["Platform - Document Sources"],
    dependencies=[Depends(require_admin_token)],
)


class DocumentSourceCreate(BaseModel):
    source_id: Optional[str] = ""
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


def _inventory_path(source_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9가-힣_.-]+", "_", source_id).strip("._") or "source"
    INVENTORY_DIR.mkdir(parents=True, exist_ok=True)
    return INVENTORY_DIR / f"{safe_id}.json"


def _load_inventory(source_id: str) -> Optional[dict]:
    path = _inventory_path(source_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("files"), dict):
            return data["files"]
        return data if isinstance(data, dict) else {}
    except Exception:
        return None


def _save_inventory(source_id: str, inventory: dict) -> None:
    _inventory_path(source_id).write_text(
        json.dumps({"files": inventory}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _build_inventory(root: str) -> dict:
    root_path = Path(root)
    inventory = {}
    for file_path in _walk_files(root):
        path_obj = Path(file_path)
        try:
            stat = path_obj.stat()
            rel_path = path_obj.relative_to(root_path).as_posix()
        except Exception:
            continue
        inventory[rel_path] = {
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
        }
    return inventory


def _sample_paths(paths: list[str]) -> list[str]:
    return sorted(paths)[:10]


def _next_action(new_count: int, changed_count: int, removed_count: int, initial_scan: bool) -> str:
    if initial_scan:
        return "기준 스캔이 완료되었습니다. 이후 추가되는 Source Document를 자동 비교합니다."
    if new_count or changed_count or removed_count:
        return "Source Document 변경이 감지되었습니다. RAG 작업에서 파일 스캔, 메타데이터 생성, FAISS 빌드를 순서대로 실행하세요."
    return "새로 처리할 Source Document가 없습니다. 현재 인덱스를 유지해도 됩니다."


def _generate_source_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    for _ in range(10):
        source_id = f"src_{stamp}_{secrets.token_hex(3)}"
        if not get_record(STORE, ID_FIELD, source_id):
            return source_id
    raise HTTPException(status_code=500, detail="source_id 생성에 실패했습니다.")


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
    source_id = (body.source_id or "").strip() or _generate_source_id()
    if get_record(STORE, ID_FIELD, source_id):
        raise HTTPException(status_code=409, detail=f"source_id '{source_id}' already exists")
    data = body.model_dump()
    data["source_id"] = source_id
    data["status"] = "unknown"
    data["last_checked_at"] = None
    data["last_scanned_at"] = None
    data["last_scan_file_count"] = 0
    data["new_file_count"] = 0
    data["changed_file_count"] = 0
    data["removed_file_count"] = 0
    data["needs_rag_build"] = False
    data["next_action"] = "Source Document 기준 스캔을 먼저 실행하세요."
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
    """소스 경로를 스캔해 이전 스냅샷과 비교하고 변경 안내를 저장한다."""
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
        previous_inventory = _load_inventory(source_id)
        current_inventory = _build_inventory(scan_path)
    except Exception as e:
        return {"source_id": source_id, "scanned_at": now, "success": False, "reason": str(e)}

    previous_paths = set((previous_inventory or {}).keys())
    current_paths = set(current_inventory.keys())
    initial_scan = previous_inventory is None
    new_files = sorted(current_paths - previous_paths) if not initial_scan else []
    removed_files = sorted(previous_paths - current_paths) if not initial_scan else []
    changed_files = sorted(
        path for path in current_paths & previous_paths
        if current_inventory.get(path) != previous_inventory.get(path)
    ) if not initial_scan else []
    file_count = len(current_inventory)
    new_count = len(new_files)
    changed_count = len(changed_files)
    removed_count = len(removed_files)
    needs_rag_build = bool(new_count or changed_count or removed_count)
    next_action = _next_action(new_count, changed_count, removed_count, initial_scan)

    _save_inventory(source_id, current_inventory)
    updates = {
        "last_scanned_at": now,
        "last_scan_file_count": file_count,
        "new_file_count": new_count,
        "changed_file_count": changed_count,
        "removed_file_count": removed_count,
        "last_scan_new_files": _sample_paths(new_files),
        "last_scan_changed_files": _sample_paths(changed_files),
        "last_scan_removed_files": _sample_paths(removed_files),
        "needs_rag_build": needs_rag_build,
        "next_action": next_action,
    }
    update_record(STORE, ID_FIELD, source_id, updates)
    return {
        "source_id": source_id,
        "scanned_at": now,
        "success": True,
        "file_count": file_count,
        "scan_path": scan_path,
        "initial_scan": initial_scan,
        "new_file_count": new_count,
        "changed_file_count": changed_count,
        "removed_file_count": removed_count,
        "new_files": _sample_paths(new_files),
        "changed_files": _sample_paths(changed_files),
        "removed_files": _sample_paths(removed_files),
        "needs_rag_build": needs_rag_build,
        "next_action": next_action,
    }


def _walk_files(root: str):
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            yield os.path.join(dirpath, f)
