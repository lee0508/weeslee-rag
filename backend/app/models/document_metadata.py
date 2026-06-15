# Dataset Builder 통합 메타데이터 모델 (MySQL 기준, SQLite 비동기 동기화)
"""
Document metadata for Dataset Builder workflow.
MySQL을 primary로 사용하고, SQLite는 비동기 캐시/백업으로 동기화.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Text, DateTime, Boolean, Float, JSON, UniqueConstraint
import enum

from app.core.database import Base


class MetaStatus(str, enum.Enum):
    """Metadata review status for Dataset Builder Step 3"""
    REGISTERED = "registered"  # Step 1: Source Scan 완료
    METADATA_SUGGESTED = "metadata_suggested"  # Step 2: Metadata Auto 완료
    REVIEW_REQUIRED = "review_required"  # Step 3: 검수 필요
    METADATA_REVIEWED = "metadata_reviewed"  # Step 3: 검수 승인
    REJECTED = "rejected"  # Step 3: 검수 반려


class ProcessingStatus(str, enum.Enum):
    """Document processing status for pipeline tracking"""
    REGISTERED = "registered"  # Step 1 완료
    TEXT_EXTRACTED = "text_extracted"  # Step 4: OCR/텍스트 추출 완료
    CHUNKED = "chunked"  # Step 5: 청킹 완료
    EMBEDDED = "embedded"  # Step 6: 임베딩 완료
    FAISS_INDEXED = "faiss_indexed"  # Step 7: FAISS 인덱스 완료
    GRAPH_CREATED = "graph_created"  # Step 8: 그래프 생성 완료
    WIKI_CREATED = "wiki_created"  # Step 9: Wiki 생성 완료
    RAG_READY = "rag_ready"  # Step 10: RAG 활성화 완료


class DocumentMetadata(Base):
    """
    Document metadata table for Dataset Builder workflow.
    Unified schema for MySQL (primary) and SQLite (sync target).
    """

    __tablename__ = "document_metadata"
    __table_args__ = (
        UniqueConstraint('source_id', 'relative_path', name='uq_document_metadata_source_path'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, nullable=False, unique=True, index=True)

    # Step 1: Source Scan - 파일 정보
    source_id = Column(String(100), nullable=True, index=True, comment="RAG Source ID")
    document_uid = Column(String(64), nullable=True, unique=True, index=True, comment="sha1(source_id:relative_path) 문서 고유 식별자")
    file_path = Column(String(1000), nullable=True, comment="Full file path on source mount")
    relative_path = Column(String(1000), nullable=True, comment="Document Source 기준 상대 경로")
    file_name = Column(String(500), nullable=True, index=True, comment="Original filename")
    file_type = Column(String(50), nullable=True, comment="File extension type (pdf, hwp, docx, etc)")
    file_size = Column(BigInteger, nullable=True, comment="File size in bytes")
    file_checksum = Column(String(64), nullable=True, comment="SHA256 파일 내용 체크섬")
    file_modified_at = Column(DateTime, nullable=True, comment="원본 파일 수정 시간")
    category_id = Column(String(100), nullable=True, comment="Category from source folder structure")
    document_group = Column(String(50), nullable=True, index=True, comment="문서 그룹: RFP, 제안서, 산출물")
    section_type = Column(String(100), nullable=True, comment="섹션 유형: 전략및방법론, 현황분석, 목표모델 등")

    # Step 2: Metadata Auto-generation
    project_name = Column(String(500), nullable=True, comment="Extracted project name")
    project_name_confidence = Column(Float, nullable=True, comment="Confidence score 0.0-1.0")
    organization = Column(String(500), nullable=True, comment="Client organization name")
    organization_confidence = Column(Float, nullable=True, comment="Confidence score 0.0-1.0")
    business_domain = Column(String(200), nullable=True, comment="Business domain category")
    reuse_level = Column(String(20), default="medium", comment="Reuse level: high, medium, low")
    document_type = Column(String(100), nullable=True, index=True, comment="RFP, 제안서, ISP보고서 etc")
    document_type_confidence = Column(Float, nullable=True, comment="Document type confidence 0.0-1.0")
    year = Column(Integer, nullable=True, comment="Project year")
    summary = Column(Text, nullable=True, comment="Document summary")

    # Processing status (pipeline tracking)
    status = Column(String(50), default=ProcessingStatus.REGISTERED.value, index=True,
                    comment="Processing status: registered, text_extracted, chunked, embedded, faiss_indexed, rag_ready")

    # Step 3: Metadata Review
    meta_status = Column(String(50), default=MetaStatus.REGISTERED.value, nullable=False, index=True)
    reviewed_by = Column(String(100), nullable=True, comment="Admin username who reviewed")
    reviewed_at = Column(DateTime, nullable=True, comment="Review timestamp")
    rejection_reason = Column(Text, nullable=True, comment="Reason for rejection")

    # Collections
    collection_candidates = Column(JSON, nullable=True, comment="Auto-suggested collection IDs")
    final_collections = Column(JSON, nullable=True, comment="Admin-confirmed collection IDs")

    # Tags & Keywords
    tags = Column(JSON, nullable=True, comment="Document tags")
    keywords = Column(JSON, nullable=True, comment="Extracted keywords")

    # Include flags for downstream steps
    include_in_rag = Column(Boolean, default=True, nullable=False, comment="Include in FAISS index")
    include_in_graph = Column(Boolean, default=True, nullable=False, comment="Include in Graph build")
    include_in_wiki = Column(Boolean, default=True, nullable=False, comment="Include in Wiki build")

    # Exclusion and removal tracking
    is_excluded = Column(Boolean, default=False, nullable=False, comment="전체 처리 제외 여부")
    exclude_reason = Column(String(255), nullable=True, comment="제외 사유")
    removed_at = Column(DateTime, nullable=True, comment="원본 파일 삭제 감지 일시")
    removed_reason = Column(String(255), nullable=True, comment="삭제/제거 사유")
    is_orphan = Column(Boolean, default=False, nullable=False, comment="Document Source 매칭 실패 여부")
    orphan_reason = Column(String(255), nullable=True, comment="orphan 사유")

    # FAISS integration
    faiss_snapshot = Column(String(100), nullable=True, comment="FAISS snapshot name")
    chunk_count = Column(Integer, default=0, comment="Number of chunks")

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<DocumentMetadata(id={self.id}, document_id={self.document_id}, status={self.status}, meta_status={self.meta_status})>"

    def to_dict(self):
        """Convert to dictionary for API responses and SQLite sync."""
        return {
            "id": self.id,
            "document_id": self.document_id,
            "source_id": self.source_id,
            "document_uid": self.document_uid,
            "file_path": self.file_path,
            "relative_path": self.relative_path,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "file_checksum": self.file_checksum,
            "file_modified_at": self.file_modified_at.isoformat() if self.file_modified_at else None,
            "category_id": self.category_id,
            "document_group": self.document_group,
            "section_type": self.section_type,
            "project_name": self.project_name,
            "project_name_confidence": self.project_name_confidence,
            "organization": self.organization,
            "organization_confidence": self.organization_confidence,
            "business_domain": self.business_domain,
            "reuse_level": self.reuse_level,
            "document_type": self.document_type,
            "document_type_confidence": self.document_type_confidence,
            "year": self.year,
            "summary": self.summary,
            "status": self.status,
            "meta_status": self.meta_status,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "rejection_reason": self.rejection_reason,
            "collection_candidates": self.collection_candidates,
            "final_collections": self.final_collections,
            "tags": self.tags,
            "keywords": self.keywords,
            "include_in_rag": self.include_in_rag,
            "include_in_graph": self.include_in_graph,
            "include_in_wiki": self.include_in_wiki,
            "is_excluded": self.is_excluded,
            "exclude_reason": self.exclude_reason,
            "removed_at": self.removed_at.isoformat() if self.removed_at else None,
            "removed_reason": self.removed_reason,
            "is_orphan": self.is_orphan,
            "orphan_reason": self.orphan_reason,
            "faiss_snapshot": self.faiss_snapshot,
            "chunk_count": self.chunk_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
