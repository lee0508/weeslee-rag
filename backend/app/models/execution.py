"""
Execution log models
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class ExecutionLog(Base):
    """Execution log table - AI generation history"""

    __tablename__ = "execution_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prompt_id = Column(Integer, ForeignKey("prompts.id"), nullable=False, index=True)

    # Input
    input_variables = Column(JSON, nullable=True, comment="Variable values used")
    extra_request = Column(Text, nullable=True, comment="Additional user request")
    collections_used = Column(JSON, nullable=True, comment="List of collection IDs used")

    # Model settings
    model_name = Column(String(100), nullable=True)
    temperature = Column(String(10), nullable=True)
    max_tokens = Column(Integer, nullable=True)

    # Output
    result_text = Column(Text, nullable=True)
    token_count = Column(Integer, nullable=True)

    # Timing
    execution_time_ms = Column(Integer, nullable=True, comment="Execution time in milliseconds")

    # Status
    status = Column(String(50), default="completed")
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    prompt = relationship("Prompt", back_populates="executions")
    references = relationship("ReferenceLog", back_populates="execution", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ExecutionLog(id={self.id}, prompt_id={self.prompt_id}, status='{self.status}')>"


class ReferenceLog(Base):
    """Reference log table - documents referenced in generation"""

    __tablename__ = "reference_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(Integer, ForeignKey("execution_logs.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    chunk_id = Column(Integer, ForeignKey("document_chunks.id"), nullable=True)

    # Reference details
    document_name = Column(String(255), nullable=True)
    chunk_content = Column(Text, nullable=True)
    similarity_score = Column(String(10), nullable=True)
    page_number = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    execution = relationship("ExecutionLog", back_populates="references")

    def __repr__(self):
        return f"<ReferenceLog(id={self.id}, execution_id={self.execution_id})>"
