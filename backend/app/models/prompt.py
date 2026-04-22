"""
Prompt template models
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class PromptCategory(str, enum.Enum):
    """Prompt categories"""
    REPORT = "report"
    QA = "qa"
    SUMMARY = "summary"
    ANALYSIS = "analysis"


class PromptStatus(str, enum.Enum):
    """Prompt approval status"""
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    REJECTED = "rejected"


class VariableType(str, enum.Enum):
    """Variable input types"""
    TEXT = "text"
    TEXTAREA = "textarea"
    SELECT = "select"
    NUMBER = "number"
    DATE = "date"


class Prompt(Base):
    """Prompt template table"""

    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    category = Column(Enum(PromptCategory), nullable=False, index=True)
    system_prompt = Column(Text, nullable=True)
    user_prompt_template = Column(Text, nullable=False)
    output_format = Column(Text, nullable=True, comment="Expected output format guidance")

    # Flags
    is_favorite = Column(Boolean, default=False)
    is_org_standard = Column(Boolean, default=False)
    is_personal = Column(Boolean, default=True)

    # Status and versioning
    status = Column(Enum(PromptStatus), default=PromptStatus.DRAFT)
    version = Column(String(20), default="1.0")

    # Ownership
    creator_id = Column(Integer, nullable=True, comment="User ID who created this")

    # Statistics
    usage_count = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    variables = relationship("PromptVariable", back_populates="prompt", cascade="all, delete-orphan")
    executions = relationship("ExecutionLog", back_populates="prompt")

    def __repr__(self):
        return f"<Prompt(id={self.id}, name='{self.name}', category={self.category})>"


class PromptVariable(Base):
    """Prompt variable definitions"""

    __tablename__ = "prompt_variables"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prompt_id = Column(Integer, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False, comment="Variable name like 'organization_name'")
    label = Column(String(200), nullable=False, comment="Display label like '기관명'")
    variable_type = Column(Enum(VariableType), default=VariableType.TEXT)
    is_required = Column(Boolean, default=True)
    default_value = Column(String(500), nullable=True)
    placeholder = Column(String(500), nullable=True)
    options = Column(Text, nullable=True, comment="JSON array for select type")
    order_index = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    prompt = relationship("Prompt", back_populates="variables")

    def __repr__(self):
        return f"<PromptVariable(id={self.id}, name='{self.name}', label='{self.label}')>"
