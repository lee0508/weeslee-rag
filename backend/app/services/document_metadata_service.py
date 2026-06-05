# Document Metadata Service for Dataset Builder Step 3
"""
Service layer for document_metadata table operations.
Uses SQLAlchemy ORM with MySQL database.
"""
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from app.core.database import get_db
from app.models.document_metadata import DocumentMetadata, MetaStatus


class DocumentMetadataService:
    """Document metadata service for Step 3 Metadata Review"""

    def get_documents_for_review(
        self,
        db: Session,
        status: Optional[str] = None,
        source_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[DocumentMetadata]:
        """검수 대기 문서 목록을 조회한다."""
        query = db.query(DocumentMetadata)

        if status:
            query = query.filter(DocumentMetadata.meta_status == status)

        if source_id:
            query = query.filter(DocumentMetadata.source_id == source_id)

        query = query.order_by(DocumentMetadata.updated_at.desc())
        query = query.limit(limit).offset(offset)

        return query.all()

    def get_document_by_id(self, db: Session, document_id: int) -> Optional[DocumentMetadata]:
        """문서 ID로 상세 조회한다 (Step 3)."""
        return db.query(DocumentMetadata).filter(
            DocumentMetadata.document_id == document_id
        ).first()

    def update_document_metadata(
        self, db: Session, document_id: int, updates: Dict[str, Any]
    ) -> bool:
        """문서 메타데이터를 업데이트한다 (Step 3)."""
        metadata = self.get_document_by_id(db, document_id)
        if not metadata:
            return False

        for key, value in updates.items():
            if hasattr(metadata, key):
                setattr(metadata, key, value)

        db.commit()
        return True

    def approve_document_metadata(
        self, db: Session, document_id: int, reviewer: str
    ) -> bool:
        """메타데이터를 승인한다 (Step 3)."""
        from datetime import datetime

        metadata = self.get_document_by_id(db, document_id)
        if not metadata:
            return False

        metadata.meta_status = MetaStatus.METADATA_REVIEWED.value
        metadata.reviewed_by = reviewer
        metadata.reviewed_at = datetime.utcnow()

        db.commit()
        return True

    def reject_document_metadata(
        self, db: Session, document_id: int, reviewer: str, reason: Optional[str] = None
    ) -> bool:
        """메타데이터를 반려한다 (Step 3)."""
        from datetime import datetime

        metadata = self.get_document_by_id(db, document_id)
        if not metadata:
            return False

        metadata.meta_status = MetaStatus.REJECTED.value
        metadata.reviewed_by = reviewer
        metadata.reviewed_at = datetime.utcnow()
        metadata.rejection_reason = reason

        db.commit()
        return True

    def get_status_counts(self, db: Session) -> Dict[str, int]:
        """메타 상태별 문서 수를 집계한다 (Step 3)."""
        counts = db.query(
            DocumentMetadata.meta_status,
            func.count(DocumentMetadata.id).label('count')
        ).group_by(DocumentMetadata.meta_status).all()

        return {status or "registered": count for status, count in counts}

    def get_review_stats(self, db: Session) -> Dict[str, Any]:
        """검수 현황 통계를 반환한다 (Step 3)."""
        stats = {}

        # 전체 문서 수
        stats["total"] = db.query(func.count(DocumentMetadata.id)).scalar()

        # 상태별 카운트
        stats["status_counts"] = self.get_status_counts(db)

        # source_id별 통계
        source_stats = db.query(
            DocumentMetadata.source_id,
            func.count(DocumentMetadata.id).label('total'),
            func.sum(
                case((DocumentMetadata.meta_status == MetaStatus.REVIEW_REQUIRED.value, 1), else_=0)
            ).label('review_required'),
            func.sum(
                case((DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value, 1), else_=0)
            ).label('reviewed')
        ).filter(
            DocumentMetadata.source_id.isnot(None)
        ).group_by(DocumentMetadata.source_id).all()

        stats["source_stats"] = [
            {
                "source_id": row.source_id,
                "total": row.total,
                "review_required": row.review_required,
                "reviewed": row.reviewed,
                "progress": round(row.reviewed / row.total * 100, 1) if row.total > 0 else 0,
            }
            for row in source_stats
        ]

        return stats

    def count_documents(
        self,
        db: Session,
        status: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> int:
        """문서 수를 센다."""
        query = db.query(func.count(DocumentMetadata.id))

        if status:
            query = query.filter(DocumentMetadata.meta_status == status)

        if source_id:
            query = query.filter(DocumentMetadata.source_id == source_id)

        return query.scalar()


# 싱글톤 인스턴스
document_metadata_service = DocumentMetadataService()
