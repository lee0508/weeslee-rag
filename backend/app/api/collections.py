"""
Collection management API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.core.auth import require_admin_token
from app.core.config import settings
from app.core.database import get_db
from app.models.collection import Collection
from app.services.platform_store import create_record, get_record, update_record
from app.services.rag_runtime import get_active_snapshot
from app.services.vectordb import get_vectordb, VectorDBService

router = APIRouter()
MAIN_COLLECTION_NAME = "weeslee_rag_main"


# Pydantic schemas
class CollectionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    source_id: Optional[str] = None
    client_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    dataset_id: Optional[str] = None


class CollectionUpdate(BaseModel):
    description: Optional[str] = None
    snapshot_id: Optional[str] = None
    dataset_id: Optional[str] = None


class CollectionResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_system: bool
    document_count: int
    vector_count: int
    storage_size: int
    source_id: Optional[str] = None
    client_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    dataset_id: Optional[str] = None

    class Config:
        from_attributes = True


class CollectionStats(BaseModel):
    id: int
    name: str
    document_count: int
    vector_count: int
    storage_size: int
    vectordb_count: int


class CollectionsBootstrapRequest(BaseModel):
    client_id: str
    source_id: str
    overwrite: bool = False


def _get_source_mount_path(source_id: str) -> str:
    rec = get_record("document_sources", "source_id", source_id) or {}
    return rec.get("mount_path") or rec.get("source_uri") or ""


def bootstrap_collection_config(client_id: str, source_id: str, overwrite: bool = False) -> dict:
    mount_path = _get_source_mount_path(source_id)
    active_snapshot = get_active_snapshot()
    coll_key = MAIN_COLLECTION_NAME
    record = {
        "collection_key": coll_key,
        "collection_name": MAIN_COLLECTION_NAME,
        "client_id": client_id,
        "source_id": source_id,
        "snapshot_id": active_snapshot,
        "name": MAIN_COLLECTION_NAME,
        "description": f"{settings.rag_source_folder} 통합 컬렉션. 문서 그룹과 문서 카테고리는 metadata filter로 처리",
        "source_root": settings.rag_source_folder,
        "mount_path": mount_path,
        "enabled": True,
    }
    existing = get_record("collections_active", "collection_key", coll_key)
    created = skipped = 0
    if existing:
        if overwrite:
            update_record("collections_active", "collection_key", coll_key, record)
            created = 1
        else:
            skipped = 1
    else:
        create_record("collections_active", record, id_field="collection_key")
        created = 1

    return {
        "success": True,
        "client_id": client_id,
        "source_id": source_id,
        "snapshot_id": active_snapshot,
        "created": created,
        "skipped": skipped,
        "items": [{"collection_key": coll_key, "name": MAIN_COLLECTION_NAME}],
    }


@router.get("/collections", response_model=List[CollectionResponse])
async def list_collections(
    db: Session = Depends(get_db)
):
    """List all collections"""
    collections = db.query(Collection).order_by(Collection.name).all()
    return collections


@router.post("/collections", response_model=CollectionResponse, status_code=status.HTTP_201_CREATED)
async def create_collection(
    data: CollectionCreate,
    db: Session = Depends(get_db),
    vectordb: VectorDBService = Depends(get_vectordb)
):
    """Create a new collection"""
    # Check if name already exists
    existing = db.query(Collection).filter(Collection.name == data.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Collection '{data.name}' already exists"
        )

    # Create in database
    collection = Collection(
        name=data.name,
        description=data.description,
        source_id=data.source_id,
        client_id=data.client_id,
        snapshot_id=data.snapshot_id,
        dataset_id=data.dataset_id,
    )
    db.add(collection)
    db.commit()
    db.refresh(collection)

    # Create in VectorDB
    vectordb.get_or_create_collection(
        name=data.name,
        metadata={"description": data.description or "", "db_id": collection.id}
    )

    return collection


@router.get("/collections/{collection_id}", response_model=CollectionResponse)
async def get_collection(
    collection_id: int,
    db: Session = Depends(get_db)
):
    """Get a collection by ID"""
    collection = db.query(Collection).filter(Collection.id == collection_id).first()
    if not collection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found"
        )
    return collection


@router.put("/collections/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: int,
    data: CollectionUpdate,
    db: Session = Depends(get_db)
):
    """Update a collection"""
    collection = db.query(Collection).filter(Collection.id == collection_id).first()
    if not collection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found"
        )

    if data.description is not None:
        collection.description = data.description
    if data.snapshot_id is not None:
        collection.snapshot_id = data.snapshot_id
    if data.dataset_id is not None:
        collection.dataset_id = data.dataset_id

    db.commit()
    db.refresh(collection)
    return collection


@router.delete("/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: int,
    db: Session = Depends(get_db),
    vectordb: VectorDBService = Depends(get_vectordb)
):
    """Delete a collection"""
    collection = db.query(Collection).filter(Collection.id == collection_id).first()
    if not collection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found"
        )

    if collection.is_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete system collection"
        )

    # Delete from VectorDB
    vectordb.delete_collection(collection.name)

    # Delete from database
    db.delete(collection)
    db.commit()


@router.get("/collections/{collection_id}/stats", response_model=CollectionStats)
async def get_collection_stats(
    collection_id: int,
    db: Session = Depends(get_db),
    vectordb: VectorDBService = Depends(get_vectordb)
):
    """Get collection statistics"""
    collection = db.query(Collection).filter(Collection.id == collection_id).first()
    if not collection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found"
        )

    # Get VectorDB stats
    vectordb_stats = vectordb.get_collection_stats(collection.name)

    return CollectionStats(
        id=collection.id,
        name=collection.name,
        document_count=collection.document_count,
        vector_count=collection.vector_count,
        storage_size=collection.storage_size,
        vectordb_count=vectordb_stats.get("count", 0)
    )


@router.post("/collections/{collection_id}/reindex", status_code=status.HTTP_202_ACCEPTED)
async def reindex_collection(
    collection_id: int,
    db: Session = Depends(get_db)
):
    """Trigger collection reindexing (async task)"""
    collection = db.query(Collection).filter(Collection.id == collection_id).first()
    if not collection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found"
        )

    # TODO: Trigger Celery task for reindexing
    return {
        "message": f"Reindexing started for collection '{collection.name}'",
        "collection_id": collection.id
    }


@router.post("/admin/collections/bootstrap", dependencies=[Depends(require_admin_token)])
async def bootstrap_collections_admin(body: CollectionsBootstrapRequest):
    """Document Source / Client 컨텍스트 기준 Collection bootstrap alias."""
    return bootstrap_collection_config(
        client_id=body.client_id,
        source_id=body.source_id,
        overwrite=body.overwrite,
    )
