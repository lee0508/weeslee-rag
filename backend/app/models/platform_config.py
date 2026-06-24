"""
Platform configuration models for service-level admin data.
"""
from sqlalchemy import Boolean, Column, Integer, String, Text
from sqlalchemy.types import JSON

from app.core.database import Base


class PlatformClient(Base):
    """Client configuration stored in DB."""

    __tablename__ = "clients"

    client_id = Column(String(100), primary_key=True)
    client_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    service_data_path = Column(String(500), nullable=True)
    default_llm_model = Column(String(100), nullable=True)
    default_embedding_model = Column(String(100), nullable=True)
    default_vectordb_type = Column(String(50), nullable=True)
    default_graph_mode = Column(String(50), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(String(40), nullable=True)
    updated_at = Column(String(40), nullable=True)


class PlatformDocumentSource(Base):
    """Document Source configuration and runtime status stored in DB."""

    __tablename__ = "document_sources"

    source_id = Column(String(100), primary_key=True)
    dataset_id = Column(String(150), nullable=True, index=True)
    dataset_status = Column(String(50), nullable=True)
    dataset_created_at = Column(String(40), nullable=True)
    client_id = Column(String(100), nullable=False, index=True)
    source_name = Column(String(255), nullable=False)
    source_type = Column(String(50), nullable=True)
    source_uri = Column(String(1000), nullable=True)
    mount_path = Column(String(1000), nullable=True)
    root_subpath = Column(String(1000), nullable=True)
    readonly = Column(Boolean, default=True, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    status = Column(String(50), nullable=True)
    last_checked_at = Column(String(40), nullable=True)
    last_scanned_at = Column(String(40), nullable=True)
    last_scan_file_count = Column(Integer, default=0, nullable=False)
    new_file_count = Column(Integer, default=0, nullable=False)
    changed_file_count = Column(Integer, default=0, nullable=False)
    removed_file_count = Column(Integer, default=0, nullable=False)
    last_scan_new_files = Column(JSON, nullable=True)
    last_scan_changed_files = Column(JSON, nullable=True)
    last_scan_removed_files = Column(JSON, nullable=True)
    needs_rag_build = Column(Boolean, default=False, nullable=False)
    next_action = Column(Text, nullable=True)
    created_at = Column(String(40), nullable=True)
    updated_at = Column(String(40), nullable=True)
