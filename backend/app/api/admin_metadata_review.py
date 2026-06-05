# Step 3: Metadata Review API 엔드포인트
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import require_admin_token
from app.core.database import get_db
from app.services.document_metadata_service import document_metadata_service
from app.models.document import Document

router = APIRouter(
    prefix="/admin/metadata-review",
    tags=["Admin - Metadata Review"],
    dependencies=[Depends(require_admin_token)],
)


# ── Request/Response Models ─────────────────────────────────────────────────


class DocumentMetadataResponse(BaseModel):
    """검수 대기 문서 메타데이터"""
    document_id: int
    file_path: Optional[str] = None
    file_name: str
    source_id: Optional[str] = None
    category_id: Optional[str] = None

    # Auto-generated metadata (Step 2)
    project_name: Optional[str] = None
    project_name_confidence: Optional[float] = None
    organization: Optional[str] = None
    organization_confidence: Optional[float] = None
    document_type: Optional[str] = None
    year: Optional[int] = None

    # Review status
    meta_status: str  # registered, metadata_suggested, review_required, metadata_reviewed
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None

    # Collections
    collection_candidates: Optional[List[str]] = []
    final_collections: Optional[List[str]] = []

    # Tags & Keywords
    tags: Optional[List[str]] = []
    keywords: Optional[List[str]] = []

    # Include flags
    include_in_rag: bool = True
    include_in_graph: bool = True
    include_in_wiki: bool = True

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MetadataReviewListResponse(BaseModel):
    """검수 대기 문서 목록 응답"""
    total: int
    documents: List[DocumentMetadataResponse]
    status_counts: dict  # {"review_required": 10, "metadata_reviewed": 50, ...}


class UpdateMetadataRequest(BaseModel):
    """메타데이터 수정 요청"""
    project_name: Optional[str] = None
    organization: Optional[str] = None
    document_type: Optional[str] = None
    year: Optional[int] = None
    final_collections: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    keywords: Optional[List[str]] = None
    include_in_rag: Optional[bool] = None
    include_in_graph: Optional[bool] = None
    include_in_wiki: Optional[bool] = None


class ApproveMetadataRequest(BaseModel):
    """메타데이터 승인 요청"""
    document_ids: List[int]
    reviewer: str = "admin"


class RejectMetadataRequest(BaseModel):
    """메타데이터 반려 요청"""
    document_ids: List[int]
    reason: Optional[str] = None
    reviewer: str = "admin"


# ── API Endpoints ───────────────────────────────────────────────────────────


@router.get("/documents", response_model=MetadataReviewListResponse)
async def get_documents_for_review(
    status: Optional[str] = Query(None, description="필터: review_required, metadata_reviewed 등"),
    source_id: Optional[str] = Query(None, description="필터: source_id"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Step 3: 검수 대기 문서 목록 조회

    - status: review_required만 조회하거나 전체 조회
    - source_id: 특정 소스만 필터링
    """
    try:
        # 문서 목록 조회
        metadata_list = document_metadata_service.get_documents_for_review(
            db=db,
            status=status,
            source_id=source_id,
            limit=limit,
            offset=offset
        )

        # 상태별 카운트 집계
        status_counts = document_metadata_service.get_status_counts(db)

        # 전체 수 조회
        total = document_metadata_service.count_documents(db, status=status, source_id=source_id)

        # Response 생성
        documents = []
        for meta in metadata_list:
            doc = db.query(Document).filter(Document.id == meta.document_id).first()
            doc_data = DocumentMetadataResponse(
                document_id=meta.document_id,
                file_path=meta.file_path,
                file_name=doc.filename if doc else "Unknown",
                source_id=meta.source_id,
                category_id=meta.category_id,
                project_name=meta.project_name,
                project_name_confidence=meta.project_name_confidence,
                organization=meta.organization,
                organization_confidence=meta.organization_confidence,
                document_type=meta.document_type,
                year=meta.year,
                meta_status=meta.meta_status,
                reviewed_by=meta.reviewed_by,
                reviewed_at=meta.reviewed_at,
                collection_candidates=meta.collection_candidates or [],
                final_collections=meta.final_collections or [],
                tags=meta.tags or [],
                keywords=meta.keywords or [],
                include_in_rag=meta.include_in_rag,
                include_in_graph=meta.include_in_graph,
                include_in_wiki=meta.include_in_wiki,
                created_at=meta.created_at,
                updated_at=meta.updated_at,
            )
            documents.append(doc_data)

        return MetadataReviewListResponse(
            total=total,
            documents=documents,
            status_counts=status_counts
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"문서 목록 조회 실패: {str(e)}")


@router.get("/documents/{document_id}", response_model=DocumentMetadataResponse)
async def get_document_metadata(document_id: int, db: Session = Depends(get_db)):
    """
    Step 3: 특정 문서의 메타데이터 상세 조회
    """
    try:
        metadata = document_metadata_service.get_document_by_id(db, document_id)

        if not metadata:
            raise HTTPException(status_code=404, detail=f"문서를 찾을 수 없습니다: {document_id}")

        doc = db.query(Document).filter(Document.id == metadata.document_id).first()

        return DocumentMetadataResponse(
            document_id=metadata.document_id,
            file_path=metadata.file_path,
            file_name=doc.filename if doc else "Unknown",
            source_id=metadata.source_id,
            category_id=metadata.category_id,
            project_name=metadata.project_name,
            project_name_confidence=metadata.project_name_confidence,
            organization=metadata.organization,
            organization_confidence=metadata.organization_confidence,
            document_type=metadata.document_type,
            year=metadata.year,
            meta_status=metadata.meta_status,
            reviewed_by=metadata.reviewed_by,
            reviewed_at=metadata.reviewed_at,
            collection_candidates=metadata.collection_candidates or [],
            final_collections=metadata.final_collections or [],
            tags=metadata.tags or [],
            keywords=metadata.keywords or [],
            include_in_rag=metadata.include_in_rag,
            include_in_graph=metadata.include_in_graph,
            include_in_wiki=metadata.include_in_wiki,
            created_at=metadata.created_at,
            updated_at=metadata.updated_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"문서 조회 실패: {str(e)}")


@router.patch("/documents/{document_id}")
async def update_document_metadata(
    document_id: int,
    request: UpdateMetadataRequest,
    db: Session = Depends(get_db),
):
    """
    Step 3: 문서 메타데이터 수정

    - 관리자가 자동 생성된 메타데이터를 수정
    - 수정 후에도 meta_status는 변경되지 않음 (승인은 별도 API)
    """
    try:
        # 문서 존재 확인
        metadata = document_metadata_service.get_document_by_id(db, document_id)
        if not metadata:
            raise HTTPException(status_code=404, detail=f"문서를 찾을 수 없습니다: {document_id}")

        # 메타데이터 업데이트
        updated = document_metadata_service.update_document_metadata(
            db=db,
            document_id=document_id,
            updates=request.dict(exclude_none=True)
        )

        return {
            "success": True,
            "document_id": document_id,
            "updated_fields": list(request.dict(exclude_none=True).keys()),
            "message": "메타데이터가 수정되었습니다."
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"메타데이터 수정 실패: {str(e)}")


@router.post("/approve")
async def approve_metadata(request: ApproveMetadataRequest, db: Session = Depends(get_db)):
    """
    Step 3: 메타데이터 승인

    - meta_status를 'metadata_reviewed'로 변경
    - reviewed_by, reviewed_at 기록
    """
    try:
        approved_count = 0
        failed_ids = []

        for document_id in request.document_ids:
            try:
                document_metadata_service.approve_document_metadata(
                    db=db,
                    document_id=document_id,
                    reviewer=request.reviewer
                )
                approved_count += 1
            except Exception as e:
                failed_ids.append(document_id)

        return {
            "success": True,
            "approved_count": approved_count,
            "total_requested": len(request.document_ids),
            "failed_ids": failed_ids,
            "message": f"{approved_count}개 문서가 승인되었습니다."
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"승인 처리 실패: {str(e)}")


@router.post("/reject")
async def reject_metadata(request: RejectMetadataRequest, db: Session = Depends(get_db)):
    """
    Step 3: 메타데이터 반려

    - meta_status를 'rejected'로 변경
    - 반려 사유 기록
    """
    try:
        rejected_count = 0
        failed_ids = []

        for document_id in request.document_ids:
            try:
                document_metadata_service.reject_document_metadata(
                    db=db,
                    document_id=document_id,
                    reviewer=request.reviewer,
                    reason=request.reason
                )
                rejected_count += 1
            except Exception as e:
                failed_ids.append(document_id)

        return {
            "success": True,
            "rejected_count": rejected_count,
            "total_requested": len(request.document_ids),
            "failed_ids": failed_ids,
            "message": f"{rejected_count}개 문서가 반려되었습니다."
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"반려 처리 실패: {str(e)}")


@router.get("/stats")
async def get_review_stats(db: Session = Depends(get_db)):
    """
    Step 3: 검수 현황 통계

    - 상태별 문서 수
    - source_id별 검수 진행률
    """
    try:
        stats = document_metadata_service.get_review_stats(db)

        return {
            "status_counts": stats.get("status_counts", {}),
            "source_stats": stats.get("source_stats", {}),
            "total_documents": stats.get("total", 0),
            "review_required": stats.get("status_counts", {}).get("review_required", 0),
            "reviewed": stats.get("status_counts", {}).get("metadata_reviewed", 0),
            "rejected": stats.get("status_counts", {}).get("rejected", 0),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"통계 조회 실패: {str(e)}")
