# Dataset Builder Step 5: Chunk Build API
"""
Step 4에서 추출된 텍스트를 청킹하여 FAISS 인덱싱 준비
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field
from pathlib import Path
from datetime import datetime
import re

from app.core.database import get_db
from app.services.dataset_context import update_source_dataset_status
from app.services.chunking import ChunkingService
from app.services.processed_text_store import ProcessedTextStore
from app.services.source_artifact_index import sync_source_index

# [2026-07-08] structured_json fallback을 위한 resolver 임포트
try:
    from app.services.structured_content_resolver import StructuredContentResolver
    HAS_STRUCTURED_RESOLVER = True
except ImportError:
    HAS_STRUCTURED_RESOLVER = False
    StructuredContentResolver = None

router = APIRouter(prefix="/admin/dataset-builder/step5")


# ── Request/Response Models ──────────────────────────────────────────────

class ChunkBuildRequest(BaseModel):
    """청킹 설정 요청"""
    source_id: Optional[str] = Field(None, description="Document Source ID (특정 소스만 처리)")
    snapshot_id: Optional[str] = Field(None, description="연결할 Snapshot ID")
    document_ids: Optional[List[int]] = Field(None, description="처리할 문서 ID 목록 (비어있으면 전체)")
    chunk_size: int = Field(512, ge=100, le=2000, description="청크 크기 (토큰)")
    chunk_overlap: int = Field(50, ge=0, le=500, description="청크 오버랩 (토큰)")
    min_chunk_size: int = Field(100, ge=50, le=500, description="최소 청크 크기")
    force_rebuild: bool = Field(False, description="이미 청킹된 문서도 재처리")
    chunking_mode: str = Field("auto", description="청킹 모드 (auto, semantic, plain)")


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


_ORDER_PREFIX_RE = re.compile(r"^\s*\d+\.\s*")


def strip_order_prefix(name: str) -> str:
    """폴더/섹션명 앞의 '숫자. ' 접두사를 제거한다."""
    return _ORDER_PREFIX_RE.sub("", str(name or "")).strip()


def build_chunk_meta(doc, file_name: str, structured_data: dict, snapshot_id: str = "") -> dict:
    """Step 5 청크 메타데이터를 정규화해 생성한다."""
    organization = (
        getattr(doc, "final_organization", None)
        or getattr(doc, "ocr_organization", None)
        or getattr(doc, "organization", None)
        or getattr(doc, "scan_organization", None)
        or ""
    )
    project_name = (
        getattr(doc, "final_project_name", None)
        or getattr(doc, "ocr_project_name", None)
        or getattr(doc, "project_name", None)
        or getattr(doc, "scan_project_name", None)
        or ""
    )

    org_type = ""
    project_type = ""
    try:
        from app.services.knowledge_graph import get_organization_type, classify_project_type

        org_type = get_organization_type(organization) or ""
        proj_types = classify_project_type(
            " ".join(
                part for part in [
                    project_name,
                    file_name,
                    getattr(doc, "relative_path", "") or "",
                ]
                if part
            )
        )
        project_type = proj_types[0] if proj_types else ""
    except Exception:
        org_type = getattr(doc, "organization_type", "") or ""
        project_type = getattr(doc, "project_type", "") or ""

    org_type = getattr(doc, "organization_type", "") or org_type
    project_type = getattr(doc, "project_type", "") or project_type

    chunk_meta = {
        "document_id": doc.document_id,
        "file_name": file_name,
        "source_id": doc.source_id,
        "dataset_id": doc.dataset_id,
        "document_uid": doc.document_uid,
        "relative_path": doc.relative_path,
        "snapshot_id": snapshot_id or getattr(doc, "faiss_snapshot", "") or "",
        "document_group": strip_order_prefix(getattr(doc, "document_group", "") or ""),
        "document_category": strip_order_prefix(
            getattr(doc, "final_document_category", None)
            or getattr(doc, "scan_document_category", None)
            or getattr(doc, "section_type", None)
            or ""
        ),
        "category_id": getattr(doc, "category_id", "") or "",
        "section_type": strip_order_prefix(getattr(doc, "section_type", "") or ""),
        "project_name": project_name,
        "organization": organization,
        "organization_type": org_type,
        "client_type": org_type,
        "project_type": project_type,
    }

    semantic_tags = (structured_data or {}).get("semantic_tags") or {}
    if semantic_tags:
        chunk_meta.update({
            "methodology": semantic_tags.get("methodology", ""),
            "domain": semantic_tags.get("domain", ""),
            "technology": semantic_tags.get("technology", ""),
        })

    return chunk_meta


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

    parser_type = str(report.get("parser_type") or "").strip().lower()
    extracted_text = text_store.get_text(str(document_id), format="txt") or ""
    if parser_type in {"python-pptx", "docx", "openxml", "libreoffice"}:
        estimated_tokens = ChunkingService(min_chunk_size=100).estimate_tokens(extracted_text)
        if estimated_tokens >= 100:
            return True, ""

    quality_score = float(quality.get("quality_score") or 0)
    if quality_score < 0.7:
        return False, f"Quality score too low: {quality_score}"

    if parser_type == "hwp_all_failed":
        return False, "HWP extraction failed"

    return True, ""


def allow_parser_text_fallback(
    report: dict,
    extracted_text: str,
    chunking_service: ChunkingService,
) -> tuple[bool, str]:
    """
    OCR 품질 점수는 낮지만 파서가 실제 텍스트를 정상 추출한 문서는
    Step 5에서 청킹을 계속 진행할 수 있게 예외 처리한다.
    """
    parser_type = str(report.get("parser_type") or "").strip().lower()
    if parser_type not in {"python-pptx", "docx", "openxml", "libreoffice"}:
        return False, ""

    clean_text = str(extracted_text or "").strip()
    if not clean_text:
        return False, ""

    estimated_tokens = chunking_service.estimate_tokens(clean_text)
    if estimated_tokens < chunking_service.min_chunk_size:
        return False, ""

    return True, f"Parser text fallback accepted: parser={parser_type}, tokens={estimated_tokens}"


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
        # 처리할 문서 조회 (RAG 포함 + 제외/삭제되지 않은 문서)
        from app.models.document_metadata import DocumentMetadata, ProcessingStatus

        query = db.query(DocumentMetadata).filter(
            DocumentMetadata.include_in_rag.is_(True),
            DocumentMetadata.is_excluded.is_(False),
            DocumentMetadata.removed_at.is_(None),
        )

        if req.source_id:
            query = query.filter(DocumentMetadata.source_id == req.source_id)

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

                # Step 4에서 추출된 텍스트/페이지 결과 로드
                from app.services.processed_text_store import processed_text_store
                extracted_text = processed_text_store.get_text(str(document_id), format="txt")
                extraction_result = processed_text_store.get_result(str(document_id))
                report = processed_text_store.get_report(str(document_id)) or {}
                structured_data = processed_text_store.get_structured_data(str(document_id)) or {}

                # [2026-07-08] structured_json fallback - sections 정보가 없으면 외부 파일에서 로드
                if not structured_data.get("sections") and HAS_STRUCTURED_RESOLVER:
                    try:
                        resolver = StructuredContentResolver({
                            "use_structured_txt": True,
                            "use_structured_json": True,
                            "prefer_structured_content": True,
                        })
                        external_content = resolver.resolve_document_content(doc)
                        if external_content.get("structured_json"):
                            external_json = external_content["structured_json"]
                            if external_json.get("sections"):
                                structured_data = external_json
                                structured_data["_source"] = "structured_json_fallback"
                    except Exception:
                        pass  # fallback 실패 시 무시하고 기존 로직 진행

                # Step 4 품질 게이트 통과 문서만 청킹한다.
                quality_ok, quality_error = validate_step4_quality(document_id, processed_text_store)
                if not quality_ok:
                    fallback_ok, fallback_reason = allow_parser_text_fallback(
                        report,
                        extracted_text or "",
                        chunking_service,
                    )
                    if not fallback_ok:
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

                page_rows = []
                for page in (extraction_result.pages if extraction_result else []):
                    page_number = page.get("page_number") or page.get("page_num")
                    content = page.get("content") or page.get("text") or ""
                    if page_number is None or not str(content).strip():
                        continue
                    page_rows.append({
                        "page_number": page_number,
                        "content": content,
                    })

                chunk_meta = build_chunk_meta(doc, file_name, structured_data, req.snapshot_id or "")

                # 청킹 실행
                use_semantic = (
                    req.chunking_mode == "semantic"
                    or (req.chunking_mode == "auto" and bool(structured_data))
                )
                if use_semantic and structured_data:
                    chunks = chunking_service.chunk_semantic_sections(structured_data, metadata=chunk_meta)
                elif page_rows and req.chunking_mode != "plain":
                    chunks = chunking_service.chunk_pages(page_rows, metadata=chunk_meta)
                else:
                    chunks = chunking_service.chunk_text(extracted_text, metadata=chunk_meta)

                # 저장
                save_result = save_chunks_to_store(document_id, chunks, text_store)

                if save_result["success"]:
                    text_store.save_run_config(
                        str(document_id),
                        {
                            "source_id": doc.source_id or "",
                            "dataset_id": doc.dataset_id or "",
                            "document_uid": doc.document_uid or "",
                            "relative_path": doc.relative_path or "",
                            "snapshot_id": req.snapshot_id or getattr(doc, "faiss_snapshot", "") or "",
                            "chunk": {
                                "chunk_size": req.chunk_size,
                                "chunk_overlap": req.chunk_overlap,
                                "min_chunk_size": req.min_chunk_size,
                                "chunking_mode": req.chunking_mode,
                                "chunks_count": save_result["chunks_count"],
                                "total_tokens": save_result["total_tokens"],
                            },
                        },
                        snapshot_id=req.snapshot_id or getattr(doc, "faiss_snapshot", "") or "",
                    )
                    processed += 1
                    total_chunks += save_result["chunks_count"]
                    if req.snapshot_id:
                        doc.faiss_snapshot = req.snapshot_id
                    doc.status = ProcessingStatus.CHUNKED.value
                    doc.chunk_count = save_result["chunks_count"]
                    doc.updated_at = datetime.utcnow()
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

        db.commit()
        if req.source_id:
            if processed > 0:
                update_source_dataset_status(req.source_id, "chunked")
            sync_source_index(req.source_id, db=db)

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
    from app.models.document_metadata import DocumentMetadata
    text_store = get_text_store()

    try:
        # 전체 문서 수 (RAG 포함 + 제외/삭제되지 않은 문서)
        total_documents = db.query(DocumentMetadata).filter(
            DocumentMetadata.include_in_rag.is_(True),
            DocumentMetadata.is_excluded.is_(False),
            DocumentMetadata.removed_at.is_(None),
        ).count()

        # 청킹된 문서 수 계산
        chunked_documents = 0
        total_chunks = 0

        docs = db.query(DocumentMetadata).filter(
            DocumentMetadata.include_in_rag.is_(True),
            DocumentMetadata.is_excluded.is_(False),
            DocumentMetadata.removed_at.is_(None),
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
        # 검수 완료 + RAG 포함 + 제외/삭제되지 않은 문서
        docs = db.query(DocumentMetadata).filter(
            DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value,
            DocumentMetadata.include_in_rag.is_(True),
            DocumentMetadata.is_excluded.is_(False),
            DocumentMetadata.removed_at.is_(None),
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
