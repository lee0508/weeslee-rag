"""
Collection management API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.models.collection import Collection
from app.services.vectordb import get_vectordb, VectorDBService

router = APIRouter()


# Pydantic schemas
class CollectionCreate(BaseModel):
    name: str
    description: Optional[str] = None


class CollectionUpdate(BaseModel):
    description: Optional[str] = None


class CollectionResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_system: bool
    document_count: int
    vector_count: int
    storage_size: int

    class Config:
        from_attributes = True


class CollectionStats(BaseModel):
    id: int
    name: str
    document_count: int
    vector_count: int
    storage_size: int
    vectordb_count: int


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
        description=data.description
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
