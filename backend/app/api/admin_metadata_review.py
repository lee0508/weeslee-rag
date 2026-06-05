# Step 3: Metadata Review API 엔드포인트
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.auth import require_admin_token
from app.services.metadata_db import metadata_db_service

router = APIRouter(
    prefix="/admin/metadata-review",
    tags=["Admin - Metadata Review"],
    dependencies=[Depends(require_admin_token)],
)


# ── Request/Response Models ─────────────────────────────────────────────────


class DocumentMetadataResponse(BaseModel):
    """검수 대기 문서 메타데이터"""
    document_id: str
    file_path: str
    file_name: str
    source_id: str
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
    collection_candidates: List[str] = []
    final_collections: List[str] = []

    # Tags & Keywords
    tags: List[str] = []
    keywords: List[str] = []

    # Include flags
    include_in_rag: bool = True
    include_in_graph: bool = True
    include_in_wiki: bool = True

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


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
    document_ids: List[str]
    reviewer: str = "admin"


class RejectMetadataRequest(BaseModel):
    """메타데이터 반려 요청"""
    document_ids: List[str]
    reason: Optional[str] = None
    reviewer: str = "admin"


# ── API Endpoints ───────────────────────────────────────────────────────────


@router.get("/documents", response_model=MetadataReviewListResponse)
async def get_documents_for_review(
    status: Optional[str] = Query(None, description="필터: review_required, metadata_reviewed 등"),
    source_id: Optional[str] = Query(None, description="필터: source_id"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """
    Step 3: 검수 대기 문서 목록 조회

    - status: review_required만 조회하거나 전체 조회
    - source_id: 특정 소스만 필터링
    """
    try:
        # metadata_db_service에서 문서 목록 조회
        # 실제 구현은 metadata_db_service 메서드에 의존
        documents = metadata_db_service.get_documents_for_review(
            status=status,
            source_id=source_id,
            limit=limit,
            offset=offset
        )

        # 상태별 카운트 집계
        status_counts = metadata_db_service.get_status_counts()

        return MetadataReviewListResponse(
            total=len(documents),
            documents=documents,
            status_counts=status_counts
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"문서 목록 조회 실패: {str(e)}")


@router.get("/documents/{document_id}", response_model=DocumentMetadataResponse)
async def get_document_metadata(document_id: str):
    """
    Step 3: 특정 문서의 메타데이터 상세 조회
    """
    try:
        document = metadata_db_service.get_document_by_id(document_id)

        if not document:
            raise HTTPException(status_code=404, detail=f"문서를 찾을 수 없습니다: {document_id}")

        return document

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"문서 조회 실패: {str(e)}")


@router.patch("/documents/{document_id}")
async def update_document_metadata(
    document_id: str,
    request: UpdateMetadataRequest
):
    """
    Step 3: 문서 메타데이터 수정

    - 관리자가 자동 생성된 메타데이터를 수정
    - 수정 후에도 meta_status는 변경되지 않음 (승인은 별도 API)
    """
    try:
        # 문서 존재 확인
        document = metadata_db_service.get_document_by_id(document_id)
        if not document:
            raise HTTPException(status_code=404, detail=f"문서를 찾을 수 없습니다: {document_id}")

        # 메타데이터 업데이트
        updated = metadata_db_service.update_document_metadata(
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
async def approve_metadata(request: ApproveMetadataRequest):
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
                metadata_db_service.approve_document_metadata(
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
async def reject_metadata(request: RejectMetadataRequest):
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
                metadata_db_service.reject_document_metadata(
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
async def get_review_stats():
    """
    Step 3: 검수 현황 통계

    - 상태별 문서 수
    - source_id별 검수 진행률
    """
    try:
        stats = metadata_db_service.get_review_stats()

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
