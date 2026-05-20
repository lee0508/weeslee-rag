# Collection/Metadata/Tag/Keyword 템플릿 CRUD API
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import require_admin_token
from app.services.platform_store import (
    list_records, get_record, create_record, update_record,
    delete_record, seed_if_empty,
)

router = APIRouter(
    prefix="/admin/templates",
    tags=["Platform - Templates"],
    dependencies=[Depends(require_admin_token)],
)

# ─────────────────────────────────────────────
# Collection Templates
# ─────────────────────────────────────────────
COL_STORE = "collection_templates"
COL_ID = "template_id"

_WEESLEE_COLLECTIONS = [
    {"template_id": "col_all", "client_id": "weeslee", "name": "전체",
     "collection_key": "rag_source_all", "description": "모든 문서", "enabled": True},
    {"template_id": "col_rfp", "client_id": "weeslee", "name": "RFP",
     "collection_key": "rag_source_rfp", "description": "RFP 문서", "enabled": True},
    {"template_id": "col_proposal", "client_id": "weeslee", "name": "제안서",
     "collection_key": "rag_source_proposal", "description": "제안서 전체", "enabled": True},
    {"template_id": "col_deliverable", "client_id": "weeslee", "name": "산출물",
     "collection_key": "rag_source_deliverable", "description": "산출물 전체", "enabled": True},
    {"template_id": "col_prop_strategy", "client_id": "weeslee", "name": "제안서/전략및방법론",
     "collection_key": "rag_source_proposal_strategy", "description": "", "enabled": True},
    {"template_id": "col_prop_tech", "client_id": "weeslee", "name": "제안서/기술및기능",
     "collection_key": "rag_source_proposal_tech", "description": "", "enabled": True},
    {"template_id": "col_prop_pm", "client_id": "weeslee", "name": "제안서/프로젝트관리",
     "collection_key": "rag_source_proposal_pm", "description": "", "enabled": True},
    {"template_id": "col_prop_support", "client_id": "weeslee", "name": "제안서/프로젝트지원",
     "collection_key": "rag_source_proposal_support", "description": "", "enabled": True},
    {"template_id": "col_del_env", "client_id": "weeslee", "name": "산출물/환경분석",
     "collection_key": "rag_source_deliverable_env", "description": "", "enabled": True},
    {"template_id": "col_del_current", "client_id": "weeslee", "name": "산출물/현황분석",
     "collection_key": "rag_source_deliverable_current", "description": "", "enabled": True},
    {"template_id": "col_del_target", "client_id": "weeslee", "name": "산출물/목표모델",
     "collection_key": "rag_source_deliverable_target", "description": "", "enabled": True},
    {"template_id": "col_del_plan", "client_id": "weeslee", "name": "산출물/이행계획",
     "collection_key": "rag_source_deliverable_plan", "description": "", "enabled": True},
]


class CollectionTemplateCreate(BaseModel):
    template_id: Optional[str] = None
    client_id: str
    name: str
    collection_key: str
    description: Optional[str] = ""
    enabled: bool = True


class CollectionTemplateUpdate(BaseModel):
    name: Optional[str] = None
    collection_key: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None


@router.get("/collections")
async def list_collection_templates(client_id: Optional[str] = None):
    seed_if_empty(COL_STORE, _WEESLEE_COLLECTIONS, id_field=COL_ID)
    records = list_records(COL_STORE)
    if client_id:
        records = [r for r in records if r.get("client_id") == client_id]
    return records


@router.post("/collections", status_code=201)
async def create_collection_template(body: CollectionTemplateCreate):
    seed_if_empty(COL_STORE, _WEESLEE_COLLECTIONS, id_field=COL_ID)
    if body.template_id and get_record(COL_STORE, COL_ID, body.template_id):
        raise HTTPException(status_code=409, detail=f"template_id '{body.template_id}' already exists")
    return create_record(COL_STORE, body.model_dump(), id_field=COL_ID)


@router.get("/collections/{template_id}")
async def get_collection_template(template_id: str):
    seed_if_empty(COL_STORE, _WEESLEE_COLLECTIONS, id_field=COL_ID)
    rec = get_record(COL_STORE, COL_ID, template_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Collection template not found")
    return rec


@router.put("/collections/{template_id}")
async def update_collection_template(template_id: str, body: CollectionTemplateUpdate):
    updates = body.model_dump(exclude_unset=True)
    rec = update_record(COL_STORE, COL_ID, template_id, updates)
    if not rec:
        raise HTTPException(status_code=404, detail="Collection template not found")
    return rec


@router.delete("/collections/{template_id}", status_code=204)
async def delete_collection_template(template_id: str):
    if not delete_record(COL_STORE, COL_ID, template_id):
        raise HTTPException(status_code=404, detail="Collection template not found")


# ─────────────────────────────────────────────
# Metadata Templates
# ─────────────────────────────────────────────
META_STORE = "metadata_templates"
META_ID = "template_id"

_WEESLEE_METADATA_FIELDS = [
    "source_root", "source_path", "file_name", "file_ext",
    "document_group", "document_type", "proposal_section", "deliverable_section",
    "project_name", "project_type", "collection", "tags", "keywords",
    "index_policy", "search_priority", "confidential_level",
]

_WEESLEE_METADATA = [
    {
        "template_id": "meta_weeslee_default",
        "client_id": "weeslee",
        "name": "위즐리 기본 메타데이터",
        "fields": _WEESLEE_METADATA_FIELDS,
        "enabled": True,
    }
]


class MetadataTemplateCreate(BaseModel):
    template_id: Optional[str] = None
    client_id: str
    name: str
    fields: List[str]
    enabled: bool = True


class MetadataTemplateUpdate(BaseModel):
    name: Optional[str] = None
    fields: Optional[List[str]] = None
    enabled: Optional[bool] = None


@router.get("/metadata")
async def list_metadata_templates(client_id: Optional[str] = None):
    seed_if_empty(META_STORE, _WEESLEE_METADATA, id_field=META_ID)
    records = list_records(META_STORE)
    if client_id:
        records = [r for r in records if r.get("client_id") == client_id]
    return records


@router.post("/metadata", status_code=201)
async def create_metadata_template(body: MetadataTemplateCreate):
    seed_if_empty(META_STORE, _WEESLEE_METADATA, id_field=META_ID)
    if body.template_id and get_record(META_STORE, META_ID, body.template_id):
        raise HTTPException(status_code=409, detail=f"template_id '{body.template_id}' already exists")
    return create_record(META_STORE, body.model_dump(), id_field=META_ID)


@router.get("/metadata/{template_id}")
async def get_metadata_template(template_id: str):
    seed_if_empty(META_STORE, _WEESLEE_METADATA, id_field=META_ID)
    rec = get_record(META_STORE, META_ID, template_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Metadata template not found")
    return rec


@router.put("/metadata/{template_id}")
async def update_metadata_template(template_id: str, body: MetadataTemplateUpdate):
    updates = body.model_dump(exclude_unset=True)
    rec = update_record(META_STORE, META_ID, template_id, updates)
    if not rec:
        raise HTTPException(status_code=404, detail="Metadata template not found")
    return rec


@router.delete("/metadata/{template_id}", status_code=204)
async def delete_metadata_template(template_id: str):
    if not delete_record(META_STORE, META_ID, template_id):
        raise HTTPException(status_code=404, detail="Metadata template not found")
