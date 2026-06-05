# Dataset Builder Step 3 메타데이터 모델
"""
Document metadata for Dataset Builder workflow
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Float, JSON
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class MetaStatus(str, enum.Enum):
    """Metadata review status for Dataset Builder Step 3"""
    REGISTERED = "registered"  # Step 1: Source Scan 완료
    METADATA_SUGGESTED = "metadata_suggested"  # Step 2: Metadata Auto 완료
    REVIEW_REQUIRED = "review_required"  # Step 3: 검수 필요
    METADATA_REVIEWED = "metadata_reviewed"  # Step 3: 검수 승인
    REJECTED = "rejected"  # Step 3: 검수 반려


class DocumentMetadata(Base):
    """
    Document metadata table for Dataset Builder workflow.
    Stores operational metadata separate from basic document info.
    """

    __tablename__ = "document_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)

    # Step 1: Source Scan
    source_id = Column(String(100), nullable=True, index=True, comment="RAG Source ID")
    file_path = Column(String(1000), nullable=True, comment="Full file path on source mount")
    category_id = Column(String(100), nullable=True, comment="Category from source folder structure")

    # Step 2: Metadata Auto-generation
    project_name = Column(String(500), nullable=True, comment="Extracted project name")
    project_name_confidence = Column(Float, nullable=True, comment="Confidence score 0.0-1.0")
    organization = Column(String(500), nullable=True, comment="Client organization name")
    organization_confidence = Column(Float, nullable=True, comment="Confidence score 0.0-1.0")
    document_type = Column(String(100), nullable=True, comment="RFP, 제안서, ISP보고서 etc")
    year = Column(Integer, nullable=True, comment="Project year")

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

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    # document = relationship("Document", backref="metadata")  # Commented for Dataset Builder workflow

    def __repr__(self):
        return f"<DocumentMetadata(id={self.id}, document_id={self.document_id}, status={self.meta_status})>"
