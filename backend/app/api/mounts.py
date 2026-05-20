# 마운트 상태 확인 및 경로 유효성 테스트 API (초기 버전: 실행 없이 상태/경로 확인만)
import os
import shutil
from datetime import datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import require_admin_token
from app.services.platform_store import list_records

router = APIRouter(
    prefix="/admin/mounts",
    tags=["Platform - Mounts"],
    dependencies=[Depends(require_admin_token)],
)


class CheckPathRequest(BaseModel):
    path: str
    label: Optional[str] = None


class TestMountRequest(BaseModel):
    source_uri: str
    mount_path: Optional[str] = None


def _is_safe_path(path: str) -> bool:
    """관리자 입력 경로의 기본 안전성을 검증한다 (null 바이트·경로 순회 방지)."""
    if not path or len(path) > 512 or "\x00" in path:
        return False
    try:
        parts = PurePosixPath(path).parts + PureWindowsPath(path).parts
        return ".." not in parts
    except Exception:
        return False


def _path_info(path: str) -> dict:
    """경로의 존재/접근/타입/디스크 사용량을 반환한다."""
    if not path:
        return {"path": path, "accessible": False, "reason": "경로가 비어있습니다."}
    if not _is_safe_path(path):
        return {"path": path, "accessible": False, "reason": "유효하지 않은 경로입니다."}
    try:
        exists = os.path.exists(path)
        if not exists:
            return {"path": path, "accessible": False, "reason": "경로를 찾을 수 없습니다."}
        is_dir = os.path.isdir(path)
        result: dict = {"path": path, "accessible": True, "is_directory": is_dir}
        if is_dir:
            try:
                usage = shutil.disk_usage(path)
                result["disk"] = {
                    "total_gb": round(usage.total / 1e9, 2),
                    "used_gb": round(usage.used / 1e9, 2),
                    "free_gb": round(usage.free / 1e9, 2),
                }
            except Exception:
                pass
        return result
    except PermissionError:
        return {"path": path, "accessible": False, "reason": "접근 권한이 없습니다."}
    except Exception as e:
        return {"path": path, "accessible": False, "reason": str(e)}


@router.get("/status")
async def mount_status():
    """등록된 모든 Document Source의 마운트 경로 상태를 일괄 확인한다."""
    sources = list_records("document_sources")
    results = []
    checked_at = datetime.now(timezone.utc).isoformat()
    for src in sources:
        mount_path = src.get("mount_path", "")
        source_uri = src.get("source_uri", "")
        results.append({
            "source_id": src.get("source_id"),
            "source_name": src.get("source_name"),
            "client_id": src.get("client_id"),
            "mount_path": mount_path,
            "source_uri": source_uri,
            "mount_path_info": _path_info(mount_path) if mount_path else None,
            "source_uri_info": _path_info(source_uri) if source_uri else None,
            "checked_at": checked_at,
        })
    return {"checked_at": checked_at, "sources": results}


@router.post("/check-path")
async def check_path(body: CheckPathRequest):
    """단일 경로의 접근 가능 여부를 확인한다."""
    if not _is_safe_path(body.path):
        raise HTTPException(status_code=400, detail="유효하지 않은 경로입니다.")
    info = _path_info(body.path)
    return {
        "label": body.label,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        **info,
    }


@router.post("/test")
async def test_mount(body: TestMountRequest):
    """source_uri와 mount_path 양쪽을 모두 확인해 연결 가능 여부를 반환한다."""
    if not _is_safe_path(body.source_uri):
        raise HTTPException(status_code=400, detail="유효하지 않은 source_uri입니다.")
    if body.mount_path and not _is_safe_path(body.mount_path):
        raise HTTPException(status_code=400, detail="유효하지 않은 mount_path입니다.")

    now = datetime.now(timezone.utc).isoformat()
    uri_info = _path_info(body.source_uri)
    mount_info = _path_info(body.mount_path) if body.mount_path else None

    connected = uri_info.get("accessible") or (
        mount_info is not None and mount_info.get("accessible")
    )

    mount_commands = None
    if not connected and body.mount_path:
        mount_commands = {
            "mkdir": f"sudo mkdir -p {body.mount_path}",
            "mount_cifs": (
                f'sudo mount -t cifs "{body.source_uri}" {body.mount_path} '
                "-o credentials=/etc/samba/credentials.cred,iocharset=utf8,vers=3.0,ro"
            ),
            "fstab_entry": (
                f'"{body.source_uri}" {body.mount_path} cifs '
                "credentials=/etc/samba/credentials.cred,iocharset=utf8,vers=3.0,ro 0 0"
            ),
        }

    return {
        "tested_at": now,
        "connected": connected,
        "source_uri_info": uri_info,
        "mount_path_info": mount_info,
        "mount_commands": mount_commands,
    }
