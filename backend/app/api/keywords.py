# Keyword CRUD API — 플랫폼 설정 저장소 기반
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import require_admin_token
from app.services.metadata_db import metadata_db_service
from app.services.platform_store import (
    list_records, get_record, create_record, update_record,
    delete_record, seed_if_empty,
)

STORE = "keywords"
ID_FIELD = "keyword_id"

_DEFAULT_KEYWORDS = [
    {"keyword_id": "kw_isp", "keyword": "정보화전략계획", "category": "project_type", "weight": 2.0, "enabled": True},
    {"keyword_id": "kw_ismp", "keyword": "정보시스템마스터플랜", "category": "project_type", "weight": 2.0, "enabled": True},
    {"keyword_id": "kw_ai", "keyword": "인공지능", "category": "technology", "weight": 1.5, "enabled": True},
    {"keyword_id": "kw_llm", "keyword": "LLM", "category": "technology", "weight": 1.5, "enabled": True},
    {"keyword_id": "kw_digital_twin", "keyword": "디지털트윈", "category": "technology", "weight": 1.5, "enabled": True},
    {"keyword_id": "kw_cloud", "keyword": "클라우드", "category": "technology", "weight": 1.0, "enabled": True},
    {"keyword_id": "kw_bigdata", "keyword": "빅데이터", "category": "technology", "weight": 1.0, "enabled": True},
    {"keyword_id": "kw_strategy", "keyword": "전략 및 방법론", "category": "proposal_section", "weight": 1.0, "enabled": True},
    {"keyword_id": "kw_tech_func", "keyword": "기술 및 기능", "category": "proposal_section", "weight": 1.0, "enabled": True},
    {"keyword_id": "kw_pm", "keyword": "프로젝트 관리", "category": "proposal_section", "weight": 1.0, "enabled": True},
]

router = APIRouter(
    prefix="/admin/keywords",
    tags=["Platform - Keywords"],
    dependencies=[Depends(require_admin_token)],
)


class KeywordCreate(BaseModel):
    keyword_id: Optional[str] = None
    keyword: str
    category: Optional[str] = None
    weight: float = 1.0
    enabled: bool = True


class KeywordUpdate(BaseModel):
    keyword: Optional[str] = None
    category: Optional[str] = None
    weight: Optional[float] = None
    enabled: Optional[bool] = None


class KeywordsExtractRequest(BaseModel):
    overwrite: bool = False
    limit: int = 1000


def _seed():
    seed_if_empty(STORE, _DEFAULT_KEYWORDS, id_field=ID_FIELD)


def _normalize_keyword_value(value: str) -> str:
    import re
    return re.sub(r"\s+", " ", str(value or "")).strip()


def extract_keywords_from_metadata(body: KeywordsExtractRequest) -> dict:
    docs = metadata_db_service.list_documents(limit=max(1, min(body.limit, 10000)))
    existing = list_records(STORE)
    existing_by_keyword = {
        _normalize_keyword_value(item.get("keyword", "")).lower(): item
        for item in existing
        if _normalize_keyword_value(item.get("keyword", ""))
    }

    candidates: dict[str, dict] = {}

    def add_candidate(keyword: str, category: str, weight: float) -> None:
        normalized = _normalize_keyword_value(keyword)
        if len(normalized) < 2:
            return
        key = normalized.lower()
        current = candidates.get(key)
        if current and current["weight"] >= weight:
            return
        candidates[key] = {
            "keyword": normalized,
            "category": category,
            "weight": weight,
            "enabled": True,
        }

    for doc in docs:
        if not doc:
            continue
        project_name = doc.get("project_name") or ""
        organization = doc.get("organization") or ""
        document_type = doc.get("document_type") or ""

        if project_name:
            add_candidate(project_name, "project_name", 2.0)
        if organization:
            add_candidate(organization, "organization", 1.5)
        if document_type and document_type != "unknown":
            add_candidate(document_type, "document_type", 0.8)

    created = updated = skipped = 0
    items = []

    for key, candidate in candidates.items():
        existing_item = existing_by_keyword.get(key)
        if existing_item:
            if body.overwrite:
                update_record(STORE, ID_FIELD, existing_item[ID_FIELD], candidate)
                updated += 1
                items.append({"keyword": candidate["keyword"], "action": "updated"})
            else:
                skipped += 1
            continue

        create_record(STORE, candidate, id_field=ID_FIELD)
        created += 1
        items.append({"keyword": candidate["keyword"], "action": "created"})

    return {
        "success": True,
        "source": "metadata_documents",
        "total_documents": len(docs),
        "candidate_count": len(candidates),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "items": items[:50],
    }


@router.get("")
async def list_keywords(category: Optional[str] = None):
    _seed()
    records = list_records(STORE)
    if category:
        records = [r for r in records if r.get("category") == category]
    return records


@router.post("", status_code=201)
async def create_keyword(body: KeywordCreate):
    _seed()
    if body.keyword_id and get_record(STORE, ID_FIELD, body.keyword_id):
        raise HTTPException(status_code=409, detail=f"keyword_id '{body.keyword_id}' already exists")
    return create_record(STORE, body.model_dump(), id_field=ID_FIELD)


@router.get("/{keyword_id}")
async def get_keyword(keyword_id: str):
    _seed()
    rec = get_record(STORE, ID_FIELD, keyword_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Keyword not found")
    return rec


@router.put("/{keyword_id}")
async def update_keyword(keyword_id: str, body: KeywordUpdate):
    updates = body.model_dump(exclude_unset=True)
    rec = update_record(STORE, ID_FIELD, keyword_id, updates)
    if not rec:
        raise HTTPException(status_code=404, detail="Keyword not found")
    return rec


@router.delete("/{keyword_id}", status_code=204)
async def delete_keyword(keyword_id: str):
    if not delete_record(STORE, ID_FIELD, keyword_id):
        raise HTTPException(status_code=404, detail="Keyword not found")


@router.post("/extract")
async def extract_keywords_admin(body: KeywordsExtractRequest = KeywordsExtractRequest()):
    """Keyword extract alias for current admin structure."""
    return extract_keywords_from_metadata(body)
