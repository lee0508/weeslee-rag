# Search Scope 관리 API (admin.html의 Publish 탭 연동)
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.search_scope_service import get_search_scope_catalog, save_default_scope_id

router = APIRouter(prefix="/admin/search-scopes", tags=["admin-search-scopes"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = DATA_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "search_profiles.json"


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {"default_scope_id": "active_snapshot", "profiles": [], "updated_at": None}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"default_scope_id": "active_snapshot", "profiles": [], "updated_at": None}
    if not isinstance(data, dict):
        return {"default_scope_id": "active_snapshot", "profiles": [], "updated_at": None}
    return {
        "default_scope_id": str(data.get("default_scope_id") or "active_snapshot"),
        "profiles": data.get("profiles") if isinstance(data.get("profiles"), list) else [],
        "updated_at": data.get("updated_at"),
    }


def _save_config(config: dict[str, Any]) -> None:
    config["updated_at"] = _now_iso()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class ProfileRequest(BaseModel):
    profile_id: Optional[str] = None
    label: str
    description: Optional[str] = ""
    snapshot_ids: list[str] = []


class DefaultScopeRequest(BaseModel):
    scope_id: str


@router.get("")
async def get_search_scopes():
    """Search Scope 전체 카탈로그 조회."""
    catalog = get_search_scope_catalog()
    return {
        "success": True,
        **catalog,
        "profiles": _load_config().get("profiles", []),
    }


@router.post("/profile")
async def save_profile(request: ProfileRequest):
    """Search Scope 프로필 생성 또는 수정."""
    config = _load_config()
    profiles: list[dict[str, Any]] = config.get("profiles", [])

    label = (request.label or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="label은 필수입니다.")

    snapshot_ids = [sid.strip() for sid in request.snapshot_ids if sid.strip()]
    if not snapshot_ids:
        raise HTTPException(status_code=400, detail="최소 1개 이상의 snapshot_id가 필요합니다.")

    entries = [{"snapshot_id": sid} for sid in snapshot_ids]

    profile_id = (request.profile_id or "").strip()
    now = _now_iso()

    if profile_id:
        found = False
        for profile in profiles:
            if profile.get("profile_id") == profile_id:
                profile["label"] = label
                profile["description"] = request.description or ""
                profile["entries"] = entries
                profile["updated_at"] = now
                found = True
                break
        if not found:
            raise HTTPException(status_code=404, detail=f"profile_id '{profile_id}'를 찾을 수 없습니다.")
    else:
        profile_id = f"custom_{int(datetime.utcnow().timestamp() * 1000)}"
        profiles.append({
            "profile_id": profile_id,
            "label": label,
            "description": request.description or "",
            "entries": entries,
            "created_at": now,
            "updated_at": now,
        })

    config["profiles"] = profiles
    _save_config(config)

    return {
        "success": True,
        "profile_id": profile_id,
        "message": f"프로필 '{label}' 저장 완료",
    }


@router.post("/default")
async def set_default_scope(request: DefaultScopeRequest):
    """기본 Search Scope 설정."""
    scope_id = (request.scope_id or "").strip()
    if not scope_id:
        raise HTTPException(status_code=400, detail="scope_id는 필수입니다.")

    save_default_scope_id(scope_id)

    return {
        "success": True,
        "scope_id": scope_id,
        "message": f"기본 Scope를 '{scope_id}'로 설정했습니다.",
    }


@router.delete("/profile/{profile_id}")
async def delete_profile(profile_id: str):
    """Search Scope 프로필 삭제."""
    config = _load_config()
    profiles: list[dict[str, Any]] = config.get("profiles", [])

    original_count = len(profiles)
    profiles = [p for p in profiles if p.get("profile_id") != profile_id]

    if len(profiles) == original_count:
        raise HTTPException(status_code=404, detail=f"profile_id '{profile_id}'를 찾을 수 없습니다.")

    config["profiles"] = profiles

    if config.get("default_scope_id") == profile_id:
        config["default_scope_id"] = "active_snapshot"

    _save_config(config)

    return {
        "success": True,
        "profile_id": profile_id,
        "message": f"프로필 '{profile_id}' 삭제 완료",
    }
