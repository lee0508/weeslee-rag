# MySQL primary, SQLite 비동기 동기화 통합 문서 서비스
"""
unified_document_service.py

MySQL document_metadata 테이블을 primary로 사용하고,
SQLite documents 테이블에 비동기로 동기화하는 통합 서비스.

기존 metadata_db_service (SQLite) 호환 인터페이스를 제공하여
점진적 마이그레이션을 지원.
"""
import asyncio
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db, SessionLocal
from app.models.document_metadata import DocumentMetadata, MetaStatus, ProcessingStatus


class UnifiedDocumentService:
    """MySQL 기반 통합 문서 서비스 (SQLite 동기화 포함)."""

    # ────────────────────────────────────────────────────────────────────────
    # Document CRUD (MySQL primary)
    # ────────────────────────────────────────────────────────────────────────

    def get_document(self, document_id: int, db: Optional[Session] = None) -> Optional[Dict]:
        """문서 ID로 조회."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            doc = db.query(DocumentMetadata).filter(
                DocumentMetadata.document_id == document_id
            ).first()
            return doc.to_dict() if doc else None
        finally:
            if close_db:
                db.close()

    def get_document_by_filename(self, file_name: str, db: Optional[Session] = None) -> Optional[Dict]:
        """파일명으로 조회."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            doc = db.query(DocumentMetadata).filter(
                DocumentMetadata.file_name == file_name
            ).first()
            return doc.to_dict() if doc else None
        finally:
            if close_db:
                db.close()

    def list_documents(
        self,
        document_type: Optional[str] = None,
        status: Optional[str] = None,
        meta_status: Optional[str] = None,
        organization: Optional[str] = None,
        project_year: Optional[str] = None,
        search: Optional[str] = None,
        source_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        db: Optional[Session] = None,
    ) -> List[Dict]:
        """문서 목록 조회."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            query = db.query(DocumentMetadata)

            if source_id:
                query = query.filter(DocumentMetadata.source_id == source_id)
            if document_type:
                query = query.filter(DocumentMetadata.document_type == document_type)
            if status:
                query = query.filter(DocumentMetadata.status == status)
            if meta_status:
                query = query.filter(DocumentMetadata.meta_status == meta_status)
            if organization:
                query = query.filter(DocumentMetadata.organization.like(f"%{organization}%"))
            if project_year:
                query = query.filter(DocumentMetadata.year == int(project_year))
            if search:
                query = query.filter(
                    (DocumentMetadata.file_name.like(f"%{search}%")) |
                    (DocumentMetadata.project_name.like(f"%{search}%"))
                )

            query = query.order_by(DocumentMetadata.updated_at.desc())
            query = query.offset(offset).limit(limit)

            return [doc.to_dict() for doc in query.all()]
        finally:
            if close_db:
                db.close()

    def count_documents(
        self,
        document_type: Optional[str] = None,
        status: Optional[str] = None,
        meta_status: Optional[str] = None,
        source_id: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> int:
        """문서 수 카운트."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            query = db.query(func.count(DocumentMetadata.id))

            if source_id:
                query = query.filter(DocumentMetadata.source_id == source_id)
            if document_type:
                query = query.filter(DocumentMetadata.document_type == document_type)
            if status:
                query = query.filter(DocumentMetadata.status == status)
            if meta_status:
                query = query.filter(DocumentMetadata.meta_status == meta_status)

            return query.scalar() or 0
        finally:
            if close_db:
                db.close()

    def get_document_stats(
        self,
        source_id: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """문서 현황 통계 반환. source_id가 지정되면 해당 Source의 통계만 반환."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            stats = {}

            # 기본 쿼리 (source_id 필터 적용)
            base_query = db.query(func.count(DocumentMetadata.id))
            if source_id:
                base_query = base_query.filter(DocumentMetadata.source_id == source_id)

            # 전체 문서 수
            stats["total"] = base_query.scalar() or 0

            # 미분류 문서 수 (document_type이 없거나 unknown인 경우)
            unclassified_query = db.query(func.count(DocumentMetadata.id)).filter(
                (DocumentMetadata.document_type == None) |
                (DocumentMetadata.document_type == "unknown")
            )
            if source_id:
                unclassified_query = unclassified_query.filter(DocumentMetadata.source_id == source_id)
            stats["unclassified"] = unclassified_query.scalar() or 0

            # 메타 확정 문서 수
            confirmed_query = db.query(func.count(DocumentMetadata.id)).filter(
                DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value
            )
            if source_id:
                confirmed_query = confirmed_query.filter(DocumentMetadata.source_id == source_id)
            stats["confirmed"] = confirmed_query.scalar() or 0

            # RAG 준비 문서 수
            rag_ready_query = db.query(func.count(DocumentMetadata.id)).filter(
                DocumentMetadata.status == ProcessingStatus.RAG_READY.value
            )
            if source_id:
                rag_ready_query = rag_ready_query.filter(DocumentMetadata.source_id == source_id)
            stats["rag_ready"] = rag_ready_query.scalar() or 0

            # 상태별 문서 수
            status_query = db.query(
                DocumentMetadata.status,
                func.count(DocumentMetadata.id).label('count')
            )
            if source_id:
                status_query = status_query.filter(DocumentMetadata.source_id == source_id)
            status_stats = status_query.group_by(DocumentMetadata.status).all()
            stats["by_status"] = {s or "registered": c for s, c in status_stats}

            # 문서 유형별 수
            type_query = db.query(
                DocumentMetadata.document_type,
                func.count(DocumentMetadata.id).label('count')
            )
            if source_id:
                type_query = type_query.filter(DocumentMetadata.source_id == source_id)
            type_stats = type_query.group_by(DocumentMetadata.document_type).all()
            stats["by_type"] = {t or "unknown": c for t, c in type_stats}

            # 메타 상태별 수
            meta_query = db.query(
                DocumentMetadata.meta_status,
                func.count(DocumentMetadata.id).label('count')
            )
            if source_id:
                meta_query = meta_query.filter(DocumentMetadata.source_id == source_id)
            meta_stats = meta_query.group_by(DocumentMetadata.meta_status).all()
            stats["by_meta_status"] = {m or "registered": c for m, c in meta_stats}

            # source_id 정보 추가
            if source_id:
                stats["source_id"] = source_id

            return stats
        finally:
            if close_db:
                db.close()

    def update_document(self, document_id: int, data: Dict, db: Optional[Session] = None) -> bool:
        """문서 업데이트."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            doc = db.query(DocumentMetadata).filter(
                DocumentMetadata.document_id == document_id
            ).first()

            if not doc:
                return False

            # 허용된 필드만 업데이트
            allowed_fields = [
                "file_name", "file_path", "file_type", "file_size",
                "document_type", "document_type_confidence",
                "project_name", "project_name_confidence",
                "organization", "organization_confidence",
                "business_domain", "reuse_level", "year", "summary",
                "status", "meta_status",
                "reviewed_by", "reviewed_at", "rejection_reason",
                "collection_candidates", "final_collections",
                "tags", "keywords",
                "include_in_rag", "include_in_graph", "include_in_wiki",
                "faiss_snapshot", "chunk_count",
            ]

            for field in allowed_fields:
                if field in data:
                    setattr(doc, field, data[field])

            doc.updated_at = datetime.utcnow()
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False
        finally:
            if close_db:
                db.close()

    def delete_document(self, document_id: int, db: Optional[Session] = None) -> bool:
        """문서 삭제."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            result = db.query(DocumentMetadata).filter(
                DocumentMetadata.document_id == document_id
            ).delete()
            db.commit()
            return result > 0
        except Exception:
            db.rollback()
            return False
        finally:
            if close_db:
                db.close()

    # ────────────────────────────────────────────────────────────────────────
    # Step 3: Metadata Review Methods
    # ────────────────────────────────────────────────────────────────────────

    def get_documents_for_review(
        self,
        status: Optional[str] = None,
        source_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        db: Optional[Session] = None,
    ) -> List[Dict]:
        """검수 대기 문서 목록 조회."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            query = db.query(DocumentMetadata)

            if status:
                query = query.filter(DocumentMetadata.meta_status == status)
            if source_id:
                query = query.filter(DocumentMetadata.source_id == source_id)

            query = query.order_by(DocumentMetadata.updated_at.desc())
            query = query.offset(offset).limit(limit)

            return [doc.to_dict() for doc in query.all()]
        finally:
            if close_db:
                db.close()

    def approve_document_metadata(
        self, document_id: int, reviewer: str, db: Optional[Session] = None
    ) -> bool:
        """메타데이터 승인."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            doc = db.query(DocumentMetadata).filter(
                DocumentMetadata.document_id == document_id
            ).first()

            if not doc:
                return False

            doc.meta_status = MetaStatus.METADATA_REVIEWED.value
            doc.reviewed_by = reviewer
            doc.reviewed_at = datetime.utcnow()
            doc.updated_at = datetime.utcnow()

            db.commit()
            return True
        except Exception:
            db.rollback()
            return False
        finally:
            if close_db:
                db.close()

    def reject_document_metadata(
        self, document_id: int, reviewer: str, reason: Optional[str] = None, db: Optional[Session] = None
    ) -> bool:
        """메타데이터 반려."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            doc = db.query(DocumentMetadata).filter(
                DocumentMetadata.document_id == document_id
            ).first()

            if not doc:
                return False

            doc.meta_status = MetaStatus.REJECTED.value
            doc.reviewed_by = reviewer
            doc.reviewed_at = datetime.utcnow()
            doc.rejection_reason = reason
            doc.updated_at = datetime.utcnow()

            db.commit()
            return True
        except Exception:
            db.rollback()
            return False
        finally:
            if close_db:
                db.close()

    def get_status_counts(self, db: Optional[Session] = None) -> Dict[str, int]:
        """메타 상태별 문서 수 집계."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            stats = db.query(
                DocumentMetadata.meta_status,
                func.count(DocumentMetadata.id).label('count')
            ).group_by(DocumentMetadata.meta_status).all()

            return {m or "registered": c for m, c in stats}
        finally:
            if close_db:
                db.close()

    def get_review_stats(self, db: Optional[Session] = None) -> Dict[str, Any]:
        """검수 현황 통계 반환."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            stats = {
                "total": db.query(func.count(DocumentMetadata.id)).scalar() or 0,
                "status_counts": self.get_status_counts(db),
            }

            # source_id별 통계
            source_stats = db.query(
                DocumentMetadata.source_id,
                func.count(DocumentMetadata.id).label('total'),
                func.sum(
                    func.cast(DocumentMetadata.meta_status == MetaStatus.REVIEW_REQUIRED.value, 'INTEGER')
                ).label('review_required'),
                func.sum(
                    func.cast(DocumentMetadata.meta_status == MetaStatus.METADATA_REVIEWED.value, 'INTEGER')
                ).label('reviewed'),
            ).filter(
                DocumentMetadata.source_id != None
            ).group_by(DocumentMetadata.source_id).all()

            stats["source_stats"] = [
                {
                    "source_id": row[0],
                    "total": row[1],
                    "review_required": row[2] or 0,
                    "reviewed": row[3] or 0,
                    "progress": round((row[3] or 0) / row[1] * 100, 1) if row[1] > 0 else 0,
                }
                for row in source_stats
            ]

            return stats
        finally:
            if close_db:
                db.close()


# 싱글톤 인스턴스
unified_document_service = UnifiedDocumentService()
