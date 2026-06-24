# 문서 구조 모델 - 페이지, 섹션, 슬라이드 단위 메타데이터
# -*- coding: utf-8 -*-
"""
Document Structure Models

문서의 하위 구조 (섹션, 페이지, 슬라이드)를 저장하는 모델.
Q1 결정: A + C (OCR 추출 + 별도 테이블)
Q2 결정: B (핵심 섹션만 Graph 노드화)

구조:
- DocumentSection: 문서의 목차/섹션 (기술및기능, 프로젝트관리 등)
- DocumentPage: 문서의 페이지/슬라이드 정보
- DocumentPage는 DocumentSection에 소속될 수 있음
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Float,
    ForeignKey, UniqueConstraint, JSON
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class DocumentSection(Base):
    """
    문서 섹션 테이블 - 목차/챕터 단위.

    entity_mappings.json의 document_sections 기반으로 분류.
    Graph의 SECTION 노드와 연동.
    """

    __tablename__ = "document_sections"
    __table_args__ = (
        UniqueConstraint('document_id', 'section_index', name='uq_doc_section_index'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, nullable=False, index=True, comment="참조 문서 ID")
    document_uid = Column(String(64), nullable=True, index=True, comment="문서 고유 식별자")

    # 섹션 식별
    section_id = Column(String(100), nullable=False, unique=True, index=True,
                        comment="{document_id}-section-{index:02d}")
    section_index = Column(Integer, nullable=False, comment="섹션 순서 (0부터)")

    # 섹션 정보
    section_title = Column(String(500), nullable=True, comment="섹션 제목 (OCR 추출)")
    section_type = Column(String(100), nullable=True, index=True,
                          comment="섹션 유형 코드 (tech_func, proj_mgmt 등)")
    section_label = Column(String(200), nullable=True,
                           comment="표시용 라벨 (기술및기능, 프로젝트관리 등)")

    # 페이지 범위
    start_page = Column(Integer, nullable=True, comment="시작 페이지")
    end_page = Column(Integer, nullable=True, comment="종료 페이지")
    page_count = Column(Integer, nullable=True, comment="페이지 수")

    # 메타데이터
    is_key_section = Column(Boolean, default=False, comment="핵심 섹션 여부 (Graph 노드화 대상)")
    summary = Column(Text, nullable=True, comment="섹션 요약")
    keywords = Column(JSON, nullable=True, comment="섹션 키워드")

    # OCR 추출 신뢰도
    extraction_confidence = Column(Float, nullable=True, comment="추출 신뢰도 0.0-1.0")
    extraction_method = Column(String(50), nullable=True, comment="추출 방법 (toc, heading, folder)")

    # Graph 연동
    graph_node_id = Column(String(100), nullable=True, comment="Graph 노드 ID")

    # 타임스탬프
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    pages = relationship("DocumentPage", back_populates="section", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<DocumentSection(id={self.id}, section_id='{self.section_id}', title='{self.section_title}')>"

    def to_dict(self):
        return {
            "id": self.id,
            "document_id": self.document_id,
            "document_uid": self.document_uid,
            "section_id": self.section_id,
            "section_index": self.section_index,
            "section_title": self.section_title,
            "section_type": self.section_type,
            "section_label": self.section_label,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "page_count": self.page_count,
            "is_key_section": self.is_key_section,
            "summary": self.summary,
            "keywords": self.keywords,
            "extraction_confidence": self.extraction_confidence,
            "extraction_method": self.extraction_method,
            "graph_node_id": self.graph_node_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class DocumentPage(Base):
    """
    문서 페이지/슬라이드 테이블.

    OCR 결과에서 추출한 페이지 정보 저장.
    FAISS 청크와 연동하여 정확한 위치 제공.
    """

    __tablename__ = "document_pages"
    __table_args__ = (
        UniqueConstraint('document_id', 'page_no', name='uq_doc_page_no'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, nullable=False, index=True, comment="참조 문서 ID")
    document_uid = Column(String(64), nullable=True, index=True, comment="문서 고유 식별자")

    # 페이지 식별
    page_id = Column(String(100), nullable=False, unique=True, index=True,
                     comment="{document_id}-page-{page_no:04d}")
    page_no = Column(Integer, nullable=False, index=True, comment="페이지 번호 (1부터)")
    slide_no = Column(Integer, nullable=True, comment="슬라이드 번호 (PPT용)")

    # 섹션 소속
    section_id = Column(Integer, ForeignKey("document_sections.id", ondelete="SET NULL"),
                        nullable=True, index=True, comment="소속 섹션 ID")

    # 페이지 내용
    page_title = Column(String(500), nullable=True, comment="페이지/슬라이드 제목")
    page_type = Column(String(50), nullable=True, comment="페이지 유형 (cover, toc, content, appendix)")
    text_content = Column(Text, nullable=True, comment="페이지 텍스트 (OCR 결과)")
    char_count = Column(Integer, nullable=True, comment="문자 수")

    # 레이아웃 정보
    has_table = Column(Boolean, default=False, comment="표 포함 여부")
    has_image = Column(Boolean, default=False, comment="이미지 포함 여부")
    has_chart = Column(Boolean, default=False, comment="차트 포함 여부")

    # 핵심 장표 표시
    is_key_page = Column(Boolean, default=False, comment="핵심 장표 여부 (관리자 지정)")
    key_page_reason = Column(String(255), nullable=True, comment="핵심 장표 지정 사유")

    # 청크 연동
    chunk_ids = Column(JSON, nullable=True, comment="연관 청크 ID 목록")
    chunk_count = Column(Integer, default=0, comment="연관 청크 수")

    # OCR 품질
    ocr_quality_score = Column(Float, nullable=True, comment="OCR 품질 점수 0.0-1.0")
    extraction_method = Column(String(50), nullable=True, comment="추출 방법")

    # 타임스탬프
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    section = relationship("DocumentSection", back_populates="pages")

    def __repr__(self):
        return f"<DocumentPage(id={self.id}, document_id={self.document_id}, page_no={self.page_no})>"

    def to_dict(self):
        return {
            "id": self.id,
            "document_id": self.document_id,
            "document_uid": self.document_uid,
            "page_id": self.page_id,
            "page_no": self.page_no,
            "slide_no": self.slide_no,
            "section_id": self.section_id,
            "page_title": self.page_title,
            "page_type": self.page_type,
            "char_count": self.char_count,
            "has_table": self.has_table,
            "has_image": self.has_image,
            "has_chart": self.has_chart,
            "is_key_page": self.is_key_page,
            "key_page_reason": self.key_page_reason,
            "chunk_ids": self.chunk_ids,
            "chunk_count": self.chunk_count,
            "ocr_quality_score": self.ocr_quality_score,
            "extraction_method": self.extraction_method,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# 헬퍼 함수
def generate_section_id(document_id: int, section_index: int) -> str:
    """섹션 ID 생성."""
    return f"{document_id}-section-{section_index:02d}"


def generate_page_id(document_id: int, page_no: int) -> str:
    """페이지 ID 생성."""
    return f"{document_id}-page-{page_no:04d}"
