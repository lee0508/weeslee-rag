# -*- coding: utf-8 -*-
"""
Admin API endpoints for document management and RAG pipeline
"""
import os
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import asyncio
import json

from app.core.auth import require_admin_token
from app.services.document_pipeline import (
    document_pipeline_service,
    PipelineProgress,
    PipelineStage
)
from app.services.knowledge_source import knowledge_source_service
from app.core.config import settings


router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_admin_token)],
)


# Request/Response Models
class ProcessDocumentRequest(BaseModel):
    """Request to process a document"""
    file_path: str  # Relative path from knowledge source
    collection_name: str = "default"


class ProcessDocumentResponse(BaseModel):
    """Response from document processing"""
    success: bool
    document_id: Optional[int] = None
    collection_id: Optional[int] = None
    chunk_count: int = 0
    processing_time: float = 0.0
    metadata: Optional[dict] = None
    error: Optional[str] = None


class DocumentStatusResponse(BaseModel):
    """Document processing status"""
    document_id: int
    filename: str
    status: str
    chunk_count: int
    error_message: Optional[str] = None
    latest_progress: Optional[dict] = None
    created_at: str
    updated_at: str


class CollectionInfo(BaseModel):
    """Collection information"""
    id: int
    name: str
    description: Optional[str]
    document_count: int
    vector_count: int
    created_at: str


# Progress tracking for SSE
_processing_progress: dict = {}


def _update_progress(task_id: str, progress: PipelineProgress):
    """Update progress for a task"""
    _processing_progress[task_id] = {
        "stage": progress.stage.value,
        "progress": progress.progress,
        "message": progress.message,
        "details": progress.details
    }


@router.post("/documents/process", response_model=ProcessDocumentResponse)
async def process_document(request: ProcessDocumentRequest):
    """
    Process a document from knowledge source through RAG pipeline

    - **file_path**: Relative path to document from knowledge source root
    - **collection_name**: Target collection name (will be created if doesn't exist)
    """
    # Check if file exists
    full_path = os.path.join(
        knowledge_source_service.get_root_path(),
        request.file_path
    )

    if not os.path.exists(full_path):
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {request.file_path}"
        )

    # Process document
    result = await document_pipeline_service.process_from_knowledge_source(
        relative_path=request.file_path,
        collection_name=request.collection_name
    )

    return ProcessDocumentResponse(
        success=result.success,
        document_id=result.document_id,
        collection_id=result.collection_id,
        chunk_count=result.chunk_count,
        processing_time=result.processing_time,
        metadata=result.metadata,
        error=result.error
    )


@router.post("/documents/process-async")
async def process_document_async(
    request: ProcessDocumentRequest,
    background_tasks: BackgroundTasks
):
    """
    Start async document processing (returns task_id for progress tracking)
    """
    import uuid

    # Check if file exists
    full_path = os.path.join(
        knowledge_source_service.get_root_path(),
        request.file_path
    )

    if not os.path.exists(full_path):
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {request.file_path}"
        )

    # Generate task ID
    task_id = str(uuid.uuid4())
    _processing_progress[task_id] = {
        "stage": "initialized",
        "progress": 0,
        "message": "Processing started"
    }

    # Define progress callback
    def progress_callback(progress: PipelineProgress):
        _update_progress(task_id, progress)

    # Start background processing
    async def process_in_background():
        result = await document_pipeline_service.process_from_knowledge_source(
            relative_path=request.file_path,
            collection_name=request.collection_name,
            progress_callback=progress_callback
        )
        _processing_progress[task_id]["result"] = result.to_dict()

    background_tasks.add_task(asyncio.create_task, process_in_background())

    return {
        "task_id": task_id,
        "message": "Processing started",
        "file_path": request.file_path,
        "collection_name": request.collection_name
    }


@router.get("/documents/process-progress/{task_id}")
async def get_processing_progress(task_id: str):
    """Get progress of async document processing"""
    if task_id not in _processing_progress:
        raise HTTPException(
            status_code=404,
            detail=f"Task not found: {task_id}"
        )

    return _processing_progress[task_id]


@router.get("/documents/process-stream/{task_id}")
async def stream_processing_progress(task_id: str):
    """Stream progress updates using SSE"""
    if task_id not in _processing_progress:
        raise HTTPException(
            status_code=404,
            detail=f"Task not found: {task_id}"
        )

    async def generate():
        last_progress = -1
        while True:
            if task_id in _processing_progress:
                current = _processing_progress[task_id]
                if current.get("progress", 0) != last_progress:
                    last_progress = current.get("progress", 0)
                    yield f"data: {json.dumps(current)}\n\n"

                if current.get("stage") in ["completed", "failed"]:
                    yield f"data: {json.dumps(current)}\n\n"
                    break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream"
    )


@router.post("/documents/upload")
async def upload_and_process(
    file: UploadFile = File(...),
    collection_name: str = Query("default", description="Target collection")
):
    """
    Upload a document and process it through RAG pipeline
    """
    # Validate file type
    allowed_extensions = ['.pdf', '.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.xls', '.hwp', '.hwpx']
    file_ext = os.path.splitext(file.filename)[1].lower()

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file_ext}. Allowed: {allowed_extensions}"
        )

    # Save uploaded file
    upload_dir = os.path.join(settings.upload_dir, "documents")
    os.makedirs(upload_dir, exist_ok=True)

    file_path = os.path.join(upload_dir, file.filename)

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Process document
    try:
        result = await document_pipeline_service.process_document(
            file_path=file_path,
            collection_name=collection_name
        )

        return {
            "success": result.success,
            "document_id": result.document_id,
            "collection_id": result.collection_id,
            "chunk_count": result.chunk_count,
            "processing_time": result.processing_time,
            "metadata": result.metadata,
            "error": result.error
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Processing failed: {str(e)}"
        )


@router.get("/documents/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(document_id: int):
    """Get processing status of a document"""
    status = document_pipeline_service.get_document_status(document_id)

    if not status:
        raise HTTPException(
            status_code=404,
            detail=f"Document not found: {document_id}"
        )

    return DocumentStatusResponse(**status)


@router.get("/documents", response_model=List[dict])
async def list_documents(
    collection_id: Optional[int] = Query(None, description="Filter by collection"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000)
):
    """List processed documents"""
    from app.models.document import DocumentStatus

    doc_status = None
    if status:
        try:
            doc_status = DocumentStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status}"
            )

    return document_pipeline_service.list_processed_documents(
        collection_id=collection_id,
        status=doc_status,
        limit=limit
    )


@router.get("/documents/{document_id}/metadata")
async def get_document_metadata(document_id: int):
    """Get document metadata from metadata file"""
    metadata_dir = os.path.join(settings.upload_dir, "metadata")

    # Find metadata file
    for filename in os.listdir(metadata_dir) if os.path.exists(metadata_dir) else []:
        if filename.startswith(f"{document_id}_") and filename.endswith("_meta.json"):
            metadata_path = os.path.join(metadata_dir, filename)
            with open(metadata_path, 'r', encoding='utf-8') as f:
                return json.load(f)

    raise HTTPException(
        status_code=404,
        detail=f"Metadata not found for document: {document_id}"
    )


@router.get("/collections", response_model=List[CollectionInfo])
async def list_collections():
    """List all collections"""
    from app.core.database import SessionLocal
    from app.models.collection import Collection

    db = SessionLocal()
    try:
        collections = db.query(Collection).all()
        return [
            CollectionInfo(
                id=col.id,
                name=col.name,
                description=col.description,
                document_count=col.document_count,
                vector_count=col.vector_count,
                created_at=col.created_at.isoformat()
            )
            for col in collections
        ]
    finally:
        db.close()


@router.post("/collections")
async def create_collection(
    name: str = Query(..., description="Collection name"),
    description: Optional[str] = Query(None, description="Collection description")
):
    """Create a new collection"""
    from app.core.database import SessionLocal
    from app.models.collection import Collection

    db = SessionLocal()
    try:
        # Check if exists
        existing = db.query(Collection).filter(Collection.name == name).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Collection already exists: {name}"
            )

        collection = Collection(
            name=name,
            description=description
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)

        # Create in ChromaDB
        from app.services.vectordb import vectordb_service
        vectordb_service.get_or_create_collection(name)

        return {
            "id": collection.id,
            "name": collection.name,
            "description": collection.description,
            "created_at": collection.created_at.isoformat()
        }
    finally:
        db.close()


@router.delete("/collections/{collection_id}")
async def delete_collection(collection_id: int):
    """Delete a collection and all its documents"""
    from app.core.database import SessionLocal
    from app.models.collection import Collection
    from app.services.vectordb import vectordb_service

    db = SessionLocal()
    try:
        collection = db.query(Collection).filter(Collection.id == collection_id).first()

        if not collection:
            raise HTTPException(
                status_code=404,
                detail=f"Collection not found: {collection_id}"
            )

        if collection.is_system:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete system collection"
            )

        # Delete from ChromaDB
        vectordb_service.delete_collection(collection.name)

        # Delete from MySQL (cascades to documents and chunks)
        db.delete(collection)
        db.commit()

        return {"message": f"Collection deleted: {collection.name}"}
    finally:
        db.close()


@router.get("/system-check")
async def system_check():
    """Phase 1 검증용: HWP·OCR·Ollama·FAISS 가용 여부를 한번에 확인한다."""
    import importlib
    import subprocess
    import httpx
    from pathlib import Path

    from app.extractors.hwp_extractor import _hwp5txt_path

    project_root = Path(__file__).resolve().parents[3]

    def _run(cmd: list[str]) -> tuple[bool, str]:
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=10)
            out = (r.stdout + r.stderr).decode("utf-8", errors="replace").strip()
            return r.returncode == 0, out[:200]
        except FileNotFoundError:
            return False, "command not found"
        except Exception as e:
            return False, str(e)

    # hwp5txt (CLI) + hwp5 (Python module)
    hwp_cli_ok, hwp_cli_msg = _run([_hwp5txt_path(), "--version"])
    try:
        hwp5 = importlib.import_module("hwp5")
        hwp_module_ok = True
        hwp_module_msg = getattr(hwp5, "__file__", "hwp5 imported")
    except Exception as e:
        hwp_module_ok = False
        hwp_module_msg = str(e)

    hwp_ok = hwp_cli_ok or hwp_module_ok
    hwp_msg = (
        f"cli_ok={hwp_cli_ok}; cli={hwp_cli_msg[:120]}; "
        f"module_ok={hwp_module_ok}; module={hwp_module_msg[:120]}"
    )

    # tesseract OCR
    ocr_ok, ocr_msg = _run(["tesseract", "--version"])

    # Ollama
    ollama_ok, ollama_msg = False, ""
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
        ollama_ok = r.status_code == 200
        tags = [m.get("name", "") for m in r.json().get("models", [])]
        ollama_msg = f"{len(tags)} models: {', '.join(tags[:5])}"
    except Exception as e:
        ollama_msg = str(e)

    # FAISS active index
    active_index_path = project_root / "data" / "active_index.json"
    faiss_ok = False
    faiss_msg = "active_index.json not found"
    if active_index_path.exists():
        try:
            import json as _json
            info = _json.loads(active_index_path.read_text(encoding="utf-8"))
            snapshot = info.get("snapshot", "")
            idx = project_root / "data" / "indexes" / "faiss" / f"{snapshot}_ollama.index"
            faiss_ok = idx.exists()
            faiss_msg = f"snapshot={snapshot}, index={'exists' if faiss_ok else 'missing'}"
        except Exception as e:
            faiss_msg = str(e)

    # staged text dir
    text_dir = project_root / "data" / "staged" / "text"
    text_count = len(list(text_dir.glob("*.txt"))) if text_dir.exists() else 0

    return {
        "hwp_extractor":  {"ok": hwp_ok,    "detail": hwp_msg},
        "ocr_tesseract":  {"ok": ocr_ok,    "detail": ocr_msg},
        "ollama":         {"ok": ollama_ok,  "detail": ollama_msg},
        "faiss_index":    {"ok": faiss_ok,   "detail": faiss_msg},
        "staged_texts":   {"count": text_count, "dir": str(text_dir)},
    }


@router.get("/stats")
async def get_admin_stats():
    """Get admin dashboard statistics — FAISS-based (no MySQL dependency)."""
    import json
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[3]
    faiss_dir = project_root / "data" / "indexes" / "faiss"
    active_index_path = project_root / "data" / "active_index.json"

    # ── Active snapshot ────────────────────────────────────────────────────
    snapshot = ""
    if active_index_path.exists():
        try:
            snapshot = json.loads(active_index_path.read_text(encoding="utf-8")).get("snapshot", "")
        except Exception:
            pass

    # ── Main index stats ───────────────────────────────────────────────────
    chunk_count = 0
    doc_ids: set[str] = set()
    meta_path = faiss_dir / f"{snapshot}_ollama_metadata.jsonl" if snapshot else None
    if meta_path and meta_path.exists():
        try:
            for line in meta_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                chunk_count += 1
                try:
                    doc_ids.add(json.loads(line).get("document_id", ""))
                except Exception:
                    pass
        except Exception:
            pass

    # ── Category sub-index stats ───────────────────────────────────────────
    categories = ["rfp", "proposal", "kickoff", "final_report", "presentation"]
    category_stats: dict[str, int] = {}
    for cat in categories:
        cat_meta = faiss_dir / f"{snapshot}_{cat}_ollama_metadata.jsonl" if snapshot else None
        if cat_meta and cat_meta.exists():
            try:
                category_stats[cat] = sum(
                    1 for l in cat_meta.read_text(encoding="utf-8").splitlines() if l.strip()
                )
            except Exception:
                category_stats[cat] = 0
        else:
            category_stats[cat] = 0

    # ── Graph stats ────────────────────────────────────────────────────────
    graph_node_count = 0
    graph_edge_count = 0
    graph_dir = project_root / "data" / "indexes" / "graph"
    graph_nodes = graph_dir / "graph_nodes.jsonl"
    graph_edges = graph_dir / "graph_edges.jsonl"
    if graph_nodes.exists():
        try:
            graph_node_count = sum(
                1 for line in graph_nodes.read_text(encoding="utf-8").splitlines() if line.strip()
            )
        except Exception:
            graph_node_count = 0
    if graph_edges.exists():
        try:
            graph_edge_count = sum(
                1 for line in graph_edges.read_text(encoding="utf-8").splitlines() if line.strip()
            )
        except Exception:
            graph_edge_count = 0

    # ── Ollama status ──────────────────────────────────────────────────────
    ollama_ok = False
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
        ollama_ok = r.status_code == 200
    except Exception:
        pass

    return {
        "snapshot": snapshot or "(none)",
        "index": {
            "chunk_count": chunk_count,
            "document_count": len(doc_ids),
            "index_exists": bool(meta_path and meta_path.exists()),
        },
        "categories": category_stats,
        "graph": {
            "node_count": graph_node_count,
            "edge_count": graph_edge_count,
        },
        "ollama": {"status": "ok" if ollama_ok else "unavailable"},
        "knowledge_source": {
            "accessible": knowledge_source_service.is_accessible(),
            "root_path": knowledge_source_service.get_root_path(),
        },
    }
