"""
Document and DocumentChunk models
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, BigInteger, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class DocumentStatus(str, enum.Enum):
    """Document processing status"""
    PENDING = "pending"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    COMPLETED = "completed"
    FAILED = "failed"


class FileType(str, enum.Enum):
    """Supported file types"""
    PPT = "ppt"
    PPTX = "pptx"
    DOC = "doc"
    DOCX = "docx"
    HWP = "hwp"
    HWPX = "hwpx"
    PDF = "pdf"
    XLSX = "xlsx"


class Document(Base):
    """Document table - uploaded document metadata"""

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    collection_id = Column(Integer, ForeignKey("collections.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    original_path = Column(String(500), nullable=True)
    file_type = Column(Enum(FileType), nullable=False)
    file_size = Column(BigInteger, nullable=True, comment="File size in bytes")
    status = Column(Enum(DocumentStatus), default=DocumentStatus.PENDING)
    error_message = Column(Text, nullable=True)
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    collection = relationship("Collection", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    processing_logs = relationship("ProcessingLog", back_populates="document", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Document(id={self.id}, filename='{self.filename}', status={self.status})>"


class DocumentChunk(Base):
    """Document chunk table - text chunks with metadata"""

    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=True)
    page_number = Column(Integer, nullable=True)
    vector_id = Column(String(100), nullable=True, comment="Vector ID in ChromaDB")
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    document = relationship("Document", back_populates="chunks")

    def __repr__(self):
        return f"<DocumentChunk(id={self.id}, document_id={self.document_id}, index={self.chunk_index})>"


class ProcessingLog(Base):
    """Processing log table - track document processing progress"""

    __tablename__ = "processing_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), nullable=False)
    message = Column(Text, nullable=True)
    progress = Column(Integer, default=0, comment="Progress percentage 0-100")
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    document = relationship("Document", back_populates="processing_logs")

    def __repr__(self):
        return f"<ProcessingLog(id={self.id}, status='{self.status}', progress={self.progress})>"
