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

# 위즐리 컬렉션 템플릿 - 실제 폴더 구조 기준 (2026-06-04 정합성 검토)
# 실제 폴더 구조:
#   00. RAG 소스/
#   ├── 01. RFP (47개)
#   ├── 02. 제안서/
#   │   ├── 01. 전략및방법론 (36개)
#   │   ├── 02. 기술및기능 (36개)
#   │   ├── 03. 프로젝트관리 (34개)
#   │   ├── 04. 프로젝트지원 (32개)
#   │   └── 05. 연구과제 (9개)
#   └── 03. 산출물/
#       ├── 01. 환경분석 (8개)
#       ├── 02. 현황분석 (15개)
#       ├── 03. 목표모델 (19개)
#       ├── 04. 이행계획 (10개)
#       └── 05. 연구과제 (4개)
# 주의: 감리/PMO/PoC 폴더는 현재 존재하지 않음 (enabled=False)
_WEESLEE_COLLECTIONS = [
    # 전체 및 최상위 카테고리
    {"template_id": "col_all", "client_id": "weeslee", "name": "전체",
     "collection_key": "rag_source_all", "description": "모든 문서 (250개)", "enabled": True},
    {"template_id": "col_rfp", "client_id": "weeslee", "name": "RFP",
     "collection_key": "rag_source_rfp", "description": "RFP 문서 (47개)", "enabled": True},
    {"template_id": "col_proposal", "client_id": "weeslee", "name": "제안서",
     "collection_key": "rag_source_proposal", "description": "제안서 전체 (147개)", "enabled": True},
    {"template_id": "col_deliverable", "client_id": "weeslee", "name": "산출물",
     "collection_key": "rag_source_deliverable", "description": "산출물 전체 (56개)", "enabled": True},
    # 제안서 하위 - 실제 존재하는 폴더
    {"template_id": "col_prop_strategy", "client_id": "weeslee", "name": "제안서/전략및방법론",
     "collection_key": "rag_source_proposal_strategy", "description": "36개 파일", "enabled": True},
    {"template_id": "col_prop_tech", "client_id": "weeslee", "name": "제안서/기술및기능",
     "collection_key": "rag_source_proposal_tech", "description": "36개 파일", "enabled": True},
    {"template_id": "col_prop_pm", "client_id": "weeslee", "name": "제안서/프로젝트관리",
     "collection_key": "rag_source_proposal_pm", "description": "34개 파일", "enabled": True},
    {"template_id": "col_prop_support", "client_id": "weeslee", "name": "제안서/프로젝트지원",
     "collection_key": "rag_source_proposal_support", "description": "32개 파일", "enabled": True},
    {"template_id": "col_prop_research", "client_id": "weeslee", "name": "제안서/연구과제",
     "collection_key": "rag_source_proposal_research", "description": "9개 파일", "enabled": True},
    # 제안서 하위 - 미존재 폴더 (향후 확장용, 비활성화)
    {"template_id": "col_prop_audit", "client_id": "weeslee", "name": "제안서/감리",
     "collection_key": "rag_source_proposal_audit", "description": "폴더 미존재", "enabled": False},
    {"template_id": "col_prop_pmo", "client_id": "weeslee", "name": "제안서/PMO",
     "collection_key": "rag_source_proposal_pmo", "description": "폴더 미존재", "enabled": False},
    {"template_id": "col_prop_poc", "client_id": "weeslee", "name": "제안서/PoC",
     "collection_key": "rag_source_proposal_poc", "description": "폴더 미존재", "enabled": False},
    # 산출물 하위 - 실제 존재하는 폴더
    {"template_id": "col_del_env", "client_id": "weeslee", "name": "산출물/환경분석",
     "collection_key": "rag_source_deliverable_env", "description": "8개 파일", "enabled": True},
    {"template_id": "col_del_current", "client_id": "weeslee", "name": "산출물/현황분석",
     "collection_key": "rag_source_deliverable_current", "description": "15개 파일", "enabled": True},
    {"template_id": "col_del_target", "client_id": "weeslee", "name": "산출물/목표모델",
     "collection_key": "rag_source_deliverable_target", "description": "19개 파일", "enabled": True},
    {"template_id": "col_del_plan", "client_id": "weeslee", "name": "산출물/이행계획",
     "collection_key": "rag_source_deliverable_plan", "description": "10개 파일", "enabled": True},
    {"template_id": "col_del_research", "client_id": "weeslee", "name": "산출물/연구과제",
     "collection_key": "rag_source_deliverable_research", "description": "4개 파일", "enabled": True},
    # 산출물 하위 - 미존재 폴더 (향후 확장용, 비활성화)
    {"template_id": "col_del_audit", "client_id": "weeslee", "name": "산출물/감리",
     "collection_key": "rag_source_deliverable_audit", "description": "폴더 미존재", "enabled": False},
    {"template_id": "col_del_pmo", "client_id": "weeslee", "name": "산출물/PMO",
     "collection_key": "rag_source_deliverable_pmo", "description": "폴더 미존재", "enabled": False},
    {"template_id": "col_del_poc", "client_id": "weeslee", "name": "산출물/PoC",
     "collection_key": "rag_source_deliverable_poc", "description": "폴더 미존재", "enabled": False},
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
