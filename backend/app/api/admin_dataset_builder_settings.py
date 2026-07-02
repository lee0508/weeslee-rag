from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import require_admin_token
from app.services.dataset_build_settings import (
    get_dataset_build_settings,
    get_step_config,
    is_step_enabled,
    save_dataset_build_settings,
)


router = APIRouter(
    prefix="/admin/dataset-builder/settings",
    tags=["Admin - Dataset Builder Settings"],
    dependencies=[Depends(require_admin_token)],
)

_ALLOWED_STEPS = {"3", "4", "5", "6", "7", "8", "10"}


class DatasetBuildSettingsUpdateRequest(BaseModel):
    dataset_id: str | None = None
    step3_enabled: bool | None = None
    step3_config: dict[str, Any] | None = None
    step4_enabled: bool | None = None
    step4_config: dict[str, Any] | None = None
    step5_enabled: bool | None = None
    step5_config: dict[str, Any] | None = None
    step6_enabled: bool | None = None
    step6_config: dict[str, Any] | None = None
    step7_enabled: bool | None = None
    step7_config: dict[str, Any] | None = None
    step8_enabled: bool | None = None
    step8_config: dict[str, Any] | None = None
    step10_enabled: bool | None = None
    step10_config: dict[str, Any] | None = None


class StepSettingsUpdateRequest(BaseModel):
    enabled: bool | None = None
    config: dict[str, Any] = Field(default_factory=dict)


def _validate_step(step: str) -> str:
    step_value = str(step or "").strip()
    if step_value not in _ALLOWED_STEPS:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 step입니다: {step}")
    return step_value


@router.get("/{source_id}")
async def get_settings(source_id: str):
    return {
        "success": True,
        "source_id": source_id,
        "settings": get_dataset_build_settings(source_id),
    }


@router.put("/{source_id}")
async def update_settings(source_id: str, body: DatasetBuildSettingsUpdateRequest):
    saved = save_dataset_build_settings(source_id, body.model_dump(exclude_none=True))
    return {
        "success": True,
        "source_id": source_id,
        "settings": get_dataset_build_settings(source_id) if saved else {},
    }


@router.get("/{source_id}/step/{step}")
async def get_step_settings(source_id: str, step: str):
    step_value = _validate_step(step)
    return {
        "success": True,
        "source_id": source_id,
        "step": step_value,
        "enabled": is_step_enabled(source_id, step_value),
        "config": get_step_config(source_id, step_value),
    }


@router.put("/{source_id}/step/{step}")
async def update_step_settings(source_id: str, step: str, body: StepSettingsUpdateRequest):
    step_value = _validate_step(step)
    payload: dict[str, Any] = {
        f"step{step_value}_config": body.config or {},
    }
    if body.enabled is not None:
        payload[f"step{step_value}_enabled"] = body.enabled
    save_dataset_build_settings(source_id, payload)
    return {
        "success": True,
        "source_id": source_id,
        "step": step_value,
        "enabled": is_step_enabled(source_id, step_value),
        "config": get_step_config(source_id, step_value),
    }
