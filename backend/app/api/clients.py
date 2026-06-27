# 고객사(Client/Tenant) CRUD API — 플랫폼 설정 저장소 기반
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import require_admin_token
from app.services.platform_store import (
    list_records, get_record, create_record, update_record,
    delete_record, seed_if_empty,
)

STORE = "clients"
ID_FIELD = "client_id"

_WEESLEE_DEFAULT = {
    "client_id": "weeslee",
    "client_name": "위즐리앤컴퍼니",
    "description": "위즐리 기본 클라이언트 (PoC)",
    "service_data_path": "/data/weeslee/weeslee-rag/data/clients/weeslee",
    "default_llm_model": "llama3:8b",
    "default_embedding_model": "nomic-embed-text",
    "default_vectordb_type": "faiss",
    "default_graph_mode": "jsonl",
    "enabled": True,
}

router = APIRouter(
    prefix="/admin/clients",
    tags=["Platform - Clients"],
    dependencies=[Depends(require_admin_token)],
)


class ClientCreate(BaseModel):
    client_id: str
    client_name: str
    description: Optional[str] = ""
    service_data_path: Optional[str] = ""
    default_llm_model: Optional[str] = "llama3:8b"
    default_embedding_model: Optional[str] = "nomic-embed-text"
    default_vectordb_type: Optional[str] = "faiss"
    default_graph_mode: Optional[str] = "jsonl"
    enabled: bool = True


class ClientUpdate(BaseModel):
    client_name: Optional[str] = None
    description: Optional[str] = None
    service_data_path: Optional[str] = None
    default_llm_model: Optional[str] = None
    default_embedding_model: Optional[str] = None
    default_vectordb_type: Optional[str] = None
    default_graph_mode: Optional[str] = None
    enabled: Optional[bool] = None


def _seed():
    seed_if_empty(STORE, [_WEESLEE_DEFAULT], id_field=ID_FIELD)


@router.get("")
async def list_clients():
    _seed()
    return list_records(STORE)


@router.post("", status_code=201)
async def create_client(body: ClientCreate):
    _seed()
    if get_record(STORE, ID_FIELD, body.client_id):
        raise HTTPException(status_code=409, detail=f"client_id '{body.client_id}' already exists")
    return create_record(STORE, body.model_dump(), id_field=ID_FIELD)


@router.get("/{client_id}")
async def get_client(client_id: str):
    _seed()
    rec = get_record(STORE, ID_FIELD, client_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Client not found")
    return rec


@router.put("/{client_id}")
async def update_client(client_id: str, body: ClientUpdate):
    updates = body.model_dump(exclude_unset=True)
    rec = update_record(STORE, ID_FIELD, client_id, updates)
    if not rec:
        raise HTTPException(status_code=404, detail="Client not found")
    return rec


@router.delete("/{client_id}", status_code=204)
async def delete_client(client_id: str):
    if not delete_record(STORE, ID_FIELD, client_id):
        raise HTTPException(status_code=404, detail="Client not found")
