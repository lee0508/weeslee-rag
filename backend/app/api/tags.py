# Tag CRUD API — 플랫폼 설정 저장소 기반
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import require_admin_token
from app.services.platform_store import (
    list_records, get_record, create_record, update_record,
    delete_record, seed_if_empty,
)

STORE = "tags"
ID_FIELD = "tag_id"

_DEFAULT_TAGS = [
    {"tag_id": "tag_ai", "tag_type": "technology", "tag_name": "AI", "keywords": ["AI", "인공지능", "생성형", "LLM"], "enabled": True},
    {"tag_id": "tag_isp", "tag_type": "project_type", "tag_name": "ISP", "keywords": ["ISP", "정보화전략계획"], "enabled": True},
    {"tag_id": "tag_ismp", "tag_type": "project_type", "tag_name": "ISMP", "keywords": ["ISMP"], "enabled": True},
    {"tag_id": "tag_bprisp", "tag_type": "project_type", "tag_name": "BPR/ISP", "keywords": ["BPRISP", "BPR/ISP"], "enabled": True},
    {"tag_id": "tag_bigdata", "tag_type": "technology", "tag_name": "빅데이터", "keywords": ["빅데이터", "데이터 플랫폼", "데이터허브"], "enabled": True},
    {"tag_id": "tag_cloud", "tag_type": "technology", "tag_name": "클라우드", "keywords": ["클라우드", "Cloud", "SaaS"], "enabled": True},
    {"tag_id": "tag_gis", "tag_type": "technology", "tag_name": "공간정보", "keywords": ["공간정보", "GIS", "지리정보"], "enabled": True},
    {"tag_id": "tag_health", "tag_type": "business_domain", "tag_name": "보건의료", "keywords": ["보건의료", "의료", "병원"], "enabled": True},
    {"tag_id": "tag_education", "tag_type": "business_domain", "tag_name": "교육", "keywords": ["교육", "학교", "대학"], "enabled": True},
    {"tag_id": "tag_public_safety", "tag_type": "business_domain", "tag_name": "소방/치안", "keywords": ["소방", "119", "경찰청"], "enabled": True},
]

router = APIRouter(
    prefix="/admin/tags",
    tags=["Platform - Tags"],
    dependencies=[Depends(require_admin_token)],
)


class TagCreate(BaseModel):
    tag_id: Optional[str] = None
    tag_type: str
    tag_name: str
    keywords: List[str] = []
    enabled: bool = True


class TagUpdate(BaseModel):
    tag_type: Optional[str] = None
    tag_name: Optional[str] = None
    keywords: Optional[List[str]] = None
    enabled: Optional[bool] = None


def _seed():
    seed_if_empty(STORE, _DEFAULT_TAGS, id_field=ID_FIELD)


@router.get("")
async def list_tags(tag_type: Optional[str] = None):
    _seed()
    records = list_records(STORE)
    if tag_type:
        records = [r for r in records if r.get("tag_type") == tag_type]
    return records


@router.post("", status_code=201)
async def create_tag(body: TagCreate):
    _seed()
    if body.tag_id and get_record(STORE, ID_FIELD, body.tag_id):
        raise HTTPException(status_code=409, detail=f"tag_id '{body.tag_id}' already exists")
    return create_record(STORE, body.model_dump(), id_field=ID_FIELD)


@router.get("/{tag_id}")
async def get_tag(tag_id: str):
    _seed()
    rec = get_record(STORE, ID_FIELD, tag_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Tag not found")
    return rec


@router.put("/{tag_id}")
async def update_tag(tag_id: str, body: TagUpdate):
    updates = body.model_dump(exclude_unset=True)
    rec = update_record(STORE, ID_FIELD, tag_id, updates)
    if not rec:
        raise HTTPException(status_code=404, detail="Tag not found")
    return rec


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(tag_id: str):
    if not delete_record(STORE, ID_FIELD, tag_id):
        raise HTTPException(status_code=404, detail="Tag not found")
