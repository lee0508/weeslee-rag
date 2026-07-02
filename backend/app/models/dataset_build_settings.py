# Dataset Builder 단계별 설정 모델
from sqlalchemy import Boolean, Column, Integer, String
from sqlalchemy.types import JSON

from app.core.database import Base


class DatasetBuildSettings(Base):
    """Dataset Builder 단계별 설정 저장."""

    __tablename__ = "dataset_build_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(String(100), nullable=False, unique=True, index=True)
    dataset_id = Column(String(150), nullable=True, index=True)

    # Step 3: 메타데이터 추출 설정
    step3_enabled = Column(Boolean, default=True, nullable=False)
    step3_config = Column(JSON, nullable=True)

    # Step 4: OCR/파싱 설정
    step4_enabled = Column(Boolean, default=True, nullable=False)
    step4_config = Column(JSON, nullable=True)

    # Step 5: Tag/Keyword 생성 설정
    step5_enabled = Column(Boolean, default=True, nullable=False)
    step5_config = Column(JSON, nullable=True)

    # Step 6: 청킹/임베딩 설정
    step6_enabled = Column(Boolean, default=True, nullable=False)
    step6_config = Column(JSON, nullable=True)

    # Step 7: Knowledge Graph 설정
    step7_enabled = Column(Boolean, default=True, nullable=False)
    step7_config = Column(JSON, nullable=True)

    # Step 8: LLM Wiki 설정
    step8_enabled = Column(Boolean, default=True, nullable=False)
    step8_config = Column(JSON, nullable=True)

    # Step 10: FAISS 인덱스 설정
    step10_enabled = Column(Boolean, default=True, nullable=False)
    step10_config = Column(JSON, nullable=True)

    created_at = Column(String(40), nullable=True)
    updated_at = Column(String(40), nullable=True)
