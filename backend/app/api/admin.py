# -*- coding: utf-8 -*-
"""
Admin API endpoints for document management and RAG pipeline
"""
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import asyncio
import json

from app.core.auth import require_admin_token

# ── 메모리 캐시 (dataset/status-summary API 성능 최적화) ─────────────────────
# TTL: 60초, 반복 요청 시 캐시된 결과 반환
_status_summary_cache: Dict[str, Tuple[Any, datetime]] = {}
_STATUS_CACHE_TTL_SECONDS = 60
from app.core.database import SessionLocal
from app.services.document_pipeline import (
    document_pipeline_service,
    PipelineProgress,
)
from app.services.knowledge_source import knowledge_source_service
from app.services.metadata_db import metadata_db_service  # Legacy SQLite (deprecated)
from app.services.unified_document_service import unified_document_service  # MySQL primary
from app.services.metadata_auto_generator import metadata_auto_generator
from app.services.admin_stats_service import get_snapshot_stats
from app.services.runtime_compute_settings import (
    get_runtime_compute_snapshot,
    save_runtime_compute_settings,
)
from app.core.config import settings
from app.models.document_pipeline_status import DatasetStatusSummary


router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_admin_token)],
)

# 읽기 전용 공개 엔드포인트용 라우터 (인증 불필요)
public_router = APIRouter(
    prefix="/admin",
    tags=["Admin Public"],
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


class RuntimeComputeSettingsRequest(BaseModel):
    gpu_enabled: bool = False
    cuda_visible_devices: str = "0"
    ollama_use_gpu: bool = False
    ocr_use_gpu: bool = True
    chunk_use_gpu: bool = False
    embedding_use_gpu: bool = True
    faiss_use_gpu: bool = True


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


@router.get("/documents-legacy", response_model=List[dict])
async def list_documents_legacy(
    collection_id: Optional[int] = Query(None, description="Filter by collection"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000)
):
    """List processed documents (legacy MySQL/ChromaDB endpoint)"""
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

    compute = get_runtime_compute_snapshot()

    return {
        "hwp_extractor":  {"ok": hwp_ok,    "detail": hwp_msg},
        "ocr_tesseract":  {"ok": ocr_ok,    "detail": ocr_msg},
        "ollama":         {"ok": ollama_ok,  "detail": ollama_msg},
        "faiss_index":    {"ok": faiss_ok,   "detail": faiss_msg},
        "staged_texts":   {"count": text_count, "dir": str(text_dir)},
        "compute": compute,
    }


@router.get("/runtime-compute-settings")
async def get_runtime_compute_settings_api():
    """GPU/CPU 런타임 설정과 현재 감지 상태를 반환한다."""
    return get_runtime_compute_snapshot()


@router.post("/runtime-compute-settings")
async def save_runtime_compute_settings_api(request: RuntimeComputeSettingsRequest):
    """GPU/CPU 런타임 설정을 저장한다."""
    saved = save_runtime_compute_settings(request.model_dump())
    return {
        "success": True,
        "message": "런타임 GPU 설정이 저장되었습니다.",
        "data": saved,
        "snapshot": get_runtime_compute_snapshot(),
    }


@router.get("/stats")
async def get_admin_stats_cached():
    """Get cached admin dashboard statistics backed by snapshot artifacts."""
    import json
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[3]
    active_index_path = project_root / "data" / "active_index.json"

    snapshot = ""
    if active_index_path.exists():
        try:
            snapshot = json.loads(active_index_path.read_text(encoding="utf-8")).get("snapshot", "")
        except Exception:
            pass

    stats = get_snapshot_stats(snapshot)

    ollama_ok = False
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
        ollama_ok = r.status_code == 200
    except Exception:
        pass

    return {
        "snapshot": stats["snapshot"],
        "index": stats["index"],
        "categories": stats["categories"],
        "graph": stats["graph"],
        "ollama": {"status": "ok" if ollama_ok else "unavailable"},
        "knowledge_source": {
            "accessible": knowledge_source_service.is_accessible(),
            "root_path": knowledge_source_service.get_root_path(),
        },
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
                    1 for line in cat_meta.read_text(encoding="utf-8").splitlines() if line.strip()
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


# ────────────────────────────────────────────────────────────────────────────
# MySQL 기반 문서 메타데이터 관리 API (통합 스키마)
# ────────────────────────────────────────────────────────────────────────────

@router.get("/documents/stats")
async def get_document_stats():
    """문서 현황 통계 반환 (MySQL document_metadata 기준)."""
    return unified_document_service.get_document_stats()


@router.get("/documents")
async def list_documents_mysql(
    document_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    meta_status: Optional[str] = Query(None),
    organization: Optional[str] = Query(None),
    project_year: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    source_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """문서 목록 조회 (MySQL document_metadata 기준)."""
    documents = unified_document_service.list_documents(
        document_type=document_type,
        status=status,
        meta_status=meta_status,
        organization=organization,
        project_year=project_year,
        search=search,
        source_id=source_id,
        limit=limit,
        offset=offset,
    )
    total = unified_document_service.count_documents(
        document_type=document_type,
        status=status,
        meta_status=meta_status,
        source_id=source_id,
    )
    return {"documents": documents, "count": len(documents), "total": total}


@router.get("/documents/{document_id}")
async def get_document_detail(document_id: int):
    """문서 상세 조회 (MySQL) - suggestion 포함."""
    doc = unified_document_service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    # Legacy SQLite suggestion 데이터 포함 (하위 호환)
    try:
        suggestion = metadata_db_service.get_suggestion(document_id)
        if suggestion:
            doc["suggestion"] = suggestion
    except Exception:
        pass  # SQLite 없으면 무시
    return doc


@router.put("/documents/{document_id}")
async def update_document_metadata(document_id: int, data: dict):
    """문서 메타데이터 업데이트 (MySQL)."""
    success = unified_document_service.update_document(document_id, data)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found or no changes")
    return {"success": True}


@router.delete("/documents/{document_id}")
async def delete_document_mysql(document_id: int):
    """문서 삭제 (MySQL)."""
    success = unified_document_service.delete_document(document_id)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"success": True}


@router.get("/documents/{document_id}/suggestion")
async def get_metadata_suggestion(document_id: int):
    """자동 생성 메타데이터 제안 조회 (Legacy SQLite)."""
    suggestion = metadata_db_service.get_suggestion(document_id)
    if not suggestion:
        raise HTTPException(status_code=404, detail="No suggestion found")
    return suggestion


@router.post("/documents/{document_id}/auto-metadata")
async def auto_generate_metadata(
    document_id: int,
    use_llm: bool = Query(False, description="LLM 사용 여부")
):
    """단일 문서 자동 메타데이터 생성."""
    doc = metadata_db_service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_name = doc.get("file_name", "")
    file_path = doc.get("file_path", "")

    # 파일 내용 읽기 시도 (텍스트 파일인 경우)
    file_content = ""
    if file_path:
        try:
            from pathlib import Path
            fp = Path(file_path)
            if fp.exists() and fp.suffix.lower() in ['.txt', '.md']:
                file_content = fp.read_text(encoding='utf-8')[:3000]
        except Exception:
            pass

    # 메타데이터 추출
    if use_llm:
        extracted = await metadata_auto_generator.extract_with_llm(
            file_name=file_name,
            file_content=file_content
        )
    else:
        extracted = metadata_auto_generator.extract_metadata(
            file_name=file_name,
            file_content=file_content
        )

    # 제안 데이터 구성
    suggestion_data = {
        "document_type": extracted.get("document_type", "unknown"),
        "project_name": extracted.get("project_name", ""),
        "organization": extracted.get("organization", ""),
        "project_year": extracted.get("project_year", ""),
        "business_domain": extracted.get("business_domain", ""),
        "summary": extracted.get("summary", ""),
        "reuse_level": extracted.get("reuse_level", "medium"),
        "confidence": extracted.get("confidence", 0.0),
        "technology_tags": json.dumps(extracted.get("technology_tags", []), ensure_ascii=False),
        "business_tags": json.dumps(extracted.get("business_tags", []), ensure_ascii=False),
        "deliverable_tags": json.dumps(extracted.get("deliverable_tags", []), ensure_ascii=False),
        "reason": extracted.get("reason", ""),
        "status": "auto_suggested",
    }

    metadata_db_service.create_suggestion(document_id, suggestion_data)
    metadata_db_service.update_document(document_id, {"meta_status": "auto_suggested"})

    return {
        "success": True,
        "message": "Auto metadata generated",
        "suggestion": suggestion_data
    }


@router.post("/documents/auto-metadata-all")
async def auto_generate_all_metadata():
    """전체 문서 자동 메타데이터 일괄 생성 (규칙 기반)."""
    documents = metadata_db_service.list_documents(meta_status="pending", limit=1000)
    generated = 0
    errors = []

    for doc in documents:
        try:
            file_name = doc.get("file_name", "")
            file_path = doc.get("file_path", "")

            # 파일 내용 읽기 시도
            file_content = ""
            if file_path:
                try:
                    from pathlib import Path
                    fp = Path(file_path)
                    if fp.exists() and fp.suffix.lower() in ['.txt', '.md']:
                        file_content = fp.read_text(encoding='utf-8')[:3000]
                except Exception:
                    pass

            # 규칙 기반 메타데이터 추출
            extracted = metadata_auto_generator.extract_metadata(
                file_name=file_name,
                file_content=file_content
            )

            suggestion_data = {
                "document_type": extracted.get("document_type", "unknown"),
                "project_name": extracted.get("project_name", ""),
                "organization": extracted.get("organization", ""),
                "project_year": extracted.get("project_year", ""),
                "business_domain": extracted.get("business_domain", ""),
                "summary": extracted.get("summary", ""),
                "reuse_level": extracted.get("reuse_level", "medium"),
                "confidence": extracted.get("confidence", 0.0),
                "technology_tags": json.dumps(extracted.get("technology_tags", []), ensure_ascii=False),
                "business_tags": json.dumps(extracted.get("business_tags", []), ensure_ascii=False),
                "deliverable_tags": json.dumps(extracted.get("deliverable_tags", []), ensure_ascii=False),
                "reason": extracted.get("reason", ""),
                "status": "auto_suggested",
            }

            metadata_db_service.create_suggestion(doc["id"], suggestion_data)
            metadata_db_service.update_document(doc["id"], {"meta_status": "auto_suggested"})
            generated += 1
        except Exception as e:
            errors.append({"id": doc.get("id"), "error": str(e)})

    return {
        "success": True,
        "generated": generated,
        "total": len(documents),
        "errors": errors[:10]
    }


@router.post("/documents/auto-metadata-batch")
async def auto_generate_batch_metadata(
    data: dict,
    use_llm: bool = Query(False, description="LLM 사용 여부")
):
    """선택 문서 자동 메타데이터 일괄 생성."""
    document_ids = data.get("document_ids", [])
    generated = 0
    errors = []

    for doc_id in document_ids:
        try:
            doc = metadata_db_service.get_document(doc_id)
            if not doc:
                errors.append({"id": doc_id, "error": "Document not found"})
                continue

            file_name = doc.get("file_name", "")
            file_path = doc.get("file_path", "")

            # 파일 내용 읽기 시도
            file_content = ""
            if file_path:
                try:
                    from pathlib import Path
                    fp = Path(file_path)
                    if fp.exists() and fp.suffix.lower() in ['.txt', '.md']:
                        file_content = fp.read_text(encoding='utf-8')[:3000]
                except Exception:
                    pass

            # 메타데이터 추출
            if use_llm:
                extracted = await metadata_auto_generator.extract_with_llm(
                    file_name=file_name,
                    file_content=file_content
                )
            else:
                extracted = metadata_auto_generator.extract_metadata(
                    file_name=file_name,
                    file_content=file_content
                )

            suggestion_data = {
                "document_type": extracted.get("document_type", "unknown"),
                "project_name": extracted.get("project_name", ""),
                "organization": extracted.get("organization", ""),
                "project_year": extracted.get("project_year", ""),
                "business_domain": extracted.get("business_domain", ""),
                "summary": extracted.get("summary", ""),
                "reuse_level": extracted.get("reuse_level", "medium"),
                "confidence": extracted.get("confidence", 0.0),
                "technology_tags": json.dumps(extracted.get("technology_tags", []), ensure_ascii=False),
                "business_tags": json.dumps(extracted.get("business_tags", []), ensure_ascii=False),
                "deliverable_tags": json.dumps(extracted.get("deliverable_tags", []), ensure_ascii=False),
                "reason": extracted.get("reason", ""),
                "status": "auto_suggested",
            }

            metadata_db_service.create_suggestion(doc_id, suggestion_data)
            metadata_db_service.update_document(doc_id, {"meta_status": "auto_suggested"})
            generated += 1
        except Exception as e:
            errors.append({"id": doc_id, "error": str(e)})

    return {
        "success": True,
        "generated": generated,
        "total": len(document_ids),
        "errors": errors[:10]
    }


@router.post("/documents/{document_id}/confirm-metadata")
async def confirm_metadata(document_id: int, data: dict):
    """메타데이터 확정 저장."""
    doc = metadata_db_service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    success = metadata_db_service.confirm_suggestion(document_id, data)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to confirm metadata")

    return {"success": True, "message": "Metadata confirmed"}


@router.post("/documents/confirm-metadata-batch")
async def confirm_metadata_batch(data: dict):
    """메타데이터 일괄 확정 - 제안 데이터를 그대로 확정."""
    document_ids = data.get("document_ids", [])
    min_confidence = data.get("min_confidence", 0.5)
    confirmed = 0
    skipped = 0
    errors = []

    for doc_id in document_ids:
        try:
            doc = metadata_db_service.get_document(doc_id)
            if not doc:
                errors.append({"id": doc_id, "error": "Document not found"})
                continue

            suggestion = metadata_db_service.get_suggestion(doc_id)
            if not suggestion:
                skipped += 1
                continue

            # 신뢰도 체크
            if suggestion.get("confidence", 0) < min_confidence:
                skipped += 1
                continue

            # suggestion 데이터를 confirm
            confirm_data = {
                "document_type": suggestion.get("document_type", "unknown"),
                "project_name": suggestion.get("project_name", ""),
                "organization": suggestion.get("organization", ""),
                "project_year": suggestion.get("project_year", ""),
                "business_domain": suggestion.get("business_domain", ""),
                "summary": suggestion.get("summary", ""),
                "reuse_level": suggestion.get("reuse_level", "medium"),
            }

            success = metadata_db_service.confirm_suggestion(doc_id, confirm_data)
            if success:
                confirmed += 1
            else:
                errors.append({"id": doc_id, "error": "Confirm failed"})
        except Exception as e:
            errors.append({"id": doc_id, "error": str(e)})

    return {
        "success": True,
        "confirmed": confirmed,
        "skipped": skipped,
        "total": len(document_ids),
        "errors": errors[:10]
    }


@router.post("/documents/confirm-all-suggested")
async def confirm_all_suggested(
    min_confidence: float = Query(0.5, description="최소 신뢰도 임계값")
):
    """auto_suggested 상태인 모든 문서의 메타데이터를 일괄 확정."""
    documents = metadata_db_service.list_documents(meta_status="auto_suggested", limit=1000)
    confirmed = 0
    skipped = 0
    errors = []

    for doc in documents:
        doc_id = doc.get("id")
        try:
            suggestion = metadata_db_service.get_suggestion(doc_id)
            if not suggestion:
                skipped += 1
                continue

            # 신뢰도 체크
            if suggestion.get("confidence", 0) < min_confidence:
                skipped += 1
                continue

            # suggestion 데이터를 confirm
            confirm_data = {
                "document_type": suggestion.get("document_type", "unknown"),
                "project_name": suggestion.get("project_name", ""),
                "organization": suggestion.get("organization", ""),
                "project_year": suggestion.get("project_year", ""),
                "business_domain": suggestion.get("business_domain", ""),
                "summary": suggestion.get("summary", ""),
                "reuse_level": suggestion.get("reuse_level", "medium"),
            }

            success = metadata_db_service.confirm_suggestion(doc_id, confirm_data)
            if success:
                confirmed += 1
            else:
                errors.append({"id": doc_id, "error": "Confirm failed"})
        except Exception as e:
            errors.append({"id": doc_id, "error": str(e)})

    return {
        "success": True,
        "confirmed": confirmed,
        "skipped": skipped,
        "total": len(documents),
        "errors": errors[:10],
        "message": f"신뢰도 {min_confidence} 이상인 {confirmed}건 확정, {skipped}건 생략"
    }


@router.post("/documents/upload-multi")
async def upload_multiple_documents(
    files: List[UploadFile] = File(...),
    document_type: Optional[str] = Query(None),
    project_name: Optional[str] = Query(None),
    organization: Optional[str] = Query(None),
):
    """다중 문서 업로드 및 SQLite DB 등록."""
    from pathlib import Path

    allowed_extensions = ['.pdf', '.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.xls', '.hwp', '.hwpx', '.txt']
    project_root = Path(__file__).resolve().parents[3]
    upload_dir = project_root / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    uploaded = []
    errors = []

    for file in files:
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in allowed_extensions:
            errors.append({"file": file.filename, "error": f"Unsupported file type: {file_ext}"})
            continue

        # 파일 저장
        file_path = upload_dir / file.filename
        try:
            content = await file.read()
            with open(file_path, "wb") as f:
                f.write(content)

            # SQLite DB에 등록
            doc_data = {
                "file_name": file.filename,
                "file_path": str(file_path),
                "file_type": file_ext.lstrip('.'),
                "file_size": len(content),
                "document_type": document_type or "unknown",
                "project_name": project_name or "",
                "organization": organization or "",
                "status": "uploaded",
                "meta_status": "pending",
            }
            doc_id = metadata_db_service.create_document(doc_data)
            uploaded.append({"file": file.filename, "id": doc_id})
        except Exception as e:
            errors.append({"file": file.filename, "error": str(e)})

    return {
        "success": len(errors) == 0,
        "uploaded": uploaded,
        "errors": errors,
        "message": f"{len(uploaded)}개 업로드 완료, {len(errors)}개 실패"
    }


# ────────────────────────────────────────────────────────────────────────────
# LLM 설정 관리 API (MySQL DB 기반)
# ────────────────────────────────────────────────────────────────────────────

from app.services.platform_store import get_llm_settings_by_client, save_llm_settings_by_client


class LlmSettingsRequest(BaseModel):
    """LLM 설정 요청 모델"""
    client_id: str = "weeslee"
    system_prompt: str = ""
    temperature: float = 0.3
    top_p: float = 0.9
    max_tokens: int = 2000
    require_evidence: bool = True
    strict_mode: bool = True
    show_confidence: bool = False
    cite_source: bool = True
    typo_dict: str = ""


_LLM_SETTINGS_DEFAULTS = {
    "system_prompt": """당신은 RAG 기반 문서 검색 및 답변 시스템입니다.

규칙:
1. 검색된 문서의 내용만을 기반으로 답변하세요.
2. 검색 결과에 없는 정보는 "해당 정보를 찾을 수 없습니다"라고 답변하세요.
3. 추측하거나 일반 지식으로 답변하지 마세요.
4. 답변 시 근거 문서를 명시하세요.
5. 불확실한 경우 "확인이 필요합니다"라고 표시하세요.""",
    "temperature": 0.3,
    "top_p": 0.9,
    "max_tokens": 2000,
    "require_evidence": True,
    "strict_mode": True,
    "show_confidence": False,
    "cite_source": True,
    "typo_dict": ""
}


@router.get("/llm-settings")
async def get_llm_settings(client_id: str = "weeslee"):
    """LLM 설정 조회 (MySQL DB 기반)."""
    settings = get_llm_settings_by_client(client_id)
    if not settings:
        return {**_LLM_SETTINGS_DEFAULTS, "client_id": client_id}
    return {**_LLM_SETTINGS_DEFAULTS, **settings}


@router.post("/llm-settings")
async def save_llm_settings(request: LlmSettingsRequest):
    """LLM 설정 저장 (MySQL DB 기반)."""
    settings_data = {
        "system_prompt": request.system_prompt,
        "temperature": request.temperature,
        "top_p": request.top_p,
        "max_tokens": request.max_tokens,
        "require_evidence": request.require_evidence,
        "strict_mode": request.strict_mode,
        "show_confidence": request.show_confidence,
        "cite_source": request.cite_source,
        "typo_dict": request.typo_dict,
    }

    try:
        saved = save_llm_settings_by_client(request.client_id, settings_data)
        return {"success": True, "message": "LLM 설정 DB 저장 완료", "data": saved}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"설정 저장 실패: {str(e)}")


def get_active_llm_settings(client_id: str = "weeslee") -> dict:
    """현재 활성 LLM 설정 반환 (다른 서비스에서 사용)."""
    settings = get_llm_settings_by_client(client_id)
    if not settings:
        return {**_LLM_SETTINGS_DEFAULTS}
    return {**_LLM_SETTINGS_DEFAULTS, **settings}


def apply_typo_correction(query: str, typo_dict_str: str) -> str:
    """오타 보정 사전 적용."""
    if not typo_dict_str:
        return query

    corrected = query
    for line in typo_dict_str.split('\n'):
        if '→' in line:
            parts = line.split('→')
            if len(parts) == 2:
                from_text = parts[0].strip()
                to_text = parts[1].strip()
                if from_text and to_text:
                    corrected = corrected.replace(from_text, to_text)
    return corrected


# ────────────────────────────────────────────────────────────────────────────
# Dataset Builder 10단계 상태 집계 API
# ────────────────────────────────────────────────────────────────────────────

@public_router.get("/dataset/status-summary", response_model=DatasetStatusSummary)
async def get_dataset_status_summary(source_id: Optional[str] = None):
    """
    Dataset Builder 전체 데이터셋 상태 요약 반환
    (읽기 전용 공개 엔드포인트 - 인증 불필요)

    Args:
        source_id: Document Source ID. 지정 시 해당 source의 문서만 집계.

    10단계 파이프라인 각 단계별 처리 현황을 집계하여 반환:
    - Step 1: Source Scan
    - Step 2: Metadata Auto
    - Step 3: Metadata Review
    - Step 4: OCR/Parser
    - Step 5: Chunk Build
    - Step 6: Embedding Build
    - Step 7: FAISS Build
    - Step 8: Graph Build
    - Step 9: Wiki Build
    - Step 10: Search Quality/Activate

    성능 최적화 (2026-06-24):
    - 메모리 캐시 적용 (TTL 60초)
    - DB 쿼리 통합 (7개 → 1개)
    - manifest 파일 활용 (JSONL 전체 파싱 제거)
    """
    from pathlib import Path
    from datetime import datetime as dt
    from sqlalchemy import func
    from app.models.document_metadata import DocumentMetadata, MetaStatus, ProcessingStatus

    # ── 캐시 확인 ─────────────────────────────────────────────────────────────
    cache_key = f"status_summary:{source_id or 'all'}"
    if cache_key in _status_summary_cache:
        cached_result, cached_at = _status_summary_cache[cache_key]
        if dt.now() - cached_at < timedelta(seconds=_STATUS_CACHE_TTL_SECONDS):
            return cached_result

    project_root = Path(__file__).resolve().parents[3]

    # ── 초기화 ─────────────────────────────────────────────────────────────
    summary = DatasetStatusSummary()

    # ── MySQL document_metadata 기준 통계 (Step 1~3) ────────────────────────
    # 성능 최적화: 7개 쿼리를 1개 통합 쿼리로 변경 (2026-06-24)
    from sqlalchemy import case
    db = SessionLocal()
    try:
        # Step 2 상태값 정의
        step2_statuses = [
            MetaStatus.METADATA_SUGGESTED.value,
            MetaStatus.REVIEW_REQUIRED.value,
            MetaStatus.METADATA_REVIEWED.value,
            MetaStatus.REJECTED.value,
        ]
        review_pending_statuses = [
            MetaStatus.METADATA_SUGGESTED.value,
            MetaStatus.REVIEW_REQUIRED.value,
        ]

        # 단일 통합 쿼리로 모든 통계 집계
        q = db.query(
            func.count(DocumentMetadata.id).label('total'),
            func.count(case(
                (DocumentMetadata.meta_status.in_(step2_statuses), 1)
            )).label('step2_completed'),
            func.avg(case(
                (DocumentMetadata.project_name_confidence.isnot(None),
                 DocumentMetadata.project_name_confidence)
            )).label('avg_confidence'),
            func.count(case(
                (DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value, 1)
            )).label('step3_reviewed'),
            func.count(case(
                (DocumentMetadata.meta_status.in_(review_pending_statuses), 1)
            )).label('step3_review_required'),
            func.count(case(
                (DocumentMetadata.meta_status == MetaStatus.REJECTED.value, 1)
            )).label('step3_rejected'),
        )

        if source_id:
            q = q.filter(DocumentMetadata.source_id == source_id)

        result = q.first()

        if result:
            summary.total_documents = result.total or 0
            summary.step1_completed = summary.total_documents
            summary.step2_completed = result.step2_completed or 0
            summary.step2_pending = summary.total_documents - summary.step2_completed
            if result.avg_confidence:
                summary.step2_avg_confidence = round(float(result.avg_confidence), 3)
            summary.step3_reviewed = result.step3_reviewed or 0
            summary.step3_review_required = result.step3_review_required or 0
            summary.step3_rejected = result.step3_rejected or 0

    except Exception:
        pass
    finally:
        db.close()

    # ── Step 4: OCR/Parser ─────────────────────────────────────────────────
    # processed_text 디렉토리에서 OCR 완료 문서 집계
    text_dir = project_root / "data" / "processed_text"
    quality_sum = 0.0
    quality_count = 0

    if text_dir.exists():
        text_files = list(text_dir.glob("*.txt"))
        summary.step4_completed = len(text_files)

        # OCR 품질 정보가 있는 경우 집계 (향후 구현)
        # ocr_report.json 파일에서 품질 점수 읽기

    if quality_count > 0:
        summary.step4_avg_quality = round(quality_sum / quality_count, 3)

    # ── Step 5, 6, 7: Chunk/Embedding/FAISS Build ────────────────────────────
    # 성능 최적화: manifest 파일에서 통계 읽기 (JSONL 전체 파싱 제거) (2026-06-24)
    faiss_dir = project_root / "data" / "indexes" / "faiss"
    active_index_path = project_root / "data" / "active_index.json"

    snapshot = ""
    if active_index_path.exists():
        try:
            snapshot = json.loads(active_index_path.read_text(encoding="utf-8")).get("snapshot", "")
        except Exception:
            pass

    if snapshot and faiss_dir.exists():
        # manifest 파일에서 통계 읽기 (빠름)
        manifest_path = faiss_dir / f"{snapshot}_ollama.manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                summary.step5_total_chunks = manifest.get("vector_count", 0)
                summary.step5_completed = manifest.get("document_count", 0)
                if summary.step5_completed > 0:
                    summary.step5_avg_chunks_per_doc = round(summary.step5_total_chunks / summary.step5_completed, 1)

                # Step 6: Embedding (manifest에서 읽기)
                summary.step6_total_embeddings = summary.step5_total_chunks
                summary.step6_completed = summary.step5_completed
                summary.step6_embedding_model = settings.ollama_embed_model

                # Step 7: FAISS
                summary.step7_snapshot_id = snapshot
                summary.step7_total_vectors = summary.step5_total_chunks
            except Exception:
                pass

        # manifest가 없는 경우 index 파일 존재 여부만 확인
        elif (faiss_dir / f"{snapshot}_ollama.index").exists():
            summary.step6_embedding_model = settings.ollama_embed_model
            summary.step7_snapshot_id = snapshot

    # collection 수 집계 (glob은 빠름)
    if faiss_dir.exists():
        collection_indexes = list(faiss_dir.glob("*_ollama.index"))
        summary.step7_collections_built = len(collection_indexes)

    # ── Step 8: Graph Build ────────────────────────────────────────────────
    # 성능 최적화: graph_manifest.json에서 통계 읽기 (JSONL 전체 파싱 제거) (2026-06-24)
    graph_dir = project_root / "data" / "indexes" / "graph"

    if graph_dir.exists():
        # manifest 파일에서 통계 읽기 (빠름)
        graph_manifest_path = graph_dir / "graph_manifest.json"
        if graph_manifest_path.exists():
            try:
                graph_manifest = json.loads(graph_manifest_path.read_text(encoding="utf-8"))
                summary.step8_nodes_created = graph_manifest.get("node_count", 0)
                summary.step8_edges_created = graph_manifest.get("edge_count", 0)
                if summary.step8_nodes_created > 0 or summary.step8_edges_created > 0:
                    summary.step8_graph_storage = "json"
            except Exception:
                pass
        else:
            # manifest가 없는 경우 파일 라인 수 집계 (fallback)
            graph_nodes_path = graph_dir / "graph_nodes.jsonl"
            graph_edges_path = graph_dir / "graph_edges.jsonl"

            if graph_nodes_path.exists():
                try:
                    node_lines = [line for line in graph_nodes_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                    summary.step8_nodes_created = len(node_lines)
                except Exception:
                    pass

            if graph_edges_path.exists():
                try:
                    edge_lines = [line for line in graph_edges_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                    summary.step8_edges_created = len(edge_lines)
                except Exception:
                    pass

            if summary.step8_nodes_created > 0 or summary.step8_edges_created > 0:
                summary.step8_graph_storage = "json"

    # ── Step 9: Wiki Build ─────────────────────────────────────────────────
    wiki_dir = project_root / "data" / "wiki"

    if wiki_dir.exists():
        wiki_files = list(wiki_dir.glob("*.md"))
        summary.step9_wiki_count = len(wiki_files)

        # Wiki 생성 모델 정보는 wiki 파일 내부에서 추출 가능
        # 현재는 기본값 사용
        if summary.step9_wiki_count > 0:
            summary.step9_wiki_model = "gemma3:12b"

    # ── Step 10: Search Quality / Activate ─────────────────────────────────
    if active_index_path.exists():
        try:
            active_info = json.loads(active_index_path.read_text(encoding="utf-8"))
            summary.step10_active_snapshot = active_info.get("snapshot", "")

            # collection 목록 추출
            if faiss_dir.exists():
                collection_indexes = list(faiss_dir.glob(f"{summary.step10_active_snapshot}_*_ollama.index"))
                summary.step10_active_collections = [
                    idx.stem.replace(f"{summary.step10_active_snapshot}_", "").replace("_ollama", "")
                    for idx in collection_indexes
                ]

            # quality 검증 여부 확인 (quality_report.json 파일 존재 여부)
            quality_report_path = project_root / "data" / "indexes" / "quality_report.json"
            if quality_report_path.exists():
                try:
                    quality_info = json.loads(quality_report_path.read_text(encoding="utf-8"))
                    summary.step10_quality_passed = quality_info.get("passed", False)
                    summary.step10_quality_score = quality_info.get("score", 0.0)
                except Exception:
                    pass
        except Exception:
            pass

    # ── 마지막 업데이트 시간 설정 ───────────────────────────────────────────
    summary.last_updated = datetime.utcnow()

    # ── 캐시 저장 (Phase 3-1: 메모리 캐시) ─────────────────────────────────────
    _status_summary_cache[cache_key] = (summary, dt.now())

    return summary
