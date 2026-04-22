"""
Collection model for VectorDB collections
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, BigInteger, DateTime
from sqlalchemy.orm import relationship

from app.core.database import Base


class Collection(Base):
    """Collection table - represents VectorDB collections"""

    __tablename__ = "collections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    is_system = Column(Boolean, default=False, comment="System collection (cannot delete)")
    document_count = Column(Integer, default=0)
    vector_count = Column(Integer, default=0)
    storage_size = Column(BigInteger, default=0, comment="Storage size in bytes")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    documents = relationship("Document", back_populates="collection", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Collection(id={self.id}, name='{self.name}')>"
