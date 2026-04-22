"""
Document management API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import os
import shutil

from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document, DocumentStatus, FileType
from app.models.collection import Collection

router = APIRouter()


# Pydantic schemas
class DocumentResponse(BaseModel):
    id: int
    collection_id: int
    filename: str
    file_type: str
    file_size: Optional[int]
    status: str
    error_message: Optional[str]
    chunk_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    total: int
    items: List[DocumentResponse]


class ProcessingStatusResponse(BaseModel):
    id: int
    filename: str
    status: str
    progress: int
    message: Optional[str]


# Helper functions
def get_file_type(filename: str) -> Optional[FileType]:
    """Get FileType enum from filename extension"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    type_map = {
        "ppt": FileType.PPT,
        "pptx": FileType.PPTX,
        "doc": FileType.DOC,
        "docx": FileType.DOCX,
        "hwp": FileType.HWP,
        "hwpx": FileType.HWPX,
        "pdf": FileType.PDF,
        "xlsx": FileType.XLSX
    }
    return type_map.get(ext)


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    collection_id: Optional[int] = None,
    status: Optional[str] = None,
    file_type: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """List documents with filtering"""
    query = db.query(Document)

    if collection_id:
        query = query.filter(Document.collection_id == collection_id)
    if status:
        query = query.filter(Document.status == status)
    if file_type:
        query = query.filter(Document.file_type == file_type)
    if search:
        query = query.filter(Document.filename.ilike(f"%{search}%"))

    total = query.count()
    items = query.order_by(Document.created_at.desc()).offset(skip).limit(limit).all()

    return DocumentListResponse(total=total, items=items)


@router.post("/documents/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    collection_id: int = Form(...),
    auto_process: bool = Form(True),
    db: Session = Depends(get_db)
):
    """Upload a document"""
    # Validate collection exists
    collection = db.query(Collection).filter(Collection.id == collection_id).first()
    if not collection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found"
        )

    # Validate file type
    file_type = get_file_type(file.filename)
    if not file_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Supported: ppt, pptx, doc, docx, hwp, hwpx, pdf, xlsx"
        )

    # Validate file size
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Seek back to start

    if file_size > settings.max_upload_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size: {settings.max_upload_size / 1024 / 1024}MB"
        )

    # Ensure upload directory exists
    upload_dir = os.path.join(settings.upload_dir, str(collection_id))
    os.makedirs(upload_dir, exist_ok=True)

    # Save file
    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Create document record
    document = Document(
        collection_id=collection_id,
        filename=file.filename,
        original_path=file_path,
        file_type=file_type,
        file_size=file_size,
        status=DocumentStatus.PENDING
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    # Update collection document count
    collection.document_count += 1
    db.commit()

    # TODO: If auto_process, trigger Celery task

    return document


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: int,
    db: Session = Depends(get_db)
):
    """Get a document by ID"""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    return document


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: int,
    db: Session = Depends(get_db)
):
    """Delete a document"""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    # Delete file if exists
    if document.original_path and os.path.exists(document.original_path):
        os.remove(document.original_path)

    # Update collection count
    collection = db.query(Collection).filter(Collection.id == document.collection_id).first()
    if collection:
        collection.document_count = max(0, collection.document_count - 1)

    # TODO: Delete from VectorDB

    # Delete from database
    db.delete(document)
    db.commit()


@router.post("/documents/{document_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
async def reprocess_document(
    document_id: int,
    db: Session = Depends(get_db)
):
    """Trigger document reprocessing"""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    # Reset status
    document.status = DocumentStatus.PENDING
    document.error_message = None
    db.commit()

    # TODO: Trigger Celery task

    return {
        "message": f"Reprocessing started for document '{document.filename}'",
        "document_id": document.id
    }


@router.get("/documents/{document_id}/status", response_model=ProcessingStatusResponse)
async def get_document_status(
    document_id: int,
    db: Session = Depends(get_db)
):
    """Get document processing status"""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    # Get latest processing log
    from app.models.document import ProcessingLog
    latest_log = db.query(ProcessingLog).filter(
        ProcessingLog.document_id == document_id
    ).order_by(ProcessingLog.created_at.desc()).first()

    progress = 0
    message = None

    if latest_log:
        progress = latest_log.progress
        message = latest_log.message
    elif document.status == DocumentStatus.COMPLETED:
        progress = 100
        message = "Processing completed"
    elif document.status == DocumentStatus.FAILED:
        message = document.error_message

    return ProcessingStatusResponse(
        id=document.id,
        filename=document.filename,
        status=document.status.value,
        progress=progress,
        message=message
    )
