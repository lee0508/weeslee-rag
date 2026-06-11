# Dataset Builder Step 5: Chunk Build API
"""
Step 4에서 추출된 텍스트를 청킹하여 FAISS 인덱싱 준비
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from pydantic import BaseModel, Field
import json
from pathlib import Path
from datetime import datetime

from app.core.database import get_db
from app.services.chunking import ChunkingService
from app.services.processed_text_store import ProcessedTextStore
# 확장 메서드 로드
import app.services.processed_text_store_extensions

router = APIRouter(prefix="/admin/dataset-builder/step5")


# ── Request/Response Models ──────────────────────────────────────────────

class ChunkBuildRequest(BaseModel):
    """청킹 설정 요청"""
    document_ids: Optional[List[int]] = Field(None, description="처리할 문서 ID 목록 (비어있으면 전체)")
    chunk_size: int = Field(512, ge=100, le=2000, description="청크 크기 (토큰)")
    chunk_overlap: int = Field(50, ge=0, le=500, description="청크 오버랩 (토큰)")
    min_chunk_size: int = Field(100, ge=50, le=500, description="최소 청크 크기")
    force_rebuild: bool = Field(False, description="이미 청킹된 문서도 재처리")


class ChunkInfo(BaseModel):
    """청크 정보"""
    chunk_index: int
    content_preview: str
    token_count: int
    char_count: int


class ChunkBuildResult(BaseModel):
    """개별 문서 청킹 결과"""
    document_id: int
    file_name: str
    status: str  # success, failed, skipped
    chunks_count: int
    total_tokens: int
    error: Optional[str] = None


class ChunkBuildResponse(BaseModel):
    """청킹 전체 결과"""
    success: bool
    processed: int
    failed: int
    skipped: int
    total_chunks: int
    results: List[ChunkBuildResult]
    chunk_size: int
    chunk_overlap: int


class ChunkStatusResponse(BaseModel):
    """청킹 상태 조회"""
    total_documents: int
    chunked_documents: int
    total_chunks: int
    avg_chunks_per_doc: float
    not_chunked: int


class DocumentChunksResponse(BaseModel):
    """문서별 청크 조회"""
    document_id: int
    file_name: str
    chunks: List[ChunkInfo]
    total_chunks: int


# ── Helper Functions ─────────────────────────────────────────────────────

def get_text_store() -> ProcessedTextStore:
    """ProcessedTextStore 인스턴스 반환"""
    return ProcessedTextStore()


def save_chunks_to_store(document_id: int, chunks: list, text_store: ProcessedTextStore) -> dict:
    """청크를 ProcessedTextStore에 저장"""
    try:
        # 청크 데이터 준비
        chunks_data = []
        for idx, chunk in enumerate(chunks):
            chunks_data.append({
                "chunk_index": idx,
                "content": chunk.content,
                "token_count": chunk.token_count,
                "char_count": len(chunk.content),
                "start_char": chunk.start_char,
                "end_char": chunk.end_char,
                "page_number": chunk.page_number,
                "metadata": chunk.metadata or {}
            })

        # Store에 저장
        text_store.save_chunks(document_id, chunks_data)

        return {
            "success": True,
            "chunks_count": len(chunks_data),
            "total_tokens": sum(c["token_count"] for c in chunks_data)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def validate_step4_quality(document_id: int, text_store: ProcessedTextStore) -> tuple[bool, str]:
    """Step 4 OCR/Parser 결과가 RAG 청킹 기준을 통과했는지 확인한다."""
    report = text_store.get_report(str(document_id))
    if not report:
        return False, "Missing Step 4 OCR report"

    status = report.get("status")
    if status != "done":
        return False, f"Step 4 status is not done: {status}"

    text_length = int(report.get("text_length") or 0)
    if text_length < 500:
        return False, f"Extracted text too short: {text_length}"

    quality = report.get("quality") or {}
    if quality.get("rag_ready") is False:
        return False, "Step 4 quality gate did not pass"

    quality_score = float(quality.get("quality_score") or 0)
    if quality_score < 0.7:
        return False, f"Quality score too low: {quality_score}"

    if report.get("parser_type") == "hwp_all_failed":
        return False, "HWP extraction failed"

    return True, ""


# ── API Endpoints ────────────────────────────────────────────────────────

@router.post("/chunk", response_model=ChunkBuildResponse)
async def build_chunks(
    req: ChunkBuildRequest,
    db: Session = Depends(get_db)
):
    """
    Step 5: 텍스트 청킹 실행

    Step 4에서 추출된 텍스트를 설정에 따라 청킹합니다.
    """
    text_store = get_text_store()
    chunking_service = ChunkingService(
        chunk_size=req.chunk_size,
        chunk_overlap=req.chunk_overlap,
        min_chunk_size=req.min_chunk_size
    )

    results = []
    processed = 0
    failed = 0
    skipped = 0
    total_chunks = 0

    try:
        # 처리할 문서 조회
        from app.models.document_metadata import DocumentMetadata, MetaStatus

        query = db.query(DocumentMetadata).filter(
            DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value,
            DocumentMetadata.include_in_rag == True
        )

        if req.document_ids:
            query = query.filter(DocumentMetadata.document_id.in_(req.document_ids))

        docs = query.all()

        for doc in docs:
            document_id = doc.document_id
            file_name = Path(doc.file_path).name if doc.file_path else f"doc_{document_id}"

            try:
                # 이미 청킹되었는지 확인
                if not req.force_rebuild:
                    existing = text_store.load_chunks(document_id)
                    if existing and len(existing) > 0:
                        skipped += 1
                        results.append(ChunkBuildResult(
                            document_id=document_id,
                            file_name=file_name,
                            status="skipped",
                            chunks_count=len(existing),
                            total_tokens=sum(c.get("token_count", 0) for c in existing)
                        ))
                        continue

                # Step 4 품질 게이트 통과 문서만 청킹한다.
                from app.services.processed_text_store import processed_text_store
                quality_ok, quality_error = validate_step4_quality(document_id, processed_text_store)
                if not quality_ok:
                    skipped += 1
                    results.append(ChunkBuildResult(
                        document_id=document_id,
                        file_name=file_name,
                        status="skipped",
                        chunks_count=0,
                        total_tokens=0,
                        error=quality_error
                    ))
                    continue

                # Step 4에서 추출된 텍스트 로드
                extracted_text = processed_text_store.get_text(str(document_id), format="txt")

                # 텍스트 없으면 스킵
                if not extracted_text:
                    skipped += 1
                    results.append(ChunkBuildResult(
                        document_id=document_id,
                        file_name=file_name,
                        status="skipped",
                        chunks_count=0,
                        total_tokens=0,
                        error="No extracted text from Step 4"
                    ))
                    continue

                # 청킹 실행
                chunks = chunking_service.chunk_text(extracted_text)

                # 저장
                save_result = save_chunks_to_store(document_id, chunks, text_store)

                if save_result["success"]:
                    processed += 1
                    total_chunks += save_result["chunks_count"]
                    results.append(ChunkBuildResult(
                        document_id=document_id,
                        file_name=file_name,
                        status="success",
                        chunks_count=save_result["chunks_count"],
                        total_tokens=save_result["total_tokens"]
                    ))
                else:
                    failed += 1
                    results.append(ChunkBuildResult(
                        document_id=document_id,
                        file_name=file_name,
                        status="failed",
                        chunks_count=0,
                        total_tokens=0,
                        error=save_result["error"]
                    ))

            except Exception as e:
                failed += 1
                results.append(ChunkBuildResult(
                    document_id=document_id,
                    file_name=file_name,
                    status="failed",
                    chunks_count=0,
                    total_tokens=0,
                    error=str(e)
                ))

        return ChunkBuildResponse(
            success=True,
            processed=processed,
            failed=failed,
            skipped=skipped,
            total_chunks=total_chunks,
            results=results,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chunking failed: {str(e)}")


@router.get("/status", response_model=ChunkStatusResponse)
async def get_chunk_status(db: Session = Depends(get_db)):
    """
    청킹 상태 조회
    """
    from app.models.document_metadata import DocumentMetadata, MetaStatus
    text_store = get_text_store()

    try:
        # 전체 문서 수
        total_documents = db.query(DocumentMetadata).filter(
            DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value,
            DocumentMetadata.include_in_rag == True
        ).count()

        # 청킹된 문서 수 계산
        chunked_documents = 0
        total_chunks = 0

        docs = db.query(DocumentMetadata).filter(
            DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value,
            DocumentMetadata.include_in_rag == True
        ).all()

        for doc in docs:
            chunks = text_store.load_chunks(doc.document_id)
            if chunks and len(chunks) > 0:
                chunked_documents += 1
                total_chunks += len(chunks)

        avg_chunks = total_chunks / chunked_documents if chunked_documents > 0 else 0.0

        return ChunkStatusResponse(
            total_documents=total_documents,
            chunked_documents=chunked_documents,
            total_chunks=total_chunks,
            avg_chunks_per_doc=round(avg_chunks, 2),
            not_chunked=total_documents - chunked_documents
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/document/{document_id}/chunks", response_model=DocumentChunksResponse)
async def get_document_chunks(
    document_id: int,
    db: Session = Depends(get_db)
):
    """
    특정 문서의 청크 조회
    """
    from app.models.document_metadata import DocumentMetadata
    text_store = get_text_store()

    try:
        # 문서 정보 조회
        doc = db.query(DocumentMetadata).filter(
            DocumentMetadata.document_id == document_id
        ).first()

        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        file_name = Path(doc.file_path).name if doc.file_path else f"doc_{document_id}"

        # 청크 로드
        chunks_data = text_store.load_chunks(document_id)

        chunks = [
            ChunkInfo(
                chunk_index=c["chunk_index"],
                content_preview=c["content"][:200] + "..." if len(c["content"]) > 200 else c["content"],
                token_count=c["token_count"],
                char_count=c["char_count"]
            )
            for c in chunks_data
        ]

        return DocumentChunksResponse(
            document_id=document_id,
            file_name=file_name,
            chunks=chunks,
            total_chunks=len(chunks)
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_chunk_stats(db: Session = Depends(get_db)):
    """
    청킹 통계 정보
    """
    from app.models.document_metadata import DocumentMetadata, MetaStatus
    text_store = get_text_store()

    try:
        docs = db.query(DocumentMetadata).filter(
            DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value,
            DocumentMetadata.include_in_rag == True
        ).all()

        stats = {
            "total_documents": 0,
            "chunked_documents": 0,
            "total_chunks": 0,
            "min_chunks": None,
            "max_chunks": None,
            "avg_chunks": 0.0
        }

        chunk_counts = []

        for doc in docs:
            stats["total_documents"] += 1
            chunks = text_store.load_chunks(doc.document_id)
            if chunks and len(chunks) > 0:
                stats["chunked_documents"] += 1
                stats["total_chunks"] += len(chunks)
                chunk_counts.append(len(chunks))

        if chunk_counts:
            stats["min_chunks"] = min(chunk_counts)
            stats["max_chunks"] = max(chunk_counts)
            stats["avg_chunks"] = round(sum(chunk_counts) / len(chunk_counts), 2)

        return stats

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
